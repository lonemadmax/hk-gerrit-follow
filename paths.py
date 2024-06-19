import os
from os.path import join
from shutil import rmtree

from config import config
import tmpfs


def www_root():
    return config['www_root']

def www(change, build, job, full=True):
    return _www(change.cid, build['version'], build['parent'], job, full)

def www_release(branch, tag, job):
    return _www('release', branch, tag, job)

def _www(changeset, version, master, arch, full=True):
    version = str(version)
    if not full:
        version += '-sep'
    if arch is not None:
        return join(www_root(), changeset, version, master, arch)
    return join(www_root(), changeset, version, master)

def link_root():
    return config['link']

def www_link(path):
    root = www_root()
    if path.startswith(root):
        return link_root() + path[len(root):]
    return link_root()

def worktree():
    return config['worktree']

def build(arch):
    return join(config['build'], arch)

def buildtools(arch):
    return join(config['buildtools'], arch)

def jam():
    return config['jam']

def emulated_attributes():
    return join(tmpfs.preferred_root(), 'haiku_testbuilds')

def delete_release(branch, tag):
    rmtree(www_release(branch, tag, None), ignore_errors=True)

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
            if (f in ('build.err', 'build.out', 'boot.scr')
                    or f.startswith(('haiku.', 'haiku-'))
                    or f.endswith(('.hpkg', '.iso', '.image', '.xz', '.map'))):
                try:
                    os.remove(join(path, f))
                except FileNotFoundError:
                    pass
        try:
            os.remove(join(path, 'build', 'haiku-revision'))
        except FileNotFoundError:
            pass
    except FileNotFoundError:
        pass

