import os
import os.path
import subprocess


# HACK
# popen does not change PWD env var, and it seems it shouldn't
# That does not work nice here, with $PWD being used in the build.
# Problems with this:
# - It may (haven't tested) not work for those who import run from subprocess
#   before this is run
# - run may be called with a changed environment, and I'm overwriting PWD
# - I'm also overwriting OLDPWD, even if $PWD == cwd
# - os.environment has the env from first os import, does not reflect changes
#   outside of those made through os.environment itself


__all__ = ()


_run = subprocess.run

def _run_wrapper(*args, **kwargs):
    cwd = kwargs.get('cwd', None)
    if cwd is not None:
        env = kwargs.get('env', None)
        if env is None:
            env = os.environ.copy()
        try:
            env['OLDPWD'] = env['PWD']
        except KeyError:
            pass
        env['PWD'] = os.path.realpath(cwd)
        kwargs['env'] = env
    return _run(*args, **kwargs)

subprocess.run = _run_wrapper

