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
    return '   ' + '\n   '.join(sorted(set(s)))


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
        return
    current_review = _base_review(build['rebased'])
    if build['picked']:
        picked_review = _base_review(build['picked'])
        if picked_review != current_review:
            # TODO: maybe it is reviewed and now there are differences
            return
    rev_info = gerrit_change['revisions'][gerrit_change['current_revision']]
    if build['version'] != rev_info['_number']:
        return

    same_as_parent = True
    same_as_last = True
    all_ok = True
    last_review = change['sent_review']
    parent = db.data['release'][build['parent']]['result']
    for arch, result in current_review.items():
        if not result['ok']:
            all_ok = False
        if arch in last_review and last_review[arch]['ok'] != result['ok']:
            same_as_last = False
            if result['ok']:
                result['msg'] = 'fixed'
        if arch in parent and parent[arch]['ok'] != result['ok']:
            same_as_parent = False
            if result['ok']:
                result['msg'] = 'fixes ' + config['branch']

    if ((last_review['version'] != build['version'] or not same_as_last)
            and (all_ok or not same_as_parent)):
        # TODO: some revisions (like just changing the commit message) keep
        # the score, and as nothing of substance for this checker has changed,
        # we should not spam the comments with another review.
        # We check this by comparing with current score, which is removed for
        # code changes, but it only works because we are the only checkers.
        try:
            gerrit_score = gerrit_change['labels']['Verified'].keys()
            if 'approved' in gerrit_score:
                gerrit_score = '+1'
            elif 'rejected' in gerrit_score:
                gerrit_score = '-1'
            else:
                gerrit_score = ''
        except KeyError:
            gerrit_score = ''

        if all_ok:
            score = '+1'
            if gerrit_score == score:
                return
            if same_as_parent:
                message = 'Build OK rebasing over ' + build['parent']
                if not same_as_last:
                    message += ', fixes previous version'
            else:
                message = 'Build FIXES ' + build['parent']
            message += ' [' + ', '.join(current_review.keys()) + ']'
        else:
            score = '-1'
            if gerrit_score == score:
                return
            message = 'FAILED build rebasing over ' + build['parent']
            msgs = [result['msg'] for result in current_review.values()]
            for msg in msgs:
                if msg != msgs[0]:
                    for arch, result in current_review.items():
                        message += '\n\n' + arch + ': '
                        if result['ok']:
                            message += result['msg']
                        elif (arch in last_review
                                and last_review[arch]['msg'] == result['msg']):
                            message += 'still broken'
                        else:
                            message += '\n\n' + result['msg']
                    break
            else:
                message += ' [' + ', '.join(current_review.keys()) + ']'
                message += '\n\n' + list(current_review.values())[0]['msg']
        message += ('\n\n' + config['site'] + paths.www_link(
            paths.www(gerrit_change['change_id'], build['version'],
            build['parent'], None)))
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

