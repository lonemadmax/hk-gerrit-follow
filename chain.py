__all__ = ('changes', 'changeid', 'set_base_commit', 'update_changes',
    'fetch_changes', 'delete_obsolete_branches')

from collections import defaultdict

import builder
import config
import db
import gitutils


REPO = gitutils.get_repo()

# TODO: we are not checking that all the changes in a chain have the same base
# when we build them. Maybe we should just have a global base, old_base and no
# instance base. Or keep the instance ones, remove _base_commit and check
# against db each time pick() and rebase() are called.
_base_commit = db.data['current']

changes = {}    # cid: Change
_children = defaultdict(set)	# cid: set(cid, cid, cid) (changes containing key)
_hexsha_to_cid = {}


class Change:
    _DELETED         =  0
    _NEW             = 10 # New version
    _FETCHED         = 20 # Fetched from gerrit
    _PICKED          = 30 # Cherrypicked (or found conflicts in doing so) to master
    _CONFLICT_PARENT = 40 # Conflict "rebasing" to master in a parent change
    _CONFLICT        = 50 # Conflict "rebasing" to master
    _REBASED         = 60 # "Rebased" to master

    def __init__(self, change, base=None):
        self.cid = change.cid
        self.number = change['id']
        self.version = change['version']
        self.branch = change.branch
        self.ref = change['ref']
        self.remote = change.remote
        if base is None:
            base = _base_commit
        self.base = base
        self.rebased_conflicting = None
        self.rebased_conflicts = []
        self.rebased = None
        self.picked = None
        self.pick_conflicts = []
        self.uploaded_chain = []
        self._state = Change._NEW

        changes[self.cid] = self

        self._check_fetched()
        # We may not have info about parents yet, so leave the rebase branch
        # for later, when we need it. We may look for the picked one, or just
        # pick(), but we don't really need to now.

    def _rebuild_uploaded_chain(self):
        for cid in self.uploaded_chain:
            _children[cid].discard(self.cid)
        self.uploaded_chain.clear()

        if self.fetched is not None:
            for commit in gitutils.history(self.base, self.fetched, REPO)[:-1]:
                cid = self._get_cid(commit)
                if cid is not None:
                    self.uploaded_chain.append(cid)
                    _children[cid].add(self.cid)

    def _get_cid(self, commit):
        hexsha = commit.hexsha
        try:
            return _hexsha_to_cid[hexsha]
        except KeyError:
            cid = changeid(commit)
            if cid is None:
                cid = self.branch.change_for_commit_sha(hexsha)
            _hexsha_to_cid[hexsha] = cid
            return cid

    def update(self, change=None, base=None):
        if base is None:
            base = _base_commit
        if change is not None:
            if self.cid != change.cid:
                raise Exception("updated with different cid: "
                    + self.cid + " -> " + change.cid)
            if self.number != change['id']:
                raise Exception("updated with different id: "
                    + str(self.number) + " -> " + str(change['id']))
            if self.branch != change.branch:
                raise Exception("updated with different branch: "
                    + self.branch.ref + " -> " + change.branch.ref)
            if change['version'] != self.version:
                self.base = base
                self._downgrade(Change._NEW)
                self.version = change['version']
            self.ref = change['ref']
        if base != self.base:
            self.base = base
            self._downgrade(Change._FETCHED)

    def _downgrade_children(self):
        for cid in _children[self.cid]:
            try:
                changes[cid]._downgrade(Change._PICKED)
            except KeyError:
                pass

    def _downgrade(self, state):
        if self._state <= state:
            return
        if self._state > Change._PICKED >= state:
            self.rebased_conflicting = None
            self.rebased_conflicts.clear()
            self.rebased = None
        if self._state > Change._FETCHED >= state:
            self.pick_conflicts.clear()
            self.picked = None
        if self._state > Change._NEW >= state:
            self.fetched = None
            self._rebuild_uploaded_chain()
        self._state = state
        self._downgrade_children()

    def fetched_branch_name(self):
        return builder.changeset_branch_name(self.cid, self.version)

    def picked_branch_name(self):
        return (builder.changeset_branch_name(self.cid, 'd/')
            + self.base + ',' + self.version_signature())

    def rebased_branch_name(self):
        return (builder.changeset_branch_name(self.cid, 'd/')
            + self.base + ',' + self.chain_signature())

    def version_signature(self):
        return '{:03x}'.format(self.version)

    def chain_signature(self):
        signature = [self.version_signature()]
        if self.fetch():
            for cid in self.active_chain()[:-1]:
                change = changes[cid]
                signature.append('{0:x}{1:03x}'.format(
                    change.number, change.version))
        return ','.join(signature)

    def delete(self):
        if self._state <= Change._DELETED:
            return
        self._downgrade(Change._DELETED)

    def _forced_fetch_refspec(self):
        return '+' + self.ref + ':' + self.fetched_branch_name()

    def _check_fetched(self):
        if self._state >= Change._FETCHED:
            return
        branch_name = self.fetched_branch_name()
        try:
            self.fetched = REPO.heads[branch_name].commit
            _hexsha_to_cid[self.fetched.hexsha] = self.cid
            self._state = Change._FETCHED
            self._rebuild_uploaded_chain()
        except IndexError:
            self.fetched = None

    def fetch(self):
        if self._state < Change._NEW:
            return None
        if self._state < Change._FETCHED:
            gitutils.get_remote(REPO, self.remote, 'anonymous').fetch(
                self._forced_fetch_refspec())
            self._check_fetched()
        return self.fetched

    def _pick_on_top(self, base, branch_name):
        if self.fetch() is None:
            return (None, None)
        try:
            return (REPO.heads[branch_name].commit, [])
        except IndexError:
            pass
        branch = REPO.create_head(branch_name, base)
        branch.checkout(force=True)
        try:
            REPO.git.cherry_pick(self.fetched)
            return (REPO.heads[branch_name].commit, [])
        except:
            conflicts = list(REPO.index.unmerged_blobs())
            REPO.git.cherry_pick(abort=True)
            gitutils.checkout_detached_head(REPO, self.fetched)
            REPO.delete_head(branch_name, force=True)
            return (None, conflicts)

    def pick(self):
        if self._state < Change._PICKED:
            tip_commit = self.fetch()
            if tip_commit:
                self._state = Change._PICKED
                branch_name = self.picked_branch_name()
                if tip_commit.parents[0] == self.base:
                    branch = REPO.create_head(branch_name, tip_commit)
                    self.picked = tip_commit
                else:
                    self.picked, self.pick_conflicts = self._pick_on_top(
                        self.base, branch_name)

        return (self.picked, self.pick_conflicts)

    def rebase(self):
        if self._state < Change._REBASED:
            self.pick()
            self.rebased_conflicting = None
            self.rebased_conflicts.clear()
            if self.fetched:
                branch_name = self.rebased_branch_name()
                try:
                    self.rebased = REPO.heads[branch_name].commit
                    self._state = Change._REBASED
                except IndexError:
                    base = self.active_parent()
                    if base:
                        tip_commit, _, conflicting = changes[base].rebase()
                        if conflicting:
                            self._state = Change._CONFLICT_PARENT
                            self.rebased_conflicting = conflicting
                        else:
                            self.rebased, self.rebased_conflicts = \
                                self._pick_on_top(tip_commit, branch_name)
                            if self.rebased:
                                self._state = Change._REBASED
                            else:
                                self._state = Change._CONFLICT
                                self.rebased_conflicting = self.cid
                    else:
                        self.rebased = self.picked
                        self.rebased_conflicts.extend(self.pick_conflicts)
                        if self.rebased:
                            self._state = Change._REBASED
                            # pick and rebase branches have the same name
                            #REPO.create_head(branch_name, self.rebased)
                        else:
                            self._state = Change._CONFLICT
                            self.rebased_conflicting = self.cid

        return (self.rebased, self.rebased_conflicts, self.rebased_conflicting)

    def active_parent(self):
        if self.fetch() is None:
            return None
        for cid in reversed(self.uploaded_chain):
            try:
                if changes[cid].fetch():
                    return cid
            except KeyError:
                pass
        return None

    def active_chain(self):
        chain = []
        if self.fetch() is None:
            return chain
        parent = self.cid
        while parent is not None:
            chain.append(parent)
            parent = changes[parent].active_parent()
        chain.reverse()
        return chain

    def containing_chains(self):
        if self.fetch() is None:
            return []
        chains = [self.active_chain()]
        sets = [set(chains[0])]
        for cid in _children[self.cid]:
            try:
                candidate = changes[cid].active_chain()
            except IndexError:
                continue
            if self.cid not in candidate:
                continue
            candidate_set = set(candidate)
            for i, chain in enumerate(sets):
                if candidate_set.issuperset(chain):
                    chains[i] = candidate
                    sets[i] = candidate_set
                    break
                if candidate_set.issubset(chain):
                    break
            else:
                chains.append(candidate)
                sets.append(candidate_set)
        return chains


def changeid(commit):
    cid = None
    for trailer in gitutils.trailers_list(commit.message):
        key = trailer[0].lower()
        if key == 'change-id':
            value = trailer[1]
        elif key == 'link':
            # The commit-msg hook uses $reviewURL/id/I$hashlooks
            # and looks for .*/id/I[0-9a-f]{40}
            prefix = config['gerrit_url']
            if prefix[-1] == '/':
                prefix += 'id/'
            else:
                prefix += '/id/'
            if not trailer[1].startswith(prefix):
                continue
            value = trailer[1][len(prefix):]
            if len(value) < 41:
                continue
            if value[0] != 'I':
                continue
            if [c for c in value[1:]
                    if not (('0' <= c <= '9') or ('a' <= c <= 'f'))]:
                continue
        else:
            continue
        if cid and cid != value:
            raise Exception("commit " + commit.hexsha + " reports several Change-ids")
        cid = value
    return cid


def set_base_commit(commit):
    global _base_commit
    if commit != _base_commit:
        _base_commit = commit
        for change in changes.values():
            change.update()


def update_changes():
    global _base_commit
    _base_commit = db.data['current']

    active = set()

    for change in db.active_changes():
        cid = change.cid
        active.add(cid)
        try:
            changes[cid].update(change)
        except KeyError:
            changes[cid] = Change(change)
            # In case an abandoned change is resurrected
            changes[cid]._downgrade_children()

    for cid in list(changes.keys()):
        if cid not in active:
            changes[cid].delete()
            # TODO: do we really want to get rid of this?
            del changes[cid]

    fetch_changes([change for change in changes.values()
        if change._state < Change._FETCHED])

    delete_obsolete_branches()


def fetch_changes(changes):
    urls = defaultdict(list)
    for change in changes:
        if change._state < Change._FETCHED:
            urls[change.remote].append(change)
    for url, changes in urls.items():
        refspecs = []
        for change in changes:
            refspecs.append(change._forced_fetch_refspec())
        gitutils.get_remote(REPO, url, 'anonymous').fetch(refspecs)
        # TODO: check flags in the FetchInfo items returned by fetch()?
        for change in changes:
            change._check_fetched()


def delete_obsolete_branches(keep=10):
    index = {}
    for change in changes.values():
        current_prefix = change.picked_branch_name()
        prefix = current_prefix.split('/')[0]
        used = []
        used.append(current_prefix)
        for group in ('change', 'done'):
            try:
                for build in db.data[group][change.cid]['build']:
                    used.append(build['parent'] + ','
                        + '{:03x}'.format(build['version']))
            except KeyError:
                pass
        index[prefix] = (used, [])
    for branch in REPO.heads:
        name = branch.name.split('/')
        if len(name) == 2:
            try:
                used, obsolete = index[name[0]]
                for prefix in used:
                    if name[1].startswith(prefix):
                        break
                else:
                    obsolete.append(branch)
            except KeyError:
                pass
    delete = []
    if keep:
        for _, obsolete in index.values():
            if len(obsolete) > keep:
                delete.extend(sorted(obsolete, key=lambda b: b.name)[:-keep])
    else:
        for _, obsolete in index.values():
            delete.extend(obsolete)
    if obsolete:
        REPO.delete_head(*obsolete, force=True)

