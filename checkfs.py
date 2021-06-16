#! /usr/bin/python

import os
from os.path import join

import db
import paths

db_master = set(db.data['release'].keys())
f_master = set(os.listdir(join(paths.www_root(), 'release', 'master')))

for r in db_master.difference(f_master):
    print("Ref with no file: ", r)
for r in f_master.difference(db_master):
    print("File with no ref: ", r)

db_master.intersection_update(f_master)

db_cid = set(db.data['change'].keys())
db_cid.update(db.data['done'].keys())
f_cid = set(os.listdir(paths.www_root()))
f_cid.difference_update({'release', 'builds.json', 'index.html', 'js', 'css', 'assets'})

for r in db_cid.difference(f_cid):
    print("cid with no file: ", r)
for r in f_cid.difference(db_cid):
    print("File with no cid: ", r)

for cid in db_cid.intersection(f_cid):
    db_r = set()
    try:
        change = db.data['change'][cid]
    except KeyError:
        change = db.data['done'][cid]
    for b in change['build']:
        master = b['parent']
        if master not in db_master:
            print("Unknown release:", cid, master)
        db_r.add(paths.www(cid, b['version'], master, None))
        if b['picked']:
            db_r.add(paths.www(cid, b['version'], master, None, full=False))
    f_r = set()
    for v in os.listdir(join(paths.www_root(), cid)):
        for m in os.listdir(join(paths.www_root(), cid, v)):
            f_r.add(join(paths.www_root(), cid, v, m))
    for r in db_r.difference(f_r):
        print("No file: ", r)
    for r in f_r.difference(db_r):
        print("No ref: ", r)

