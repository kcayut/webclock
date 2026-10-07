'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/group-assignment.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
let active = null;
function element(tag = 'div') {
    return {tag, children: [], attributes: {}, listeners: {}, textContent: '', className: '', disabled: false,
        setAttribute(key, value) { this.attributes[key] = value; }, getAttribute(key) { return this.attributes[key]; },
        append(...children) { children.forEach(child => { child.remove(); this.children.push(child); child.parentNode = this; }); },
        insertBefore(child, before) { child.remove(); this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, child); child.parentNode = this; },
        remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(item => item !== this); this.parentNode = null; },
        addEventListener(event, callback) { this.listeners[event] = callback; },
        trigger(event) { return this.listeners[event]?.({preventDefault() {}}); }, focus() { active = this; }
    };
}
const descendants = el => el.children.flatMap(child => [child, ...descendants(child)]);
const pending = [];
const context = vm.createContext({window: {confirm: () => true}, document: {createElement: element, getElementById: () => ({content: 'csrf'})},
    fetch(url, options) { return new Promise(resolve => pending.push({url, options, resolve})); }});
vm.runInContext(source, context);
function take(method) {
    const index = pending.findIndex(item => item.options.method === method); assert.ok(index >= 0, method);
    const request = pending.splice(index, 1)[0]; assert.ok(request.url.startsWith('/api/v1/groups/assignments'));  return request;
}
function reply(request, data, ok = true) { request.resolve({ok, json: async () => JSON.parse(JSON.stringify(data))}); }
const empty = {group_ids: [], partial_group_ids: []};
async function main() {
    let language = 'en', changes = 0;
    let calendarAssignment = {group_ids: ['a'], partial_group_ids: ['b'], revision: 'calendar-r1'};
    const manager = context.window.WebClockAssignments.create({t: key => language + ':' + key,
        onChange() { changes++; noteEditor.set({kind: 'manual_note', id: 1}, manager.get('manual_note', 1)); calendarEditor.set(calendarItem, calendarAssignment); },
        onSaved(item, assignment) { if (item.kind === 'calendar') calendarAssignment = assignment; }
    });
    const noteContainer = element(), calendarContainer = element(), summary = element();
    const noteEditor = manager.createEditor(noteContainer), calendarEditor = manager.createEditor(calendarContainer);
    const calendarItem = {kind: 'calendar', target: {source_id: 'cal', uid: 'weekly', scope: 'series', recurrence_id: ''}};
    const find = (container, attr, value = '') => descendants(container).find(el => el.getAttribute(attr) === value);
    const button = (container, name) => descendants(container).find(el => el.tag === 'button' && el.textContent.endsWith(':' + name));
    noteEditor.set({kind: 'manual_note', id: 1}, null); calendarEditor.set(calendarItem, calendarAssignment);
    assert.equal(button(noteContainer, 'assignment_save').disabled, true);
    assert.ok(descendants(noteContainer).filter(el => el.tag === 'button').every(el => el.type === 'button'), 'Assignment saves never submit the enclosing note form');
    manager.load(); manager.load(); assert.equal(pending.length, 1, 'Editors share an in-flight catalog read');
    reply(take('GET'), {}, false); await flush();
    assert.equal(button(noteContainer, 'assignment_save').disabled, true);
    assert.equal(button(noteContainer, 'assignment_retry').hidden, false);
    manager.load();
    const catalog = {groups: [{id: 'a', name: 'Alpha'}, {id: 'b', name: 'Beta'}], manual_notes: {'1': {group_ids: ['a'], partial_group_ids: [], revision: 'note-r1'}}, schedules: {}};
    reply(take('GET'), catalog); await flush();
    assert.equal(find(noteContainer, 'data-assignment-group', 'a').checked, true);
    assert.equal(find(noteContainer, 'data-assignment-all').indeterminate, true);
    const partial = find(calendarContainer, 'data-assignment-group', 'b');
    assert.equal(partial.checked, false); assert.equal(partial.indeterminate, true);
    manager.summary(summary, calendarAssignment); assert.equal(summary.textContent, 'Alpha · Beta · en:assignment_partial');
    const alpha = find(calendarContainer, 'data-assignment-group', 'a');
    alpha.checked = false; alpha.trigger('change'); alpha.focus();
    language = 'ja'; manager.applyLanguage();
    assert.equal(active, alpha); assert.equal(partial.indeterminate, true);
    button(calendarContainer, 'assignment_save').trigger('click');
    let write = take('PUT');
    assert.deepEqual(JSON.parse(write.options.body), {item: calendarItem, group_ids: [], keep_partial_group_ids: ['b'], revision: 'calendar-r1'});
    assert.equal(write.options.headers['X-CSRF-Token'], 'csrf');
    reply(write, {}, false); await flush();
    assert.equal(alpha.checked, false); assert.equal(partial.indeterminate, true, 'Failed saves retain mixed membership and edits');
    assert.ok(descendants(calendarContainer).some(el => el.textContent === 'ja:assignment_failed'));
    manager.load(); const oldRead = take('GET');
    partial.checked = true; partial.trigger('change');
    button(calendarContainer, 'assignment_save').trigger('click'); write = take('PUT');
    assert.deepEqual(JSON.parse(write.options.body).group_ids, ['b']);
    assert.equal('keep_partial_group_ids' in JSON.parse(write.options.body), false, 'Clicking a partial membership explicitly changes it to full');
    reply(write, {groups: [...catalog.groups, {id: 'c', name: 'Gamma'}], assignment: {group_ids: ['b'], partial_group_ids: [], revision: 'calendar-r2'}}); await flush();
    reply(oldRead, {groups: [], manual_notes: {}, schedules: {}}); await flush();
    assert.ok(find(calendarContainer, 'data-assignment-group', 'c'), 'An old catalog response cannot overwrite the post-save group catalog');
    const all = find(noteContainer, 'data-assignment-all'); all.checked = true; all.trigger('change');
    assert.equal(all.checked, true); assert.equal(all.indeterminate, false);
    button(noteContainer, 'assignment_save').trigger('click'); write = take('PUT');
    assert.deepEqual(JSON.parse(write.options.body), {item: {kind: 'manual_note', id: 1}, group_ids: ['a', 'b', 'c'], revision: 'note-r1'}, 'All means the current group snapshot, not future groups');
    reply(write, {groups: catalog.groups, assignment: {group_ids: ['a', 'b'], partial_group_ids: [], revision: 'note-r2'}}); await flush();
    assert.deepEqual(JSON.parse(JSON.stringify(manager.get('manual_note', 1))), {group_ids: ['a', 'b'], partial_group_ids: [], revision: 'note-r2'});
    const b = find(noteContainer, 'data-assignment-group', 'b'); b.checked = false; b.trigger('change');
    noteEditor.set(null, null); assert.equal(noteContainer.hidden, true);
    noteEditor.set({kind: 'manual_note', id: 1}, manager.get('manual_note', 1));
    assert.equal(noteContainer.hidden, false); assert.equal(b.checked, false, 'Returning to an editor preserves its unsaved assignment');
    manager.load(); reply(take('GET'), catalog); await flush();
    assert.equal(b.checked, false, 'Background reads do not replace a dirty assignment draft');
    button(noteContainer, 'assignment_save').trigger('click'); write = take('PUT');
    assert.equal(JSON.parse(write.options.body).revision, 'note-r2', 'Background reads cannot give stale drafts a fresh revision');
    reply(write, {code: 'assignment_changed'}, false); await flush();
    assert.equal(b.checked, false); assert.equal(button(noteContainer, 'assignment_save').disabled, true);
    language = 'en'; manager.applyLanguage();
    assert.ok(descendants(noteContainer).some(el => el.textContent === 'en:assignment_conflict'));
    context.window.confirm = () => false;
    await button(noteContainer, 'assignment_retry').trigger('click'); assert.equal(pending.length, 0);
    context.window.confirm = () => true;
    button(noteContainer, 'assignment_retry').trigger('click');
    let reload = take('GET');
    assert.deepEqual(JSON.parse(decodeURIComponent(reload.url.split('?item=')[1])), {kind: 'manual_note', id: 1});
    b.checked = true; b.trigger('change');
    reply(reload, {groups: catalog.groups, assignment: {group_ids: [], partial_group_ids: [], revision: 'note-r3'}}); await flush();
    assert.equal(b.checked, true); assert.equal(button(noteContainer, 'assignment_save').disabled, true, 'Reload cannot replace edits made while the request was pending');
    button(noteContainer, 'assignment_retry').trigger('click'); reload = take('GET');
    reply(reload, {groups: catalog.groups, assignment: {group_ids: ['b'], partial_group_ids: [], revision: 'note-r3'}}); await flush();
    assert.equal(b.checked, true); assert.equal(button(noteContainer, 'assignment_save').disabled, false);
    // Calendar reload refreshes its external card snapshot too, so onChange cannot restore stale data.
    alpha.checked = true; alpha.trigger('change'); button(calendarContainer, 'assignment_save').trigger('click');
    reply(take('PUT'), {code: 'assignment_changed'}, false); await flush();
    button(calendarContainer, 'assignment_retry').trigger('click'); reload = take('GET');
    assert.deepEqual(JSON.parse(decodeURIComponent(reload.url.split('?item=')[1])), calendarItem);
    reply(reload, {groups: catalog.groups, assignment: {group_ids: [], partial_group_ids: [], revision: 'calendar-r3'}}); await flush();
    assert.equal(alpha.checked, false); assert.equal(calendarAssignment.revision, 'calendar-r3');
    assert.ok(changes > 0); assert.equal(pending.length, 0);
    console.log('Group assignments: independent saves, shared reads, mixed memberships, current-group select-all, retained drafts/focus and stale-response guards passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
