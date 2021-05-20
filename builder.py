import git
import html
import json
import os
from os.path import basename, exists, join, relpath, split
from shutil import copy, move, rmtree
import stat
import subprocess
import sys
import time

from archive import archive
import buildtools
import db
import gitutils
from jam import jam
import log_analysis
import paths
import subprocess_wrapper


__all__ = ('update_release', 'build_change', 'changeset_branch_name',
    'remove_done_changes', 'mrproper')


BRANCH_BASE = 'testbuild_base'
BRANCH_ROLLING = 'testbuild'

ARCHES = ('x86_64', 'x86_gcc2h')

REPO = gitutils.get_repo()


def mrproper():
    if REPO.currently_replaying():
        try:
            REPO.git.rebase(abort=True)
        except git.exc.GitCommandError:
            # barf if this one also fails
            REPO.git.cherry_pick(abort=True)
    rolling_branch = REPO.branches[BRANCH_ROLLING]
    head = REPO.head
    head.ref = rolling_branch
    head.set_commit(REPO.heads[BRANCH_BASE].commit)
    rolling_branch.checkout(force=True)

            
def configure_build(wd, arch):
    command = [join(paths.worktree(), 'configure'),
        '--use-gcc-pipe', '--include-sources']
    # '--use-gcc-graphite' spits spurious maybe-uninitialized error in RAW.cpp
    for prefix in buildtools.get_arch_prefixes('master', arch):
        command.extend(('--cross-tools-prefix', prefix))
    with open(join(wd, 'configure.log'), 'wb') as out:
        subprocess.run(command, stdout=out, stderr=subprocess.STDOUT,
            check=True, cwd=wd)


def build(arch, tag):
    remove_emulated_attributes()
    path = paths.build(arch)
    os.makedirs(path, exist_ok=True)
    paths.clean_up(path)

    # Some time measurements:
    # Command line, with everything from last build:
    #   real 3m34s, user 0m54s, sys 0m25s
    # Command line, wihtout objects/ and images:
    #   real 8m27s, user 25m30s, sys 2m13s
    # Command line, without images:
    #   real 2m12s, user 1m9s, sys  0m25s
    # Program (rmtree objects, remove images): 8m30s (7m7s for gcc2h)

    if not exists(join(path, 'build', 'BuildConfig')):
        configure_build(path, arch)
    res, fname = jam(path, '@nightly-anyboot', options=(
            '-sHAIKU_REVISION='+tag,
            '-sHAIKU_BUILD_ATTRIBUTES_DIR='+paths.emulated_attributes(),
            '-sHAIKU_IMAGE_SIZE=900'),
        jam_cmd=paths.jam(), output=join(path, 'build.out'))
    remove_emulated_attributes()
    with open(fname, 'rt') as logf:
        log = logf.read().split('\n')
    PT = log_analysis.PathTransformer()
    for i, s in enumerate(PT.transform(log)):
        log[i] = s
    return res.returncode == 0, log


def remove_emulated_attributes():
    rmtree(paths.emulated_attributes(), ignore_errors=True)


# TODO: keep modifications in sync with reextract.py:_process_build
def _process_build(src, dst, log, title, linker, parent, result, arch):
    arch_data = result[arch]

    result = log_analysis.analyse(log)
    arch_data['message'] = result['failures']
    msg_refs = {'warnings': [], 'errors': []}
    for k in ('warnings', 'errors'):
        arch_data[k] = sum(len(v) for v in result[k].values())
        for msgs in result[k].values():
            for i, v in enumerate(msgs):
                lf, ls, msg = v
                msg_refs[k].append(lf)
                msgs[i] = (0, lf, ls, msg)
    result['files'] = ['buildlog.html']

    title = html.escape(title, quote=True)
    lead_items = ['<h1>', title, '</h1>\n<p>',
        str(arch_data['warnings']), '', ' warnings<br>\n',
        str(arch_data['errors']), '', ' errors', '',
        '</p>\n<pre>', html.escape(arch_data['message']), '</pre>\n']
    if parent:
        parent_result = db.data['release'][parent]['result']
        if arch in parent_result:
            for t, i in (('warnings', 4), ('errors', 7)):
                delta = arch_data[t] - parent_result[arch][t]
                if delta:
                    lead_items[i] = ' (%+d)' % delta
                    lead_items[9] = '<br>\n(vs ' + parent + ')'
    lead = ''.join(lead_items)
    css = paths.link_root() + '/css/log.css'

    def write_log(log, dst, body, line_msgs):
        with open(dst, 'wt') as fout:
            fout.write('<!DOCTYPE html>\n<html><head>'
                '<meta charset="utf-8" />\n<title>')
            fout.write(title)
            fout.write('</title>\n<link rel="stylesheet" href="')
            fout.write(css)
            fout.write('" />\n</head><body>\n')
            fout.write(lead)
            body(log, fout, file_linker=linker, line_msgs=line_msgs)
            fout.write('\n</body></html>')

    m = 0
    for k in ('warnings', 'errors'):
        try:
            m = max(max(msg_refs[k]), m)
        except ValueError:
            pass
    line_msgs = [0] * (m + 1)
    for k, v in (('warnings', 1), ('errors', 2)):
        for i in msg_refs[k]:
            line_msgs[i] = v

    write_log(log, join(dst, 'buildlog.html'), log_analysis.htmlout, line_msgs)

    pkgs = set(result['packages'])
    obj_dir = join(src, 'objects', 'haiku')
    for entry in os.scandir(obj_dir):
        if entry.is_dir():
            pkg_dir = join(obj_dir, entry.name, 'packaging', 'packages')
            if exists(pkg_dir):
                for f in os.listdir(pkg_dir):
                    # TODO: may have disappeared
                    move(join(pkg_dir, f), dst)
                    try:
                        pkgs.remove(f)
                    except KeyError:
                        print('PKGGET UNEXPECTED', pkg_dir, f, file=sys.stderr)
    for pkg in pkgs:
        print('PKGGET NOTFOUND', pkg, file=sys.stderr)

    # TODO: efi.map? Probably not. Text with adresses, object names, etc.
    # Maybe x86_64/objects/haiku/x86_64/release/system/boot/efi/{haiku_loader.efi,boot_loader_efi}
    # gcc2h does not have efi.map and esp.image
    for f in ('esp.image', 'haiku-nightly-anyboot.iso'):
        try:
            f = join(src, f)
            os.chmod(f, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            move(f, dst)
        except FileNotFoundError:
            pass

    result['packages'] = list(result['packages'])

    messages = [''] * (max(result['messages'].values()) + 1)
    for k, v in result['messages'].items():
        messages[v] = k
    result['messages'] = messages

    with open(join(dst, 'build-messages.json'), 'wt') as f:
        json.dump(result['full'], f)
    del result['full']

    with open(join(dst, 'build-result.json'), 'wt') as f:
        json.dump(result, f)


def _fill_empty_results(d=None):
    if d is None:
        d = {}
    for a in ARCHES:
        d[a] = {'ok': None, 'warnings': 0, 'errors': 0}
    d['*'] = {'ok': None}
    return d


def build_release():
    commit = REPO.heads[BRANCH_BASE].commit
    head = REPO.head
    head.set_commit(commit)
    head.ref.checkout(force=True)
    tag = gitutils.decorate(commit)
    if tag is None:
        # Shouldn't happen?
        tag = commit.hexsha

    dst = paths.www('release', 'master', tag, None)
    os.makedirs(dst, exist_ok=True)

    old_tag = db.data['current']
    if old_tag != tag:
        data_master = {
            'commit': commit.hexsha,
            'title': commit.summary,
            'parent': old_tag,
            'time': int(time.time()),
            'result': _fill_empty_results()
        }
        data_master['result']['*'] = {'ok': True}
        db.data['release'][tag] = data_master
        db.data['current'] = tag
        db.save()
    else:
        # Error in previous pass with same revision:
        # - keep what was built
        data_master = db.data['release'][old_tag]

    for f in os.listdir(dst):
        if f.startswith('src.'):
            # don't archive again, it takes some time
            break
    else:
        archive(dst, 'master', tag, '')

    for arch in ARCHES:
        if data_master['result'][arch]['ok'] is None:
            data_master['result'][arch]['ok'], log = build(arch, tag)
            build_dst = paths.www('release', 'master', tag, arch)
            os.makedirs(build_dst, exist_ok=True)
            _process_build(paths.build(arch), build_dst, log,
                'master: ' + tag + ' [' + arch + ']',
                log_analysis.file_link_release(tag),
                data_master['parent'], data_master['result'], arch)
            db.save()


def update_release():
    base = REPO.heads[BRANCH_BASE]
    remote_branch = base.tracking_branch()
    REPO.remotes[remote_branch.remote_name].fetch(
        remote_branch.remote_head, tags=True)
    commit = remote_branch.commit
    last = db.data['current']
    if ((not last) or db.data['release'][last]['commit'] != commit.hexsha
            or None in (a['ok'] for a in
                db.data['release'][last]['result'].values())):
        base.set_commit(commit)
        build_release()
        return True
    return False


def _build_change(cid, build_data, rebased):
    legacy_id = str(db.data['change'][cid]['id'])
    version = str(build_data['version'])
    parent = build_data['parent']
    tag = parent + '_' + legacy_id + '_' + version

    if rebased:
        result = build_data['rebased']
    else:
        result = build_data['picked']
        tag += '_sep'

    for arch in ARCHES:
        if result[arch]['ok'] is None:
            result[arch]['ok'], log = build(arch, tag)
            build_dst = paths.www(cid, version, parent, arch, rebased)
            os.makedirs(build_dst, exist_ok=True)
            _process_build(paths.build(arch), build_dst, log,
                cid + ' v' + version + ' on ' + parent + ' [' + arch + ']',
                log_analysis.file_link_change(legacy_id, version),
                parent, result, arch)
            db.save()


def _process_conflicts(dst):
    src = paths.worktree()
    file_list = []
    for f in REPO.index.unmerged_blobs():
        file_list.append(f)
        d, n = split(f)
        d = join(dst, d)
        os.makedirs(d, exist_ok=True)
        try:
            copy(join(src, f), d)
        except FileNotFoundError:
            # Renames, may have "both deleted" and the file doesn't exist now
            print('DDD FileNotFoundError', f)
            pass
    return file_list


def _conflict_page(dst, patches, applied, conflicts):
    # TODO: by default filename length is limited to 64 in format-patch,
    # and there's also no guarantee that subject lines are unique, so we may
    # have duplicate keys
    _applied = {}
    for patch in applied:
        patch = relpath(patch, start=dst)
        name = basename(patch)
        _applied[name[name.find('-'):]] = patch

    with open(join(dst, 'conflicts.html'), 'wt') as f:
        f.write('<!DOCTYPE html>\n<html><head><meta charset="utf-8" />'
            '\n<title>Conflicts applying patches</title>'
            '\n<link rel="stylesheet" href="')
        f.write(paths.link_root() + '/css/main.css')
        f.write('" />\n</head><body>\nPatches<ol>')
        for patch in patches:
            item = ['\n<li><a href="']
            patch = relpath(patch, start=dst)
            name = basename(patch)
            item.append(html.escape(patch, quote=True))
            item.append('">')
            item.append(html.escape(name, quote=True))
            item.append('</a>')
            try:
                applied_patch = _applied.pop(name[name.find('-'):])
                item.append(' <a href="')
                item.append(html.escape(applied_patch, quote=True))
                item.append('">[applied]</a>')
            except KeyError:
                pass
            item.append('</li>')
            f.write(''.join(item))
        if _applied:
            print('DDD applied inexistent patches?', dst, _applied, '|',
                patches, '|', applied)
        f.write('\n</ol>Conflicts<ul>')
        for conflict in conflicts:
            item = ['\n<li><a href="conflicts/']
            escaped = html.escape(conflict, quote=True)
            item.append(escaped)
            item.append('">')
            item.append(escaped)
            item.append('</a></li>')
            f.write(''.join(item))
        f.write('\n</ul>\n</body></html>')


def changeset_branch_name(cid, version):
    return 'changeset-' + cid + '-' + str(version)


def build_change(cid):
    change = db.data['change'][cid]
    base = REPO.heads[BRANCH_BASE]
    change_branch = changeset_branch_name(cid, change['version'])
    if change_branch not in REPO.branches:
        REPO.remotes[base.tracking_branch().remote_name].fetch(
            change['ref']+':refs/heads/'+change_branch)

    parent = db.data['current']
    build_data = {
        'parent': parent,
        'version': change['version'],
        'time': int(time.time()),
        'logs_only': False,
        'rebased': _fill_empty_results(),
        'picked': {}
    }
    change['build'].append(build_data)

    def _merge_and_build(cherry):
        dst = paths.www(cid, build_data['version'], parent, None, not cherry)
        patches_dir = join(dst, 'patches')
        os.makedirs(patches_dir, exist_ok=True)
        os.symlink(relpath(paths.www('release', 'master', parent, None),
            start=dst), join(dst, 'master'))
        if cherry:
            i = 1
            patches = []
            for c in cherry:
                patches.extend(gitutils.format_patch(REPO, c.hexsha + '^!',
                    patches_dir, start_number=i))
                i += 1
            result = build_data['picked']
        else:
            patches = gitutils.format_patch(REPO, parent + '..' + change_branch,
                patches_dir)
            result = build_data['rebased']
        clean_rebase = len(patches) <= 1

        rolling_branch = REPO.branches[BRANCH_ROLLING]
        REPO.head.ref = rolling_branch

        try:
            if cherry:
                rolling_branch.set_commit(base.commit)
                rolling_branch.checkout(force=True)
                REPO.git.cherry_pick(*cherry)
            else:
                rolling_branch.set_commit(change_branch)
                rolling_branch.checkout(force=True)
                REPO.git.rebase(BRANCH_BASE, rolling_branch)
            real_patches = gitutils.format_patch(REPO, parent,
                    join(dst, 'applied'))
            if len(real_patches) <= 1:
                clean_rebase = True
            # TODO: this check is probably unnecessary
            if real_patches[0]:
                result['*'] = {'ok': True}
            else:
                result['*'] = {
                    'ok': False,
                    'message': 'Already merged'
                }
            db.save()
            if real_patches[0]:
                _build_change(cid, build_data, not cherry)
        except git.exc.GitCommandError:
            message = []
            commit = REPO.currently_replaying()
            if commit is not None:
                message.append('Conflict with ' + commit.hexsha + ' ['
                        + commit.summary + ']:')
            else:
                message.append('Merge conflict:')
            applied = gitutils.format_patch(REPO, parent, join(dst, 'applied'))
            conflicts = _process_conflicts(join(dst, 'conflicts'))
            message.extend(conflicts)
            result['*'] = {
                'ok': False,
                'message': '\n'.join(message)
            }
            _conflict_page(dst, patches, applied, conflicts)
            db.save()
            if cherry:
                REPO.git.cherry_pick(abort=True)
            else:
                REPO.git.rebase(abort=True)

        REPO.head.ref = rolling_branch
        rolling_branch.set_commit(base.commit)
        rolling_branch.checkout(force=True)
        return clean_rebase

    if not _merge_and_build(False):
        # TODO: The change-id may or not be in the message, and I don't know
        # if it's possible to have several commits with the same change-id.
        # Let's just check if rebasing produced just one commit, else try
        # cherrypicking the head one
        _fill_empty_results(build_data['picked'])
        _merge_and_build((REPO.commit(change_branch),))
    #
    #cid_history = []
    #discarded_commits = False
    #signature = 'change-id: ' + cid.lower()
    #for commit in gitutils.history(base, change_branch, REPO):
    #    if signature in commit.message.lower().split('\n'):
    #        cid_history.append(commit)
    #    else:
    #        discarded_commits = True
    #if discarded_commits and cid_history:
    #    # I don't even know if this is possible in gerrit
    #    # Let's cherry-pick just the commits for this changeset
    #    _merge_and_build(cid_history)


def remove_done_changes(cids):
    for cid in cids:
        del db.data['done'][cid]
        paths.delete_change(cid)
        remove = []
        prefix = changeset_branch_name(cid, '')
        for branch in REPO.branches:
            if branch.name.startswith(prefix):
                remove.append(branch)
        if remove:
            REPO.delete_head(*remove, force=True)

