;(function (){
    'use strict';

    let builds = null;
    const compose = app.dom.compose;
    const text = app.dom.text;
    const textLink = app.dom.textLink;
    const linebreak = app.dom.linebreak;

    function releaseBasePath(tag) {
        return 'release/master/' + tag;
    }

    function changesetBasePath(change) {
        return change.tag;
    }

    function buildBasePath(build, rebased=true) {
        const components = [changesetBasePath(build.change)]
        if (rebased) {
            components.push(build.version);
        } else {
            components.push(build.version + '-sep');
        }
        components.push(build.parent.tag);
        return components.join('/');
    }

    function externalFilePath(build, file, line=0) {
        // TODO: should escape file?
        if (build.change == build) {
            const base = 'https://git.haiku-os.org/haiku/tree/' + file
                + '?id=' + build.tag;
            if (line) return base + '#n' + line;
            return base;
        } else {
            const base = 'https://review.haiku-os.org/c/haiku/+/'
                + build.change.id + '/' + build.version + '/' + file
            if (line) return base + '#' + line;
            return base;
        }
    }

    function tagsRun(change) {
        const fragment = document.createDocumentFragment();
        let have = false;
        if (change.review) {
            if (have) {
                fragment.appendChild(text(', '));
            }
            const value = ['Rejected', 'Disliked', '', 'Liked', 'Approved']
                [change.review + 2];
            const pill = text('span', value);
            pill.classList.add('pill', 'CR-' + value);
            fragment.appendChild(pill);
            have = true;
        }
        if (change.pendingComments) {
            if (have) {
                fragment.appendChild(text(', '));
            }
            const pill = text('span', 'Pending comments');
            pill.classList.add('pill', 'pending-comments');
            fragment.appendChild(pill);
            have = true;
        }
        if (change.wip) {
            if (have) {
                fragment.appendChild(text(', '));
            }
            const pill = text('span', 'WIP');
            pill.classList.add('pill', 'wip');
            fragment.appendChild(pill);
            have = true;
        }
        if (change.tags.length > 0) {
            if (have) {
                fragment.appendChild(text(', '));
            }
            fragment.appendChild(text(change.tags.join(', ')));
            have = true;
        }
        return fragment;
    }

    function releaseLinkFragment(tag) {
        const fragment = document.createDocumentFragment();
        fragment.appendChild(textLink('https://git.haiku-os.org/haiku/tree/?h='
            + tag, tag));
        if (builds.release[tag]?.result['*'].ok) {
            fragment.appendChild(text(' '));
            fragment.appendChild(compose('small',
                textLink(releaseBasePath(tag), '[build]')));
        }
        return fragment;
    }

    function loadErrors(ev) {
        const button = ev.currentTarget;
        const arch = button.dataset.arch;
        const path = button.dataset.path + '/' + arch;
        const change = button.dataset.change.split(' ');
        let build;
        if (change[1]) {
            build = builds.change[change[0]].build[change[1]];
        } else {
            build = builds.release[change[0]];
        }
        Promise.all([app.util.fetchJSON(path + '/build-result.json'),
            build.parent
            ? app.util.fetchJSON(releaseBasePath(build.parent.tag)
                + '/' + arch + '/build-result.json')
            : {warnings: {}, errors: {}, messages: [], files: []}])
        .then(values => {
            const view = document.createElement('msg-view');
            view.setMessages(values[0], values[1], path + '/',
                externalFilePath(build, ''));
            button.parentNode.replaceChild(view, button);
        })
        ;
    }

    function loadErrorsButton(build, path, arch) {
        const change = [build.change.tag];
        if (build != build.change) {
            change.push(build.change.build.indexOf(build));
        }
        const button = text('button', 'Load errors');
        button.setAttribute('type', 'button');
        button.dataset.path = path;
        button.dataset.arch = arch;
        button.dataset.change = change.join(' ');
        button.addEventListener('click', loadErrors);
        return button;
    }

    function successfulBuildDetails(build, archData, arch, rebased=true) {
        return brokenBuildDetails(build, archData, arch, rebased);
        //const fragment = buildDetailsHead(build, arch, rebased);
        //return fragment;
    }

    function _appendCountDiff(arr, diff) {
        arr.push(' (');
        if (diff == 0) {
            arr.push('=');
        } else {
            if (diff > 0) {
                arr.push('+');
            }
            arr.push(diff);
        }
        arr.push(')');
    }

    function messageCountCmp(build, arch, rebased=true) {
        let res;
        if (build == build.change) {
            res = build.result[arch];
        } else if (rebased) {
            res = build.rebased[arch];
        } else {
            res = build.picked[arch];
        }
        const w = [res.warnings, ' warnings'];
        const e = [res.errors, ' errors'];
        if (build.parent) {
            const pres = build.parent.result;
            if (pres['*'].ok) {
                _appendCountDiff(w, res.warnings - pres[arch].warnings);
                _appendCountDiff(e, res.errors - pres[arch].errors);
            }
        }
        return [e.join(''), w.join('')];
    }

    function buildDetailsHead(build, arch, rebased=true) {
        const fragment = document.createDocumentFragment();
        const change = build.change;
        const tag = change.tag;
        const lastLine = document.createDocumentFragment();
        let path;
        // TODO: dirty way to know if we have a release or a changeset
        // TODO: put the common/similar stuff into a prototype
        if (change === build) {
            fragment.appendChild(textLink(
                'https://git.haiku-os.org/haiku/tree/?h=' + tag, change.title));
            path = releaseBasePath(tag);
            lastLine.appendChild(textLink(path, tag));
        } else {
            fragment.appendChild(textLink(
                'https://review.haiku-os.org/c/haiku/+/' + change.id
                    + '/' + build.version,
                change.title));
            fragment.appendChild(textLink(changesetBasePath(change), tag));
            path = buildBasePath(build, rebased);
            lastLine.appendChild(textLink(path, 'version ' + build.version));
            if (build.picked['*'] !== undefined) {
                lastLine.appendChild(text(', '
                    + (rebased ? 'rebased' : 'cherrypicked')));
            }
        }
        lastLine.appendChild(text(', '));
        lastLine.appendChild(textLink(path + '/' + arch, arch));
        fragment.appendChild(compose('div', lastLine));
        fragment.appendChild(text(messageCountCmp(build, arch, rebased)
            .join(', ')));
        return fragment;
    }

    function brokenBuildDetails(build, archData, arch, rebased=true) {
        const fragment = buildDetailsHead(build, arch, rebased);
        fragment.appendChild(compose('pre', text('samp', archData.message)));
        let path;
        if (build === build.change) {
            path = releaseBasePath(build.tag);
        } else {
            path = buildBasePath(build, rebased);
        }
        fragment.appendChild(loadErrorsButton(build, path, arch));
        return fragment;
    }

    function archPill(cid, build, archData, arch, rebased=true) {
        let detail = null;
        let extra = null;
        let result = null;
        switch (archData.ok) {
        case null:
            extra = ' waiting';
            result = 'build-wait';
            break;
        case false:
            extra = ' broken';
            result = 'build-fail';
            detail = brokenBuildDetails(build, archData, arch, rebased);
            break;
        default:
            extra = ' ok';
            result = 'build-ok';
            detail = successfulBuildDetails(build, archData, arch, rebased);
            break;
        }
        let el;
        if (detail == null) {
            el = document.createElement('span');
            el.classList.add('build', result);
            el.appendChild(text(arch));
            el.appendChild(app.dom.hiddenText(extra));
        } else {
            const sum = document.createElement('summary');
            sum.classList.add('build', result);
            sum.appendChild(text(arch));
            sum.appendChild(app.dom.hiddenText(extra));
            el = document.createElement('details');
            el.appendChild(sum);
            detail = compose('aside', detail);
            detail.classList.add('vbox');
            el.appendChild(detail);
        }
        return el;
    }

    function releaseStateFragment(release) {
        return changesetBuildStateFragment(release.tag, release, release.result,
            true);
    }

    function changesetBuildStateFragment(cid, data, buildData, rebased) {
        if (buildData['*'].ok) {
            const fragment = document.createDocumentFragment();
            for (const arch of Object.keys(buildData)) {
                if (arch != '*') {
                    fragment.appendChild(archPill(cid, data, buildData[arch],
                        arch, rebased));
                    fragment.appendChild(text(' '));
                }
            }
            return fragment;
        }
        // TODO: might also be an already merged patch in a different form
        const conflictLink = textLink(buildBasePath(data, rebased)
            + '/conflicts.html', 'Conflict');
        if (buildData['*'].message) {
            const details = document.createElement('details');
            details.appendChild(compose('summary', conflictLink));
            details.appendChild(compose('aside', text('pre',
                buildData['*'].message)));
            return details;
        }
        return conflictLink;
    }

    function changesetStateFragment(cid, data) {
        const rebased = changesetBuildStateFragment(cid, data, data.rebased,
            true);
        if (data.picked['*'] !== undefined) {
            const fragment = document.createDocumentFragment();
            fragment.appendChild(rebased);
            const cherry = document.createElement('div');
            cherry.classList.add('cherry');
            cherry.appendChild(text('🍒'));
            cherry.appendChild(app.dom.hiddenText('cherrypicking:'));
            fragment.appendChild(cherry);
            fragment.appendChild(changesetBuildStateFragment(cid, data,
                data.picked, false));
            return fragment;
        }
        return rebased;
    }

    function lastRelease() {
        // TODO: appendTo -> replace?
        app.dom.appendTo('lastupdate', text(app.util.timeString(builds.time)));
        const release = builds.sortedReleases[0];
        app.dom.appendTo('lastrevision', releaseLinkFragment(release.tag));
        app.dom.appendTo('lastsubject', text(release.title));
        app.dom.appendTo('laststatus', releaseStateFragment(release));
    }

    function releaseTable() {
        const fragment = document.createDocumentFragment();
        for (const release of builds.sortedReleases) {
            const tag = release.tag;
            const tr = document.createElement('tr');
            tr.setAttribute('id', tag);
            tr.appendChild(compose('td', releaseLinkFragment(tag)));
            tr.appendChild(compose('td', releaseStateFragment(release)));
            tr.appendChild(compose('td', text(release.title)));
            tr.classList.add('age' + release.age);
            fragment.appendChild(tr);
        }
        app.dom.getElement('allreleases').appendChild(fragment);
    }

    function changesetBuildsTable(change) {
        const fragment = document.createElement('details');
        fragment.appendChild(text('summary', ''));
        const open = document.createElement('aside');
        open.appendChild(text('Created: '
            + app.util.timeString(change.time.create)));
        open.appendChild(linebreak());
        open.appendChild(textLink('https://review.haiku-os.org/c/haiku/+/'
            + change.id, 'Last version'));
        open.appendChild(text(': ' + app.util.timeString(change.time.version)));
        open.appendChild(linebreak());
        open.appendChild(text('Last update: '
            + app.util.timeString(change.time.update)));
        open.appendChild(linebreak());
        open.appendChild(linebreak());
        const table = document.createElement('table');
        table.appendChild(text('caption', 'Build for changeset: '
            + change.title));
        const head = document.createElement('tr');
        for (const title of ['Version', 'status', 'mode', 'master', 'queued']) {
            head.appendChild(text('th', title));
        }
        table.appendChild(compose('thead', head));
        for (const build of change.build) {
            for (const rebased of [true, false]) {
                const res = rebased ? build.rebased : build.picked;
                if (res['*'] !== undefined) {
                    const row = document.createElement('tr');
                    row.appendChild(compose('td', textLink(
                        'https://review.haiku-os.org/c/haiku/+/' + change.id
                            + '/' + build.version,
                        build.version)));
                    row.appendChild(compose('td',
                        changesetBuildStateFragment(change.tag, build, res,
                            rebased)));
                    row.appendChild(text('td', rebased
                        ? 'rebased' : 'cherrypicked'));
                    row.appendChild(compose('td', textLink(
                        releaseBasePath(build.parent.tag), build.parent.tag)));
                    row.appendChild(compose('td', textLink(
                        buildBasePath(build, rebased),
                        app.util.timeString(build.time))));
                    table.appendChild(row);
                }
            }
        }
        open.appendChild(table);
        fragment.appendChild(open);
        return fragment;
    }

    function changesetTable() {
        const fragment = document.createDocumentFragment();
        for (const k of Object.keys(builds.change).sort(
                (a,b) => builds.change[b].time.update
                    - builds.change[a].time.update)) {
            const tr = document.createElement('tr');
            tr.setAttribute('id', k);
            const change = builds.change[k];
            const expandCell = text('td', change.queue ?? '');
            tr.appendChild(expandCell);
            let age = 'age1';
            if (change.build.length > 0) {
                if (change.build.length > 1) {
                    expandCell.appendChild(changesetBuildsTable(change));
                }
                const lastbuild = change.build[0];
                tr.appendChild(text('td', app.util.timeString(lastbuild.time)));
                const parent = lastbuild.parent;
                const parentCell = compose('td',
                    textLink(releaseBasePath(parent.tag), parent.tag));
                    //textLink('#'+parent.tag, parent.tag));
                parentCell.classList.add('age'+parent.age);
                tr.appendChild(parentCell);
                tr.appendChild(compose('td',
                    changesetStateFragment(k, lastbuild)));
                if (lastbuild.version == change.version) {
                    age = 'age0';
                }
            } else {
                tr.appendChild(text('td', ''));
                tr.appendChild(text('td', ''));
                tr.appendChild(text('td', ''));
            }
            const changeCell = compose('td',
                textLink('https://review.haiku-os.org/c/haiku/+/' + change.id,
                    change.title));
            changeCell.classList.add(age);
            tr.appendChild(changeCell);
            tr.appendChild(compose('td', tagsRun(change)));
            fragment.appendChild(tr);
        }
        app.dom.getElement('changesets').appendChild(fragment);
    }

    function update() {
        app.util.fetchJSON('builds.json')
        .then(b => {
            let i = 1;
            for (const cid of b.queued) {
                b.change[cid].queue = i;
                i++;
            }
            delete b.queued;
            for (const [tag, rel] of Object.entries(b.release)) {
                rel.tag = tag;
                rel.change = rel;
                rel.parent = b.release[rel.parent];
            }
            b.sortedReleases = Object.values(b.release).sort((x, y) =>
                y.time - x.time);
            if (b.sortedReleases.length > 1) {
                let last = b.sortedReleases[1].time;
                let count = 0;
                let age = 1;
                for (const rel of b.sortedReleases) {
                    if ((count >= 5 || last - rel.time > 3 * 24 * 60 * 60)
                            && age < 3) {
                        age++;
                        count = 1;
                        last = rel.time;
                    }
                    rel.age = age;
                    count++;
                }
            }
            b.sortedReleases[0].age = 0;
            for (const group of [b.change, b.done]) {
                for (const [cid, change] of Object.entries(group)) {
                    change.tag = cid;
                    let found = change.tags.indexOf('Unresolved comments');
                    change.pendingComments = found != -1;
                    delete change.tags[found];
                    found = change.tags.indexOf('WIP');
                    change.wip = found != -1;
                    delete change.tags[found];
                    change.tags = change.tags.filter(v=>true).sort();
                    for (const build of change.build) {
                        build.change = change;
                        build.parent = b.release[build.parent];
                    }
                    change.build.reverse()
                }
            }
            builds = b;
            ///////////////
            lastRelease();
            releaseTable();
            changesetTable();
        })
        ;
    }

    app.update = update;
}());

/********* builds
change{cid}:
    id (number, oldstyle)
    tag (cid)
    title
    version
    ref
    time{}:
       create
       version
       update
    queue  (n if queued, optional)
    tags[]
    wip
    pendingComments (currently a boolean)
    review (-2...2)
    sent_review (build result)
    build[] (in descending build time order):
        parent (release object)
        change (change object)
        version
        time
        logs_only
        rebased/picked{*(prepare)/x86_64/x86_gcc2h}:
            ok: result
            warnings: n
            errors: n
            message: optional error message

done{cid}
    ...change{cid}
    lastbuild (last build time or 0)

time (last file update)
current (last hrev)
release{hrev}
    tag
    commit (sha1)
    parent (release object)
    title (subject)
    change  (itself, to make it like a change build item)
    time (build)
    age (0 for last one, 1..3 for the rest)
    result{}: result per arch

sortedReleases[releaseObject]  (in descending build time order)
*********/
