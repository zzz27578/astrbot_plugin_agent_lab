import {chromium} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createFixture} from './fixture.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=path.join(root,'docs/screenshots/v0.3.3');fs.mkdirSync(out,{recursive:true});
const fixture=createFixture();
const task=fixture.state.tasks[0];
task.workflow_data.usage_metrics={model_calls:12,reported_calls:11,unreported_calls:1,tokens:{total:23100},
 context:{raw_chars:232807,sent_chars:11950,estimated_tokens:4300,capacity_tokens:1000000,trigger_tokens:700000,raw_role_chars:{assistant:82000,tool:150000}},
 handoff:{raw_chars:232807,source_chars:11677,summary_chars:697,summary_limit:1000,reported_tokens:7400,unreported_calls:1,quality:'normal',repairs:1}};
task.budget={tokens_used:23800,max_total_tokens:240000,max_tools_per_tick:24};
fixture.taskMessages.set(task.task_id,[{kind:'progress',text:'先把未完成的事件接线接好，再跑语法和挂载测试。',status:'sent',chars:25},
 {kind:'metrics',status:'recorded',chars:120,text:'上下文记录：原始 232,807 字符 → 工作视图 11,950 字符；约 4,300 Token（估算）。\n最近交接：697/1,000 字符摘要；1次修正。\n已报告 Token 23,100；1次请求未报告。'}]);
await new Promise(resolve=>fixture.server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[],checks=[];
function check(label,condition){assert.ok(condition,label);checks.push(label);}
try{
 for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:1000}}),frame=page.frameLocator('iframe');
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${fixture.server.address().port}/host`);
  await frame.locator('[data-project-action="open-project"]').first().count().then(async count=>{
   if(count)await frame.locator('[data-project-action="open-project"]').first().click();
   else await frame.locator('.project-folder-open[data-project-id="project_a1"]').click();
  });
  await frame.locator('.project-task-row[data-task-id="task_a1"]').click();
  const metrics=frame.locator('.task-usage-metrics');await metrics.waitFor();await metrics.locator('summary').click();
  check(`${width}: shows raw context characters`,(await metrics.innerText()).includes('232,807'));
  check(`${width}: shows model work view characters`,(await metrics.innerText()).includes('11,950'));
  check(`${width}: labels estimate separately`,(await metrics.innerText()).includes('估算'));
  check(`${width}: summary character cap visible`,(await metrics.innerText()).includes('697 / 1,000'));
  check(`${width}: missing usage explicit`,(await metrics.innerText()).includes('请求没有报告Token'));
  check(`${width}: timeline contains local-only metrics`,(await frame.locator('.task-message-timeline').innerText()).includes('上下文与用量 · 已记录'));
  const storage=frame.locator('.project-storage-details').filter({hasText:'记录与存储'});await storage.locator('summary').first().click();
  check(`${width}: storage text characters visible`,(await storage.innerText()).includes('48,000 字符'));
  check(`${width}: native history characters visible`,(await storage.innerText()).includes('7,000 字符'));
  check(`${width}: file list includes character count`,(await storage.locator('.project-file-list').innerText()).includes('48,000 字符'));
  check(`${width}: no horizontal overflow`,await frame.locator('body').evaluate(body=>body.scrollWidth<=innerWidth+2));
  await metrics.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`usage-${width}.png`)});
  await page.close();
 }
 check('no browser exceptions',errors.length===0);
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));
 console.log(JSON.stringify({passed:checks.length,errors}));
}finally{await browser.close();fixture.server.close();}
