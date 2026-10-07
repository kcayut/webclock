/* Optional ES5 display: announcement text and deadlines stay in memory only. */
(function () {
    'use strict';
    var rows = [], timer = null, rendered = '', startedWall = 0, startedMono = 0, lastWall = 0, lastMono = 0;
    function wall() { return new Date().getTime(); }
    function mono() { return window.performance && typeof window.performance.now === 'function' ? window.performance.now() : wall(); }
    function elapsed() { return Math.max(0, mono() - startedMono, wall() - startedWall); }
    function clearTimer() { if (timer !== null) clearTimeout(timer); timer = null; }
    function tick() {
        var container = document.getElementById('announcement-container');
        if (!container) return;
        clearTimer();
        var currentWall = wall(), currentMono = mono();
        if (currentWall < lastWall || currentMono < lastMono) rows = [];
        lastWall = currentWall; lastMono = currentMono;
        var age = elapsed(), live = [], next = Infinity;
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].duration <= age) continue;
            live.push(rows[i]); next = Math.min(next, rows[i].duration - age);
        }
        rows = live;
        var signature = JSON.stringify(rows.map(function (row) { return row.text; }));
        if (signature !== rendered) {
            rendered = signature; container.textContent = '';
            for (var j = 0; j < rows.length; j++) {
                var item = document.createElement('p'); item.textContent = rows[j].text; container.appendChild(item);
            }
        }
        container.style.display = rows.length ? 'block' : 'none';
        document.body.classList.toggle('has-announcements', rows.length > 0);
        if (rows.length) timer = setTimeout(tick, Math.min(next, 2147483647));
    }
    function clear() { rows = []; tick(); }
    function set(items, serverTime, requestElapsed) {
        clearTimer(); rows = []; startedWall = wall(); startedMono = mono();
        lastWall = startedWall; lastMono = startedMono;
        requestElapsed = typeof requestElapsed === 'number' && isFinite(requestElapsed) ? Math.max(0, requestElapsed) : 0;
        if (Array.isArray(items) && typeof serverTime === 'number' && isFinite(serverTime)) {
            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                if (!item || typeof item.text !== 'string' || typeof item.visible_until !== 'number' || !isFinite(item.visible_until)) continue;
                if (item.visible_until > serverTime + requestElapsed) rows.push({text: item.text, duration: item.visible_until - serverTime - requestElapsed});
            }
        }
        tick();
    }
    window.WebClockAnnouncements = {set: set, clear: clear, tick: tick};
}());
