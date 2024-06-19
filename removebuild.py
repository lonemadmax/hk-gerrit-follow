#! /usr/bin/python

import argparse
import os
from os.path import exists
from shutil import rmtree

from config import config
import db
import paths


def pop_master(builds, hrev):
    for i, v in enumerate(builds):
        if v['parent'] == hrev:
            return builds.pop(i)
    return None


def remove_changeset(cid, hrev):
    try:
        change = db.data['change'][cid]
    except KeyError:
        change = db.data['done'][cid]
    old = pop_master(change['build'], hrev)
    if old is None:
        raise Exception('Unknown build')
    rmtree(paths.www(change, old, None), ignore_errors=True)
    if old['picked']:
        rmtree(paths.www(change, old, None, full=False), ignore_errors=True)


def remove_master(hrev):
    if hrev not in db.data['release']:
        raise Exception('Unknown revision')
    if hrev == db.data['current']:
        raise Exception('Current revision')
    for group in ('done', 'change'):
        for cid, change in db.data[group].items():
            old = pop_master(change['build'], hrev)
            if old is not None:
                rmtree(paths.www(change, old, None), ignore_errors=True)
                if old['picked']:
                    rmtree(paths.www(change, old, None, full=False),
                        ignore_errors=True)
    paths.delete_release(config['branch'], hrev)
    del db.data['release'][hrev]
                

parser = argparse.ArgumentParser()
parser.add_argument('changeset', help='change id or hrev')
parser.add_argument('hrev', nargs='?', help='hrev, non-optional for changesets')
args = parser.parse_args()

if not exists('stop.please'):
    # TODO: this is no guarantee
    raise Exception('Make sure the main process is not running')

if args.hrev is None:
    remove_master(args.changeset)
else:
    remove_changeset(args.changeset, args.hrev)

db.save()

