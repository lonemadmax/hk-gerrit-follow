import json
import os
from os.path import join
import re

from config import config
import db
import gerrit
import paths


__all__ = ('review',)


_CLEAN_MSG = (
    (re.compile(r'objects/haiku/[^/]*/'), 'objects/haiku/<arch>/'),
    (re.compile(r'(download/\S+-)[^-]+\.hpkg'), r'\1<arch>.hpkg'),
)


def _clean_msg(s):
    for re, substitution in _CLEAN_MSG:
        s = re.sub(substitution, s)
    s = s.split('\n')
    last = s[-1]
    if (last.startswith('...failed updating ')
            and last.endswith(' target(s)...')):
        s = s[:-1]
    s = '   ' + '\n   '.join(sorted(set(s)))
    if len(s) > 1400:
        s = '   Too many errors to list here'
    return s



def _base_review(build_result):
    review = {}
    for arch, result in build_result.items():
        if arch == '*':
            continue
        review[arch] = {
            'ok': result['ok'],
            'msg': 'OK'
        }
        if not result['ok']:
            review[arch]['msg'] = _clean_msg(result['message'])
    return review


def _new_messages(cid, build, arch):
    messages = []
    path = join(paths.www(cid, build['version'], build['parent'], arch),
        'new-messages.json')
    try:
        with open(path, 'rt') as f:
            data = json.load(f)
        for k, v in data.items():
            for m in v:
                messages.append((k, m[1], m[2]))
        messages.sort()
    except:
        pass
    return messages


def _list_new_messages(messages):
    limit = 1400
    s = []
    for m in messages:
        if limit < 0:
            s.append('...')
            break
        limit -= len(m)
        s.append(m)
    return '\n'.join(s)


def _format_new_messages(messages):
    if not messages:
        return ''
    n = 0
    empty = set()
    for arch, m in messages.items():
        if m:
            n += 1
        else:
            empty.add(arch)
    for arch in empty:
        del messages[arch]
    if n == 0:
        return ''
    if n == 1:
        return (next(iter(messages.keys())) + ':\n'
            + _list_new_messages((file + ':' + str(line) + ':' + warning
                for file, line, warning in next(iter(messages.values())))))
    repeated = set()
    keys = {}
    for arch, v in messages.items():
        ikeys = set()
        keys[arch] = ikeys
        k_prev = ''
        for i, m in enumerate(v):
            k_cur = m[0] + ':' + str(m[1]) + ':'
            if k_cur == k_prev:
                repeated.add(k_cur)
            k_prev = k_cur
            ikeys.add(k_cur)
            v[i] = (k_cur, m[2])
    common = set()
    for v in keys.values():
        common |= v
    common -= repeated
    for v in keys.values():
        common &= v
    s = []
    if common:
        # TODO: this 'all' does not include arches built with no warnings
        s.append('all:')
        s.append(_list_new_messages((k + m
            for k, m in next(iter(messages.values())) if k in common)))
    for arch, v in messages.items():
        w = _list_new_messages((k + m for k, m in v if k not in common))
        if w:
            s.append('')
            s.append(arch + ':')
            s.append(w)
    return '\n'.join(s)


def review(change, gerrit_change):
    if config['AUTH'] is None:
        return
    # TODO: db.get_latest_build
    try:
        build = change['build'][-1]
    except IndexError:
        return
    if not build['rebased']['*']:
        # TODO: maybe it is reviewed and now there are conflicts
        # or it was merged with another change and maybe we should warn
        return
    current_review = _base_review(build['rebased'])
    rev_info = gerrit_change['revisions'][gerrit_change['current_revision']]
    if build['version'] != rev_info['_number']:
        return

    same_as_parent = True
    same_as_last = True
    all_ok = True
    last_review = change['sent_review']
    parent = db.data['release'][build['parent']]['result']

    # Don't review arches for which we don't have a baseline
    for arch in list(a for a in current_review.keys() if a not in parent):
        del current_review[arch]
    if not current_review:
        return

    for arch, result in current_review.items():
        if not result['ok']:
            if 'DownloadLocatedFile' in result['msg']:
                # TODO: this might be a reference to something that doesn't
                # exist (I haven't checked), but I prefer not to spam gerrit
                # when it's just a temporary failure
                return
            all_ok = False
        if arch in last_review and last_review[arch]['ok'] != result['ok']:
            same_as_last = False
            if result['ok']:
                result['msg'] = 'fixed'
        if parent[arch]['ok'] != result['ok']:
            same_as_parent = False
            if result['ok']:
                result['msg'] = 'fixes ' + config['branch']

    try:
        # TODO: check that this is our review. Working now because there are
        # no more checkers.
        # TODO: rejected (previous) and not OK (current) may have different
        # failures, in particular may change result per arch
        # TODO: current OK, parent FAIL, last OK but its parent didn't fail:
        # this one fixes master. And the other way around. Maybe never say it?
        gerrit_score = gerrit_change['labels']['Verified'].keys()
        if ((all_ok and 'approved' in gerrit_score)
                or ('rejected' in gerrit_score and not all_ok)):
            return
    except KeyError:
        pass

    if same_as_parent and not all_ok:
        # TODO: check changes in errors
        return

    picked_review = None
    if build['picked'] and build['picked']['*']['ok']:
        picked_review = _base_review(build['picked'])
        for arch, result in list(picked_review.items()):
            if arch not in parent or 'DownloadLocatedFile' in result['msg']:
                del picked_review[arch]
            elif not result['ok']:
                picked_review = False
                break
        if (picked_review is not False
                and picked_review.keys() == current_review.keys()):
            picked_review = True

    includes_warnings = False
    cid = gerrit_change['change_id']
    if all_ok:
        score = '+1'
        if same_as_parent:
            warnings = {arch: _new_messages(cid, build, arch)
                for arch in current_review.keys()}
            n_warnings = max((len(m) for m in warnings.values()))
            if n_warnings:
                message = ('Build OK with ' + str(n_warnings)
                    + ' new problems rebasing over ' + build['parent'])
            else:
                message = 'Build OK rebasing over ' + build['parent']
            if not same_as_last:
                message += ', fixes previous version'
        else:
            warnings = None
            message = 'Build FIXES ' + build['parent']
        message += ' [' + ', '.join(current_review.keys()) + ']'
        if picked_review is False:
            message += ', but cannot be cherry-picked'
        warnings = _format_new_messages(warnings)
        if warnings:
            includes_warnings = True
            message += '\n\n' + warnings
    else:
        score = '-1'
        message = 'FAILED build rebasing over ' + build['parent']
        if picked_review is True:
            message += ', but can be cherry-picked'
        arch_msg = ({}, {})

        for arch, result in current_review.items():
            dest = arch_msg[0]
            if result['ok']:
                dest = arch_msg[1]
                warnings = _new_messages(cid, build, arch)
                if warnings:
                    includes_warnings = True
                    arch_message = ('OK, with ' + str(len(warnings))
                        + ' new problems\n' + _list_new_messages((file + ':'
                            + str(line) + ':' + warning
                            for file, line, warning in warnings)))
                else:
                    arch_message = 'OK'
                if result['msg'] != 'OK':
                    arch = arch + ' (' + result['msg'] + ')'
            else:
                if (arch in last_review
                        and last_review[arch]['msg'] == result['msg']):
                    arch_message = ' still broken'
                else:
                    arch_message = '\n\n' + result['msg']
                if not parent[arch]['ok']:
                    arch = arch + ' (' + build['parent'] + ' also broken)'

            try:
                dest[arch_message].append(arch)
            except KeyError:
                dest[arch_message] = [arch]

        if arch_msg[0]:
            failed = []
            for arch_list in arch_msg[0].values():
                failed.extend(arch_list)
            message += ' [' + ', '.join(sorted(failed)) + ']'
            if len(arch_msg[0]) == 1:
                message += list(arch_msg[0].keys())[0]
                arch_msg[0].clear()
        for msg_type in arch_msg:
            for msg, arches in msg_type.items():
                message += '\n\n' + ', '.join(sorted(arches)) + ': ' + msg

    message += ('\n\n' + config['site'] + paths.www_link(
        paths.www(cid, build['version'], build['parent'], None)))
    if includes_warnings:
        message += ('\nLine numbers are of rebased code, which may not '
            'match the ones in the patch. Warnings may also come from '
            'ancestor patches or be detected in macro definition instead '
            'of uses. The full log provides a bit more context.')
    try:
        gerrit.post_review(gerrit_change, {
            'message': message,
            'tag': 'autogenerated:buildbot',
            'labels': {'Verified': score},
            'notify': 'NONE',
            'omit_duplicate_comments': True
        }, config['AUTH'])
        current_review['version'] = build['version']
        current_review['parent'] = build['parent']
        change['sent_review'] = current_review
        db.save()
    except Exception:
        pass

