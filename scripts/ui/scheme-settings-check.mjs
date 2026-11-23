import {chromium} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createFixture} from './fixture.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=path.join(root,'docs/screenshots/v0.3.1');fs.mkdirSync(out,{recursive:true});
const fixture=createFixture();
fixture.state.plugins.push({name:'workspace',display_name:'项目工作区',description:'组织项目文件、模块与素材。',activated:true},
 {name:'browser',display_name:'浏览器',description:'检索网页并核对资料。',activated:true},
 {name:'paused',display_name:'图片生成',activated:false});
fixture.state.tools.push(...['read_file','write_file','search_files','list_directory'].map(name=>({name:'workspace_'+name,plugin_name:'workspace',description:'在授权范围内操作项目文件，保存可回查的结果。',active:true})),
 ...['open','search','capture'].map(name=>({name:'browser_'+name,plugin_name:'browser',description:'浏览、搜索并保存网页资料。',active:true})),
 {name:'astrbot_execute_shell',description:'执行终端命令与测试。',active:true},
 {name:'image_generate',plugin_name:'paused',description:'生成图片。',active:true});
const a=fixture.state.agents[0];a.plugin_overrides={gitlink:true,workspace:true,browser:true};a.isolation_policy={mode:'strict',tool_mode:'full'};a.enabled_tools=[];
await new Promise(resolve=>fixture.server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[],results=[];
try{
 for(const width of [1440,1100,390]){
  const page=await browser.newPage({viewport:{width,height:1000}});
  page.on('pageerror',error=>errors.push(error.message));
  await page.route(/raw\.githubusercontent\.com|fonts\.googleapis|githubusercontent/,route=>route.abort());
  await page.goto(`http://127.0.0.1:${fixture.server.address().port}/host`);
  const frame=page.frameLocator('iframe');
  await frame.locator('.project-workspace').waitFor();
  await frame.locator('[data-route="presets"]').first().click();
  await frame.locator('[data-nav-action="preset-rules"]').first().click();
  await frame.locator('.scheme-root-node').waitFor();
  assert.equal(await frame.locator('[data-global-skill]').count(),0);
  const graph=await frame.locator('.scheme-graph-surface').boundingBox();
  const view=await frame.locator('#view').boundingBox();
  assert.ok(graph.width>view.width*.94,'graph uses full content width');
  await frame.locator('body').evaluate(()=>{window.scrollTo(0,0);document.querySelector('.main').scrollTop=0;document.querySelector('.shell').scrollTop=0;});
  await page.screenshot({path:path.join(out,`scheme-${width}.png`)});
  const group=frame.locator('[data-capability-group="workspace"]');
  await group.locator('summary').click();
  await group.locator('[data-capability-id="workspace_read_file"]').waitFor({state:'visible'});
  if(width===1440)await page.screenshot({path:path.join(out,'scheme-tools-1440.png')});
  const tool=group.locator('[data-capability-id="workspace_read_file"]');
  await tool.click();assert.equal(await tool.getAttribute('aria-checked'),'false');
  await frame.locator('.scheme-savebar [data-action="save-preset-rules"]').click();
  await page.waitForTimeout(200);
  assert.ok(fixture.state.agents[0].disabled_tools.includes('workspace_read_file'));
  await frame.locator('[data-action="back-to-presets"]').first().click();
  await frame.locator('[data-nav-action="preset-rules"]').first().click();
  assert.equal(await frame.locator('[data-capability-id="workspace_read_file"]').getAttribute('aria-checked'),'false');
  const host=frame.locator('[data-capability-action="group"][data-capability-id="paused"]');
  assert.equal(await host.isDisabled(),true);
  await frame.locator('[data-capability-action="disable-all"]').click();
  assert.equal(await frame.locator('[data-capability-id="astrbot_execute_shell"]').getAttribute('aria-checked'),'false');
  await frame.locator('[data-capability-action="enable-all"]').click();
  assert.equal(await frame.locator('[data-capability-id="astrbot_execute_shell"]').getAttribute('aria-checked'),'true');
  await frame.locator('.scheme-savebar [data-action="save-preset-rules"]').click();
  await page.waitForTimeout(200);
  const overflow=await frame.locator('body').evaluate(body=>body.scrollWidth>innerWidth+2);
  assert.equal(overflow,false,'no horizontal overflow');
  results.push({width,graphWidth:Math.round(graph.width),contentWidth:Math.round(view.width),checks:10});
  await page.close();
 }
 assert.equal(errors.length,0,errors.join('\n'));
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({results,errors},null,2));
 console.log(JSON.stringify({results,errors}));
}finally{await browser.close();fixture.server.close();}
