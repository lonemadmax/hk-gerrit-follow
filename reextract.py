#! /usr/bin/python

from collections import defaultdict
import json
from html import escape, unescape
import os
from os.path import basename, exists, join
import re
from shutil import move

import db
import log_analysis
import paths
import tmpfs


RE_NOHTML = re.compile(r'<[^>]*>')

TMPDIR = tmpfs.preferred_root()


if not exists('stop.please'):
    # TODO: this is no guarantee
    raise Exception('Make sure the main process is not running')

badbefore = set()
badafter = set()

def extract_bad(file, set):
    with open(file, 'rt') as f:
        data = json.load(f)
        for s in data['messages']:
            if ' ' in s:
                set.add(s)

def clear_html_log(file):
    with open(file, 'rt') as f:
        outname = join(tmpfs.preferred_root(), 'haiku_'+basename(file))
        with open(outname, 'wt') as out:
            for line in f:
                if line.startswith('<li>'):
                    out.write(unescape(RE_NOHTML.sub('', line)))
    return outname

# TODO: keep modifications in sync with builder.py:_process_build
# TODO: legacy, remove when all logs use one file
def _process_build2(stdout, stderr, dst, title, linker, arch_data, parent_arch_data):
    result = log_analysis.analyse(stderr, stdout)
    arch_data['message'] = result['failures']
    files = defaultdict(lambda: len(files))
    msg_refs = {'warnings': [[], []], 'errors': [[], []]}
    for k in ('warnings', 'errors'):
        arch_data[k] = sum(len(v) for v in result[k].values())
        for msgs in result[k].values():
            for i, v in enumerate(msgs):
                f, lf, ls, msg = v
                if f == stderr:
                    f = 'buildlog-stderr.html'
                    msg_refs[k][1].append(lf)
                elif f == stdout:
                    f = 'buildlog-stdout.html'
                    msg_refs[k][0].append(lf)
                msgs[i] = (files[f], lf, ls, msg)
    result['files'] = [''] * len(files.values())
    for k, v in files.items():
        result['files'][v] = k

    title = escape(title, quote=True)
    lead_items = ['<h1>', title, '</h1>\n<p>',
        str(arch_data['warnings']), '', ' warnings<br>\n',
        str(arch_data['errors']), '', ' errors</p>\n<pre>',
        escape(arch_data['message']), '</pre>\n']
    if parent_arch_data:
        for t, i in (('warnings', 4), ('errors', 7)):
            delta = arch_data[t] - parent_arch_data[t]
            if delta:
                lead_items[i] = ' (%+d)' % delta
    lead = ''.join(lead_items)
    css = paths.link_root() + '/css/log.css'

    def write_log(src, dst, title2, body, line_msgs):
        with open(src, 'rt') as fin:
            with open(dst, 'wt') as fout:
                fout.write('<!DOCTYPE html>\n<html><head>'
                    '<meta charset="utf-8" />\n<title>')
                fout.write(' '.join((title, title2)))
                fout.write('</title>\n<link rel="stylesheet" href="')
                fout.write(css)
                fout.write('" />\n</head><body>\n')
                fout.write(lead)
                body(fin, fout, file_linker=linker, line_msgs=line_msgs)
                fout.write('\n</body></html>')

    def gen_line_msgs(outn):
        m = 0
        for k in ('warnings', 'errors'):
            try:
                m = max(max(msg_refs[k][outn]), m)
            except ValueError:
                pass
        line_msgs = [0] * (m + 1)
        for k, v in (('warnings', 1), ('errors', 2)):
            for i in msg_refs[k][outn]:
                line_msgs[i] = v
        return line_msgs

    line_msgs = gen_line_msgs(0)
    write_log(stdout, join(dst, 'buildlog-stdout.html'), 'build stdout',
        log_analysis.htmlout, line_msgs)
    line_msgs = gen_line_msgs(1)
    write_log(stderr, join(dst, 'buildlog-stderr.html'), 'build stderr',
        log_analysis.htmlout, line_msgs)

    result['packages'] = list(result['packages'])

    messages = [''] * (max(result['messages'].values()) + 1)
    for k, v in result['messages'].items():
        messages[v] = k
    result['messages'] = messages

    with open(join(dst, 'build-result.json'), 'wt') as f:
        json.dump(result, f)

# TODO: keep modifications in sync with builder.py:_process_build
def _process_build1(stdout, dst, title, linker, arch_data, parent_arch_data):
    result = log_analysis.analyse(stdout)
    arch_data['message'] = result['failures']
    files = defaultdict(lambda: len(files))
    msg_refs = {'warnings': [[], []], 'errors': [[], []]}
    for k in ('warnings', 'errors'):
        arch_data[k] = sum(len(v) for v in result[k].values())
        for msgs in result[k].values():
            for i, v in enumerate(msgs):
                f, lf, ls, msg = v
                f = 'buildlog.html'
                msg_refs[k][0].append(lf)
                msgs[i] = (files[f], lf, ls, msg)
    result['files'] = [''] * len(files.values())
    for k, v in files.items():
        result['files'][v] = k

    title = escape(title, quote=True)
    lead_items = ['<h1>', title, '</h1>\n<p>',
        str(arch_data['warnings']), '', ' warnings<br>\n',
        str(arch_data['errors']), '', ' errors</p>\n<pre>',
        escape(arch_data['message']), '</pre>\n']
    if parent_arch_data:
        for t, i in (('warnings', 4), ('errors', 7)):
            delta = arch_data[t] - parent_arch_data[t]
            if delta:
                lead_items[i] = ' (%+d)' % delta
    lead = ''.join(lead_items)
    css = paths.link_root() + '/css/log.css'

    def write_log(src, dst, title2, body, line_msgs):
        with open(src, 'rt') as fin:
            with open(dst, 'wt') as fout:
                fout.write('<!DOCTYPE html>\n<html><head>'
                    '<meta charset="utf-8" />\n<title>')
                fout.write(' '.join((title, title2)))
                fout.write('</title>\n<link rel="stylesheet" href="')
                fout.write(css)
                fout.write('" />\n</head><body>\n')
                fout.write(lead)
                body(fin, fout, file_linker=linker, line_msgs=line_msgs)
                fout.write('\n</body></html>')

    def gen_line_msgs(outn):
        m = 0
        for k in ('warnings', 'errors'):
            try:
                m = max(max(msg_refs[k][outn]), m)
            except ValueError:
                pass
        line_msgs = [0] * (m + 1)
        for k, v in (('warnings', 1), ('errors', 2)):
            for i in msg_refs[k][outn]:
                line_msgs[i] = v
        return line_msgs

    line_msgs = gen_line_msgs(0)
    write_log(stdout, join(dst, 'buildlog.html'), 'build',
        log_analysis.htmlout, line_msgs)

    result['packages'] = list(result['packages'])

    messages = [''] * (max(result['messages'].values()) + 1)
    for k, v in result['messages'].items():
        messages[v] = k
    result['messages'] = messages

    with open(join(dst, 'build-result.json'), 'wt') as f:
        json.dump(result, f)

def process(basedir, result, parent, title, linker):
    print(basedir)
    for arch in result:
        if arch != '*':
            base = join(basedir, arch)
            resultfile = join(base, 'build-result.json')
            if exists(resultfile):
                extract_bad(resultfile, badbefore)
                parent_result = None
                if parent:
                    try:
                        parent_result = parent['result'][arch]
                    except KeyError:
                        pass
                stdout = join(base, 'buildlog-stdout.html')
                if exists(stdout):
                    newstdout = clear_html_log(stdout)
                    stderr = join(base, 'buildlog-stderr.html')
                    newstderr = clear_html_log(stderr)
                    _process_build2(newstdout, newstderr, TMPDIR,
                        title + ' [' + arch + ']', linker,
                        result[arch], parent_result)
                    move(join(TMPDIR, 'buildlog-stdout.html'), stdout)
                    move(join(TMPDIR, 'buildlog-stderr.html'), stderr)
                else:
                    stdout = join(base, 'buildlog.html')
                    newstdout = clear_html_log(stdout)
                    _process_build1(newstdout, TMPDIR,
                        title + ' [' + arch + ']', linker,
                        result[arch], parent_result)
                    move(join(TMPDIR, 'buildlog.html'), stdout)
                move(join(TMPDIR, 'build-result.json'), resultfile)
                extract_bad(resultfile, badafter)
            elif not exists(join(basedir, 'conflicts.html')):
                print('No results', base)
    db.save()

def parent(build):
    if build['parent']:
        try:
            return db.data['release'][build['parent']]
        except KeyError:
            pass
    return None

for tag, build in sorted(db.data['release'].items(), key=lambda x: x[1]['time']):
    base = paths.www('release', 'master', tag, None)
    process(base, build['result'], parent(build), 'master: ' + tag,
        log_analysis.file_link_release(tag))

for group in ('done', 'change'):
    for cid, change in db.data[group].items():
        for build in change['build']:
            base = paths.www(cid, build['version'], build['parent'], None)
            title = cid + ' v' + str(build['version']) + ' on ' + build['parent']
            linker = log_analysis.file_link_change(change['id'], build['version'])
            process(base, build['rebased'], parent(build), title, linker)
            if build['picked']:
                base = paths.www(cid, build['version'], build['parent'], None,
                    False)
                process(base, build['picked'], parent(build), title, linker)

print(len(badbefore), '->', len(badafter))
print('REMOVED', badbefore.difference(badafter))
print('NEW', badafter.difference(badbefore))
print(badafter)
