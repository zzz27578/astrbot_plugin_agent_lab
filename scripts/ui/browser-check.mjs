import {chromium} from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createFixture} from './fixture.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const before=process.argv.includes('--before');
const out=path.join(root,'_preview',before?'before-025':'after-025');fs.mkdirSync(out,{recursive:true});
const fixture=createFixture();await new Promise(r=>fixture.server.listen(0,'127.0.0.1',r));
const url=`http://127.0.0.1:${fixture.server.address().port}/host`;
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[];const metrics=[];
try {
 for(const width of [1440,1100,820]){
  const page=await browser.newPage({viewport:{width,height:900},deviceScaleFactor:1});
  page.on('pageerror',e=>errors.push({width,error:e.message}));
  await page.route(/raw\.githubusercontent\.com|fonts\.googleapis|githubusercontent/,r=>r.abort());
  await page.goto(url);const frame=page.frameLocator('iframe');
  await frame.locator('.project-workspace').waitFor({timeout:15000});
  await frame.locator('.project-folder-card').first().waitFor({timeout:15000});
  await page.waitForTimeout(300);
  await page.screenshot({path:path.join(out,`home-${width}.png`)});
  for(const route of before?['workflow','canvas','integrations']:['presets','settings','workflow']){
   if(await frame.locator('body.workflow-nav-collapsed').count())await frame.locator('[data-action="toggle-workflow-nav"]').click();
   if(route==='settings')await frame.locator('#settings-btn').click();
   else if(route==='workflow'&&!before){await frame.locator('[data-route="presets"]').first().click();await frame.locator('[data-nav-action="open-preset"]').first().click();}
   else await frame.locator(`[data-route="${route}"]`).first().click();
   await page.waitForTimeout(280);
   await page.screenshot({path:path.join(out,`${route}-${width}.png`)});
   const data=await frame.locator('body').evaluate(body=>({overflow:body.scrollWidth>innerWidth+2,width:innerWidth,view:document.querySelector('#view').getBoundingClientRect().toJSON(),nodes:document.querySelectorAll('.flow-node').length}));
   if(route==='workflow'&&!before){
     data.materialSearchUncovered=await frame.locator('.workflow-material-filter').evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el;});
     if(!data.materialSearchUncovered)errors.push({width,error:'Material search is covered by another overlay'});
   }
   metrics.push({width,route,...data});
  }
  await page.close();
 }
 fs.writeFileSync(path.join(out,'metrics.json'),JSON.stringify({errors,metrics,requests:fixture.requests.length},null,2));
 console.log(JSON.stringify({out,errors,metrics},null,2));
 if(errors.length)process.exitCode=1;
}finally{await browser.close();fixture.server.close();}
