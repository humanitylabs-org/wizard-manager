// Read-only installed-shell acceptance: no asset/API substitutes and no sends.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const base=process.env.QA_ORIGIN,out=process.env.QA_OUT;
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
 const receipts=[];
 try {
  for(const mobile of [true,false]) {
   const context=await browser.newContext({viewport:mobile?{width:412,height:915}:{width:1440,height:1000},isMobile:mobile,hasTouch:mobile,serviceWorkers:'block'});
   const writes=[],errors=[];
   await context.route('**/*',async r=>{
    if(!['GET','HEAD','OPTIONS'].includes(r.request().method())){writes.push(new URL(r.request().url()).pathname);return r.fulfill({json:{}});}
    return r.continue();
   });
   const p=await context.newPage();p.on('pageerror',e=>errors.push(e.message));
   await p.goto(base+'/wizard-os-home/?open=wizard-manager&shell='+(mobile?'phone':'desktop'));
   await p.waitForFunction(()=>[...document.querySelectorAll('iframe')].some(f=>f.src.includes('/wizard-manager/')&&f.contentWindow?.WizardApp?.hosted));
   const f=p.frames().find(f=>f.url().includes('/wizard-manager/'));
   await f.waitForSelector('[data-message-id]');
   const state=await f.evaluate(async()=>await (await fetch('api/state',{cache:'no-store'})).json());
   const hidden=state.suppressed_sources;
   assert(Array.isArray(hidden)&&hidden.length>0,'live canonical suppression exists');
   assert.equal(state.messages.filter(m=>m.role!=='user'&&hidden.includes(m.source_id)).length,0);
   assert.equal(state.messages.filter(m=>(m.source_id||'').startsWith('wizard_resource_canary_')||(m.source_id||'').startsWith('wizard_resource_question_')).length,0);
   const ids=await f.locator('[data-message-id]').evaluateAll(ns=>ns.map(n=>Number(n.dataset.messageId)));
   assert.deepEqual(ids,state.messages.map(m=>m.id));
   assert.equal((await f.locator('body').innerText()).includes('wizard_resource_canary_'),false);
   await f.locator('#message').fill('Local-only retained draft — never send.');
   await f.evaluate(()=>dispatchEvent(new Event('online')));
   await p.waitForTimeout(400);
   assert.equal(await f.locator('#message').inputValue(),'Local-only retained draft — never send.');
   const asset=await f.evaluate(async()=>await(await fetch('app.js',{cache:'no-store'})).text());
   await p.screenshot({path:path.join(out,(mobile?'phone':'desktop')+'.png')});
   assert.equal(errors.length,0);
   receipts.push({mode:mobile?'phone':'desktop',messageCount:ids.length,hiddenSourceCount:hidden.length,jobs:state.jobs.length,visibleIds:ids,appJsSha256:crypto.createHash('sha256').update(asset).digest('hex'),assetOverrides:0,blockedMutations:writes,errors});
   await context.close();
  }
 } finally {fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(receipts,null,2));await browser.close();}
 console.log(JSON.stringify(receipts));
})().catch(e=>{console.error(e);process.exitCode=1;});
