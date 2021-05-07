import git
import os
from os.path import join

import paths


__all__ = ('get_repo', 'get_worktrees', 'update', 'history', 'track',
    'decorate_with_tags', 'decorate', 'format_patch', 'commit_from_git_file')


def _clone(url, path):
    repo = git.Repo.clone_from(url, path, no_checkout=True)
    null_object = repo.git.hash_object('-t', 'tree', '/dev/null')
    empty_tree = repo.git.commit_tree('-m', 'empty tree', null_object)
    empty_head = repo.create_head('EMPTY_HEAD', empty_tree)
    empty_head.checkout()
    return repo


def get_repo():
    return git.Repo(paths.worktree(), expand_vars=False)


def get_worktrees(repo):
    wt = []
    cur = {'flags': set()}
    for line in repo.git.worktree('list', '--porcelain').split('\n'):
        if line:
            spc = line.find(' ')
            if spc >= 0:
                cur[line[:spc]] = line[spc+1:]
            else:
                cur['flags'].add(line)
        else:
            wt.append(cur)
            cur = {'flags': set()}
    return wt


def update(repo, fetch_only=False):
    for remote in repo.remotes:
        remote.fetch()

    worktrees = {}
    for w in get_worktrees(repo):
        if w['branch'].startswith('refs/heads/'):
            branch_name = w['branch'][11:]
            w['branch_name'] = branch_name
            worktrees[branch_name] = w
        else:
            raise Exception('Unexpected ref in worktree: ' + str(w))

    changes = []
    for branch in repo.branches:
        tracking_branch = branch.tracking_branch()
        if tracking_branch is None:
            continue
        try:
            w = worktrees.pop(branch.name)
        except KeyError:
            fake_wt = {
                'flags': set(),
                'worktree': None,
                'branch': branch.path,
                'branch_name': branch.name,
                'HEAD': branch.commit.hexsha
            }

            if branch.commit != tracking_branch.commit:
                if not fetch_only:
                    branch.set_commit(tracking_branch.commit)
                fake_wt['FETCH'] = tracking_branch.commit
                changes.append(fake_wt)
            else:
                if fake_wt['branch'].startswith('refs/heads/'):
                    worktrees[fake_wt['branch_name']] = fake_wt

            continue

        if w['HEAD'] != branch.commit.hexsha:
            raise Exception('Unexpected commit in worktree: ' + str(w)
                + ' should be ' + branch.commit.hexsha)

        if branch.commit != tracking_branch.commit:
            head = git.Repo(w['worktree']).head
            commit = head.reference.tracking_branch().commit
            if not fetch_only:
                head.set_commit(commit, index=True, working_tree=True)
                head.ref.checkout(force=True)
            w['FETCH'] = commit
            changes.append(w)

    return changes, worktrees


def history(a, b, repo):
    # Commits reacheable from a that are not reacheable from b: a..b
    # returns newest last
    first = repo.commit(a)
    last = repo.commit(b)
    # Don't check ancestry
    #if not repo.is_ancestor(first, last):
    h = list(repo.iter_commits(first.hexsha+'..'+last.hexsha, topo_order=True))
    h.reverse()
    return h


def track(repo, branch, ref):
    if branch in repo.branches:
        branch = repo.branches[branch]
    else:
        branch = repo.create_head(branch)
    tracking = branch.tracking_branch()
    if tracking is None or tracking.remote_head != ref:
        for remote in repo.remotes:
            try:
                tracking = remote.refs[ref]
                branch.set_tracking_branch(tracking)
                break
            except IndexError:
                pass
        else:
            raise IndexError('remote ref not found', ref)
    branch.set_commit(tracking)
    return branch


def decorate_with_tags(commits):
    # SLOW with many tags
    if not commits:
        return []
    repo = commits[0].repo
    tagged = {}
    for commit in commits:
        if commit.repo != repo:
            raise ValueError('Commits from different repos')
        tagged[commit] = []
    tags = repo.tags
    for t in tags:
        tagged_commit = t.commit
        try:
            tagged[tagged_commit].append(t.name)
        except KeyError:
            pass
    return [(c, t) for c, t in tagged.items()]


def decorate(commit, exact=True):
    if exact:
        try:
            name = commit.repo.git.describe(commit.hexsha, tags=True,
                exact_match=True)
            return name
        except git.exc.CommandError:
            return None
    else:
        try:
            name = commit.repo.git.describe(commit.hexsha, tags=True, long=True)
            return name[:name.rfind('-')]
        except git.exc.CommandError:
            return commit.hexsha


def format_patch(repo, rev, outdir, **kwargs):
    patches = (repo.git.format_patch(rev, o=outdir, numstat=True, **kwargs)
        .split('\n'))
    if patches[0] == '':
        return []
    return patches


def commit_from_git_file(repo, *file):
    file = join(repo.git_dir, *file)
    try:
        with open(file, 'rt') as f:
            return repo.commit(f.readline().strip())
    except FileNotFoundError:
        return None


def currently_replaying(self):
    commit = self.currently_rebasing_on()
    if commit is None:
        commit = commit_from_git_file(self, 'rebase-apply', 'original-commit')
        if commit is None:
            # Cherry-picking?
            commit = commit_from_git_file(self, 'CHERRY_PICK_HEAD')
    return commit

# TODO: monkey patching
git.Repo.currently_replaying = currently_replaying

