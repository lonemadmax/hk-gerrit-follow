import os
from os.path import join

import paths


__all__ = ('get_arch_prefixes',)


def get_arch_prefixes(branch, arch):
    bpath = paths.buildtools(arch)
    if arch == 'x86_gcc2h':
        prefix = ['x86_gcc2', 'x86']
    else:
        prefix = [arch]
    for i, p in enumerate(prefix):
        base_prefix = []
        p = join(bpath, 'cross-tools-'+p, 'bin')
        for f in os.listdir(p):
            pos = f.find('-haiku-')
            if pos > -1:
                f_prefix = f[:pos+7]
                if f_prefix in base_prefix:
                    prefix[i] = join(p, f_prefix)
                    break
                else:
                    base_prefix.append(f_prefix)
        else:
            raise Exception('Could not find buildtools prefix for ' + arch
                + ' in ' + branch)
    return prefix

