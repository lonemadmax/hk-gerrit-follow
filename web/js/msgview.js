; (function (){
    'use strict';

    const compose = app.dom.compose;
    const text = app.dom.text;
    const textLink = app.dom.textLink;

    function markNew(old, current) {
        // TODO: this is still not good.
        // Errors with line 0 will point to whichever, for example.
        while (old.length) {
            const f = (a, b) => Math.abs(a.line - b.line);
            let bestOld = 0;
            let bestCurrent = 0;
            let best = f(old[0], current[0]);
            for (let iOld = 0; iOld < old.length; iOld++) {
                for (let iCur = 0; iCur < current.length; iCur++) {
                    const v = f(old[iOld], current[iCur]);
                    if (v < best) {
                        bestOld = iOld;
                        bestCurrent = iCur;
                        best = v;
                    }
                }
            }
            old[bestOld] = old[old.length - 1];
            old.length--;
            current[bestCurrent] = current[current.length - 1];
            current.length--;
        }
        for (const msg of current) {
            msg.new = true;
        }
    }

    class MsgView extends HTMLElement {
        constructor() {
            super();
            this._onlyError = document.createElement('input');
            this._onlyNew = document.createElement('input');
            this._current = text('samp', '');
            this._msgType = {};
            this._msgList = document.createElement('ul');
            this._msgs = [];
            this._msgTable = document.createElement('tbody');

            const style = document.createElement('link');
            style.setAttribute('rel', 'stylesheet');
            style.setAttribute('href', 'css/msgview.css');
            const shadow = this.attachShadow({mode: 'open'});
            shadow.appendChild(style);
            const content = document.createDocumentFragment();

            this._onlyError.setAttribute('type', 'checkbox');
            this._onlyError.checked = false;
            this._onlyError.addEventListener('change', () => this.update());
            let label = compose('label', this._onlyError);
            label.appendChild(text('Only errors'));
            content.appendChild(label);

            this._onlyNew.setAttribute('type', 'checkbox');
            this._onlyNew.checked = true;
            this._onlyNew.addEventListener('change', () => this.update());
            label = compose('label', this._onlyNew);
            label.appendChild(text('Only new'));
            content.appendChild(label);

            const up = text('button', '⬆');
            up.addEventListener('click', (ev) => this.navigate('..'));
            const block = compose('div', up);
            block.appendChild(text(' '));
            // TODO: editable?
            block.appendChild(this._current);
            content.appendChild(block);

            const errors = document.createElement('div');
            errors.setAttribute('id', 'errors');

            errors.appendChild(compose('div', compose('table', this._msgTable)));
            this._msgTable.addEventListener('click', (ev) => {
                const row = ev.target.closest('tr');
                if (row && !row.classList.contains('no-navigate')) {
                    this.navigate(row.childNodes[0].textContent);
                }
            });

            errors.appendChild(this._msgList);
            this._msgList.setAttribute('id', 'msgtypes');
            this._msgList.addEventListener('click', (ev) => {
                const item = ev.target.closest('li');
                if (item) {
                    const msgData = this._msgType[item.textContent];
                    msgData.active = !msgData.active;
                    item.dataset.active = msgData.active;
                    this.update();
                }
            });

            content.appendChild(errors);
            shadow.appendChild(content);
        }

        update() {
            for (const msg of Object.values(this._msgType)) {
                msg.count = 0;
            }
            const prefix = this._current.textContent;
            const prefixLength = prefix.length;
            const onlyError = this._onlyError.checked;
            const onlyNew = this._onlyNew.checked;
            const msgs = [];
            let current = { path: [], msgs: []};
            let dir = false;
            for (const msg of this._msgs) {
                if (onlyError && !msg.error) continue;
                if (onlyNew && !msg.new) continue;
                if (!msg.file.startsWith(prefix)) continue;
                const msgData = this._msgType[msg.msg];
                msgData.count++;
                if (msgData.active) {
                    const path = msg.file.substring(prefixLength).split('/');
                    let step = 0;
                    while (step < current.path.length
                            && current.path[step] === path[step]) {
                        step++;
                    }
                    if (step) {
                        current.msgs.push(msg);
                        if (step < current.path.length) {
                            current.path.length = step;
                            dir = true;
                        }
                    } else {
                        if (current.msgs.length) {
                            msgs.push(current);
                            if (dir) {
                                current.path.push('');
                            }
                        }
                        dir = false;
                        current = { path: path, msgs: [msg]};
                    }
                }
            }
            if (current.msgs.length) {
                msgs.push(current);
                if (dir) {
                    current.path.push('');
                }
            }

            /* TODO: only when we are moving up
             * We can find it also when selecting msg types
            if (prefix && msgs.length <= 1) {
                this.navigate('..');
                return;
            }
            */

            for (const msg of Object.values(this._msgType)) {
                msg.element.dataset.count = msg.count;
            }

            const fragment = document.createDocumentFragment();
            for (const msg of msgs) {
                const path = msg.path.join('/');
                const row = document.createElement('tr');
                if (path.endsWith('/')) {
                    row.appendChild(text('td', path));
                } else {
                    row.classList.add('no-navigate');
                    const cell = compose('details', text('summary', path));
                    row.appendChild(compose('td', cell));
                    const list = document.createElement('ul');
                    for (const imsg of msg.msgs) {
                        const li = document.createElement('li');
                        li.classList.add(imsg.error ? 'error' : 'warning');
                        if (imsg.line) {
                            li.appendChild(textLink(
                                this._baseExternal(imsg.file, imsg.line),
                                'line ' + imsg.line));
                            li.appendChild(text(': '));
                        }
                        li.appendChild(textLink(this._baseLocal
                            + imsg.log + '#n' + imsg.logline,
                            imsg.msg));
                        list.appendChild(li);
                    }
                    cell.appendChild(list);
                }
                row.appendChild(text('td', msg.msgs.length));
                fragment.appendChild(row);
            }
            let last = this._msgTable.lastChild;
            while (last) {
                this._msgTable.removeChild(last);
                last = this._msgTable.lastChild;
            }
            this._msgTable.appendChild(fragment);
        }

        navigate(where) {
            if (where == '..') {
                const path = this._current.textContent.split('/');
                if (path[path.length - 1] == '') {
                    path[path.length - 2] = '';
                    path.length--;
                } else {
                    path[path.length - 1] = '';
                }
                this._current.textContent = path.join('/');
            } else {
                this._current.textContent += where;
            }
            this.update();
        }

        setMessages(own, parent, baseLocal, baseExternal) {
            this._baseLocal = baseLocal;
            this._baseExternal = baseExternal;
            this._msgType = {};
            for (const msg of own.messages) {
                const element = text('li', msg);
                element.dataset.active = true;
                element.dataset.count = 0;
                this._msgType[msg] = {
                    element: element,
                    count: 0,
                    active: true
                }
            }
            const fragment = document.createDocumentFragment();
            for (const [msg, data] of Object.entries(this._msgType).sort()) {
                fragment.appendChild(data.element);
            }
            let last = this._msgList.lastChild;
            while (last) {
                this._msgList.removeChild(last);
                last = this._msgList.lastChild;
            }
            this._msgList.appendChild(fragment);

            this._msgs = [];
            for (const group of ['warnings', 'errors']) {
                const error = group == 'errors';
                for (const [file, msgs] of Object.entries(own[group])) {
                    const current = {};
                    for (const msgData of msgs) {
                        const msg = {
                            file: file,
                            line: msgData[2],
                            log: own.files[msgData[0]],
                            logline: msgData[1],
                            msg: own.messages[msgData[3]],
                            error: error,
                            new: false
                        };
                        this._msgs.push(msg);
                        if (current[msg.msg] === undefined) {
                            current[msg.msg] = [msg];
                        } else {
                            current[msg.msg].push(msg);
                        }
                    }
                    const old = {};
                    for (const msgData of parent[group][file]??[]) {
                        const msg = {
                            line: msgData[2],
                            log: parent.files[msgData[0]]
                        };
                        const k = parent.messages[msgData[3]];
                        if (old[k] === undefined) {
                            old[k] = [msg];
                        } else {
                            old[k].push(msg);
                        }
                    }
                    for (const [k, v] of Object.entries(current)) {
                        const oldEntries = old[k];
                        if (oldEntries === undefined) {
                            for (const msg of v) {
                                msg.new = true;
                            }
                        } else if (oldEntries.length < v.length) {
                            markNew(oldEntries, v);
                        }
                    }
                }
            }
            this._msgs.sort((a, b) => (a.file < b.file) ? -1
                : (a.file > b.file) ? 1 : a.line - b.line
            );
            this.update();
        }
    }
    customElements.define('msg-view', MsgView);

}());
