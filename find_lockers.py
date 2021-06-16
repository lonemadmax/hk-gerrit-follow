#! /usr/bin/python

import db

rel = { k: ([],[],[]) for k in db.data['release'].keys() }
for k in ('change', 'done'):
    for cid, change in db.data[k].items():
        try:
            rel[change['sent_review']['parent']][2].append(cid)
        except KeyError:
            pass
        for build in change['build']:
            if build['logs_only']:
                group = 0
            else:
                group = 1
            rel[build['parent']][group].append(cid)
for k in sorted(rel.keys()):
    #print(k)
    if k == db.data['current']:
        print(k, 'current')
    for i, g in enumerate(('log', 'full', 'review')):
        for cid in rel[k][i]:
            print(k, g, cid)

