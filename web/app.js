'use strict';
const el = id => document.getElementById(id);
// The owner's local day: the box clock is UTC, the person is not.
const localDay = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
let state = { day: localDay(), habits: [] };

// Errors are shown; confirmations are announced to screen readers only (the list already shows them).
function say(text, kind = '') { // kind: '' (screen readers only), 'error', 'note'
  const s = el('status');
  s.classList.toggle('wz-sr', !kind);
  s.classList.toggle('note', kind === 'note');
  s.textContent = text;
}
async function request(path, data) {
  const init = data === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...data, day: localDay() }) };
  const response = await fetch(path, init);
  let body = {};
  try { body = await response.json(); } catch (e) {}
  if (!response.ok) throw new Error(body.error || 'The app could not save this. Try again.');
  return body;
}

function check() {
  const box = document.createElement('span'); box.className = 'wz-check'; box.setAttribute('aria-hidden', 'true');
  box.innerHTML = '<i><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></i>';
  return box;
}

function render(data) {
  state = data;
  const when = new Date(data.day + 'T12:00:00');
  el('day').textContent = when.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  el('day-short').textContent = when.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  const total = data.habits.length, done = data.habits.filter(h => h.done).length;
  el('empty').hidden = total > 0;
  el('count').hidden = el('progress').hidden = total === 0;
  el('count').textContent = done + ' / ' + total;
  el('count').classList.toggle('all', total > 0 && done === total);
  el('progress').firstElementChild.style.width = (total ? (100 * done / total) : 0) + '%';

  const list = el('habits'); list.replaceChildren();
  for (const habit of data.habits) {
    const li = document.createElement('li');
    const row = document.createElement('button');
    row.type = 'button'; row.className = 'wz-row';
    row.setAttribute('aria-pressed', String(habit.done));
    row.setAttribute('aria-label', habit.name + (habit.done ? ', done today' : ', not done yet'));
    const main = document.createElement('span'); main.className = 'wz-main';
    const name = document.createElement('b'); name.textContent = habit.name;
    main.append(name);
    if (habit.done) { const sub = document.createElement('small'); sub.textContent = 'Done today'; main.append(sub); }
    row.append(check(), main);
    row.onclick = async () => {
      row.disabled = true;
      try { render(await request('api/habits/' + habit.id + '/today', { done: !habit.done })); say(habit.name + (habit.done ? ' unmarked.' : ' done.')); }
      catch (error) { say(error.message, 'error'); row.disabled = false; }
    };
    li.append(row); list.append(li);
  }
}

const input = el('habit-name'), add = el('add');
let draftHold = null;
function syncDraftHold() {
  const unsaved = !!input.value.trim();
  if (unsaved && !draftHold && window.WizardApp?.version === 1) draftHold = WizardApp.update.hold('Unsubmitted habit');
  if (!unsaved && draftHold) { draftHold.release(); draftHold = null; }
}
input.addEventListener('input', () => { syncDraftHold(); add.disabled = !input.value.trim(); if (el('status').textContent) say(''); });
el('add-form').onsubmit = async event => {
  event.preventDefault();
  if (!input.value.trim()) return;
  add.disabled = true; input.disabled = true;
  try {
    await request('api/habits', { name: input.value });
    // The update hold is released only after a durable task API readback.
    render(await request('api/habits?day=' + localDay()));
    input.value = ''; syncDraftHold(); say('Habit added.');
  }
  catch (error) { say(error.message, 'error'); }
  finally { input.disabled = false; add.disabled = !input.value.trim(); }
};

// Domain-only Back callbacks. Core owns the root guard in hosted and standalone modes.
// This one-screen app is already at root. Add nested route/overlay state here, not exit logic.
if (!window.WizardApp || WizardApp.version !== 1) {
  say('Wizard system functions are unavailable. Open this preview through Wizard.', 'error');
} else {
  WizardApp.ready({ name: 'wizard-manager', version: '0.2.0' });
  // A routed variant uses WizardApp.back.useHistory({isRoot}) with its real router.
  // This one-screen app has no route history to adapt.
  WizardApp.back.register({ canGoBack: () => false, back: () => false });
}

request('api/habits?day=' + localDay()).then(render).catch(error => say(error.message, 'error'));
// A new day while the app stays open.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && state.day !== localDay()) request('api/habits?day=' + localDay()).then(render).catch(() => {});
});
