// Real shell, isolated Manager records. Every write is intercepted.
const {chromium}=require(process.env.PW);const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const base=process.env.QA_ORIGIN,out=process.env.QA_OUT;fs.mkdirSync(out,{recursive:true});const results=[];
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});try{for(const mobile of [true,false]){
 const context=await browser.newContext({viewport:mobile?{width:412,height:915}:{width:1440,height:1000},isMobile:mobile,hasTouch:mobile,serviceWorkers:'block'});const p=await context.newPage(),mode=mobile?'phone':'desktop';
 const row=id=>({id,role:'assistant',kind:'chat',text:'Manager update '+id+'\n'+('A substantial update to read before moving on. '.repeat(12)),created:1792070000+id});let messages=Array.from({length:20},(_,i)=>row(i+1));
 await context.addInitScript(()=>{const k='wizard-manager:conversation:v1';if(!localStorage.getItem(k))localStorage.setItem(k,JSON.stringify({rev:0,text:'Retained draft',scroll:{pinned:true},read:{seen:0,viewed:[19,20],divider:1}}));});
 await context.route('**/*',async r=>{const u=new URL(r.request().url());if(process.env.QA_APP&&u.pathname==='/wizard-manager/app.js')return r.fulfill({contentType:'text/javascript',body:fs.readFileSync(process.env.QA_APP)});
 if(u.pathname==='/wizard-manager/api/state')return r.fulfill({json:{enabled:true,jobs:[],threads:[],messages:messages.filter(x=>x.id>Number(u.searchParams.get('after')||0))}});
 if(!['GET','HEAD','OPTIONS'].includes(r.request().method()))return r.fulfill({json:{}});return r.continue();});
 await p.goto(base+'/wizard-os-home/?open=wizard-manager&shell='+mode);await p.waitForFunction(m=>m?!!window.__wos:!!window.__wux,mobile);
 const getFrame=async()=>{await p.waitForFunction(()=>[...document.querySelectorAll('iframe')].some(f=>f.src.includes('/wizard-manager/')&&f.contentWindow?.WizardApp?.hosted));return p.frames().find(f=>f.url().includes('/wizard-manager/'));};
 let f=await getFrame();await f.waitForSelector('[data-message-id="20"]');await p.waitForTimeout(900);
 assert.equal(await f.evaluate(()=>JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).read.seen),20,'old persisted read receipts migrate');
 await f.locator('#conversation').evaluate(e=>e.scrollTop=e.scrollHeight);await p.waitForTimeout(350);
 await p.evaluate(m=>m?__wos.goDesk(0):__wux.goHome(),mobile);await p.waitForTimeout(500);assert.equal(await f.evaluate(()=>WizardApp.view.isVisible()),false);
 messages.push(row(21),row(22),row(23));
 await p.evaluate(async m=>{await WizCore.appsLoaded();(m?__wos:__wux).openApp(WizCore.apps(m?'mobile':'desktop').APP['wizard-manager']);},mobile);
 await f.waitForSelector('[data-message-id="23"]');
 const geometry=await f.evaluate(()=>{const s=document.querySelector('#conversation').getBoundingClientRect(),d=document.querySelector('.mgr-new-messages'),r=d?.getBoundingClientRect();return{id:d?.nextElementSibling?.dataset.messageId,offset:r?.top-s.top,bottom:r?.bottom-s.top,height:s.height};});
 assert.equal(geometry.id,'21');assert(geometry.offset>=0&&geometry.bottom<geometry.height,'new messages line visible where reading resumes');
 await p.screenshot({path:path.join(out,mode+'-return.png')});
 const before=await f.locator('#conversation').evaluate(e=>e.scrollTop);messages.push(row(24));await f.evaluate(()=>dispatchEvent(new Event('online')));await f.waitForSelector('[data-message-id="24"]');assert(Math.abs(await f.locator('#conversation').evaluate(e=>e.scrollTop)-before)<3,'new arrival preserves reading position');
 await f.locator('#conversation').evaluate(e=>e.scrollTop+=30);await p.waitForTimeout(300);const saved=await f.evaluate(()=>JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')).scroll);
 await p.reload();f=await getFrame();await f.waitForSelector('[data-message-id="24"]');await p.waitForTimeout(400);const restored=await f.evaluate(()=>JSON.parse(localStorage.getItem('wizard-manager:conversation:v1')));assert.equal(restored.scroll.anchorMessageId,saved.anchorMessageId);assert(Math.abs(restored.scroll.offset-saved.offset)<3);assert.equal(restored.text,'Retained draft');assert.equal(await f.locator('.mgr-new-messages').evaluate(e=>e.nextElementSibling.dataset.messageId),'21');
 results.push({mode,passed:true,geometry,saved,restored:restored.scroll,candidate:!!process.env.QA_APP});console.log(JSON.stringify(results.at(-1)));await context.close();
}}finally{fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(results,null,2));await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
