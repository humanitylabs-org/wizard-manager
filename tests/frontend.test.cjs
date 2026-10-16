/* Isolated browser contracts. No live API: the HTTP server explicitly rejects /api.
 * Thales: CORE_CLIENT=/path/to/core/app-client.js PLAYWRIGHT_MODULE=/path/to/playwright
 * CHROMIUM_EXECUTABLE=/path/to/Chromium node --test tests/frontend.test.cjs
 * Optional FRONTEND_EVIDENCE_DIR retains screenshots on the remote worker.
 */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../web');
let server, browser, origin;
const evidence = process.env.FRONTEND_EVIDENCE_DIR;
const stamp = 1750000000;
const ready = (id, title = 'Research notes', extra = {}) => ({ id, role: 'assistant', kind: 'ready', title, source_id: 'thread/' + id, source_message: 'response-' + id, text: 'A source response is ready. Review the evidence and choose what to do next.', created: stamp, ...extra });
const user = (id, request, text = 'Hello') => ({ id, role: 'user', kind: 'chat', job_id: 'user:' + request, text, created: stamp });
const answer = (id, request, text = 'Hello. What would you like to work on?') => ({ id, role: 'assistant', kind: 'chat', job_id: 'answer:' + request, text, created: stamp });
const fixtureHost = `<!doctype html><html><body style="margin:0"><button id="back" onclick="window.domain.back()">Host Back</button><iframe title="Manager fixture" src="/index.html" style="border:0;width:100%;height:calc(100vh - 30px)"></iframe><script>
window.holds=0;window.WizAppServices={connect:(frame,domain)=>{window.domain=domain;return{ready:()=>({version:1,hosted:true}),view:{isVisible:()=>!window.qaHidden},nav:{openThread:id=>{window.openedThread=id;return true;}},update:{hold:()=>{window.holds++;let released=false;return{release:()=>{if(!released){released=true;window.holds--;}}}}}}}};
</script></body></html>`;
before(async () => {
  assert.ok(process.env.CORE_CLIENT, 'CORE_CLIENT must point to the real shared core source');
  assert.ok(fs.existsSync(process.env.CORE_CLIENT), 'CORE_CLIENT file must exist; missing core invalidates this QA run');
  server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://fixture').pathname;
    if (pathname.includes('/api/')) { res.writeHead(500); return res.end('Live API forbidden in frontend tests'); }
    if (pathname === '/host') { res.setHeader('Content-Type', 'text/html'); return res.end(fixtureHost); }
    const file = pathname === '/wizard-os-home/core/app-client.js' ? process.env.CORE_CLIENT : path.join(root, pathname === '/' ? 'index.html' : pathname.slice(1));
    if (pathname.includes('..') || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); return res.end(); }
    res.setHeader('Content-Type', ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.webp': 'image/webp' })[path.extname(file)] || 'text/plain');
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = 'http://127.0.0.1:' + server.address().port;
  browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}) });
  if (evidence) fs.mkdirSync(evidence, { recursive: true });
});
after(async () => { await browser?.close(); if (server) await new Promise(resolve => server.close(resolve)); });
async function setup(t, options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 390, height: 844 }, hasTouch: options.touch ?? true });
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = []; page.on('pageerror', e => errors.push(String(e))); t.after(() => assert.deepEqual(errors, []));
  const state = { enabled: true, messages: [], jobs: [], ...options.state };
  const posts = [];
  let custom = options.route || null;
  await context.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url());
    if (custom && await custom(route, req, url)) return;
    const fulfill = data => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    if (url.pathname === '/api/state') return fulfill({ ...state, messages: state.messages.filter(m => m.id > Number(url.searchParams.get('after') || 0)).slice(0, 1000) });
    const body = req.postDataJSON(); posts.push({ path: url.pathname, body });
    if (url.pathname === '/api/messages') {
      if (!state.messages.some(m => m.job_id === 'user:' + body.request_id)) {
        state.messages.push(user((state.messages.at(-1)?.id || 0) + 1, body.request_id, body.text));
        state.jobs.push({ id: body.request_id, status: 'queued' });
      }
      return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ accepted: true, request_id: body.request_id }) });
    }
    if (url.pathname === '/api/settings') { state.enabled = body.enabled; return fulfill(state); }
    if (url.pathname === '/api/retry') { const job = state.jobs.find(j => j.id === body.request_id); if (job?.status === 'failed') job.status = 'queued'; return fulfill({ accepted: true }); }
    throw new Error('Unexpected API ' + url.pathname);
  });
  if (options.init) await context.addInitScript(options.init);
  await page.goto(origin + (options.hosted ? '/host' : '/index.html'));
  const frame = options.hosted ? page.frames().find(f => f.url().endsWith('/index.html')) : page;
  await frame.waitForFunction(() => !document.getElementById('notice').textContent.includes('Connecting'));
  const poll = async () => { await frame.evaluate(() => window.dispatchEvent(new Event('online'))); await page.waitForTimeout(100); };
  const draft = () => frame.evaluate(() => JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')));
  return { page, frame, context, state, posts, poll, draft, custom: fn => { custom = fn; } };
}
for (const viewport of [{width:390,height:844},{width:1280,height:900}]) test(`caught-up return keeps last messages and exposes first new boundary ${viewport.width}`, async t => {
  const f=await setup(t,{hosted:true,viewport,state:{messages:Array.from({length:20},(_,i)=>ready(i+1))},init:()=>localStorage.getItem('wizard-manager:conversation:v1')||localStorage.setItem('wizard-manager:conversation:v1',JSON.stringify({rev:0,text:'kept draft',scroll:{pinned:true},read:{seen:0,viewed:[19,20],divider:1}}))});
  await f.page.waitForTimeout(1100);
  assert.equal((await f.draft()).read.seen,20,'migrate the stranded old-history boundary');
  await f.frame.evaluate(()=>{const e=document.querySelector('#conversation');e.scrollTop=e.scrollHeight;});
  await f.page.waitForTimeout(300);const before=(await f.draft()).scroll;
  await f.page.evaluate(()=>{window.qaHidden=true;document.querySelector('iframe').style.display='none';});
  await f.page.waitForTimeout(400);
  assert.deepEqual((await f.draft()).scroll,before,'hidden zero geometry must not overwrite saved position');
  f.state.messages.push(ready(21),ready(22),ready(23));
  await f.page.evaluate(()=>{window.qaHidden=false;document.querySelector('iframe').style.display='';});
  await f.poll();await f.frame.waitForSelector('[data-message-id="23"]');
  const view=await f.frame.evaluate(()=>{const s=document.querySelector('#conversation').getBoundingClientRect(),d=document.querySelector('.mgr-new-messages'),r=d?.getBoundingClientRect();return {id:d?.nextElementSibling?.dataset.messageId,offset:r?.top-s.top,bottom:r?.bottom-s.top,height:s.height};});
  assert.equal(view.id,'21');assert(view.offset>=0&&view.bottom<view.height,'first new boundary must be visible on return');
  assert(view.offset>=77,'keep a little of the last-read message above the line');
  const top=await f.frame.locator('#conversation').evaluate(e=>e.scrollTop);
  f.state.messages.push(ready(24));await f.poll();
  assert(Math.abs(await f.frame.locator('#conversation').evaluate(e=>e.scrollTop)-top)<3,'subsequent arrivals must not jump to the end');
  assert.equal(await f.frame.locator('.mgr-new-messages').evaluate(e=>e.nextElementSibling.dataset.messageId),'21');
  const saved=(await f.draft()).scroll;
  await f.page.reload();const frame=f.page.frames().find(x=>x.url().endsWith('/index.html'));await frame.waitForSelector('[data-message-id="24"]');await f.page.waitForTimeout(300);
  const restored=await frame.evaluate(()=>JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')));
  assert.equal(restored.scroll.anchorMessageId,saved.anchorMessageId);assert(Math.abs(restored.scroll.offset-saved.offset)<3);assert.equal(restored.text,'kept draft');
});
for (const viewport of [{width:390,height:844},{width:1280,height:900}]) test(`messages-below badge counts restored unread history and follows reading ${viewport.width}`, async t => {
  const f = await setup(t, {hosted:true, viewport, state:{messages:Array.from({length:20},(_,i)=>ready(i+1))}, init:()=> {
    if (!localStorage.getItem('wizard-manager:conversation:v1')) localStorage.setItem('wizard-manager:conversation:v1', JSON.stringify({rev:0,text:'keep draft',scroll:{pinned:false,anchorMessageId:5,offset:0},read:{version:2,seen:4,viewed:[],divider:5}}));
  }});
  const expected = () => f.frame.evaluate(() => {
    const bottom = document.querySelector('#conversation').getBoundingClientRect().bottom;
    const read = JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).read;
    return [...document.querySelectorAll('.mgr-assistant[data-message-id]')].filter(n => Number(n.dataset.messageId)>read.seen && !read.viewed.includes(Number(n.dataset.messageId)) && n.getBoundingClientRect().bottom>bottom+1).length;
  });
  await f.page.waitForTimeout(350);
  const first = await expected(); assert(first>0);
  assert.equal(await f.frame.locator('#jump').textContent(), first+' new below ↓');
  await f.frame.locator('#conversation').evaluate(e=>e.scrollTop+=600); await f.page.waitForTimeout(350);
  const second = await expected(); assert(second<first);
  assert.equal(await f.frame.locator('#jump').textContent(), second+' new below ↓');
  const top = await f.frame.locator('#conversation').evaluate(e=>e.scrollTop);
  f.state.messages.push(ready(21)); await f.poll();
  assert.equal(await f.frame.locator('#conversation').evaluate(e=>e.scrollTop),top);
  assert.equal(await f.frame.locator('#jump').textContent(),(await expected())+' new below ↓');
  await f.page.reload(); f.frame=f.page.frames().find(x=>x.url().endsWith('/index.html')); await f.frame.waitForSelector('[data-message-id="21"]'); await f.page.waitForTimeout(350);
  assert.equal(await f.frame.locator('#jump').textContent(),(await expected())+' new below ↓');
  if(evidence) await f.page.screenshot({path:path.join(evidence,'messages-below-'+viewport.width+'.png')});
  await f.frame.locator('#jump').click(); assert.equal(await f.frame.locator('#jump').isVisible(),false);
  assert.equal(await f.frame.locator('#message').inputValue(),'keep draft');
  await f.page.waitForTimeout(1000);
  await f.frame.locator('#conversation').evaluate(e=>e.scrollTop=0); await f.page.waitForTimeout(350);
  assert.equal(await f.frame.locator('#jump').textContent(),'↓ Latest','read history retains navigation without an unread badge');
  assert.equal(f.posts.length,0);
});

test('hidden sources purge retained cards and receipt metadata without losing user text; recovery replays older IDs', async t => {
  const hidden = ready(1, 'Hidden source title');
  const f = await setup(t, {state:{messages:[hidden, user(2,'fixture-user','Keep my words'), ready(3,'Archived genuine result')], suppressed_sources:[]}});
  await f.frame.locator('[data-ready-id="1"] button').click();
  await f.frame.locator('#message').fill('Keep my unsent draft');
  await f.frame.evaluate(() => { window.keptUserNode = document.querySelector('[data-message-id="2"]'); });
  f.state.suppressed_sources = [hidden.source_id];
  f.state.messages = f.state.messages.filter(m => m.id !== 1);
  await f.poll();
  assert.equal(await f.frame.locator('[data-message-id="1"]').count(), 0);
  assert.equal(await f.frame.locator('[data-message-id="3"]').count(), 1, 'archive is not hidden');
  assert.equal(await f.frame.locator('#message').inputValue(), 'Keep my unsent draft');
  assert.equal(await f.frame.locator('#send').isEnabled(), false, 'do not silently redirect a hidden-target draft');
  assert.equal(await f.frame.evaluate(() => document.body.textContent.includes('Hidden source title')), false);
  assert.equal(JSON.stringify(await f.draft()).includes('Hidden source title'), false);
  assert(await f.frame.evaluate(() => window.keptUserNode === document.querySelector('[data-message-id="2"]')));
  f.state.messages.unshift(hidden); f.state.suppressed_sources = [];
  await f.poll();
  assert.deepEqual(await f.frame.locator('[data-message-id]').evaluateAll(ns => ns.map(n => Number(n.dataset.messageId))), [1,2,3]);
  assert.equal(await f.frame.locator('#message').inputValue(), 'Keep my unsent draft');
  assert.equal(f.posts.length, 0);
  f.state.messages.shift(); f.state.suppressed_sources = [hidden.source_id]; await f.poll();
  await f.page.reload(); await f.frame.waitForSelector('[data-message-id="3"]');
  assert.equal(await f.frame.locator('[data-message-id="1"]').count(), 0);
  assert.equal(await f.frame.locator('#message').inputValue(), 'Keep my unsent draft');
});
test('a fully suppressed page drains using raw next_after rather than visible count', async t => {
  const offsets = [];
  const f = await setup(t, {route: async (route, req, url) => {
    if (url.pathname !== '/api/state') return false;
    const after = Number(url.searchParams.get('after')); offsets.push(after);
    await route.fulfill({json:{enabled:true,jobs:[],suppressed_sources:['hidden'],messages: after === 0 ? [] : [user(1001,'fixture-after-page')].filter(m => m.id > after),next_after:after === 0 ? 1000 : 1001,has_more:after === 0}}); return true;
  }});
  await f.frame.waitForSelector('[data-message-id="1001"]');
  assert(offsets.includes(1000)); assert.equal(f.posts.length,0);
});
test('inline named links update historical display only; safe anchors retain draft and exact destinations', async t => {
  const threads = [{id: 'thread/one', title: 'Wizard OS · Share files'}, {id: 'thread/two', title: 'Unify responsive features across desktop and mobile'}];
  const text = 'Share files and Unify responsive features are running.';
  const f = await setup(t, { hosted: true, state: { threads: [], messages: [answer(1, 'history', text), user(2, 'human', text), ready(3, 'Summary', {text})] } });
  await f.frame.locator('#message').fill('Do not change my draft <>&');
  await f.frame.evaluate(() => { window.savedTurn = document.querySelector('[data-message-id="1"]'); });
  f.state.threads = threads; await f.poll();
  const links = f.frame.locator('[data-message-id="1"] .mgr-text a');
  assert.deepEqual(await links.evaluateAll(nodes => nodes.map(n => [n.textContent, n.getAttribute('href'), n.target])), [
    ['Share files', '/wizard-os-home/?session=thread%2Fone', '_top'], ['Unify responsive features', '/wizard-os-home/?session=thread%2Ftwo', '_top']]);
  assert.equal(await f.frame.locator('.mgr-summary a').count(), 2);
  assert.equal(await f.frame.locator('.mgr-user a').count(), 0);
  assert.equal(await f.frame.locator('.mgr-user .mgr-text').textContent(), text);
  assert.equal(await f.frame.locator('[data-message-id="1"] .mgr-text').textContent(), text);
  await f.frame.evaluate(() => { window.savedAnchor = document.querySelector('.mgr-text a'); });
  await f.poll();
  assert(await f.frame.evaluate(() => window.savedTurn === document.querySelector('[data-message-id="1"]') && window.savedAnchor === document.querySelector('.mgr-text a')));
  const before = await f.draft();
  f.state.threads = []; await f.poll();
  assert.equal(await links.count(), 0, 'unavailable inventory removes inline links, not text');
  assert.equal((await f.draft()).text, before.text);
  f.state.threads = threads; await f.poll();
  await f.context.route('**/wizard-os-home/?session=*', route => route.fulfill({contentType: 'text/html', body: '<h1>Isolated destination</h1>'}));
  await links.nth(1).click();
  assert.equal(await f.page.evaluate(() => openedThread), 'thread/two');
  assert.match(f.page.url(), /\/host$/);
  assert.equal(await f.page.evaluate(() => JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).text), before.text);
  assert.equal(f.posts.length, 0);
});
test('explicit canonical links escape labels, reject arbitrary URLs and block navigation if draft save fails', async t => {
  const text = '[<img src=x onerror=alert(1)>](/wizard-os-home/?session=thread%2Fone) [Share files](javascript:alert) [Share files](/wizard-os-home/?session=missing)';
  const f = await setup(t, {state: {threads: [{id:'thread/one', title:'Share files'}], messages:[{...answer(1,'safe',text),source_id:'original'}]}});
  assert.equal(await f.frame.locator('.mgr-text img').count(), 0);
  assert.equal(await f.frame.locator('.mgr-text a').count(), 1);
  assert.equal(await f.frame.locator('.mgr-text a').textContent(), '<img src=x onerror=alert(1)>');
  assert.equal(await f.frame.locator('.mgr-actions a').getAttribute('href'), '/wizard-os-home/?session=original', 'existing source link remains');
  await f.frame.locator('#message').fill('Unsent draft');
  await f.frame.evaluate(() => { Storage.prototype.setItem = () => { throw new Error('fixture storage failure'); }; });
  await f.frame.locator('.mgr-text a').click();
  assert.ok(f.page.url().endsWith('/index.html'));
  assert.equal(await f.frame.locator('#message').inputValue(), 'Unsent draft');
});
test('read-only captured historical Manager paragraph resolves all nine canonical destinations', {skip: !process.env.MANAGER_HISTORY_SNAPSHOT}, async t => {
  const snapshot = JSON.parse(fs.readFileSync(process.env.MANAGER_HISTORY_SNAPSHOT, 'utf8'));
  for (const viewport of [{width:390,height:844}, {width:1440,height:1000}]) {
    const f = await setup(t, {hosted: true, viewport, state:{threads:snapshot.threads,messages:[snapshot.message]}});
    const actual = await f.frame.locator('.mgr-text a').evaluateAll(nodes => nodes.map(n => ({text:n.textContent,href:n.getAttribute('href')})));
    assert.deepEqual(actual, snapshot.expected);
    assert.equal(await f.frame.locator('.mgr-text').textContent(), snapshot.message.text);
    assert.equal(f.posts.length, 0);
    if (evidence) {
      await f.page.screenshot({path:path.join(evidence, 'historical-inline-' + viewport.width + '.png')});
      fs.writeFileSync(path.join(evidence, 'historical-inline-' + viewport.width + '.json'), JSON.stringify(actual,null,2));
    }
  }
});
test('empty is honest; standalone and hosted identity, width, and transparent inherited canvas', async t => {
  const f = await setup(t, { hosted: true, viewport: { width: 1440, height: 900 } });
  assert.equal(await f.frame.locator('#thread li').count(), 0);
  assert.match(await f.frame.locator('#empty-copy').textContent(), /Talk to me here/);
  assert.equal(await f.frame.locator('.mgr-head').isVisible(), false);
  assert.equal(await f.frame.locator('.mgr').evaluate(n => n.getBoundingClientRect().width), 640);
  assert.equal(await f.frame.locator('body').evaluate(n => getComputedStyle(n).backgroundColor), 'rgba(0, 0, 0, 0)');
  assert.equal(await f.frame.locator('[aria-live]').count(), 1);
  assert.equal(await f.frame.locator('#announcer').textContent(), '');
  if (evidence) await f.page.screenshot({ path: path.join(evidence, 'empty-desktop.png') });
});
test('Ready content is inert, faithful structured ask; stable exact card targeting and Back layers', async t => {
  const f = await setup(t, { hosted: true, state: { messages: [ready(1, 'First thread', { attention: JSON.stringify({ state: 'needs_approval', ask: 'May I publish this draft?', buttons: ['Approve everything'] }), text: '<img src=x onerror=alert(1)> Worker text.' }), ready(2, 'Second thread')] } });
  assert.equal(await f.frame.locator('.mgr-summary img').count(), 0);
  assert.match(await f.frame.locator('.mgr-ask').textContent(), /May I publish/);
  assert.equal(await f.frame.getByRole('button', { name: 'Approve everything' }).count(), 0);
  assert.equal(await f.frame.locator('[data-ready-id="1"] a').getAttribute('href'), '/wizard-os-home/?session=thread%2F1');
  assert.equal(await f.frame.locator('[data-ready-id="1"] a').getAttribute('target'), '_top');
  await f.frame.locator('#message').fill('Please approve the publication');
  await f.frame.locator('[data-ready-id="1"] button').click();
  assert.match(await f.frame.locator('#confirmation').textContent(), /Reply in First thread instead/);
  await f.page.locator('#back').click();
  assert.equal(await f.frame.locator('#confirmation').isVisible(), false);
  await f.frame.locator('[data-ready-id="1"] button').click();
  await f.frame.getByRole('button', { name: 'Switch to First thread', exact: true }).click();
  assert.equal((await f.draft()).target.reply_to, 1);
  await f.frame.locator('#options-open').click();
  await f.page.evaluate(() => window.domain.back());
  assert.equal(await f.frame.locator('#options').evaluate(n => n.open), false);
  assert.equal((await f.draft()).target.reply_to, 1);
  await f.page.locator('#back').click();
  assert.equal((await f.draft()).target, null);
  assert.equal(await f.frame.locator('#message').inputValue(), 'Please approve the publication');
  assert.match(await f.frame.locator('#destination').textContent(), /To Archimedes/);
  assert.equal(await f.page.evaluate(() => window.domain.back()), false, 'root delegates to core, no extra guard');
  assert.ok(f.page.url().endsWith('/host'));
  assert.equal(f.posts.length, 0);
});
test('durable admission is not delivery; actual user nodes dedupe and later answer unlocks delivery', async t => {
  const f = await setup(t, { state: { messages: [ready(1, 'Source result')] } });
  await f.frame.locator('[data-ready-id="1"] button').click();
  await f.frame.locator('#message').fill('Yes, publish the approved draft.');
  await f.frame.locator('#send').click();
  await f.frame.waitForFunction(() => document.querySelectorAll('.mgr-user').length === 1 && !document.getElementById('message').value);
  const sent = f.posts.find(p => p.path === '/api/messages').body;
  assert.equal(sent.reply_to, 1);
  assert.match(await f.frame.locator('.mgr-user').textContent(), /↳ to Source result/);
  assert.match(await f.frame.locator('.mgr-user').textContent(), /Waiting for thread delivery/);
  assert.doesNotMatch(await f.frame.locator('.mgr-user').textContent(), /Delivered/);
  await f.frame.locator('#message').fill('Another request');
  assert.equal(await f.frame.locator('#send').isEnabled(), true, 'queue does not block composition');
  await f.poll(); assert.equal(await f.frame.locator('.mgr-user').count(), 1);
  f.state.messages.push({ ...answer(3, sent.request_id), kind: 'delegation', source_id: 'thread/1', title: 'Source result' }); f.state.jobs = [];
  await f.poll();
  assert.match(await f.frame.locator('.mgr-user').textContent(), /Delivered to thread/);
  assert.match(await f.frame.locator('.mgr-receipt').textContent(), /Accepted—not finished yet/);
});
test('acceptance clears only submitted revision, not newer typing or new target', async t => {
  const f = await setup(t); let release; const gate = new Promise(r => { release = r; });
  f.custom(async (route, req, url) => {
    if (url.pathname !== '/api/messages') return false;
    const b = req.postDataJSON(); await gate;
    f.state.messages.push(user(1, b.request_id, b.text));
    await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ accepted: true, request_id: b.request_id }) }); return true;
  });
  await f.frame.locator('#message').fill('First revision'); await f.frame.locator('#send').click();
  await f.frame.locator('#message').fill('Newer text while sending'); release();
  await f.frame.waitForFunction(() => !JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).sending);
  assert.equal(await f.frame.locator('#message').inputValue(), 'Newer text while sending');
  assert.equal((await f.draft()).text, 'Newer text while sending');
});
test('lost acknowledgment survives reload; original key/payload replay, no automatic replay', async t => {
  const f = await setup(t); const captured = []; let lose = true;
  f.custom(async (route, req, url) => {
    if (url.pathname !== '/api/messages') return false;
    const b = req.postDataJSON(); captured.push(b);
    if (lose) { await route.abort('failed'); return true; }
    f.state.messages.push(user(1, b.request_id, b.text));
    await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ accepted: true, request_id: b.request_id }) }); return true;
  });
  await f.frame.locator('#message').fill('Original uncertain message'); await f.frame.locator('#send').click();
  await f.frame.locator('#send-state').getByText('Couldn’t confirm this was sent.', { exact: true }).waitFor();
  await f.frame.locator('#message').fill('New draft must survive');
  const key = (await f.draft()).sending.request_id;
  await f.page.reload(); await f.frame.getByRole('button', { name: 'Retry original' }).waitFor();
  assert.equal((await f.draft()).sending.request_id, key);
  assert.equal(captured.length, 1); assert.equal(await f.frame.locator('#send').isEnabled(), false);
  lose = false; await f.frame.getByRole('button', { name: 'Retry original' }).click();
  await f.frame.waitForFunction(() => !JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).sending);
  assert.deepEqual(captured[0], captured[1]);
  assert.equal(await f.frame.locator('#message').inputValue(), 'New draft must survive');
  assert.equal(await f.frame.locator('.mgr-user').count(), 1);
});
test('late accepted original reconciles via message job_id without retry POST', async t => {
  const f = await setup(t); let original;
  f.custom(async (route, req, url) => { if (url.pathname !== '/api/messages') return false; original = req.postDataJSON(); await route.abort('failed'); return true; });
  await f.frame.locator('#message').fill('Late acknowledgment'); await f.frame.locator('#send').click();
  await f.frame.getByRole('button', { name: 'Retry original' }).waitFor();
  f.state.messages.push(user(1, original.request_id, original.text));
  await f.frame.getByRole('button', { name: 'Check again', exact: true }).click();
  await f.frame.waitForFunction(() => !JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).sending);
  assert.equal(await f.frame.locator('#message').inputValue(), '');
  assert.equal(f.posts.length, 0);
});
test('failed accepted job uses /retry only, never creates another user message', async t => {
  const f = await setup(t, { state: { messages: [user(1, 'failed_00001')], jobs: [{ id: 'failed_00001', status: 'failed', error: 'PRIVATE PROVIDER STACK' }] } });
  assert.doesNotMatch(await f.frame.locator('body').textContent(), /PRIVATE PROVIDER/);
  await f.frame.getByRole('button', { name: 'Retry', exact: true }).click();
  await f.frame.getByText('Waiting for a response…', { exact: true }).waitFor();
  assert.deepEqual(f.posts.map(p => p.path), ['/api/retry']); assert.equal(await f.frame.locator('.mgr-user').count(), 1);
});
test('pause is immediately gated and state switch uses authoritative readback', async t => {
  const f = await setup(t); let release; const gate = new Promise(r => { release = r; });
  f.custom(async (route, req, url) => { if (url.pathname !== '/api/settings') return false; await gate; f.state.enabled = req.postDataJSON().enabled; await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }); return true; });
  await f.frame.locator('#message').fill('Kept while paused'); await f.frame.locator('#options-open').click(); await f.frame.locator('#enabled').click();
  assert.equal(await f.frame.locator('#enabled').getAttribute('aria-checked'), 'true');
  assert.equal(await f.frame.locator('#send').isEnabled(), false);
  assert.match(await f.frame.locator('#options-state').textContent(), /Turning off/);
  release(); await f.frame.waitForFunction(() => document.getElementById('enabled').getAttribute('aria-checked') === 'false');
  assert.equal(await f.frame.locator('#message').inputValue(), 'Kept while paused');
  await f.frame.locator('#options-close').click(); assert.match(await f.frame.locator('#notice').textContent(), /Work already started continues/);
});
test('invalid restored target never silently reroutes; explicit clear retains draft', async t => {
  const f = await setup(t, { init: () => { localStorage.setItem('wizard-manager:conversation:v1', JSON.stringify({ rev: 2, text: 'Retain me', target: { reply_to: 99, source_id: 'gone', title: 'Missing result' }, sending: null })); } });
  assert.match(await f.frame.locator('#destination').textContent(), /Can’t reply/); assert.equal(await f.frame.locator('#send').isEnabled(), false);
  await f.frame.getByRole('button', { name: 'Message Archimedes instead' }).click();
  assert.equal(await f.frame.locator('#message').inputValue(), 'Retain me'); assert.equal(await f.frame.locator('#send').isEnabled(), true);
  assert.match(await f.frame.locator('#destination').textContent(), /To Archimedes/);
});
test('storage failure gates send and source navigation, keeps an update hold', async t => {
  const f = await setup(t, { hosted: true, state: { messages: [ready(1)] }, init: () => { Storage.prototype.setItem = () => { throw new Error('disk full'); }; } });
  await f.frame.locator('#message').fill('Not durable yet');
  assert.equal(await f.frame.locator('#storage-state').isVisible(), true); assert.equal(await f.frame.locator('#send').isEnabled(), false);
  assert.ok(await f.page.evaluate(() => window.holds > 0));
  await f.frame.locator('.mgr-actions a').click(); assert.ok(f.page.url().endsWith('/host'));
  assert.equal(await f.frame.locator('#message').inputValue(), 'Not durable yet'); assert.equal(f.posts.length, 0);
});
test('touch Enter and IME never submit; explicit control-enter sends', async t => {
  const f = await setup(t);
  await f.frame.locator('#message').fill('One line'); await f.frame.locator('#message').press('Enter');
  assert.equal(await f.frame.locator('#message').inputValue(), 'One line\n'); assert.equal(f.posts.length, 0);
  await f.frame.locator('#message').evaluate(n => n.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, isComposing: true, bubbles: true })));
  assert.equal(f.posts.length, 0);
  await f.frame.locator('#message').press('Control+Enter'); await f.frame.locator('.mgr-user').waitFor();
  assert.equal(f.posts.length, 1);
});
test('all five appearance fixtures preserve draft, target, message identity, selection, and scroll', async t => {
  const history = Array.from({ length: 24 }, (_, i) => ready(i + 1, 'A long source title that stays readable on a small phone ' + i));
  const f = await setup(t, { hosted: true, viewport: { width: 360, height: 740 }, state: { messages: history } });
  await f.frame.locator('[data-ready-id="24"] button').click(); await f.frame.locator('#message').fill('Saved draft across skins');
  await f.frame.evaluate(() => { window.originalNode = document.querySelector('[data-message-id="1"]'); const s = document.getElementById('conversation'); s.scrollTop = 160; const n = document.getElementById('message'); n.focus(); n.setSelectionRange(2, 8); });
  await f.page.waitForTimeout(80);
  const top = await f.frame.locator('#conversation').evaluate(n => n.scrollTop);
  let revision = 0;
  for (const skin of ['nebula', 'grove', 'tide', 'ember', 'signal']) {
    // Protocol fixtures, not a claim to reproduce the live skin registry's exact colours.
    const theme = { version: 1, revision: ++revision, skin, colorScheme: 'dark', presentation: 'immersive', tokens: Object.fromEntries(['canvas', 'base', 'chrome', 'overlay', 'surface', 'surface-raised', 'text', 'text-secondary', 'text-muted', 'border', 'accent', 'accent-soft', 'on-accent', 'reader-surface'].map(k => [k, k.startsWith('text') ? '#f3efff' : k === 'accent' ? '#b99bff' : '#202030'])) };
    await f.page.evaluate(theme => document.querySelector('iframe').contentWindow.postMessage({ type: 'wizard:appearance', appearance: theme }, location.origin), theme);
    await f.frame.waitForFunction(skin => document.documentElement.dataset.skin === skin, skin);
    assert.equal(await f.frame.locator('#message').inputValue(), 'Saved draft across skins');
    assert.equal((await f.draft()).target.reply_to, 24);
    assert.equal(await f.frame.evaluate(() => window.originalNode === document.querySelector('[data-message-id="1"]')), true);
    assert.equal(await f.frame.locator('#conversation').evaluate(n => n.scrollTop), top);
    assert.equal(await f.frame.locator('#message').evaluate(n => n.selectionStart), 2);
    assert.equal(await f.frame.locator('.mgr-head').isVisible(), false);
    assert.equal(await f.frame.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (evidence) await f.page.screenshot({ path: path.join(evidence, 'mobile-' + skin + '.png') });
  }
  assert.equal(await f.page.evaluate(() => window.holds), 0, 'durably saved draft must not block updates');
  f.state.messages.push(ready(25, 'New result')); await f.poll();
  assert.equal(await f.frame.locator('#conversation').evaluate(n => n.scrollTop), top);
  assert.match(await f.frame.locator('#jump').textContent(), /\d+ new below/); // includes unread history already below the viewport
  assert.match(await f.frame.locator('#announcer').textContent(), /Ready: New result/);
  await f.frame.locator('#jump').click(); assert.equal(await f.frame.locator('#jump').isVisible(), false);
});
test('pagination drains beyond 1000 messages before validating restored reply target', async t => {
  const history = Array.from({ length: 1001 }, (_, i) => ready(i + 1));
  const f = await setup(t, { state: { messages: history }, init: () => localStorage.setItem('wizard-manager:conversation:v1', JSON.stringify({ rev: 1, text: 'Reply to oldest page edge', target: { reply_to: 1001, source_id: 'thread/1001', source_message: 'response-1001', title: 'Research notes' } })) });
  await f.frame.waitForFunction(() => document.querySelectorAll('#thread > li[data-message-id]').length === 1001);
  assert.equal(await f.frame.locator('#send').isEnabled(), true); assert.doesNotMatch(await f.frame.locator('#destination').textContent(), /Can’t reply/);
  assert.equal(await f.frame.locator('#announcer').textContent(), '', 'initial inventory must not replay announcements');
});
test('portrait load failure shows named monogram; missing source retains full text and disables reply', async t => {
  const f = await setup(t, { state: { messages: [ready(1, 'Unavailable source', { source_id: null, source_available: false, text: 'Full retained summary. '.repeat(40) })] }, init: () => { document.addEventListener('DOMContentLoaded', () => { for (const img of document.querySelectorAll('img')) img.dispatchEvent(new Event('error')); }); } });
  assert.match(await f.frame.locator('.mgr-card').textContent(), /This thread isn’t available anymore/);
  assert.equal(await f.frame.locator('.mgr-card button').isEnabled(), false);
  assert.equal(await f.frame.locator('.mgr-card a').count(), 0);
  assert.equal(await f.frame.locator('.mgr-summary').evaluate(n => getComputedStyle(n).webkitLineClamp), 'none');
  assert.ok(await f.frame.locator('span.mgr-face').count() > 0);
});

test('initial outage is truthful; reconnect removes notice without sending retained text', async t => {
  let unavailable = true;
  const f = await setup(t, { route: async (route, req, url) => {
    if (url.pathname === '/api/state' && unavailable) { await route.abort('failed'); return true; }
    return false;
  } });
  assert.match(await f.frame.locator('#notice').textContent(), /Can’t reach Manager right now/);
  await f.frame.locator('#message').fill('Not automatically sent');
  assert.equal(await f.frame.locator('#send').isEnabled(), false);
  unavailable = false; await f.frame.getByRole('button', { name: 'Try again', exact: true }).click();
  await f.frame.waitForFunction(() => document.getElementById('notice').hidden);
  assert.equal(await f.frame.locator('#send').isEnabled(), true);
  assert.equal(f.posts.length, 0);
  await f.context.setOffline(true);
  await f.frame.waitForFunction(() => document.getElementById('notice').textContent.includes('offline'));
  assert.match(await f.frame.locator('#notice').textContent(), /Your draft is saved on this device/);
  assert.equal(await f.frame.locator('#send').isEnabled(), false);
});

test('unknown pause outcome never claims off; check again reads actual state', async t => {
  const f = await setup(t); let unavailable = false;
  f.custom(async (route, req, url) => {
    if (url.pathname === '/api/settings') { unavailable = true; await route.abort('failed'); return true; }
    if (url.pathname === '/api/state' && unavailable) { await route.abort('failed'); return true; }
    return false;
  });
  await f.frame.locator('#message').fill('Kept'); await f.frame.locator('#options-open').click(); await f.frame.locator('#enabled').click();
  await f.frame.waitForFunction(() => document.getElementById('options-state').textContent.includes('Couldn’t confirm'));
  assert.equal(await f.frame.locator('#enabled').getAttribute('aria-checked'), 'true');
  assert.equal(await f.frame.locator('#send').isEnabled(), false);
  await f.frame.locator('#options-close').click(); unavailable = false;
  await f.frame.getByRole('button', { name: 'Check again', exact: true }).click();
  await f.frame.waitForFunction(() => document.getElementById('notice').hidden);
  assert.equal(await f.frame.locator('#send').isEnabled(), true);
  assert.equal(await f.frame.locator('#message').inputValue(), 'Kept');
});

test('modal contains focus, Escape restores trigger, large text and long tokens do not overflow', async t => {
  const f = await setup(t, { viewport: { width: 360, height: 740 }, state: { messages: [ready(1, 'Unbroken'.repeat(35))] } });
  await f.frame.locator('#options-open').click();
  for (let i = 0; i < 5; i++) {
    await f.page.keyboard.press('Tab');
    assert.equal(await f.frame.evaluate(() => document.getElementById('options').contains(document.activeElement) || document.activeElement === document.body), true);
  }
  if (evidence) await f.page.screenshot({ path: path.join(evidence, 'mobile-options.png') });
  await f.page.keyboard.press('Escape');
  assert.equal(await f.frame.locator('#options').evaluate(n => n.open), false);
  assert.equal(await f.frame.locator('#options-open').evaluate(n => n === document.activeElement), true);
  await f.frame.addStyleTag({ content: 'html { font-size:32px } .mgr-text,.mgr-card p,.mgr-card h2,.mgr-dest {font-size:30px}' });
  await f.frame.locator('#message').fill('Long draft\n'.repeat(12));
  assert.equal(await f.frame.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.equal(await f.frame.locator('#message').evaluate(n => n.scrollHeight > n.clientHeight), true);
  const button = await f.frame.locator('#send').boundingBox();
  assert.ok(button.width >= 44 && button.height >= 44 && button.y + button.height <= 740);
});

test('reading anchor and offset restore after reload without new-history announcements', async t => {
  const f = await setup(t, { state: { messages: Array.from({ length: 18 }, (_, i) => ready(i + 1)) } });
  await f.frame.locator('#conversation').evaluate(n => { n.scrollTop = 350; }); await f.page.waitForTimeout(100);
  const previous = await f.draft(); assert.equal(previous.scroll.pinned, false);
  await f.page.reload(); await f.frame.waitForFunction(() => document.querySelectorAll('#thread > li[data-message-id]').length === 18);
  await f.page.waitForTimeout(100);
  assert.ok(Math.abs(await f.frame.locator('#conversation').evaluate(n => n.scrollTop) - 350) <= 2);
  assert.equal(await f.frame.locator('#announcer').textContent(), '');
});

test('orb receiver seals reply target and leaves later draft intact', async t => {
  const f = await setup(t, { hosted: true, state: { messages: [ready(1, 'First'), ready(2, 'Second')] } });
  await f.frame.locator('[data-message-id="1"] button').click();
  const target = await f.page.evaluate(() => domain.conversation.snapshot());
  await f.frame.locator('[data-message-id="2"] button').click();
  await f.frame.locator('#message').fill('Later draft');
  const result = await f.page.evaluate(target => domain.conversation.receive({ request_id: 'qa-orb-original', text: 'Voice original', target }, () => {}), target);
  assert.equal(result.accepted, true);
  assert.equal(f.posts.at(-1).body.reply_to, 1);
  assert.equal(await f.frame.locator('#message').inputValue(), 'Later draft');
  assert.equal((await f.draft()).target.reply_to, 2);
  await f.page.evaluate(target => domain.conversation.receive({ request_id: 'qa-orb-original', text: 'Voice original', target }, () => {}), target);
  assert.equal(f.posts.filter(p => p.path === '/api/messages').length, 1);
});

test('hosted source links save Manager draft and request the exact native canonical ID', async t => {
  const f = await setup(t, { hosted: true, state: { messages: [ready(1)] } });
  await f.frame.locator('#message').fill('Keep this draft');
  await f.frame.locator('[data-message-id="1"] a').click();
  assert.equal(await f.page.evaluate(() => openedThread), 'thread/1');
  assert.equal((await f.draft()).text, 'Keep this draft');
  assert.match(f.page.url(), /\/host$/);
  assert.equal(await f.frame.locator('#message').inputValue(), 'Keep this draft');
});

test('read watermark advances only after visibility; away arrivals start a persistent catch-up boundary', async t => {
  const f = await setup(t, { hosted: true, state: { messages: [answer(1, 'one')] } });
  await f.frame.waitForFunction(() => JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).read.seen === 1);
  assert.equal((await f.draft()).read.divider, 1, 'reading does not move the active boundary');
  await f.page.evaluate(() => window.qaHidden = true); await f.page.waitForTimeout(350);
  assert.equal((await f.draft()).read.divider, null, 'completed boundary retires on leaving');
  f.state.messages.push(answer(2, 'two')); await f.poll(); await f.page.waitForTimeout(1000);
  assert.equal((await f.draft()).read.seen, 1, 'fetch while hidden cannot read the arrival');
  assert.equal((await f.draft()).read.divider, 2);
  await f.frame.goto(origin + '/index.html'); await f.page.evaluate(() => window.qaHidden = false); await f.frame.waitForFunction(() => document.querySelector('[data-message-id="2"]'));
  assert.equal((await f.draft()).read.divider, 2, 'reload retains first unread boundary');
  await f.frame.waitForFunction(() => JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).read.seen === 2);
  assert.equal((await f.draft()).read.divider, 2, 'new read receipt does not shift the divider');
  f.state.messages.push(answer(3, 'three')); await f.poll();
  assert.equal((await f.draft()).read.divider, 2, 'arrivals during catch-up retain the same line');
});

test('reading the latest message advances catch-up position; hidden arrivals stay unread across reload', async t => {
  const f = await setup(t, { hosted: true, state: { messages: Array.from({length:12}, (_,i) => ready(i+1)) } });
  await f.frame.locator('#conversation').evaluate(n => { n.scrollTop = n.scrollHeight; });
  await f.page.waitForTimeout(1100);
  assert.equal((await f.draft()).read.seen, 12, 'older gaps cannot strand the next-visit marker');
  assert.equal((await f.draft()).read.divider, 1, 'current-visit boundary stays stable');
  await f.page.evaluate(() => window.qaHidden = true); await f.page.waitForTimeout(300);
  f.state.messages.push(ready(13)); await f.poll(); await f.page.waitForTimeout(850);
  assert.equal((await f.draft()).read.seen, 12, 'hidden fetch never advances read position');
  assert.equal((await f.draft()).read.divider, 13, 'new visit boundary follows the last-read message');
  await f.frame.goto(origin + '/index.html'); await f.page.evaluate(() => window.qaHidden = false); await f.frame.waitForFunction(() => document.querySelector('[data-message-id="13"]'));
  assert.equal((await f.draft()).read.divider, 13);
  assert.equal((await f.draft()).read.seen, 12);
});

test('orb receiver rechecks pinned authorization after state read and before POST', async t => {
  const f = await setup(t, { hosted: true });
  const error = await f.page.evaluate(async () => {
    try { await domain.conversation.receive({request_id:'qa-orb-detached',text:'Keep me',target:{replyTo:null}}, () => { throw Error('frame detached'); }); }
    catch (e) { return e.message; }
  });
  assert.equal(error, 'frame detached');
  assert.equal(f.posts.length, 0);
});
