import json
import os
from os.path import exists, join
import time

import paths


__all__ = ('data', 'load', 'save', 'set_change_info', 'set_change_done',
    'get_latest_build', 'is_broken', 'unused_releases', 'Change')

_DATAFILE = join(paths.www_root(), 'builds.json')
_BACKUP = _DATAFILE + '.bck'


class Change(dict):
    def __init__(self, data):
        super().__init__(data)
        if not 'build' in self:
            self['build'] = []
        if not 'sent_review' in self:
            self['sent_review'] = {'version': -1}


def load():
    global data
    with open(_DATAFILE, 'rt') as f:
        data = json.load(f)
    for k in ('change', 'done'):
        container = data[k]
        for cid, change in container.items():
            container[cid] = Change(change)


def save():
    data['time'] = int(time.time())
    with open(_BACKUP, 'wt') as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(_BACKUP, _DATAFILE)


def set_change_info(cid, info):
    try:
        data['change'][cid].update(info)
    except KeyError:
        data['change'][cid] = Change(info)
    try:
        del data['done'][cid]
    except KeyError:
        pass


def set_change_done(cid):
    try:
        change = data['done'][cid] = data['change'][cid]
        try:
            time = max(b['time'] for b in change['build'])
        except ValueError:
            time = 0
        change['lastbuild'] = time
        del data['change'][cid]
    except KeyError:
        pass
    try:
        data['queued'].remove(cid)
    except ValueError:
        pass


def get_latest_build(cid):
    try:
        return data['change'][cid]['build'][-1]
    except (KeyError, IndexError):
        return None


def is_broken(arch):
    for k, v in arch.items():
        if v['ok'] is not True:
            # Also when None (not built)
            return k
    return False


def broken_for(cid, arches):
    try:
        broken = [0] * (data['change'][cid]['version'] + 1)
        for build in reversed(data['change'][cid]['build']):
            if (all(build['rebased'][arch]['ok'] for arch in arches)
                    or (build['picked'] and all(build['picked'][arch]['ok']
                        for arch in arches))):
                return build, broken
            elif (all(data['release'][build['parent']]['result'][arch]['ok']
                    for arch in arches)):
                # TODO: maybe only count None if the prev real build is False?
                broken[build['version']] += 1
        return None, broken
    except KeyError:
        pass
    return None, None


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
