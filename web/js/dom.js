;(function (){
    'use strict';

    function getElement(id) {
        return document.getElementById(id);
    }

    function appendTo(id, el) {
        getElement(id).appendChild(el);
    }

    function compose(tag, element) {
        const parent = document.createElement(tag);
        parent.appendChild(element);
        return parent;
    }

    function text(tag, t) {
        if (t === undefined) {
            return document.createTextNode(tag);
        }
        return compose(tag, document.createTextNode(t));
    }

    function link(src) {
        const el = document.createElement('a');
        el.setAttribute('href', src);
        return el;
    }

    function textLink(src, t) {
        const el = link(src);
        el.appendChild(text(t));
        return el;
    }

    function show(element) {
        element.classList.remove('hide');
    }

    function hide(element) {
        element.classList.add('hide');
    }

    function hiddenText(t) {
        const el = text('span', t);
        el.classList.add('visuallyhidden');
        return el;
    }

    function linebreak() {
        return document.createElement('br');
    }

    app.dom = {
        getElement: getElement,
        appendTo: appendTo,
        compose: compose,
        text: text,
        link: link,
        textLink: textLink,
        show: show,
        hide: hide,
        hiddenText: hiddenText,
        linebreak: linebreak
    }    
}());
