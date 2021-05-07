import os
from os.path import exists, join
import tempfile


__all__ = ('preferred_root', 'link_temp_dir', 'free')


_keepalive = {}


def preferred_root():
    # TODO: also check TMPDIR, TEMP, TMP?
    d = os.getenv('XDG_RUNTIME_DIR')
    if d and exists(d):
        return d
    # TODO: also check /var/tmp, /usr/tmp?
    for d in ('/dev/shm', '/tmp'):
        if exists(d):
            return d
    return tempfile.gettempdir()


def link_temp_dir(name):
    d = preferred_root()
    d = tempfile.TemporaryDirectory(dir=d)
    os.symlink(d, name)
    _keepalive[name] = d


def free(name):
    try:
        del _keepalive[name]
    except KeyError:
        pass

