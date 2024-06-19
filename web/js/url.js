;(function (){
    'use strict';

    const gitbase = 'https://git.haiku-os.org/haiku/';
    const gerritbase = 'https://review.haiku-os.org/c/haiku/+/';

    // TODO: should escape paths?

    function git(view, change, path, line) {
        let tag = change.tag;
        if (tag.includes('+')) {
            // This may be an internal name for untagged releases
            tag = change.commit;
        }
        if (path) {
            let url = gitbase + view +'/' + path + '?id=' + tag;
            if (line) {
                url += '#n' + line;
            }
            return url;
        }
        return gitbase + view +'/' + '?id=' + tag;
    }

    function gerrit(change, path, line) {
        let url = gerritbase;
        if (change.hasOwnProperty('id')) {
            url += change.id;
        } else {
            // Build-specific
            url += change.change.id + '/' + change.version;
        }
        if (path) {
            url += '/' + path;
            if (line) {
                url += '#' + line;
            }
        }
        return url;
    }

    function localRelease(tag) {
        return 'release/master/' + tag;
    }

    function localChangeset(change) {
        return change.tag;
    }

    function localBuild(build, rebased=true) {
        const components = [localChangeset(build.change)]
        if (rebased) {
            components.push(build.version);
        } else {
            components.push(build.version + '-sep');
        }
        components.push(build.parent.tag);
        return components.join('/');
    }

    app.url = {
        gitTree: (change, path, line) => git('tree', change, path, line),
        gitCommit: (change) => git('commit', change),
        gerrit: gerrit,
        local: {
            release: localRelease,
            change: localChangeset,
            build: localBuild
        }
    }
}());
