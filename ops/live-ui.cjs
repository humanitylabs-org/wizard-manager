const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
(async()=>{
 const out=process.env.MANAGER_QA_OUT || './qa-evidence';fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const results=[];
 for(const [mode,w,h] of [['desktop',1440,1000],['phone',412,915]]){
  const context=await browser.newContext({viewport:{width:w,height:h},isMobile:mode==='phone',hasTouch:mode==='phone'});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`${process.env.MANAGER_PUBLIC_ORIGIN}/wizard-os-home/?shell=${mode}&open=wizard-manager`,{waitUntil:'domcontentloaded'});
  await page.waitForTimeout(2000);
  const frame=page.frames().find(f=>f.url().includes('/wizard-manager/'));
  if(!frame) throw new Error('Manager did not open from exact launcher deep link: '+mode);
  await frame.locator('#message').waitFor({state:'visible'});
  await page.screenshot({path:out+'/'+mode+'.png'});
  results.push({mode,url:page.url(),frames:page.frames().map(f=>f.url()),errors,app:await frame.locator('body').innerText(),skin:await frame.evaluate(()=>({skin:document.documentElement.dataset.skin,presentation:document.documentElement.dataset.presentation,background:getComputedStyle(document.body).backgroundColor})),buttons:await page.locator('button').evaluateAll(es=>es.map(e=>({text:e.textContent,aria:e.getAttribute('aria-label')})).filter(x=>x.aria||x.text).slice(0,100))});
  await context.close();
 }
 await browser.close(); fs.writeFileSync(out+'/initial.json',JSON.stringify(results,null,2)); console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
