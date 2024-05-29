import json
import os
from os.path import exists, join
import re
import time

import gerrit
import paths


__all__ = ('data', 'load', 'save', 'set_change_done',
    'is_broken', 'unused_releases', 'Change', 'change', 'active_changes')

_DATAFILE = join(paths.www_root(), 'builds.json')
_BACKUP = _DATAFILE + '.bck'

RE_WIP = re.compile(r'\bWIP\b', flags=re.IGNORECASE)
TAG_WIP = 'WIP'
TAG_UNRESOLVED = 'Unresolved comments'


class Change(dict):
    def __init__(self, cid, data=()):
        super().__init__(data)
        if not 'build' in self:
            self['build'] = []
        if not 'sent_review' in self:
            self['sent_review'] = {'version': -1}
        self.cid = cid

    def update_gerrit_data(self, info):
        # We only get open changes, no need to check status
        rev_info = info['revisions'][info['current_revision']]
        self['id'] = info['_number']
        self['title'] = info['subject']
        self['version'] = rev_info['_number']
        self['ref'] = rev_info['ref']
        self['time'] = {
            'create': gerrit.timestamp_to_time(info['created']),
            'version': gerrit.timestamp_to_time(rev_info['created']),
            'update': gerrit.timestamp_to_time(info['updated'])
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
        for tag in list(tags):
            if tag.lower() == 'wip':
                tags.remove(tag)
                tags.add(TAG_WIP)
        try:
            if info['work_in_progress']:
                tags.add(TAG_WIP)
        except KeyError:
            pass
        if (RE_WIP.search(self['title'])
                or 'needs work' in self['title'].lower()
                or 'work in progress' in self['title'].lower()):
            tags.add(TAG_WIP)
        try:
            self.unresolved_comment_count = info['unresolved_comment_count']
            if self.unresolved_comment_count > 0:
                tags.add(TAG_UNRESOLVED)
        except KeyError:
            self.unresolved_comment_count = 0
        self['tags'] = list(tags)

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
        self['review'] = cr

    def is_wip(self):
        return TAG_WIP in self['tags']

    def unresolved_comments(self):
        return self.unresolved_comment_count

    def latest_build(self):
        try:
            return self['build'][-1]
        except IndexError:
            return None

    def broken_for(self, job):
        # TODO: probably unnecessary, and we are using db.data
        try:
            broken = [0] * (self['version'] + 1)
            for build in reversed(self['build']):
                if (build['rebased'][job]['ok']
                        or (build['picked'] and build['picked'][job]['ok'])):
                    return build, broken
                elif data['release'][build['parent']]['result'][job]['ok']:
                    # TODO: maybe only count None if the prev real build is False?
                    broken[build['version']] += 1
            return None, broken
        except KeyError:
            pass
        return None, None


def load():
    global data
    with open(_DATAFILE, 'rt') as f:
        data = json.load(f)
    for k in ('change', 'done'):
        container = data[k]
        for cid, change in container.items():
            container[cid] = Change(cid, change)


def save():
    data['time'] = int(time.time())
    with open(_BACKUP, 'wt') as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(_BACKUP, _DATAFILE)


def change(cid):
    try:
        return data['change'][cid]
    except KeyError:
        change = Change(cid)
        data['change'][cid] = change
        return change


def active_changes():
    return list(data['change'].values())


def set_change_done(change):
    cid = change.cid
    data['done'][cid] = change
    try:
        del data['change'][cid]
    except KeyError:
        pass
    try:
        data['queued'].remove(cid)
    except ValueError:
        pass
    try:
        time = max(b['time'] for b in change['build'])
    except ValueError:
        time = 0
    change['lastbuild'] = time


def is_broken(arch):
    for k, v in arch.items():
        if v['ok'] is not True:
            # Also when None (not built)
            return k
    return False


def unused_releases():
    rel = set(data['release'].keys())
    rel.discard(data['current'])
    used = set()
    logs = set()
    for k in ('change', 'done'):
        for change in data[k].values():
            for build in change['build']:
                if build['logs_only']:
                    group = logs
                else:
                    group = used
                group.add(build['parent'])
    logs.difference_update(used)
    rel.difference_update(used)
    rel.difference_update(logs)
    return rel, logs



if exists(_BACKUP):
    raise Exception('Broken DB')

try:
    load()
except FileNotFoundError:
    data = {
        'change': {},
        'queued': [],
        'done': {},
        'time': 0,
        'current': None,
        'release': {}
    }

#
#change{cid}:
#    id (number, oldstyle)
#    title
#    version
#    ref
#    time{}:
#       create
#       version
#       update
#    tags[]
#    review (code review numeric value)
#    sent_review {...} last sent build report
#    build[]:
#        parent (hrev)
#        version
#        time
#        logs_only: boolean, have we kept artifacts?
#        rebased/picked{*(prepare)/x86_64/x86_gcc2h}:
#            ok: result
#            warnings: n
#            errors: n
#            message: optional error message
#
#queued[cid]
#
#done{cid}
#    ...change{cid}
#    lastbuild (last build time or 0)
#
#time (last file update)
#current (last hrev)
#release{hrev}
#    commit (sha1)
#    parent (hrev)
#    title (subject)
#    time (build)
#    result{}: result per arch
#
