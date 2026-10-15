/* Manager owns conversation state only. Wizard core owns appearance and Back. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const core = window.WizardApp?.version === 1 ? window.WizardApp : null;
  const KEY = 'wizard-manager:conversation:v1';
  const input = $('message'), scroller = $('conversation'), thread = $('thread');
  const messages = new Map(), nodes = new Map(), jobNodes = new Map();
  let draft = { rev: 0, text: '', target: null, sending: null, scroll: { pinned: true }, receipts: {} };
  let saved = true, hold = null, loaded = false, connected = false, enabled = null, connectionFailed = false;
  let cursor = 0, jobs = [], refreshing = null, submitting = false, togglePending = null;
  let toggleUnknown = false, toggleError = '', pendingTarget = null, confirmLayer = null, optionsLayer = null;
  let newBelow = 0, pinned = true, scrollFrame = 0, retrying = new Set(), jobErrors = new Set();
  let restoring = true;
  const panels = new Map();
  const validTarget = t => t && Number.isSafeInteger(t.reply_to) && t.reply_to > 0 && typeof t.source_id === 'string' && t.source_id.length > 0;
  function restore() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return;
      const d = JSON.parse(raw);
      if (!Number.isSafeInteger(d.rev) || typeof d.text !== 'string' || d.text.length > 12000) throw new Error('Invalid draft');
      if (d.target && !validTarget(d.target)) throw new Error('Invalid destination');
      if (d.sending && (typeof d.sending.text !== 'string' || d.sending.text.length > 12000 || !/^[A-Za-z0-9_-]{8,100}$/.test(d.sending.request_id || '') || !Number.isSafeInteger(d.sending.rev))) throw new Error('Invalid submission');
      draft = { ...draft, ...d, receipts: d.receipts && typeof d.receipts === 'object' ? d.receipts : {} };
      if (draft.sending && draft.sending.state !== 'rejected') draft.sending.state = 'uncertain';
    } catch (_) {
      saved = false;
      $('storage-state').textContent = 'Saved draft couldn’t be restored on this device. Keep this window open.';
    }
  }
  function persist() {
    hold ||= core?.update.hold('unsaved Manager draft');
    try {
      const raw = JSON.stringify(draft);
      localStorage.setItem(KEY, raw);
      if (localStorage.getItem(KEY) !== raw) throw new Error('Draft readback failed');
      saved = true;
      hold?.release(); hold = null;
    } catch (_) {
      saved = false;
      $('storage-state').textContent = 'Draft couldn’t be saved on this device. Keep this window open.';
    }
    $('storage-state').hidden = saved;
    return saved;
  }
  function say(text) { $('announcer').textContent = text; }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function action(text, fn, disabled = false) {
    const b = element('button', 'mgr-text-action', text); b.type = 'button'; b.disabled = disabled; b.onclick = fn; return b;
  }
  function panel(id, signature, build) {
    if (panels.get(id) === signature) return;
    panels.set(id, signature);
    const node = $(id); node.replaceChildren(); build(node); node.hidden = !node.childNodes.length;
  }
  function portrait(identity = false) {
    const img = element('img', 'mgr-face'); img.src = 'archimedes.webp'; img.alt = identity ? 'Archimedes' : ''; img.width = img.height = 28;
    img.onerror = () => {
      const fallback = element('span', 'mgr-face', 'A');
      if (identity) { fallback.setAttribute('role', 'img'); fallback.setAttribute('aria-label', 'Archimedes'); }
      else fallback.setAttribute('aria-hidden', 'true');
      img.replaceWith(fallback);
    };
    return img;
  }
  function time(value) {
    const date = new Date(typeof value === 'number' ? value * 1000 : value);
    const node = element('time', 'mgr-time');
    if (!Number.isNaN(date.getTime())) { node.dateTime = date.toISOString(); node.textContent = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); node.title = date.toLocaleString(); }
    return node;
  }
  function source(m) { return typeof m.source_id === 'string' && m.source_id.trim() && m.source_id.length < 2048 && m.source_available !== false; }
  function link(m, label = 'Open thread') {
    const a = element('a', '', label); a.href = '/wizard/?session=' + encodeURIComponent(m.source_id); a.target = '_top';
    a.addEventListener('click', event => { saveScroll(); if (!persist()) { event.preventDefault(); renderControls(); say('Draft couldn’t be saved. Keep this window open.'); } });
    return a;
  }
  function attention(m) {
    // Only structured plain text is displayed. No worker-provided action is executable.
    try { const value = typeof m.attention === 'string' ? JSON.parse(m.attention) : m.attention; return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; } catch (_) { return {}; }
  }
  function targetOf(m) { return { reply_to: m.id, source_id: m.source_id, source_message: m.source_message || null, title: m.title || 'Work thread' }; }
  function targetInvalid() {
    if (!draft.target) return false;
    const m = messages.get(draft.target.reply_to);
    return loaded && (!m || !source(m) || m.source_id !== draft.target.source_id || (draft.target.source_message && m.source_message !== draft.target.source_message));
  }
  function renderMessage(m, previous) {
    const li = element('li', 'mgr-turn ' + (m.role === 'user' ? 'mgr-user' : 'mgr-assistant'));
    li.dataset.messageId = String(m.id);
    li.setAttribute('aria-label', m.role === 'user' ? 'You' : 'Archimedes');
    const continuation = m.role !== 'user' && previous?.role === m.role && m.kind === 'chat' && previous.kind === 'chat';
    li.classList.toggle('is-continuation', continuation);
    let body = li;
    if (m.role !== 'user') { body = element('div', 'mgr-body'); li.append(portrait(), body); }
    if (m.kind === 'ready') {
      const card = element('article', 'mgr-card'); card.dataset.readyId = String(m.id);
      const hasSource = !!source(m), a = attention(m), ask = typeof a.ask === 'string' ? a.ask : '';
      card.classList.toggle('has-source', hasSource);
      card.classList.toggle('has-attention', !!ask || ['blocked', 'failed', 'needs_input', 'needs_approval'].includes(a.state));
      const top = element('div', 'mgr-card-top'); top.append(element('span', '', 'Ready'), time(m.created));
      card.append(top, element('h2', '', m.title || 'Work thread'), element('p', 'mgr-summary', m.text));
      if (ask) card.append(element('p', 'mgr-ask', ask));
      if (m.source_available === false) card.append(element('p', '', 'This thread isn’t available anymore.'));
      const actions = element('div', 'mgr-actions');
      if (hasSource) actions.append(link(m));
      actions.append(action('Reply', () => chooseTarget(targetOf(m)), !hasSource));
      card.append(actions); body.append(card);
    } else if (m.kind === 'delegation' && source(m)) {
      // Backend emits delegation only after actual downstream run admission.
      const receipt = element('div', 'mgr-receipt');
      receipt.append(element('strong', '', 'Sent to a work thread · ' + (m.title || 'Work thread')), element('p', '', 'Accepted—not finished yet.'));
      const actions = element('div', 'mgr-actions'); actions.append(link(m, 'Open thread →')); receipt.append(actions); body.append(receipt, time(m.created));
    } else {
      body.append(element('p', 'mgr-text', m.text));
      if (source(m) && m.role !== 'user') { const actions = element('div', 'mgr-actions'); actions.append(link(m)); body.append(actions); }
      if (!continuation) body.append(time(m.created));
    }
    if (m.role === 'user' && typeof m.job_id === 'string' && m.job_id.startsWith('user:')) {
      const id = m.job_id.slice(5), state = element('div', 'mgr-message-state');
      body.append(state); jobNodes.set(id, state);
    }
    return li;
  }
  function requestTarget(id, m) {
    const reply = Number.isSafeInteger(m.reply_to) ? messages.get(m.reply_to) : null;
    return reply ? targetOf(reply) : draft.receipts[id] || null;
  }
  function renderJobs() {
    const active = new Map(jobs.map(j => [j.id, j]));
    const answers = new Map([...messages.values()].filter(m => m.job_id?.startsWith('answer:')).map(m => [m.job_id.slice(7), m]));
    for (const m of messages.values()) {
      if (!m.job_id?.startsWith('user:')) continue;
      const id = m.job_id.slice(5), node = jobNodes.get(id); if (!node) continue;
      const job = active.get(id), answer = answers.get(id), target = requestTarget(id, m);
      const busy = retrying.has(id), error = jobErrors.has(id);
      const key = JSON.stringify([job?.status, answer?.kind, target?.title, enabled, busy, error, connected, togglePending]);
      if (node.dataset.state === key) continue;
      node.dataset.state = key; node.replaceChildren();
      if (target) node.append(element('span', 'mgr-message-state', '↳ to ' + target.title));
      if (target && answer?.kind === 'delegation') node.append(element('span', '', 'Delivered to thread'));
      else if (job?.status === 'failed') {
        node.append(element('span', '', 'Archimedes couldn’t finish that reply.'), action(busy ? 'Checking…' : 'Retry', () => retryJob(id), busy || !canOperate()));
        if (error) node.append(element('span', '', 'Couldn’t confirm the retry. Check again before retrying.'), action('Check again', () => refresh()));
      } else if (job && ['queued', 'working'].includes(job.status)) {
        node.append(element('span', '', target ? 'Waiting for thread delivery…' : 'Waiting for a response…'));
      }
    }
  }
  function canOperate() { return !!core && loaded && connected && navigator.onLine && enabled === true && togglePending === null && !toggleUnknown; }
  function renderControls() {
    $('storage-state').hidden = saved;
    $('send').disabled = !canOperate() || !saved || !input.value.trim() || !!draft.sending || submitting || targetInvalid() || !!pendingTarget;
    input.placeholder = draft.target ? 'Reply in ' + draft.target.title + '…' : 'Message Archimedes';
    input.setAttribute('aria-label', draft.target ? 'Reply in ' + draft.target.title : 'Message Archimedes');
    $('send').setAttribute('aria-label', draft.target ? 'Send to ' + draft.target.title : 'Send to Archimedes');
    panel('destination', JSON.stringify([draft.target, targetInvalid(), !!input.value]), node => {
      if (draft.target) {
        if (targetInvalid()) {
          node.append(element('span', 'mgr-error', 'Can’t reply: ' + draft.target.title + ' isn’t available.'), action('Message Archimedes instead', clearTarget));
        } else {
          const strip = element('div', 'mgr-target'); const clear = action('×', clearTarget); clear.setAttribute('aria-label', 'Clear reply target');
          strip.append(element('span', '', '↳ Replying in ' + draft.target.title), clear); node.append(strip);
        }
      } else if (input.value) node.append(element('span', 'mgr-to', 'To Archimedes'));
    });
    panel('confirmation', JSON.stringify(pendingTarget), node => {
      if (!pendingTarget) return;
      node.append(element('span', '', 'Reply in ' + pendingTarget.title + ' instead?'));
      node.append(action('Keep current target', cancelTarget), action('Switch to ' + pendingTarget.title, () => { const next = pendingTarget; cancelTarget(); setTarget(next); }));
    });
    panel('send-state', JSON.stringify([draft.sending?.state, draft.sending?.request_id, enabled, submitting, canOperate()]), node => {
      const s = draft.sending;
      if (submitting) node.append(element('span', '', 'Sending…'));
      else if (s) {
        node.append(element('span', '', s.state === 'rejected' ? 'Not sent.' : 'Couldn’t confirm this was sent.'));
        node.append(action('Check again', () => refresh()));
        node.append(action('Retry original', retrySubmission, !canOperate() || !saved));
        node.append(element('span', 'mgr-message-state', 'Retry sends the original message, not your newer edits. Check the conversation before sending again.'));
        if (s.state === 'rejected') node.append(action('Use edited draft', () => { draft.sending = null; persist(); renderControls(); input.focus(); }));
      } else if (enabled === false) node.append(element('span', '', 'Turn on Manager to send.'));
    });
    panel('notice', JSON.stringify([!!core, navigator.onLine, saved, loaded, connected, connectionFailed, enabled, togglePending, toggleUnknown, toggleError]), node => {
      if (!core) node.append(element('span', '', 'Wizard system functions are unavailable. Open Manager through Wizard.'));
      else if (togglePending !== null) node.append(element('span', '', togglePending ? 'Turning on…' : 'Turning off… Sending is paused.'));
      else if (toggleUnknown) node.append(element('span', '', 'Couldn’t confirm Manager’s state.'), action('Check again', () => refresh()));
      else if (!navigator.onLine) node.append(element('span', '', saved ? 'You’re offline. Your draft is saved on this device.' : 'You’re offline. Keep this window open to retain your draft.'));
      else if (!connected && connectionFailed) node.append(element('span', '', 'Can’t reach Manager right now.'), action('Try again', () => refresh()));
      else if (!loaded) node.append(element('span', '', connected ? 'Loading conversation…' : 'Connecting to Manager…'), action('Try again', () => refresh()));
      else if (toggleError) node.append(element('span', '', toggleError), action('Try again', () => setEnabled(!enabled)));
      else if (enabled === false) node.append(element('span', '', 'Manager is off. Work already started continues in Chats.'), action('Turn on', () => setEnabled(true)));
    });
    $('empty').hidden = !loaded || messages.size > 0;
    $('empty-title').textContent = enabled === false ? 'Archimedes is off' : 'Archimedes';
    $('empty-copy').textContent = enabled === false ? 'Turn on Manager to chat here. Your Chats work as usual.' : 'Talk to me here. I’ll keep replies short and bring back results from your work threads.';
    $('empty-enable').hidden = enabled !== false;
    $('empty-enable').disabled = togglePending !== null || !connected;
    $('enabled').disabled = !loaded || !connected || togglePending !== null || toggleUnknown;
    $('enabled').setAttribute('aria-checked', String(enabled === true));
    $('enabled-label').textContent = enabled === null ? 'Checking…' : enabled ? 'On' : 'Off';
    $('options-state').textContent = togglePending !== null ? (togglePending ? 'Turning on…' : 'Turning off… Sending is paused.') : toggleUnknown ? 'Couldn’t confirm Manager’s state.' : toggleError;
    for (const [id, node] of nodes) node.querySelector('.mgr-card')?.classList.toggle('is-target', draft.target?.reply_to === id);
    renderJobs();
  }
  function resizeInput() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 156, Math.max(44, scroller.parentElement.clientHeight * .35)) + 'px';
  }
  function saveScroll() {
    const first = [...nodes.values()].find(node => node.getBoundingClientRect().bottom > scroller.getBoundingClientRect().top);
    draft.scroll = { pinned, anchorMessageId: first ? Number(first.dataset.messageId) : null, offset: first ? first.getBoundingClientRect().top - scroller.getBoundingClientRect().top : 0 };
  }
  function toBottom() { scroller.scrollTop = scroller.scrollHeight; pinned = true; newBelow = 0; $('jump').hidden = true; saveScroll(); persist(); }
  function reconcileSubmission() {
    const s = draft.sending; if (!s) return;
    const accepted = [...messages.values()].some(m => m.job_id === 'user:' + s.request_id || m.job_id === 'answer:' + s.request_id);
    if (!accepted) return;
    if (s.target) draft.receipts[s.request_id] = s.target;
    // Receipts are only a compatibility aid until the server includes reply_to in user turns.
    const entries = Object.entries(draft.receipts); if (entries.length > 300) draft.receipts = Object.fromEntries(entries.slice(-300));
    if (draft.rev === s.rev && draft.text === s.draftText) {
      draft.text = ''; draft.target = null; draft.rev++; input.value = ''; cancelTarget(); resizeInput();
    }
    draft.sending = null; persist();
  }
  async function api(path, body) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const r = await fetch(path, { signal: controller.signal, cache: 'no-store', ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
      if (!r.ok) { const error = new Error('Request failed'); error.status = r.status; throw error; }
      return await r.json();
    } finally { clearTimeout(timeout); }
  }
  function merge(data) {
    if (typeof data.enabled !== 'boolean' || !Array.isArray(data.messages) || !Array.isArray(data.jobs)) throw new Error('Invalid state');
    const newMessages = [];
    for (const m of data.messages) {
      if (!Number.isSafeInteger(m.id) || m.id <= 0 || !['user', 'assistant'].includes(m.role) || typeof m.text !== 'string') throw new Error('Invalid message');
      if (!messages.has(m.id)) { messages.set(m.id, m); newMessages.push(m); }
      cursor = Math.max(cursor, m.id);
    }
    if (enabled !== data.enabled) toggleError = '';
    jobs = data.jobs; enabled = data.enabled; connected = true; connectionFailed = false; toggleUnknown = false;
    const ordered = [...messages.values()].sort((a, b) => a.id - b.id);
    // Append only unseen stable IDs: no polling replacement, selection loss or theme rerender.
    for (let i = 0; i < ordered.length; i++) {
      const m = ordered[i]; if (nodes.has(m.id)) continue;
      const li = renderMessage(m, ordered[i - 1]); nodes.set(m.id, li); thread.append(li);
    }
    reconcileSubmission();
    if (loaded && newMessages.length) {
      if (pinned) { scroller.scrollTop = scroller.scrollHeight; }
      else { newBelow += newMessages.length; $('jump').textContent = newBelow + ' new below ↓'; $('jump').hidden = false; }
      const recent = newMessages.filter(m => m.role === 'assistant').at(-1);
      if (recent) say(recent.kind === 'ready' ? 'Ready: ' + (recent.title || 'Work thread') : 'Archimedes: ' + recent.text.slice(0, 180));
    }
  }
  async function refresh() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
      try {
        // state is paged by ascending integer id; drain full pages before validating restored targets.
        let page;
        do {
          const before = cursor;
          page = await api('api/state?after=' + cursor); merge(page);
          if (page.messages.length && cursor <= before) throw new Error('State cursor did not advance');
        } while (page.messages.length === 1000);
        loaded = true;
        if (restoring) {
          restoring = false; resizeInput(); pinned = draft.scroll?.pinned !== false;
          const anchor = nodes.get(draft.scroll?.anchorMessageId);
          if (pinned) scroller.scrollTop = scroller.scrollHeight;
          else if (anchor) scroller.scrollTop += anchor.getBoundingClientRect().top - scroller.getBoundingClientRect().top - (Number(draft.scroll.offset) || 0);
        }
        renderControls(); return true;
      } catch (_) { connected = false; connectionFailed = true; renderControls(); return false; }
      finally { refreshing = null; }
    })();
    return refreshing;
  }
  function cancelTarget() { pendingTarget = null; confirmLayer?.release(); confirmLayer = null; renderControls(); }
  function setTarget(target) { draft.target = target; draft.rev++; persist(); renderControls(); input.focus(); }
  function clearTarget() { cancelTarget(); setTarget(null); }
  function chooseTarget(target) {
    if (draft.target?.reply_to === target.reply_to) { input.focus(); return; }
    if (!input.value.trim()) { cancelTarget(); setTarget(target); return; }
    cancelTarget(); pendingTarget = target; confirmLayer = core?.back.push(() => { cancelTarget(); return true; }); renderControls();
    $('confirmation').querySelector('button')?.focus();
  }
  async function submitSnapshot() {
    const s = draft.sending; if (!s || submitting || !canOperate() || !saved) return;
    submitting = true; s.state = 'sending';
    if (!persist()) { submitting = false; s.state = 'uncertain'; renderControls(); return; }
    renderControls(); toBottom();
    try {
      const result = await api('api/messages', { text: s.text, request_id: s.request_id, ...(s.reply_to == null ? {} : { reply_to: s.reply_to }) });
      if (result.accepted !== true || result.request_id !== s.request_id) throw new Error('No admission receipt');
      // Read back the actual user turn before clearing the exact submitted revision.
      await refresh();
      if (draft.sending?.request_id === s.request_id) { draft.sending.state = 'uncertain'; persist(); }
    } catch (error) {
      if (draft.sending?.request_id === s.request_id) {
        draft.sending.state = [400, 401, 403, 404, 409, 413, 422, 429].includes(error.status) ? 'rejected' : 'uncertain';
        persist(); say(draft.sending.state === 'rejected' ? 'Not sent.' : 'Couldn’t confirm this was sent.');
      }
    } finally { submitting = false; renderControls(); }
  }
  async function retrySubmission() {
    // A replay uses POST /messages with the original key AND payload. /retry is only for accepted failed jobs.
    await refresh();
    if (draft.sending && canOperate()) await submitSnapshot();
  }
  async function retryJob(id) {
    if (retrying.has(id) || !canOperate()) return;
    retrying.add(id); jobErrors.delete(id); renderJobs();
    try {
      await refresh();
      if (!jobs.some(j => j.id === id && j.status === 'failed') || !canOperate()) return;
      await api('api/retry', { request_id: id });
      if (!await refresh()) throw new Error('Retry unconfirmed');
    } catch (_) { jobErrors.add(id); say('Couldn’t confirm the retry. Check again.'); }
    finally { retrying.delete(id); renderJobs(); }
  }
  async function setEnabled(next) {
    if (togglePending !== null) return;
    togglePending = next; toggleError = ''; renderControls();
    let succeeded = false;
    try {
      if (refreshing) await refreshing;
      await api('api/settings', { enabled: next });
      if (refreshing) await refreshing;
      succeeded = await refresh();
      if (!succeeded) throw new Error('Settings unconfirmed');
      if (enabled !== next) throw new Error('Settings mismatch');
      say(enabled ? 'Manager is on.' : 'Manager is off. Work already started continues in Chats.');
    } catch (_) {
      // A fresh authoritative read, never the pre-toggle switch, determines failure copy.
      succeeded = await refresh();
      if (!succeeded) toggleUnknown = true;
      else if (enabled !== next) toggleError = next ? 'Couldn’t turn Manager on. It’s off.' : 'Couldn’t turn Manager off. It’s on.';
      else say(enabled ? 'Manager is on.' : 'Manager is off. Work already started continues in Chats.');
    } finally { togglePending = null; renderControls(); }
  }
  function closeOptions() { if ($('options').open) $('options').close(); optionsLayer?.release(); optionsLayer = null; $('options-open').focus(); }
  $('options-open').onclick = () => { $('options').showModal(); optionsLayer = core?.back.push(() => { closeOptions(); return true; }); $('options-close').focus(); };
  $('options-close').onclick = closeOptions;
  $('options').addEventListener('cancel', event => { event.preventDefault(); closeOptions(); });
  $('options').addEventListener('click', event => { if (event.target === $('options')) { const r = $('options').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeOptions(); } });
  $('enabled').onclick = () => setEnabled(!enabled);
  $('empty-enable').onclick = () => setEnabled(true);
  $('jump').onclick = toBottom;
  input.addEventListener('input', () => { draft.text = input.value; draft.rev++; persist(); resizeInput(); renderControls(); if (pinned) scroller.scrollTop = scroller.scrollHeight; });
  input.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229 || event.shiftKey) return;
    // Touch/hybrid devices default to newline unless the user explicitly presses Ctrl/Cmd+Enter.
    const hardwareOnly = navigator.maxTouchPoints === 0 && matchMedia('(pointer:fine)').matches;
    if (event.ctrlKey || event.metaKey || hardwareOnly) { event.preventDefault(); if (!$('send').disabled) $('compose').requestSubmit(); }
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && pendingTarget && !$('options').open) { event.preventDefault(); cancelTarget(); input.focus(); } });
  $('compose').onsubmit = event => {
    event.preventDefault(); if ($('send').disabled) return;
    draft.sending = { request_id: crypto.randomUUID(), rev: draft.rev, text: input.value.trim(), draftText: input.value, reply_to: draft.target?.reply_to ?? null, target: draft.target ? { ...draft.target } : null, state: 'sending' };
    if (!persist()) { renderControls(); return; }
    void submitSnapshot();
  };
  scroller.addEventListener('scroll', () => {
    if (restoring) return;
    pinned = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
    if (pinned) { newBelow = 0; $('jump').hidden = true; }
    if (!scrollFrame) scrollFrame = requestAnimationFrame(() => { scrollFrame = 0; saveScroll(); persist(); });
  }, { passive: true });
  addEventListener('pagehide', () => { saveScroll(); persist(); });
  addEventListener('offline', renderControls);
  addEventListener('online', () => refresh());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); else { saveScroll(); persist(); } });
  function viewport() {
    const wasPinned = pinned;
    // Hosted height belongs to the containing window, never the outer visual viewport.
    if (!core?.hosted && !document.documentElement.classList.contains('wz-hosted') && !document.documentElement.hasAttribute('data-wz-hosted')) {
      document.querySelector('.mgr').style.height = (window.visualViewport?.height || innerHeight) + 'px';
    } else document.querySelector('.mgr').style.removeProperty('height');
    resizeInput(); if (wasPinned && !restoring) scroller.scrollTop = scroller.scrollHeight;
  }
  restore(); input.value = draft.text;
  $('header-portrait').append(portrait()); $('empty-portrait').append(portrait(true));
  if (core) {
    core.back.register({ canGoBack: () => !!draft.target, back: () => { if (!draft.target) return false; clearTarget(); return true; } });
    core.ready({ name: 'wizard-manager', version: '0.2.0' }).then(() => {
      document.documentElement.classList.toggle('wz-hosted', core.hosted);
      if (!saved) hold ||= core.update.hold('unsaved Manager draft');
      viewport();
    });
    core.theme.onChange(viewport);
  }
  window.visualViewport?.addEventListener('resize', viewport); addEventListener('resize', viewport);
  viewport(); renderControls(); refresh();
  setInterval(() => { if (!document.hidden && navigator.onLine && togglePending === null) refresh(); }, 5000);
})();
