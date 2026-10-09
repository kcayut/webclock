// Run with node tests/test_mode_accounts.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
    return {children: [], dataset: {}, value: '',
        set textContent(value) { this.text = value; this.children = []; },
        get textContent() { return this.text || ''; },
        appendChild(child) { this.children.push(child); }, reset() { this.resetCalled = true; }};
}
const nodes = {};
['mode-i18n', 'mode-accounts', 'mode-status', 'accounts-list', 'account-create', 'account-name', 'account-password', 'csrf-token']
    .forEach(id => { nodes[id] = element(); });
nodes['mode-i18n'].textContent = JSON.stringify({en: {title: 'Accounts', created: 'Created', disable: 'Disable', delete: 'Delete'},
    ja: {title: '管理', created: '作成', disable: '無効', delete: '削除'}});
nodes['mode-accounts'].textContent = JSON.stringify([{owner_id: 'admin-id', username: 'admin', role: 'admin', enabled: true}]);
nodes['csrf-token'].content = 'csrf';
nodes['account-name'].value = 'member';
nodes['account-password'].value = 'member password';
const requests = [], window = {location: {}};
const document = {getElementById: id => nodes[id] || null, createElement: element,
    documentElement: {lang: 'en'}, querySelectorAll: () => [nodes['mode-status']]};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../static/mode.js'), 'utf8'), {
    window, document, fetch: async (url, options) => {
        requests.push({url, options});
        return {ok: true, json: async () => ({account: {owner_id: 'member-id', username: 'member', role: 'member', enabled: true}})};
    }
});
async function run() {
    assert.equal(nodes['accounts-list'].children.length, 1, 'HA account list renders without a mode form');
    nodes['account-create'].onsubmit({preventDefault() {}});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests[0].url, '/api/accounts');
    assert.equal(requests[0].options.headers['X-CSRF-Token'], 'csrf');
    assert.equal(JSON.parse(requests[0].options.body).username, 'member');
    assert.equal(nodes['accounts-list'].children.length, 2);
    assert.equal(nodes['mode-status'].textContent, 'Created');
    assert.equal(nodes['account-create'].resetCalled, true);
    document.documentElement.lang = 'ja';
    window.applyManagementLanguage();
    assert.equal(nodes['mode-status'].textContent, '作成');
    assert.equal(nodes['accounts-list'].children.length, 2);
    assert.equal(requests.length, 1, 'Account actions never invoke a mode switch');
    console.log('HA account management without mode controls passed');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
