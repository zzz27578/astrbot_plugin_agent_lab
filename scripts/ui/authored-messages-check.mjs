import {chromium} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createFixture} from './fixture.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const output=path.join(root,'docs/screenshots/v0.3.4');fs.mkdirSync(output,{recursive:true});
const fixture=createFixture(),task=fixture.state.tasks[0];
const authored='老爸，这一段我已经把接口摸清啦。接下来只清理两个临时文件，备份还留着；你回复批准或拒绝，我再继续。';
task.approvals=[{approval_id:'approval_authored',status:'pending',operation:'清理指定临时文件',message:authored,reason:'替换旧缓存',impact:'只涉及a.tmp和b.tmp，保留其他文件。',rollback:'保留原副本。'}];
fixture.taskMessages.set(task.task_id,[{kind:'stage',status:'sent',text:'第一段交给你：接口和位置都确认了，下一段补测试。'},
 {kind:'warning',status:'recorded',text:'{"reason":"liveness_warning","counters":{"no_progress_ticks":2}}'},
 {kind:'approval',status:'sent',text:authored}]);
await new Promise(resolve=>fixture.server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'msedge',headless:true});const checks=[],errors=[];
function check(name,value){assert.ok(value,name);checks.push(name);}
try{
 for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:1000}});page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${fixture.server.address().port}/host`);const frame=page.frameLocator('iframe');
  await frame.locator('.project-folder-open[data-project-id="project_a1"]').click();
  await frame.locator('.project-task-row[data-task-id="task_a1"]').click();
  const approval=frame.locator('.project-approval');await approval.waitFor();
  check(`${width}: authored approval body preserved`,(await approval.innerText()).includes(authored));
  check(`${width}: exact parameters are in separate detail`,await approval.getByText('核对完整范围与影响',{exact:true}).count()===1);
  check(`${width}: approval controls retained`,await approval.locator('[data-project-action="approval"]').count()===2);
  const line=frame.locator('.task-message-timeline');
  check(`${width}: stage delivery has its own label`,(await line.innerText()).includes('阶段交付'));
  check(`${width}: diagnostic is not impersonated as progress`,(await line.innerText()).includes('系统诊断 · 已记录'));
  check(`${width}: no horizontal overflow`,await frame.locator('body').evaluate(body=>body.scrollWidth<=innerWidth+2));
  await approval.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,`authored-${width}.png`)});await page.close();
 }
 check('no browser exceptions',errors.length===0);
 fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({passed:checks.length,errors}));
}finally{await browser.close();fixture.server.close();}
