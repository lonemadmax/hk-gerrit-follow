__all__ = ('changes', 'changeid', 'set_base_commit', 'update_changes',
    'fetch_changes')

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

    def __init__(self, change, base=_base_commit):
        self.cid = change.cid
        self.version = change['version']
        self.branch = change.branch
        self.ref = change['ref']
        self.remote = change.remote
        self.base = base
        self.rebased_conflicting = None
        self.rebased_conflicts = []
        self.pick_conflicts = []
        self.uploaded_chain = []
        self._state = Change._NEW

        changes[self.cid] = self

        self._check_fetched()
        if self._state < Change._FETCHED:
            self.rebased = None
            self.picked = None
            return

        try:
            branch_name = self.picked_branch_name()
            self.picked = REPO.heads[branch_name].commit
            if REPO.merge_base(self.picked, base) != base:
                self.picked = None
                REPO.delete_head(branch_name, self.rebased_branch_name(),
                                force=True)
        except IndexError:
            self.picked = None
        try:
            branch_name = self.rebased_branch_name()
            self.rebased = REPO.heads[branch_name].commit
            if (self.picked is None
                    and REPO.merge_base(self.rebased, base) != base):
                self.rebased = None
                REPO.delete_head(branch_name, force=True)
        except IndexError:
            self.rebased = None
        if self.rebased is not None:
            self._state = Change._REBASED
        elif self.picked is not None:
            self._state = Change._PICKED

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

    def update(self, change=None, base=_base_commit):
        if change is not None:
            if self.cid != change.cid:
                raise Exception("updated with different cid: "
                    + self.cid + " -> " + change.cid)
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
            if self.rebased is not None:
                REPO.delete_head(self.rebased_branch_name(), force=True)
                self.rebased = None
        if self._state > Change._FETCHED >= state:
            self.pick_conflicts.clear()
            if self.picked is not None:
                REPO.delete_head(self.picked_branch_name(), force=True)
                self.picked = None
        if self._state > Change._NEW >= state:
            self.fetched = None
            self._rebuild_uploaded_chain()
        self._state = state
        self._downgrade_children()

    def fetched_branch_name(self):
        return builder.changeset_branch_name(self.cid, self.version)

    def picked_branch_name(self):
        return self.fetched_branch_name() + '-pick'

    def rebased_branch_name(self):
        return self.fetched_branch_name() + '-rebase'

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
        head = REPO.head.ref
        branch = REPO.create_head(branch_name, base)
        branch.checkout(force=True)
        try:
            REPO.git.cherry_pick(self.fetched)
            return (REPO.heads[branch_name].commit, None)
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
                        REPO.create_head(branch_name, self.rebased)
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

    def check_rebased_branch(self):
        if self._state < Change._REBASED:
            return
        chain = []
        for commit in gitutils.history(self.base, self.rebased, REPO)[:-1]:
            cid = self._get_cid(commit)
            try:
                change = changes[cid]
            except KeyError:
                # TODO: it'd be nice if we hinted the builder that this is
                # now as if the change had a new version. Also in the other
                # case down here and for all children when a change is deleted.
                self._downgrade(Change._PICKED)
                return
            if change.rebase != commit:
                self._downgrade(Change._PICKED)
                return
            chain.append(cid)
        if chain != self.active_chain():
            self._downgrade(Change._PICKED)
            return


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
    new = []

    for change in db.active_changes():
        cid = change.cid
        active.add(cid)
        try:
            changes[cid].update(change)
        except KeyError:
            changes[cid] = Change(change)
            new.append(changes[cid])

    for cid in list(changes.keys()):
        if cid not in active:
            changes[cid].delete()
            del changes[cid]

    fetch_changes([change for change in changes.values()
        if change._state < Change._FETCHED])

    # Say we had A>B from a previous run, both rebased, and B is updated (or
    # merged, or abandoned) while we are not running. When we run again we'll
    # see the rebase branch for A and mark it as REBASED, but it will be on
    # top of an old B.
    for change in new:
        if change._state > Change._PICKED:
            change.check_rebased_branch()


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

