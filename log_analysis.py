from collections import defaultdict
import html
import os
from os.path import dirname, normpath, relpath
import re

from config import config
import paths


__all__ = ('analyse', 'htmlout', 'file_link_release', 'file_link_change',
    'PathTransformer', 'diff')



#ERROR
#sFile:nLine:nRow: error: sText [-Werror=sErr]
#sFile:nLine:nRow: fatal error: sFile2: No such file or directory

#WARNING
#sFile:nLine:nRow: warning: sText
#sFile:nLine: warning: sText
# where sText may or not end in [-WsWarn]

RE_COMPILER_MSG = re.compile(r'(?P<file>.*?):(?P<line>\d*):(?:(?P<row>\d*):)? '
    r'(?P<mode>warning|error|fatal error): '
    r'(?P<msg>.*?(?:\[-W(?:error=)?(?P<error>.*)\])?)$')
RE_COMPILER_MSG2 = re.compile(r'(?P<file>.*?):(?P<line>\d*):(?:(?P<row>\d*):)? '
    r'(?P<msg>.*?(?:\[-W(?:error=)?(?P<error>.*)\])?)$')
RE_SRCFILE = re.compile(r'/s/(?P<file>.*?)[:,\s$](?:(?P<line>\d+)[:,\s$])?'
    r'(?:\d+[:,\s$])?')
RE_NOTICE = re.compile(r'\b(warning|(?:fatal )error|error)\s*:.*',
    flags=re.IGNORECASE)

# Should be good enough for this
RE_URL = re.compile(r'\b\w+://[\w\./-]*\b')


class PathTransformer():
    abs_src = paths.worktree()
    build_root = paths.build('fake')
    rel_src = relpath(abs_src, start=build_root)
    build_root = dirname(build_root)
    bt_root = dirname(paths.buildtools('fake'))

    def transform_line(self, line):
        line = line.replace(self.rel_src, '/s')
        line = line.replace(self.abs_src, '/s')
        line = line.replace(self.build_root, '/b')
        line = line.replace(self.bt_root, '/t')
        return line

    def transform(self, f):
        for line in f:
            yield self.transform_line(line)


def match_error_key(s):
    if s.endswith('comparison between signed and unsigned'):
        return 'sign-compare'
    if ' be used uninitialized' in s:
        return 'maybe-uninitialized'
    if ' is used uninitialized' in s:
        return 'uninitialized'
    if s.startswith('too many arguments for format'):
        return 'format-extra-args'
    if s.endswith(' in format'):
        return 'format='
    if s.startswith('unused variable '):
        return 'unused-variable'
    if s.startswith('implicit declaration of function '):
        return 'implicit-function-declaration'
    if s.startswith('no previous prototype for '):
        return 'missing-prototypes'
    if s.startswith('pointer of type ') and s.endswith(' used in arithmetic'):
        return 'pointer-arith'
    if s.startswith(('integer overflow in expression',
            'large integer implicitly truncated')):
        return 'overflow'
    if s.endswith(' redefined'):
        return 'cpp-redefine'
    if s.endswith(' attribute directive ignored'):
        return 'attributes'
    if ' discards qualifiers ' in s:
        return 'discarded-qualifiers'
    if s.endswith(' from incompatible pointer type'):
        return 'incompatible-pointer-types'
    if s.endswith(' makes pointer from integer without a cast'):
        return 'int-conversion'
    if s.endswith(")' defined but not used"):
        return 'unused-function'
    if s.endswith("' defined but not used"):
        if s.startswith('label '):
            return 'unused-label'
        # could also be unused-const-variable=, unused-function...
        return 'unused-variable'
    if ' (arg ' in s:
        return 'format='
    if s.endswith('No such file or directory'):
        return 'file-not-found'
    if s.endswith('empty declaration'):
        # with a 'useless storage class specifier in empty declaration' in gcc8,
        # so duplicated there
        return 'empty-declaration'
    if s.endswith(' does return') or ' non-void function' in s:
        return 'return-type'
    if s.startswith('#warning '):
        return 'cpp'
    if s.startswith('initialization ') and 'int' in s:
        return 'int-conversion'
    if s.startswith('cast to pointer from integer of different size'):
        return 'int-to-pointer-cast'
    if ' clobbered ' in s:
        return 'clobbered'
    if s.endswith(' was hidden'):
        return 'hidden'
    if s.endswith(' some locales'):
        return 'locales'
    if s.startswith(('Unknown section', 'label alone ')):
        return 'assembler'
    if s.endswith(('undeclared (first use this function)', 'not declared',
            'has not been declared')):
        return 'undeclared'
    if s.startswith('no matching function for call to'):
        return 'unmatched-call'
    if ((s.startswith('prototype for') and ' does not match ' in s)
            or s.startswith('no declaration matches ')):
        return 'unmatched-prototype'
    if ' used where ' in s and ' was expected' in s:
        return 'unmatched-type'
    if s.startswith('invalid use of undefined type'):
        return 'undefined-type'
    if (s.startswith('invalid conversion') or 'cannot convert' in s
            or 'lacks a cast' in s):
        return 'invalid-conversion'
    if s.endswith('not declared in this scope'):
        return 'undeclared'
    if 'declared inside parameter list' in s:
        return 'invisible-outside'
    if s.startswith('forward declaration of '):
        return 'forward-declaration'
    if s.startswith(('parse error', 'expected ', 'lvalue required',
            'syntax error')):
        return 'parse'
    if 'has incomplete type' in s:
        return 'incomplete-type'
    if (' has no member named ' in s or ' does not have a nested type ' in s
            or 'does not name a type' in s
            or s.startswith('request for member ')):
        # TODO: ' has no member named ' may not be about types
        # seems to be about using anonymous unions/structs pre C11.
        return 'undefined-type'
    if s.startswith('too few arguments'):
        return 'too-few-arguments'
    if 'is not a pointer-to-object type' in s:
        # TODO: I don't know if this is always the same
        return 'delete-incomplete'
    if s.startswith('assignment to ') and ('float' in s or 'double' in s):
        return 'float-conversion'
    if s.startswith('incompatible implicit declaration'):
        return 'incompatible-implicit-declaration'
    if s.startswith('member initializers for'):
        return 'reorder'
    if s.startswith('invalid type') or s.endswith('with no type'):
        return 'invalid-type'
    if s.endswith('is ambiguous'):
        return 'ambiguous'
    if 'aggregate initializer' in s:
        return 'invalid-offsetof'
    if (s.startswith('conflicting types for')
            or s.endswith('redeclared as different kind of symbol')):
        return 'declaration-mismatch'
    if s.startswith('enumeration value') and s.endswith('not handled in switch'):
        return 'switch'
    if s.startswith('too many arguments'):
        return 'extra-args'
    return s


def itemize(f):
    for lineno, line in enumerate(f, start=1):
        #if line.startswith(file_prefix):
        if ' warning: ' in line or ' error: ' in line:
            match = RE_COMPILER_MSG.match(line)
            if match:
                msg = match.group('msg')
                if msg.startswith(' '):
                    continue
                error_key = match.group('error')
                if error_key is None:
                    error_key = match_error_key(msg)
                if error_key == msg:
                    if (error_key.startswith(('this is the location', 'by ',
                            'its scope is only', 'In function', 'At top level'))
                            or '/s/' in error_key or 'warning: ' in error_key):
                        continue
                    print('DDD filter?', error_key, '|', line)
                if match.group('file').startswith('/s/'):
                    file = match.group('file')[3:]
                else:
                    file = match.group('file')
                # TODO: this uses \ on Windows
                file = normpath(file)
                if match.group('mode') == 'warning':
                    type = 'WARN'
                else:
                    type = 'ERR'
                yield (type, lineno, (file, int(match.group('line')),
                    match.group('row'), msg, error_key))
            elif ('ld: warning' in line and ' needed by ' in line
                    and ' not found ' in line):
                yield ('WARN', lineno, ('ld', 0, None, line, 'lib-not-found'))
            elif line.startswith('collect2: error: ld returned'):
                # TODO: there is some specific info, but in other lines
                yield ('ERR', lineno, ('ld', 0, None, line, 'linker'))
            elif ('dprintf("dosfs error: ' not in line
                    and 'In function' not in line):
                # DEBUG
                print('DDD warn/error not matched', line)
        elif line.startswith('collect2: ld returned'):
            # TODO: there is some specific info, but in other lines
            # objects/..../bla.o: In function bla:
            # ...cpp:(...): undefined reference to ...
            # collect2: ld returned 1 exit status
            yield ('ERR', lineno, ('ld', 0, None, line, 'linker'))
        elif line.startswith("Warning: couldn't resolve catalog-access:"):
            yield ('WARN', lineno, ('catkeys', 0, None, line, 'catalog'))
        elif line.startswith('warning: using independent target'):
            yield ('WARN', lineno,
                ('jambuild', 0, None, line, 'jam-independent-target'))
        elif line.startswith('build-feature packages unavailable'):
            line, pkglist = line.split(':', maxsplit=1)
            line += ': '
            for pkg in pkglist.split():
                yield ('WARN', lineno, ('jambuild', 0, None, line + pkg,
                    'jam-unavailable-build-pkg'))
        elif (line.startswith('AddHaikuImagePackages: package')
                and line.endswith(' not available! ')):
            yield ('WARN', lineno,
                ('jambuild', 0, None, line, 'jam-unavailable-pkg'))
        elif line.startswith('warning: unknown rule '):
            yield ('WARN', lineno, ('jambuild', 0, None, line, 'jam-rule'))
        elif ((line.startswith(('...failed ', "...can't "))
                and line.endswith('...'))
                or line.startswith("don't know how to")):
            yield ('FAIL', lineno, line)
            yield ('ERR', lineno, ('jambuild', 0, None, line, 'jam-fail'))
        elif line.endswith('.hpkg: Creating the package ...'):
            yield ('PKG', lineno, line[:-len(': Creating the package ...')])
            # TODO: also get downloaded pkgs or...
            # Extracting download/git-2.26.0-2-x86_64.hpkg ...
            # Extracting ../../../../worktrees/haiku/testbuilds/src/apps/webpositive/bookmarks/WebPositiveBookmarks.zip
        elif ((line.startswith('ERROR: ') and ' dependenc' in line)
                or (line.startswith('problem') and ' nothing provides ' in line)):
            yield ('ERR', lineno,
                ('jambuild', 0, None, line, 'jam-dependencies'))
        elif line.startswith('failed: Connection timed out.'):
            # TODO?
            #wget: unable to resolve host address ‘eu.hpkg.haiku-os.org’
            yield ('ERR', lineno, ('connection', 0, None, line, 'timeout'))
        else:
            match = RE_COMPILER_MSG2.match(line)
            if match:
                msg = match.group('msg')
                if (msg.startswith(('note: ', 'required from ', ' '))
                        or 'reported only once' in msg
                        or 'for each function' in msg):
                    continue
                file = match.group('file')
                file_tokens = file.split()
                if (len(file_tokens) > 1 and '/' not in file_tokens[0]
                        or ':' in file):
                    # Probably messed output from two processes
                    #print('DDD messed line', file, '|', line)
                    continue
                error_key = match.group('error')
                if error_key is None:
                    error_key = match_error_key(msg)
                    if error_key == msg:
                        if not (msg.startswith(('In file included from ',
                                'In function', 'at this point in file',
                                'candidates are: ', 'candidate is: ',
                                'previous declaration'))
                                or 'previously defined here' in msg):
                            print('DDD should WARN?', msg, '|', line)
                        continue
                if file.startswith('/s/'):
                    file = file[3:]
                # TODO: this uses \ on Windows
                file = normpath(file)
                if (error_key in ('file-not-found', 'invalid-type', 'ambiguous',
                            'undefined-type')
                        or error_key.startswith('unmatched')
                        or 'error' in msg.lower()):
                    # TODO: a filename could have it
                    type = 'ERR'
                else:
                    type = 'WARN'
                yield (type, lineno, (file, int(match.group('line')),
                    match.group('row'), msg, error_key))


def analyse(log):
    msg_key = defaultdict(lambda: len(msg_key))
    warnings = defaultdict(list)
    errors = defaultdict(list)
    full = defaultdict(list)
    failures = []
    pkgs = set()
    for type, line, data in itemize(log):
        if type in ('WARN', 'ERR'):
            if type == 'WARN':
                d = warnings
            else:
                d = errors
            origin, origin_line, row, msg, short_msg = data
            # TODO: Some of these are in "included code" and I don't get
            # the caller. Some seem to be duplicates.
            d[origin].append((line, origin_line, msg_key[short_msg]))
            full[origin].append((line, origin_line, msg))
        elif type == 'PKG':
            pkgs.add(data)
        elif type == 'FAIL':
            failures.append(data)
        # else nothing
    return {
        'packages': pkgs,
        'failures': '\n'.join(failures),
        'messages': msg_key,
        'warnings': warnings,
        'errors': errors,
        'full': full,
    }


def file_link_release(commit):
    base = 'https://git.haiku-os.org/haiku/tree/'
    commit = '?id=' + commit
    def linker(path, line):
        url = base + path + commit
        if line is not None:
            url += '#n' + line
        return url
    return linker


def file_link_change(change_number, change_version):
    base = (config['gerrit_url'] + '/c/' + config['project'] + '/+/'
        + str(change_number) + '/' + str(change_version) + '/')
    def linker(path, line):
        url = base + path
        if line is not None:
            url += '#' + line
        return url
    return linker


def htmlout(log, fout, anchor_prefix='n', lineno=1, file_linker=None,
        line_msgs=None):
    msg_name = [None, 'warning', 'error']
    msg_class = None

    def repl_notice(m):
        return ('<span class="' + m.group(1).lower() + '">'
            + m.group(0) + '</span>')

    def repl_file(m):
        return ('<a href="' + file_linker(m.group('file'), m.group('line'))
            + '">' + m.group(0) + '</a>')

    fout.write('\n<pre><ol class="log">')
    for line in log:
        line = html.escape(line, quote=True)
        if line.endswith('.hpkg: Creating the package ...'):
            pkg = line[:-len(': Creating the package ...')]
            line = ('<a href="' + pkg + '" class="pkg">' + pkg + '</a>'
                + ': Creating the package ...')
        else:
            line = RE_URL.sub(r'<a href="\g<0>">\g<0></a>', line)
        if line_msgs:
            try:
                msg_class = msg_name[line_msgs[lineno]]
                if msg_class:
                    line2 = RE_NOTICE.sub(repl_notice, line)
                    if line != line2 and not line2.startswith('<span class'):
                        msg_class = None
                        line = line2
            except IndexError:
                line_msgs = None
                msg_class = None
        if file_linker:
            line = RE_SRCFILE.sub(repl_file, line)
        if msg_class:
            fout.write(''.join(('\n<li><samp id="', anchor_prefix, str(lineno),
                '" class="', msg_class, '">', line, '</samp>')))
        else:
            fout.write(''.join(('\n<li><samp id="', anchor_prefix, str(lineno),
                '">', line, '</samp>')))
        lineno += 1
    fout.write('\n</ol></pre>')


def diff(old, new):
    # WARNING: they may be defaultdicts that we don't want to change (esp. new),
    # so no try except KeyError.
    # TODO: use patch info for renames, line changes, etc
    removed = defaultdict(list)
    added = defaultdict(list)
    oldmsgs = defaultdict(list)
    newmsgs = defaultdict(list)
    for file, msgs in old.items():
        if file in new:
            oldmsgs.clear()
            for msg in msgs:
                oldmsgs[msg[2]].append(msg)
            newmsgs.clear()
            for msg in new[file]:
                newmsgs[msg[2]].append(msg)
            for k, v in newmsgs.items():
                size = len(v)
                oldsize = len(oldmsgs[k])
                # As bad a choice as any other
                if size > oldsize:
                    for msg in v[:size-oldsize]:
                        added[file].append(msg)
                elif size < oldsize:
                    for msg in oldmsgs[k][:oldsize-size]:
                        removed[file].append(msg)
                del oldmsgs[k]
            for k, v in oldmsgs.items():
                for msg in v[:size-oldsize]:
                    removed[file].append(msg)
        else:
            removed[file] = msgs.copy()
    for file, msgs in new.items():
        if file not in old:
            added[file] = msgs.copy()
    return removed, added

