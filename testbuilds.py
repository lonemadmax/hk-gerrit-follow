#! /usr/bin/python

# PREPARE:
# repo, buildtools
# branch BRANCH_BASE track remote master
# branch BRANCH_ROLLING based off BRANCH_BASE
# worktree on testbuilds for BRANCH_ROLLING
# www_root

import os
from os.path import exists, join
import re
from shutil import disk_usage, rmtree
import time

import builder
from config import config
import db
import gerrit
import paths
from review import review


RE_WIP = re.compile(r'\bWIP\b', flags=re.IGNORECASE)
TAG_WIP = 'WIP'
TAG_UNRESOLVED = 'Unresolved comments'

SECONDS_PER_DAY = 24 * 60 * 60

KNOB_OLD_VERSION = 10 * SECONDS_PER_DAY
KNOB_OLD_CHANGESET = 2 * 30 * SECONDS_PER_DAY
KNOB_OLD_BUILD = 30 * SECONDS_PER_DAY
KNOB_MINIMUM_DELAY = SECONDS_PER_DAY

GERRIT_BRANCH = gerrit.Repo(config['gerrit_url']).projects[config['project']].branches['refs/heads/' + config['branch']]


# TODO: https://review.haiku-os.org/Documentation/rest-api-changes.html#submitted-together may be interesting to know what goes with what
# submittable field? https://review.haiku-os.org/Documentation/rest-api-changes.html#submittable
# labels? https://review.haiku-os.org/Documentation/rest-api-changes.html#labels


def update_change(info):
    # We only get open changes, no need to check status
    rev_info = info['revisions'][info['current_revision']]
    change_info = {
        'id': info['_number'],
        'title': info['subject'],
        'version': rev_info['_number'],
        'ref': rev_info['ref'],
        'time': {
            'create': gerrit.timestamp_to_time(info['created']),
            'version': gerrit.timestamp_to_time(rev_info['created']),
            'update': gerrit.timestamp_to_time(info['updated'])
        }
    }

    tags = set()
    try:
        tags.update(info['hashtags'])
    except KeyError:
        pass
    try:
        tags.add(info['topic'])
    except KeyError:
        pass
    try:
        if info['work_in_progress']:
            tags.add(TAG_WIP)
    except KeyError:
        pass
    for t in ('wip', 'Wip'):
        try:
            tags.remove(t)
            tags.add(TAG_WIP)
        except KeyError:
            pass
    if (RE_WIP.search(change_info['title'])
            or 'needs work' in change_info['title'].lower()
            or 'work in progress' in change_info['title'].lower()):
        tags.add(TAG_WIP)
    try:
        if info['unresolved_comment_count'] > 0:
            tags.add(TAG_UNRESOLVED)
    except KeyError:
        pass
    change_info['tags'] = list(tags)

    cr = 0
    try:
        cr_info = info['labels']['Code-Review']
        for name, value in (('rejected', -2), ('approved', 2), ('disliked', -1),
                ('recommended', 1)):
            if name in cr_info:
                cr = value
                break
    except KeyError:
        pass
    change_info['review'] = cr

    db.change(info['change_id']).update_gerrit_data(change_info)


def update_changes():
    changes = GERRIT_BRANCH.get_changes()
    for change_info in changes.values():
        update_change(change_info)
    for change in db.active_changes():
        if change.cid not in changes:
            db.set_change_done(change)


def sorted_changes():
    # Discard already built with same version and master
    # Make changes with rejected label wait at least two days, unless they have
    # not been built before
    # Order:
    #   0 Master broken, no WIP, no unresolved messages, new
    #   1 Master broken, no WIP, new
    #   2 No WIP, no unresolved messages, new version, previous version broken
    #   3 No WIP, no unresolved messages, new
    #   4 No WIP, no unresolved messages, new version
    #   5 No unresolved messages, new version, previous version broken
    #   6 No unresolved messages, new / new version
    #   7 new version, previous version broken
    #   8 new / new version
    #   9 rest
    #       base time: now (or time_limit, not that it matters a lot) - build time
    #       + k(update - build) if updated after build time
    #       half if version created more than 10? days ago
    #       half if changeset created more than 2? months ago
    #       -1 day if WIP
    #       -1 day if unresolved messages
    #       +2 days if broken build?
    #       double if last build older than 1 month?
    # For groups 0-8, order by version time desc (build the newest one first)
    # For group 9, order by age desc (build the oldest build first)
    # Notice it's desc for both, as we are using now - t for group 9

    now = time.time()
    priority = [{} for i in range(10)]
    for cid, change in db.data['change'].items():
        latest = change.latest_build()

        if latest is None:
            # New changeset: 0, 1, 3, 6, 8

            if TAG_WIP in change['tags']:
                if TAG_UNRESOLVED in change['tags']:
                    prio = 8
                else:
                    prio = 6
            elif db.is_broken(db.data['release'][db.data['current']]['result']):
                if TAG_UNRESOLVED in change['tags']:
                    prio = 1
                else:
                    prio = 0
            elif TAG_UNRESOLVED in change['tags']:
                prio = 8
            else:
                prio = 3
            priority[prio][cid] = (change['review'], change['time']['update'])

        elif latest['version'] != change['version']:
            # New version: 2, 4, 5, 6, 7, 8

            if (db.is_broken(latest['rebased'])
                    and ((not latest['picked'])
                        or db.is_broken(latest['picked']))):
                # Both builds are broken
                if TAG_UNRESOLVED in change['tags']:
                    prio = 7
                elif TAG_WIP in change['tags']:
                    prio = 5
                else:
                    prio = 2
            elif TAG_UNRESOLVED in change['tags']:
                prio = 8
            elif TAG_WIP in change['tags']:
                prio = 6
            else:
                prio = 4
            priority[prio][cid] = (change['review'], change['time']['update'])

        elif latest['parent'] != db.data['current']:
            # change already built with a different master

            min_delay = KNOB_MINIMUM_DELAY

            # better chance the oldest the last build was
            # TODO: use time of last build with a correct master build?
            weight = now - latest['time']
            # better chance for more activity
            weight += max(0, change['time']['update'] - latest['time']) / 3
            # old version?
            if now - change['time']['version'] > KNOB_OLD_VERSION:
                min_delay *= 2
                if now - change['time']['version'] > 3 * KNOB_OLD_VERSION:
                    weight /= 2
            # wait more if WIP
            if TAG_WIP in change['tags']:
                weight -= 2 * SECONDS_PER_DAY
            # wait more if unresolved comments
            if TAG_UNRESOLVED in change['tags']:
                weight -= SECONDS_PER_DAY
                min_delay *= 2
            # try again sooner for broken builds
            if (db.is_broken(latest['rebased'])
                    and ((not latest['picked'])
                        or db.is_broken(latest['picked']))):
                weight += 2 * SECONDS_PER_DAY
            # but not always
            last_ok, broken = db.broken_for(cid, ('*',))
            if broken and broken[-1] > 2:
                weight -= (sum(broken) - 2) * SECONDS_PER_DAY
            penalty = []
            for arch in latest['rebased']:
                if arch == '*':
                    continue
                last_ok, broken = db.broken_for(cid, (arch,))
                if broken and broken[-1] > 2:
                    penalty.append(sum(broken) - 2)
                else:
                    penalty.append(0)
            min_delay += min(penalty) * SECONDS_PER_DAY / 2
            min_delay -= change['review'] * SECONDS_PER_DAY

            # don't forget anyone
            if now - latest['time'] > KNOB_OLD_BUILD:
                weight = max(0, weight * 2)
            elif weight <= min_delay:
                continue
            priority[9][cid] = (change['review'], weight)

        # else no changes, continue

    queue = []
    for pq in priority:
        queue.extend(sorted(pq.keys(), key=lambda k: pq[k], reverse=True))
    return queue


def remove_done_before(t):
    builder.remove_done_changes(list(cid for cid, cdata
        in db.data['done'].items() if cdata['lastbuild'] < t))


def remove_unused_releases():
    ditch, clean = db.unused_releases()
    for tag in ditch:
        paths.delete_release(config['branch'], tag)
        del db.data['release'][tag]
    for tag in clean:
        for arch in db.data['release'][tag]['result']:
            if arch != '*':
                paths.clean_up(paths.www('release', config['branch'], tag, arch))


def clean_up_build(cid, build):
    for res, full in (('rebased', True), ('picked', False)):
        for arch in build[res]:
            if arch != '*' and build[res][arch]:
                paths.clean_up(paths.www(cid, build['version'],
                    build['parent'], arch, full=full))
    build['logs_only'] = True


def remove_old_harder():
    remove_done_before(time.time()
        - config['keep_done_pressure'] * SECONDS_PER_DAY)
    for k, lim in (('done', 1), ('change', 3)):
        for cid, change in db.data[k].items():
            try:
                keep = change['sent_review']['parent']
            except KeyError:
                keep = ''
            builds = change['build']
            change['build'], remove = builds[-lim:], builds[:-lim]
            for old in remove:
                if old['parent'] == keep:
                    change['build'].insert(0, old)
                else:
                    rmtree(paths.www(cid, old['version'], old['parent'], None),
                        ignore_errors=True)
                    if old['picked']:
                        rmtree(paths.www(cid, old['version'], old['parent'],
                            None, full=False), ignore_errors=True)
            for old in change['build'][:-1]:
                clean_up_build(cid, old)
    remove_unused_releases()
    db.save()


def remove_old_starved():
    for cid, change in db.data['done'].items():
        if change['build']:
            clean_up_build(cid, change['build'][-1])
    if disk_usage(paths.www_root()).free > config['low_disk']:
        return True
    else:
        for cid in sorted((k for k, v in db.data['change'].items()
                    if v['build']),
                key=lambda cid: db.data['change'][cid]['build'][-1]['time']):
            clean_up_build(cid, db.data['change'][cid]['build'][-1])
            if disk_usage(paths.www_root()).free > config['low_disk']:
                return True
    return False


builder.mrproper()
time_limit = time.time() + config['time_limit']
while True:
    if exists('stop.please'):
        print('DDD stop requested')
        break
    if disk_usage(paths.www_root()).free < config['low_disk']:
        print('DDD low disk space')
        remove_old_harder()
        if disk_usage(paths.www_root()).free < config['low_disk']:
            if not remove_old_starved():
                break
    if time.time() > time_limit:
        break
    if builder.update_release():
        # new build, took our time, check if there are updates again
        continue
    update_changes()
    to_build = sorted_changes()
    db.data['queued'] = to_build
    if to_build:
        cid = to_build[0]
        builder.build_change(cid)
        db.data['queued'] = to_build[1:]
        try:
            review(db.data['change'][cid], GERRIT_BRANCH.get_change(cid))
        except KeyError:
            pass
    else:
        break

remove_done_before(time_limit - config['keep_done'] * SECONDS_PER_DAY)
remove_unused_releases()

db.save()

