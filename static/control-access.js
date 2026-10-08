(function () {
    'use strict';
    var labels = JSON.parse(document.getElementById('control-i18n').textContent);
    var form = document.getElementById('control-create');
    var list = document.getElementById('control-clients');
    var status = document.getElementById('control-status');
    var clients = [];
    var secretClientId = null;
    function text(key) { return labels[document.documentElement.lang][key]; }
    function setStatus(key) {
        if (key) status.setAttribute('data-control-text', key);
        else status.removeAttribute('data-control-text');
        status.textContent = key ? text(key) : '';
    }
    function clearSecret() {
        var input = document.getElementById('control-token');
        input.value = ''; input.type = 'password'; secretClientId = null;
        document.getElementById('control-secret').hidden = true;
    }
    function request(url, method, data) {
        return fetch(url, {method: method, credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.getElementById('csrf-token').content},
            body: data === undefined ? undefined : JSON.stringify(data)}).then(function (response) {
            if (!response.ok) throw new Error('request_failed');
            return response.json();
        });
    }
    function render() {
        list.textContent = '';
        clients.forEach(function (client) {
            var row = document.createElement('p'), label = document.createElement('span');
            label.textContent = client.name + ' · ' + text('expires') + ' ' + new Date(client.expires_at * 1000).toLocaleString(document.documentElement.lang) + ' ';
            row.appendChild(label);
            var button = document.createElement('button');
            button.type = 'button'; button.textContent = text('revoke');
            button.addEventListener('click', function () {
                if (!window.confirm(text('confirm'))) return;
                button.disabled = true;
                request(list.dataset.url + '/' + encodeURIComponent(client.id), 'DELETE').then(function () {
                    clients = clients.filter(function (item) { return item.id !== client.id; });
                    if (secretClientId === client.id) clearSecret();
                    render(); setStatus('revoked');
                }).catch(function () { button.disabled = false; setStatus('error'); });
            });
            row.appendChild(button); list.appendChild(row);
        });
        if (!clients.length) list.textContent = text('empty');
    }
    window.applyManagementLanguage = function (language) {
        document.querySelectorAll('[data-control-text]').forEach(function (node) {
            node.textContent = labels[language][node.getAttribute('data-control-text')];
        });
        document.title = text('title') + ' · WebClock'; render();
    };
    form.addEventListener('submit', function (event) {
        event.preventDefault();
        var button = form.querySelector('[type=submit]');
        var data = {name: form.elements.name.value, expires_in: Number(form.elements.days.value) * 86400};
        ['scopes', 'group_ids', 'device_ids', 'calendar_source_ids', 'schedule_ids', 'event_ids'].forEach(function (field) {
            data[field] = Array.prototype.map.call(form.querySelectorAll('[name="' + field + '"]:checked'), function (input) { return input.value; });
        });
        button.disabled = true; setStatus('');
        request(form.action, 'POST', data).then(function (result) {
            var input = document.getElementById('control-token');
            input.type = 'password'; input.value = result.client.token;
            secretClientId = result.client.id;
            delete result.client.token;
            var reveal = document.getElementById('control-reveal');
            reveal.setAttribute('aria-pressed', 'false'); reveal.setAttribute('data-control-text', 'show');
            reveal.textContent = text('show');
            document.getElementById('control-secret').hidden = false;
            clients.push(result.client); render(); setStatus('saved'); button.disabled = false;
        }).catch(function () { button.disabled = false; setStatus('error'); });
    });
    document.getElementById('control-reveal').addEventListener('click', function () {
        var input = document.getElementById('control-token');
        input.type = input.type === 'password' ? 'text' : 'password';
        var key = input.type === 'password' ? 'show' : 'hide';
        this.setAttribute('aria-pressed', String(input.type === 'text'));
        this.setAttribute('data-control-text', key); this.textContent = text(key);
    });
    window.addEventListener('pagehide', clearSecret);
    request(list.dataset.url, 'GET').then(function (result) {
        // A delayed initial list must not erase a credential just created here.
        clients = result.clients.concat(clients.filter(function (client) {
            return !result.clients.some(function (item) { return item.id === client.id; });
        }));
        render();
    }).catch(function () { setStatus('error'); });
}());
