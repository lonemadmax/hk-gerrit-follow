#! /usr/bin/python

# PREPARE:
# repo, buildtools
# branch BRANCH_BASE track remote master
# branch BRANCH_ROLLING based off BRANCH_BASE
# worktree on testbuilds for BRANCH_ROLLING
# www_root

import os
from os.path import exists, join
from shutil import disk_usage, rmtree
import time

import builder
import chain
from config import config
import db
import gerrit
import paths
from review import review


SECONDS_PER_DAY = 24 * 60 * 60

KNOB_OLD_VERSION = 10 * SECONDS_PER_DAY
KNOB_OLD_CHANGESET = 2 * 30 * SECONDS_PER_DAY
KNOB_OLD_BUILD = 30 * SECONDS_PER_DAY
KNOB_MINIMUM_DELAY = SECONDS_PER_DAY

GERRIT_BRANCH = gerrit.Repo(config['gerrit_url']).projects[config['project']].branches['refs/heads/' + config['branch']]


# TODO: https://review.haiku-os.org/Documentation/rest-api-changes.html#submitted-together may be interesting to know what goes with what
# submittable field? https://review.haiku-os.org/Documentation/rest-api-changes.html#submittable
# labels? https://review.haiku-os.org/Documentation/rest-api-changes.html#labels


def update_changes():
    changes = GERRIT_BRANCH.get_changes()
    for change_info in changes.values():
        db.change(change_info['change_id']).update_gerrit_data(change_info)
    for change in db.active_changes():
        if change.cid not in changes:
            db.set_change_done(change)
    chain.update_changes()


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
    for change in db.active_changes():
        cid = change.cid
        latest = change.latest_build()

        if latest is None:
            # New changeset: 0, 1, 3, 6, 8

            if change.is_wip():
                if change.unresolved_comments():
                    prio = 8
                else:
                    prio = 6
            elif db.is_broken(db.data['release'][db.data['current']]['result']):
                if change.unresolved_comments():
                    prio = 1
                else:
                    prio = 0
            elif change.unresolved_comments():
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
                if change.unresolved_comments():
                    prio = 7
                elif change.is_wip():
                    prio = 5
                else:
                    prio = 2
            elif change.unresolved_comments():
                prio = 8
            elif change.is_wip():
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
            if change.is_wip():
                weight -= 2 * SECONDS_PER_DAY
            # wait more if unresolved comments
            if change.unresolved_comments():
                weight -= SECONDS_PER_DAY
                min_delay *= 2
            # try again sooner for broken builds
            if (db.is_broken(latest['rebased'])
                    and ((not latest['picked'])
                        or db.is_broken(latest['picked']))):
                weight += 2 * SECONDS_PER_DAY
            # but not always
            last_ok, broken = change.broken_for('*')
            if broken and broken[-1] > 2:
                weight -= (sum(broken) - 2) * SECONDS_PER_DAY
            penalty = []
            for arch in latest['rebased']:
                if arch == '*':
                    continue
                last_ok, broken = change.broken_for(arch)
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
    builder.remove_done_changes(list(c.cid for c in db.data['done'].values()
        if c.latest_build() is None or c.latest_build()['time'] < t))


def remove_unused_releases():
    ditch, clean = db.unused_releases()
    for tag in ditch:
        paths.delete_release(config['branch'], tag)
        del db.data['release'][tag]
    for tag in clean:
        for arch in db.data['release'][tag]['result']:
            if arch != '*':
                paths.clean_up(paths.www_release(config['branch'], tag, arch))


def clean_up_build(change, build):
    for res, full in (('rebased', True), ('picked', False)):
        for arch in build[res]:
            if arch != '*' and build[res][arch]:
                paths.clean_up(paths.www(change, build, arch, full=full))
    build['logs_only'] = True


def remove_old_harder():
    remove_done_before(time.time()
        - config['keep_done_pressure'] * SECONDS_PER_DAY)
    for k, lim in (('done', 1), ('change', 3)):
        for change in db.data[k].values():
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
                    rmtree(paths.www(change, old, None), ignore_errors=True)
                    if old['picked']:
                        rmtree(paths.www(change, old, None, full=False),
                            ignore_errors=True)
            for old in change['build'][:-1]:
                clean_up_build(change, old)
    remove_unused_releases()
    db.save()


def remove_old_starved():
    for change in db.data['done'].values():
        if change['build']:
            clean_up_build(change, change['build'][-1])
    if disk_usage(paths.www_root()).free > config['low_disk']:
        return True
    else:
        for change in sorted((change for change in db.active_changes()
                    if change.latest_build()),
                key=lambda change: change.latest_build()['time']):
            clean_up_build(change, change.latest_build())
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
        change = db.change(cid)
        builder.build_change(change)
        db.data['queued'] = to_build[1:]
        try:
            review(change, GERRIT_BRANCH.get_change(cid))
        except KeyError:
            pass
    else:
        break

remove_done_before(time_limit - config['keep_done'] * SECONDS_PER_DAY)
remove_unused_releases()

db.save()

