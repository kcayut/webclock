// Run with node tests/test_offline.js. Real browser reopening is also checked manually.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const worker = fs.readFileSync(require('node:path').join(__dirname, '../sw.js'), 'utf8');

async function checkScope(scope) {
    const handlers = {};
    const stores = new Map();
    let state = 'online';
    let claimed = false;
    const getCache = name => {
        if (!stores.has(name)) stores.set(name, new Map());
        const entries = stores.get(name);
        return {
            addAll: async requests => requests.forEach(r => entries.set(r.url, new Response('installed:' + r.url))),
            put: async (key, value) => entries.set(key, value),
            match: async key => entries.get(key)?.clone(),
        };
    };
    const context = vm.createContext({
        URL, Request, Response, AbortController,
        setTimeout: callback => setTimeout(callback, 5), clearTimeout,
        self: {location: {href: scope + 'sw.js'}, clients: {claim: async () => { claimed = true; }},
            addEventListener: (name, handler) => { handlers[name] = handler; }},
        caches: {open: async name => getCache(name), keys: async () => [...stores.keys()], delete: async name => stores.delete(name)},
        fetch: async (request, options) => {
            if (state === 'timeout') return new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new Error('timeout'))));
            if (state === 'offline') throw new Error('offline');
            return new Response('fresh:' + request.url, {status: state === 'error' ? 503 : 200});
        },
    });
    vm.runInContext(worker, context);
    const prefix = 'webclock-' + new URL(scope).pathname + '-';
    stores.set(prefix + 'old', new Map());
    stores.set('unrelated-app', new Map());
    let pending;
    handlers.install({waitUntil: p => { pending = p; }}); await pending;
    handlers.activate({waitUntil: p => { pending = p; }}); await pending;
    assert.ok(claimed);
    assert.ok(!stores.has(prefix + 'old'));
    assert.ok(stores.has('unrelated-app'));
    async function fetchPage(url, method = 'GET') {
        const tasks = [];
        let response;
        handlers.fetch({request: new Request(url, {method}), respondWith: p => { response = p; }, waitUntil: p => tasks.push(p)});
        const result = response ? await response : undefined;
        await Promise.all(tasks);
        return result;
    }
    assert.equal(await (await fetchPage(scope)).text(), 'fresh:' + scope);
    for (state of ['offline', 'error', 'timeout']) {
        assert.equal(await (await fetchPage(scope + '?test=1')).text(), 'fresh:' + scope);
        assert.equal(await (await fetchPage(scope + 'index.html')).text(), 'fresh:' + scope);
        assert.ok((await (await fetchPage(scope + 'static/clock.js')).text()).startsWith('installed:'));
    }
    for (const path of ['admin', 'api/status', 'api/backup', 'private.ics', 'unknown']) {
        assert.equal(await fetchPage(scope + path), undefined, path);
    }
    assert.equal(await fetchPage(scope, 'POST'), undefined);
    assert.equal(await fetchPage('https://other.example/static/clock.js'), undefined);
}
(async () => {
    await checkScope('https://clock.example/');
    await checkScope('https://clock.example/webclock/');
    console.log('Offline checks passed: install, scope, timeout, reload, cache cleanup, API/admin exclusion.');
})().catch(error => { console.error(error); process.exitCode = 1; });
