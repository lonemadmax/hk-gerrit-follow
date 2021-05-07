import os
from os.path import join
from shutil import rmtree

import tmpfs


_BUILDER_ROOT = '/home/haiku/builder/haiku'


def www_root():
    return '/var/www/haiku/testbuild'

def www(changeset, version, master, arch, full=True):
    version = str(version)
    if not full:
        version += '-sep'
    if arch is not None:
        return join(www_root(), changeset, version, master, arch)
    return join(www_root(), changeset, version, master)

def link_root():
    return '/testbuild'

def www_link(path):
    root = www_root()
    if path.startswith(root):
        return link_root() + path[len(root):]
    return link_root()

def worktree():
    return join(_BUILDER_ROOT, 'worktrees', 'haiku', 'testbuilds')

def build(arch):
    return join(_BUILDER_ROOT, 'builds', 'haiku', 'testbuilds', arch)

def buildtools(arch):
    return join(_BUILDER_ROOT, 'builds', 'buildtools', 'master', arch)

def jam():
    return join(_BUILDER_ROOT, 'artifacts', 'buildtools', 'jam_master')

def emulated_attributes():
    return join(tmpfs.preferred_root(), 'haiku_testbuilds')

def delete_release(branch, tag):
    rmtree(www('release', branch, tag, None), ignore_errors=True)

def delete_change(cid):
    rmtree(join(www_root(), cid), ignore_errors=True)

def clean_up(path):
    """Remove some files from the directory.

    Remove artifacts from build directory.
    Just keep logs from download directory.
    """
    # TODO: maybe only objects/{catalogs,common,haiku}
    # What about tmp/ and other dangling stuff?
    # Keep at least build_packages/, download/
    rmtree(join(path, 'objects'), ignore_errors=True)
    try:
        for f in os.listdir(path):
            if (f in ('build.err', 'build.out', 'efi.map')
                    or f.startswith(('haiku.', 'haiku-'))
                    or f.endswith(('.hpkg', '.iso', '.image'))):
                try:
                    os.remove(join(path, f))
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        pass

