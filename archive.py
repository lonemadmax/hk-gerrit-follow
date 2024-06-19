import os
from os.path import basename, join, relpath
import tarfile
import zipfile

import paths


__all__ = ('archive',)


_EXCLUDE_DIRS = ('CVS', '.svn', '.git')


def zip(root, path, base=None, comment=None, format=zipfile.ZIP_DEFLATED):
    if base is None:
        base = basename(path)
    with zipfile.ZipFile(path+'.zip', 'w', compression=format) as zf:
        if comment is not None:
            zf.comment = bytes(comment)
        for dirname, subdirs, files in os.walk(root):
            for exc in _EXCLUDE_DIRS:
                if exc in subdirs:
                    subdirs.remove(exc)
            root_rel = join(base, relpath(dirname, root))
            zf.write(dirname, root_rel)
            for filename in files:
                zf.write(join(dirname, filename), join(root_rel, filename))


def tar(root, path, base=None, comment=None, format='xz'):
    if base is None:
        base = basename(path)
    if format is None:
        path = path + '.tar'
        format = 'w'
    else:
        path = path + '.tar.' + format
        format = 'w:' + format
    with tarfile.open(path, format) as tf:
        tf.add(root, arcname=base, filter=lambda x:
            None if basename(x.name) in _EXCLUDE_DIRS else x)


def _archive(root, path, base=None, comment=None, format='xz'):
    if format == 'zip':
        zip(root, path, base, comment)
    else:
        if format in ('', 'tar'):
            format = None
        elif format == 'gzip':
            format = 'gz'
        elif format == 'bzip2':
            format = 'bz2'
        elif format == 'lzma':
            format = 'xz'
        tar(root, path, base, comment, format)


def archive(dst, changeset, version, master, full=True):
    src_path = paths.worktree()
    dst = join(dst, 'src')
    if not full:
        version += '_sep'
    base = changeset + '_' + version + '-' + master
    comment = bytes('Changeset: ' + changeset + '\nVersion: ' + version
        + '\nOver: ' + master,
        encoding='UTF8')
    _archive(src_path, dst, base=base, comment=comment, format='xz')

