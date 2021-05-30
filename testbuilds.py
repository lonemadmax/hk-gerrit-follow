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

    db.set_change_info(info['change_id'], change_info)


def update_changes():
    changes = GERRIT_BRANCH.get_changes()
    for change_info in changes.values():
        update_change(change_info)
    for cid in [cid for cid in db.data['change'] if cid not in changes]:
        db.set_change_done(cid)


def sorted_changes():
    # Discard already built with same version and master
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
    #       + (update - build) if updated after build time
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
        latest = db.get_latest_build(cid)

        if latest is None:
            # New changeset: 0, 1, 3, 6, 8

            if (change['review'] < -1
                    and now - change['time']['version'] < 2 * SECONDS_PER_DAY):
                continue

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

            if (change['review'] < -1
                    and now - change['time']['version'] < 2 * SECONDS_PER_DAY):
                continue

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

            # TODO: discard changes with -2 revision points (if they are from this version)
            # better chance the oldest the last build was
            # TODO: use time of last build with a correct master build?
            weight = now - latest['time']
            # better chance for more activity
            weight += max(0, change['time']['update'] - latest['time']) / 2
            # old version?
            if now - change['time']['version'] > KNOB_OLD_VERSION:
                min_delay *= 2
                if now - change['time']['version'] > 3 * KNOB_OLD_VERSION:
                    weight /= 2
            # old changeset?
            #if now - change['time']['create'] > KNOB_OLD_CHANGESET:
            #    weight /= 2
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

        # TODO: half done builds
        # Not worth it? We'll soon get a new release

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


def remove_old_harder():
    remove_done_before(time.time()
        - config['keep_done_pressure'] * SECONDS_PER_DAY)
    for k, lim in (('done', 1), ('change', 3)):
        for cid, change in db.data[k].items():
            # TODO: We may be removing the only correct builds
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
                for res, full in (('rebased', True), ('picked', False)):
                    for arch in old[res]:
                        if arch != '*' and old[res][arch]:
                            paths.clean_up(paths.www(cid, old['version'],
                                old['parent'], arch, full=full))
                old['logs_only'] = True
    remove_unused_releases()
    db.save()


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
            break
    if builder.update_release():
        time_limit += 30 * 60
        # new build, took our time, check if there are updates again
        # TODO: if we have a constant stream of updates, this can go on forever
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
        if time.time() > time_limit:
            break
    else:
        break

remove_done_before(time_limit - config['keep_done'] * SECONDS_PER_DAY)
remove_unused_releases()

db.save()

