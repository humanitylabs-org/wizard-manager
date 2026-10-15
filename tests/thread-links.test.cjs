const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../web/thread-links.js'), 'utf8'), context);
const resolve = rows => text => JSON.parse(JSON.stringify(context.window.ManagerThreadLinks.resolver(rows)(text)));
const rows = [
  ['one', 'Wizard OS · Miguel co-work'], ['two', 'Wizard Apps · Store readiness #3'],
  ['three', 'Hermes · Gateway recursion crash'], ['four', 'Mine YouTube video'],
  ['five', 'Return to previous thread after mobile reply'], ['six', 'Unify responsive features across desktop and mobile'],
  ['seven', 'Wizard OS · App builder #2'], ['eight', 'Wizard OS · Share files'], ['nine', 'Wizard OS · Manager']
].map(([id, title]) => ({id, title}));
const text = 'Several are genuinely mid-flight: Wizard OS · Miguel co-work is queued waiting on the Mac permission, Store readiness #3 is queued with seven app subagents running, and Hermes · Gateway recursion crash is running (detector wired into the job). Mine YouTube video, Return to previous thread after mobile reply, Unify responsive features, App builder #2, Share files and Manager are also still running.';
test('historical nine-name paragraph resolves full, suffix and unique prefix names without changing text', () => {
  const parts = resolve(rows)(text);
  assert.equal(parts.map(p => p.text).join(''), text);
  assert.deepEqual(parts.filter(p => p.source_id).map(p => p.source_id), rows.map(r => r.id));
});
test('ambiguous titles and abbreviated prefixes stay plain; longest exact name wins', () => {
  const inventory = [...rows, { id: 'ten', title: 'Other · Share files' }, {id: 'eleven', title: 'Unify responsive features on tablets'}];
  assert.equal(resolve(inventory)('Share files and Unify responsive features').filter(p => p.source_id).length, 0);
  assert.deepEqual(resolve(inventory)('Wizard OS · Share files').filter(p => p.source_id), [{text: 'Wizard OS · Share files', source_id: 'eight'}]);
  assert.equal(resolve([...rows, {id: 'duplicate', title: rows[0].title}])(rows[0].title).filter(p => p.source_id).length, 0);
});
test('one-word and substring false positives are inert; quoted/named references resolve', () => {
  const render = resolve(rows);
  assert.equal(render('Manager is enabled. My manager handles work. Share filesystems.').filter(p => p.source_id).length, 0);
  assert.deepEqual(render('The thread Manager and “Manager” and `Manager`.').filter(p => p.source_id).map(p => p.source_id), ['nine', 'nine', 'nine']);
});
test('only inventory-bound explicit URLs link; invalid destinations never fall back to label matching', () => {
  const render = resolve([...rows, { id: 'slash/雪&?', title: 'Escaping test' }]);
  const explicit = '[<img src=x onerror=alert(1)>](/wizard-os-home/?session=slash%2F%E9%9B%AA%26%3F)';
  assert.deepEqual(render(explicit), [{text: '<img src=x onerror=alert(1)>', source_id: 'slash/雪&?'}]);
  for (const url of ['javascript:alert', 'https://evil.invalid/', '//evil.invalid/', '/wizard-os-home/?session=absent', '/wizard-os-home/?session=one&evil=1', '/wizard-os-home/?session=%ZZ']) {
    const value = '[Share files](' + url + ')';
    assert.deepEqual(render(value), [{text: value}]);
  }
  assert.deepEqual(render('[Open it](/wizard-os-home/?session=one)'), [{text: 'Open it', source_id: 'one'}]);
  assert.equal(resolve([])(text).filter(p => p.source_id).length, 0);
});
test('observed canonical aliases link old names after rename but collisions still remain plain', () => {
  const row = {id: 'stable-id', title: 'New thread title', aliases: ['Old thread title']};
  assert.deepEqual(resolve([row])('Old thread title'), [{text: 'Old thread title', source_id: 'stable-id'}]);
  assert.equal(resolve([row, {id:'other', title:'Old thread title'}])('Old thread title').filter(p => p.source_id).length, 0);
});
