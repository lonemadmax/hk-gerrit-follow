import os
import os.path
import subprocess
import tempfile

from config import config
import paths
import subprocess_wrapper


__all__ = ('jam',)


def jam(wd, target, options=None, quick=False, jam_cmd=None, output=None):
    if jam_cmd is None:
        jam_cmd = paths.jam()
    args = [jam_cmd]

    if quick:
        args.append('-q')
    else:
        try:
            i = min(len(os.sched_getaffinity(0)), config['max_jobs'])
            if i > 1:
                args.append('-j' + str(i))
        except:
            pass

    if options:
        args.extend(options)

    if isinstance(target, str):
        args.append(target)
        basefile = target
    else:
        args.extend(target)
        basefile = target[0]

    if not output:
        output = ''.join([c for c in basefile if c.isalnum()])
        if output:
            output = os.path.join(wd, output) + '.out'
    if output:
        out = open(output, mode='wb')
    else:
        out, output = tempfile.mkstemp(suffix='.out', prefix='jam', dir=wd)

    cp = subprocess.run(args, stdout=out, stderr=subprocess.STDOUT, cwd=wd)
    out.close()
    return cp, output

