import calendar
import json
import requests
import time
from urllib.parse import quote


__all__ = ('Repo', 'Project', 'Branch', 'timestamp_to_time', 'post_review')


CACHE_CHANGES = 5 * 60


def extract_json(response):
    response.raise_for_status()
    # This could be return response.json(), but oh, thank you gerrit for
    # protecting me from evil XSSI
    text = response.text
    if text.startswith(")]}'"):
        text = text[4:]
    return json.loads(text)


def URL_encode(s):
    return quote(s, safe='')


class Branch:
    def __init__(self, project, ref, revision):
        self.repo = project.repo
        self.project = project
        self.ref = ref
        self.revision = revision
        self._last_change = time.monotonic() - CACHE_CHANGES
        self._changes = {}

    def update(self):
        r = self.repo.session.get(self.project.baseURL + 'branches/'
            + URL_encode(self.ref), params={'pp': 0})
        self.revision = extract_json(r)['revision']

    def _update_changes(self):
        now = time.monotonic()
        if now - self._last_change < CACHE_CHANGES:
            return

        query = 'project:"' + self.project.name + '" branch:"' + self.ref + '"'
        if self._changes:
            since = ''
            for change in self._changes.values():
                if change['updated'] > since:
                    since = change['updated']
            query = query + ' since:"' + since + '"'
        else:
            query = query + ' is:open'

        url = self.repo.baseURL + 'changes/'
        before = None
        get_more = True
        while get_more:
            q = query
            if before:
                q = q + ' before:"' + before + '"'
            r = self.repo.session.get(url, params={'q': q, 'pp': 0, 'o': [
                'CURRENT_REVISION', 'SKIP_MERGEABLE', 'LABELS']})
            changes = extract_json(r)

            if not changes:
                break

            last = changes[-1]
            try:
                get_more = last['_more_changes']
                del last['_more_changes']
            except KeyError:
                get_more = False

            for change in changes:
                if change['status'] == 'NEW':
                    change['Branch'] = self
                    if 'work_in_progress' not in change:
                        change['work_in_progress'] = False
                    self._changes[change['change_id']] = change
                else:
                    try:
                        # Won't have its update time later...
                        del self._changes[change['change_id']]
                    except KeyError:
                        pass

        self._last_change = now

    def get_changes(self):
        self._update_changes()
        return self._changes

    def get_change(self, cid):
        self._update_changes()
        return self._changes[cid]


class Project:
    def __init__(self, repo, baseURL, name, pid):
        self.repo = repo
        self.baseURL = baseURL + 'projects/' + pid + '/'
        self.name = name
        self.id = pid
        self._got_prop = False

    def __getattr__(self, key):
        if key == 'branches':
            self._get_branches()
            return self.branches
        elif self._got_prop:
            raise AttributeError(key)
        else:
            r = self.repo.session.get(self.baseURL, params={'pp': 0})
            for k, v in extract_json(r).items():
                setattr(self, k, v)
            try:
                self.parent = self.repo.projects[self.parent]
            except AttributeError:
                self.parent = None
            return getattr(self, key)

    def _get_branches(self):
        r = self.repo.session.get(self.baseURL + 'branches/', params={'pp': 0})
        self.branches = { b['ref']: Branch(self, b['ref'], b['revision'])
            for b in extract_json(r) }

    def get_repo_url(self):
        return self.repo.baseURL + self.name


class Repo:
    def __init__(self, baseURL):
        if baseURL.endswith('/'):
            self.baseURL = baseURL
        else:
            self.baseURL = baseURL + '/'
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})
        self.projects = {}
        self._get_projects()

    def _get_projects(self):
        r = self.session.get(self.baseURL + 'projects/', params={'pp': 0})
        projects = extract_json(r)
        delkeys = set()
        for name in self.projects:
            if name in projects:
                del projects[name]
            else:
                delkeys.add(name)
        for name in delkeys:
            del self.projects[name]
        for name, data in projects.items():
            self.projects[name] = Project(self, self.baseURL, name, data['id'])


def timestamp_to_time(s):
    # Timestamps are given in UTC and have the format "'yyyy-mm-dd hh:mm:ss.fffffffff'" where "'ffffffffff'" represents nanoseconds.
    return int(calendar.timegm(time.strptime(s[:19], '%Y-%m-%d %H:%M:%S')))


def post_review(change, review, auth, quiet=False):
    repo = change['Branch'].repo
    r = repo.session.post(repo.baseURL + 'a/changes/' + change['change_id']
        + '/revisions/' + change['current_revision'] + '/review',
        json=review, auth=auth)
    try:
        return extract_json(r)
    except requests.exceptions.HTTPError:
        if quiet:
            return None
        raise

