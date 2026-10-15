const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');const assert=require('node:assert/strict');
(async()=>{
const out=process.env.MANAGER_QA_OUT;fs.mkdirSync(out,{recursive:true});
const b=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
const results=[];
for(const mode of ['desktop','phone']){
 const c=await b.newContext({viewport:mode==='phone'?{width:412,height:915}:{width:1440,height:1000},isMobile:mode==='phone',hasTouch:mode==='phone'});
 const p=await c.newPage();let errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto(process.env.MANAGER_PUBLIC_ORIGIN+'/wizard-os-home/?shell='+mode+'&open=wizard-manager');
 await p.waitForTimeout(2500);const f=p.frames().find(x=>x.url().includes('/wizard-manager/'));assert(f,'launcher iframe');
 await f.locator('#message').fill('Unsent acceptance draft — keep this across skins.');
 await f.evaluate(()=>window.__qaNode=document.querySelector('#message'));
 const skins=await p.evaluate(()=>window.WosSkin ? WosSkin.list.map(s=>s.id) : ['nebula']);
 for(const skin of skins){
  await p.evaluate(s=>window.WosSkin?.set(s),skin);await p.waitForTimeout(150);
  const x=await f.evaluate(()=>({skin:document.documentElement.dataset.skin,transparent:getComputedStyle(document.body).backgroundColor==='rgba(0, 0, 0, 0)',draft:document.querySelector('#message').value,node:window.__qaNode===document.querySelector('#message'),overflow:document.documentElement.scrollWidth>innerWidth+1,accent:getComputedStyle(document.documentElement).getPropertyValue('--wz-accent')}));
  assert.equal(x.skin,skin);assert(x.transparent);assert(x.node);assert(!x.overflow);assert(x.draft.startsWith('Unsent acceptance'));
  results.push({mode,check:'live skin',...x});await p.screenshot({path:out+'/'+mode+'-'+skin+'.png'});
 }
 await p.evaluate(()=>window.WosSkin?.preview(0.5));await p.waitForTimeout(100);
 results.push({mode,check:'fluid midpoint',theme:await f.evaluate(()=>WizardApp.theme.get())});
 await f.locator('#options-open').click();assert(await f.locator('#options').evaluate(e=>e.open));
 await p.evaluate(()=>history.back());await p.waitForTimeout(350);
 const modalClosed=await f.locator('#options').evaluate(e=>!e.open);
 assert(modalClosed,'Back closes app overlay');assert(p.url().startsWith(process.env.MANAGER_PUBLIC_ORIGIN));
 results.push({mode,check:'real browser Back closes options',pass:true});
 await p.locator('button[aria-label="Full screen"]:visible').last().click();
 await p.waitForTimeout(250);
 const presentation=await f.evaluate(()=>document.documentElement.dataset.presentation);
 const box=await p.locator('iframe[src*="/wizard-manager/"]').boundingBox();
 assert(box && box.height>500,'fullscreen app remains visible and usable');
 if(mode==='desktop') assert(await p.evaluate(()=>document.body.classList.contains('desktop-fullscreen')),'desktop fullscreen entered');
 results.push({mode,check:'fullscreen',presentation,box});
 await p.screenshot({path:out+'/'+mode+'-fullscreen.png'});
 await p.evaluate(()=>history.back());await p.waitForTimeout(250);
 assert(p.url().startsWith(process.env.MANAGER_PUBLIC_ORIGIN),'Back remains inside Wizard');
 await f.locator('#message').fill('');
 const link=f.locator('a[href*="wizard_manager_2314d9faefd18768861435b9"]').first();
 if(await link.count()){
  await link.click();await p.waitForTimeout(7000);
  assert(p.url().startsWith(process.env.MANAGER_PUBLIC_ORIGIN));
  const all=await p.locator('body').innerText();
  fs.writeFileSync(out+'/'+mode+'-source-body.txt',all);
  await p.screenshot({path:out+'/'+mode+'-source.png'});
  assert(all.includes('Verified Python executable:'),'actual QA source response body opens');
  results.push({mode,check:'actual source thread link',pass:true,url:p.url()});
 }
 results.push({mode,check:'page errors',errors});assert.deepEqual(errors,[]);await c.close();
}
await b.close();fs.writeFileSync(out+'/acceptance.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
