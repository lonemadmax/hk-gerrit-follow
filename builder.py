import git
import html
import json
import os
from os.path import exists, join, relpath, split
from shutil import copy, move, rmtree
import stat
import subprocess
import sys
import time

from archive import archive
import buildtools
import chain
from config import config
import db
import gitutils
from jam import jam
import log_analysis
import paths
import subprocess_wrapper


__all__ = ('update_release', 'build_change', 'changeset_branch_name',
    'remove_done_changes', 'mrproper')


BRANCH_BASE = config['branch_base']
BRANCH_ROLLING = config['branch_rolling']

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
    for prefix in buildtools.get_arch_prefixes(config['branch'], arch):
        command.extend(('--cross-tools-prefix', prefix))
    with open(join(wd, 'configure.log'), 'wb') as out:
        subprocess.run(command, stdout=out, stderr=subprocess.STDOUT,
            check=True, cwd=wd)


def configure_build_update(wd):
    command = [join(paths.worktree(), 'configure'), '--update']
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
    else:
        configure_build_update(path)

    options = ['-sHAIKU_REVISION='+tag,
        '-sHAIKU_BUILD_ATTRIBUTES_DIR='+paths.emulated_attributes()]
    options.extend(config['arches'][arch]['jam_options'])
    res, fname = jam(path, config['arches'][arch]['target'], options,
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


# TODO: this (and quite a bit more) should be somewhere else
_MASTER_MSGS = None
def _get_msgs(tag, arch):
    global _MASTER_MSGS
    if (not _MASTER_MSGS) or _MASTER_MSGS['tag'] != tag:
        _MASTER_MSGS = {'tag': tag}
    try:
        return _MASTER_MSGS[arch]
    except KeyError:
        try:
            with open(join(paths.www('release', config['branch'], tag, arch),
                    'build-messages.json'), 'rt') as f:
                _MASTER_MSGS[arch] = json.load(f)
        except Exception:
            _MASTER_MSGS[arch] = None
        return _MASTER_MSGS[arch]


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
    new_msgs = None
    if parent:
        old_msgs = _get_msgs(parent, arch)
        if old_msgs:
            _, new_msgs = log_analysis.diff(old_msgs, result['full'])
            if new_msgs:
                with open(join(dst, 'new-messages.json'), 'wt') as f:
                    json.dump(new_msgs, f)
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

            def write_msg_item(file, line, logline, msg):
                if line:
                    line = str(line)
                    fout.write(' <li><samp><a href="')
                    fout.write(linker(file, line))
                    fout.write('">')
                    fout.write(html.escape(file))
                    fout.write(':' + line + '</a>: ')
                else:
                    fout.write(' <li><samp>')
                    fout.write(html.escape(file))
                    fout.write(': ')
                fout.write('<a href="#n' + str(logline) + '">')
                fout.write(html.escape(msg))
                fout.write('</a></samp></li>\n')

            if new_msgs:
                fout.write('<h2>New messages</h2>\n<ul>\n')
                for file, msgs in sorted(new_msgs.items()):
                    for msg in msgs:
                        write_msg_item(file, msg[1], msg[0], msg[2])
                fout.write('</ul></pre>\n')

            if result['errors']:
                fout.write('\n<h2>Errors</h2>\n<ul>\n')
                for file, msgs in sorted(result['errors'].items()):
                    for msg in msgs:
                        write_msg_item(file, msg[2], msg[1], messages[msg[3]])
                fout.write('</ul></pre>\n')

            fout.write('\n<h2>Log</h2>')
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

    messages = [''] * (max(result['messages'].values()) + 1)
    for k, v in result['messages'].items():
        messages[v] = k
    result['messages'] = messages

    write_log(log, join(dst, 'buildlog.html'), log_analysis.htmlout, line_msgs)

    if config['arches'][arch]['save_artifacts']:
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

        # Maybe x86_64/objects/haiku/x86_64/release/system/boot/efi/{haiku_loader.efi,boot_loader_efi}
        # gcc2h does not have efi.map and esp.image
        for f in ('esp.image', 'haiku-nightly-anyboot.iso', 'haiku-mmc.image'):
            try:
                f = join(src, f)
                os.chmod(f, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                move(f, dst)
            except FileNotFoundError:
                pass

    result['packages'] = list(result['packages'])

    with open(join(dst, 'build-messages.json'), 'wt') as f:
        json.dump(result['full'], f)
    del result['full']

    with open(join(dst, 'build-result.json'), 'wt') as f:
        json.dump(result, f)


def _fill_empty_results(d=None):
    if d is None:
        d = {}
    for a in config['arches'].keys():
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
        tag = gitutils.decorate(commit, False).replace('-', '+')
        # TODO: it is used as commitish here and there. Instead of hunting
        # down all those places to use the commit (it should be in
        # db.data['release'][tag]['commit']), just make a branch off of it.
        # We don't want a tag so that other tagless commits are not based
        # on it when we try to decorate them.
        REPO.create_head(tag, commmit)

    dst = paths.www('release', config['branch'], tag, None)
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

    if config['archive_src']:
        for f in os.listdir(dst):
            if f.startswith('src.'):
                # don't archive again, it takes some time
                break
        else:
            archive(dst, config['branch'], tag, '')

    for arch in config['arches'].keys():
        if data_master['result'][arch]['ok'] is None:
            data_master['result'][arch]['ok'], log = build(arch, tag)
            build_dst = paths.www('release', config['branch'], tag, arch)
            os.makedirs(build_dst, exist_ok=True)
            _process_build(paths.build(arch), build_dst, log,
                config['branch'] + ': ' + tag + ' [' + arch + ']',
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


def _build_change(change, build_data, rebased):
    cid = change.cid
    legacy_id = str(change.number)
    version = str(build_data['version'])
    parent = build_data['parent']
    tag = parent + '_' + legacy_id + '_' + version

    if rebased:
        result = build_data['rebased']
    else:
        result = build_data['picked']
        tag += '_sep'

    for arch in config['arches'].keys():
        if result[arch]['ok'] is None:
            result[arch]['ok'], log = build(arch, tag)
            build_dst = paths.www(cid, version, parent, arch, rebased)
            os.makedirs(build_dst, exist_ok=True)
            _process_build(paths.build(arch), build_dst, log,
                cid + ' v' + version + ' on ' + parent + ' [' + arch + ']',
                log_analysis.file_link_change(legacy_id, version),
                parent, result, arch)
            db.save()


def changeset_branch_name(cid, version):
    return 'changeset-' + cid + '-' + str(version)


def build_change(change):
    cid = change.cid
    base = REPO.heads[BRANCH_BASE]

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

    change = chain.changes[cid]
    # except KeyError that should not happen

    def _build(commit, cherry):
        dst = paths.www(cid, build_data['version'], parent, None, not cherry)
        patches_dir = join(dst, 'patches')
        os.makedirs(patches_dir, exist_ok=True)
        os.symlink(relpath(paths.www('release', config['branch'], parent, None),
            start=dst), join(dst, 'baseline'))
        patches = gitutils.format_patch(REPO, parent + '..' + commit.hexsha,
            patches_dir)

        rolling_branch = REPO.branches[BRANCH_ROLLING]
        REPO.head.ref = rolling_branch

        #try:
        rolling_branch.set_commit(commit)
        rolling_branch.checkout(force=True)
        _build_change(change, build_data, not cherry)
        #except git.exc.GitCommandError:

        REPO.head.ref = rolling_branch
        rolling_branch.set_commit(base.commit)
        rolling_branch.checkout(force=True)

    def _do(commit, conflicts, conflict_origin, cherry):
        if cherry:
            result = build_data['picked']['*']
        else:
            result = build_data['rebased']['*']

        msg = None
        if commit:
            if REPO.commit(parent).tree == commit.tree:
                msg = 'Already merged'
        elif conflicts:
            msg = 'Conflicts in:\n' + '\n'.join(conflicts)
        else:
            # TODO: find it and add the conflicts, the subject
            # the number/version?
            msg = 'Conflicts in ancestor ' + conflict_origin

        if msg:
            result['ok'] = False
            result['message'] = msg
            db.save()
        else:
            result['ok'] = True
            db.save()
            _build(commit, cherry)

    rebase, conflicts, conflicting_cid = change.rebase()
    _do(rebase, conflicts, conflicting_cid, False)

    pick, conflicts = change.pick()
    if rebase and pick == rebase:
        return
    _fill_empty_results(build_data['picked'])
    _do(pick, conflicts, None, True)


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

