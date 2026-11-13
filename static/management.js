/* Shared management navigation, tabs, filters, dialogs and overlay controls. Switching sections keeps the existing form DOM. */
(function () {
    'use strict';
    var tabs = document.querySelectorAll('[data-management-tab]');
    var tabPanels = document.querySelectorAll('[data-management-tab-panel]');
    function activateTab(group, name) {
        var i;
        for (i = 0; i < tabs.length; i++) {
            if (tabs[i].getAttribute('data-tab-group') !== group) continue;
            var selected = tabs[i].getAttribute('data-management-tab') === name;
            tabs[i].setAttribute('aria-selected', String(selected));
            tabs[i].setAttribute('tabindex', selected ? '0' : '-1');
        }
        for (i = 0; i < tabPanels.length; i++) {
            if (tabPanels[i].getAttribute('data-tab-group') !== group) continue;
            var current = tabPanels[i].getAttribute('data-management-tab-panel') === name;
            tabPanels[i].hidden = !current;
            tabPanels[i].classList.toggle('is-current', current);
        }
    }
    for (var t = 0; t < tabs.length; t++) {
        tabs[t].addEventListener('click', function () {
            activateTab(this.getAttribute('data-tab-group'), this.getAttribute('data-management-tab'));
        });
        tabs[t].addEventListener('keydown', function (event) {
            var key = event.key;
            if (key !== 'ArrowLeft' && key !== 'ArrowRight' && key !== 'Home' && key !== 'End') return;
            var group = this.getAttribute('data-tab-group'), groupTabs = [];
            for (var i = 0; i < tabs.length; i++) {
                if (tabs[i].getAttribute('data-tab-group') === group) groupTabs.push(tabs[i]);
            }
            var index = groupTabs.indexOf(this);
            if (index < 0) return;
            if (key === 'Home') index = 0;
            else if (key === 'End') index = groupTabs.length - 1;
            else index = (index + (key === 'ArrowRight' ? 1 : -1) + groupTabs.length) % groupTabs.length;
            event.preventDefault();
            groupTabs[index].focus();
            activateTab(group, groupTabs[index].getAttribute('data-management-tab'));
        });
    }
    var filterButtons = document.querySelectorAll('[data-filter-value]');
    var filterLists = document.querySelectorAll('[data-filter-list]');
    function activateFilter(group, value) {
        var i;
        for (i = 0; i < filterButtons.length; i++) {
            if (filterButtons[i].getAttribute('data-filter-group') !== group) continue;
            filterButtons[i].setAttribute('aria-pressed', String(filterButtons[i].getAttribute('data-filter-value') === value));
        }
        for (i = 0; i < filterLists.length; i++) {
            if (filterLists[i].getAttribute('data-filter-list') === group) filterLists[i].setAttribute('data-filter-active', value);
        }
    }
    for (var f = 0; f < filterButtons.length; f++) {
        filterButtons[f].addEventListener('click', function () {
            activateFilter(this.getAttribute('data-filter-group'), this.getAttribute('data-filter-value'));
        });
    }
    var dialogOpeners = document.querySelectorAll('[data-dialog-open]');
    for (var d = 0; d < dialogOpeners.length; d++) {
        dialogOpeners[d].addEventListener('click', function () {
            var dialog = document.getElementById(this.getAttribute('data-dialog-open'));
            if (dialog && dialog.showModal) dialog.showModal();
        });
    }
    var dialogClosers = document.querySelectorAll('[data-dialog-close]');
    for (var c = 0; c < dialogClosers.length; c++) {
        dialogClosers[c].addEventListener('click', function () {
            var dialog = this.closest ? this.closest('dialog') : null;
            if (dialog) dialog.close();
        });
    }
    var dialogs = document.querySelectorAll('dialog.management-dialog');
    for (var g = 0; g < dialogs.length; g++) {
        dialogs[g].addEventListener('click', function (event) {
            if (event.target === this) this.close();
        });
    }
    var panels = document.querySelectorAll('[data-management-panel]');
    var links = document.querySelectorAll('[data-management-link]');
    var aliases = {'calendar-title': 'calendar', 'notes-title': 'calendar', 'devices-title': 'devices'};
    var initial = document.body.getAttribute('data-initial-panel');
    var themeToggle = document.getElementById('management-theme-toggle');
    if (themeToggle) {
        var themeButtons = themeToggle.querySelectorAll('button');
        function applyTheme(theme) {
            document.documentElement.setAttribute('data-management-theme', theme);
            for (var i = 0; i < themeButtons.length; i++) {
                themeButtons[i].setAttribute('aria-pressed', String(themeButtons[i].getAttribute('data-theme') === theme));
            }
        }
        applyTheme(document.documentElement.getAttribute('data-management-theme') === 'dark' ? 'dark' : 'light');
        for (var i = 0; i < themeButtons.length; i++) {
            themeButtons[i].addEventListener('click', function () {
                var theme = this.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
                applyTheme(theme);
                try { window.localStorage.setItem('webclock-management-theme', theme); } catch (error) {}
            });
        }
    }
    var languageSelect = document.getElementById('management-language-select');
    if (languageSelect) {
        languageSelect.addEventListener('change', function () {
            var select = this, language = select.value;
            select.disabled = true;
            fetch(window.webclockUrl ? window.webclockUrl('/api/management/language') : '/api/management/language', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.getElementById('csrf-token').content},
                body: JSON.stringify({language: language})
            }).then(function (response) {
                if (!response.ok) throw new Error('Language not saved');
                var labels = JSON.parse(document.getElementById('management-i18n').textContent)[language];
                document.documentElement.lang = language;
                document.querySelectorAll('[data-i18n]').forEach(function (element) {
                    element.textContent = labels[element.getAttribute('data-i18n')];
                });
                document.querySelectorAll('[data-i18n-aria-label]').forEach(function (element) {
                    element.setAttribute('aria-label', labels[element.getAttribute('data-i18n-aria-label')]);
                });
                select.setAttribute('data-error', labels.settings_save_error);
                window.applyManagementLanguage(language);
                if (window.WebClockGroups) window.WebClockGroups.applyLanguage();
                select.disabled = false;
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
        var activeGroup = null, groups = [];
        for (var k = 0; k < links.length; k++) {
            var group = links[k].closest ? links[k].closest('details.management-nav-group') : null;
            if (group && groups.indexOf(group) < 0) groups.push(group);
            var active = links[k].getAttribute('data-management-link') === selected;
            if (active) {
                links[k].setAttribute('aria-current', 'page');
                if (group) activeGroup = group;
            } else links[k].removeAttribute('aria-current');
        }
        // Only the group that contains the current item stays expanded.
        for (var g = 0; g < groups.length; g++) groups[g].open = groups[g] === activeGroup;
        if (scroll) window.scrollTo(0, 0);
    }
    window.addEventListener('hashchange', function () { showPanel(true); });
    // A direct anchor URL can scroll after defer scripts run; restore the panel top.
    window.addEventListener('load', function () {
        window.requestAnimationFrame(function () { showPanel(true); });
    });
    showPanel(true);
}());
