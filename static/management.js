/* Shared management navigation. Switching sections keeps the existing form DOM. */
(function () {
    'use strict';
    var panels = document.querySelectorAll('[data-management-panel]');
    var links = document.querySelectorAll('[data-management-link]');
    var aliases = {'calendar-title': 'calendar', 'devices-title': 'devices'};
    var initial = document.body.getAttribute('data-initial-panel');
    var languageSelect = document.getElementById('management-language-select');
    if (languageSelect) {
        languageSelect.addEventListener('change', function () {
            var select = this;
            select.disabled = true;
            fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({language: select.value})
            }).then(function (response) {
                if (!response.ok) throw new Error('Language not saved');
                window.location.reload();
            }).catch(function () {
                select.disabled = false;
                select.value = document.documentElement.lang;
                window.alert(select.getAttribute('data-error'));
            });
        });
    }
    for (var n = 0; n < links.length; n++) {
        links[n].addEventListener('click', function (event) {
            if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            var selected = this.getAttribute('data-management-link');
            for (var i = 0; i < panels.length; i++) {
                if (panels[i].getAttribute('data-management-panel') !== selected) continue;
                // A failed reminder POST is rendered at /add or /schedule/id. Keep its draft too.
                event.preventDefault();
                window.location.hash = this.getAttribute('href').split('#')[1];
                showPanel(true);
                return;
            }
        });
    }
    function showPanel(scroll) {
        var hash = window.location.hash.slice(1);
        if (hash === 'management-main') return;
        var selected = aliases[hash] || hash || initial;
        var found = false;
        for (var i = 0; i < panels.length; i++) {
            if (panels[i].getAttribute('data-management-panel') === selected) found = true;
        }
        if (!found) selected = initial;
        for (var j = 0; j < panels.length; j++) {
            var current = panels[j].getAttribute('data-management-panel') === selected;
            panels[j].classList.toggle('is-current', current);
            panels[j].hidden = !current;
        }
        for (var k = 0; k < links.length; k++) {
            var active = links[k].getAttribute('data-management-link') === selected;
            if (active) links[k].setAttribute('aria-current', 'page');
            else links[k].removeAttribute('aria-current');
        }
        if (scroll) window.scrollTo(0, 0);
    }
    window.addEventListener('hashchange', function () { showPanel(true); });
    // A direct anchor URL can scroll after defer scripts run; restore the panel top.
    window.addEventListener('load', function () {
        window.requestAnimationFrame(function () { showPanel(true); });
    });
    showPanel(true);
}());
