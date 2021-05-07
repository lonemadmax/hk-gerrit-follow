;(function (){
    'use strict';

    async function fetchJSON(url) {
        return await fetch(url).then(r => r.json());
    }

    function timeString(t) {
        return new Date(t*1000).toLocaleString();
    }

    app.util = {
        fetchJSON: fetchJSON,
        timeString: timeString
    }
}());
