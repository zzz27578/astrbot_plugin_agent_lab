import {chromium} from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createFixture} from './fixture.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=path.join(root,'_preview/task-layout-029');
fs.mkdirSync(out,{recursive:true});
const fixture=createFixture(),checks=[],errors=[];
const task=fixture.state.tasks.find(t=>t.task_id==='task_a1');
task.root_goal='排查插件执行上下文并完善任务页面：保留原有接口、配置格式、检查点和权限边界，验证长标题、多条消息与窄窗口下的操作体验。';
task.workflow_data.task_control.steps.push(
 {id:'step_3',title:'验证任务与界面行为',instruction:'检查任务切换、清单、折叠和滚轮操作。',status:'pending'},
 {id:'step_4',title:'保存结果并交接',instruction:'记录实际检查结果和未验证事项。',status:'pending'});
fixture.taskMessages.set(task.task_id,Array.from({length:24},(_,i)=>({kind:i%5===0?'approval':'progress',status:'sent',
 text:`第 ${i+1} 条记录：已检查接口与任务进度。\n${'保留原始工具结果，继续核对验证依据。\n'.repeat(3)}${i===23?'长参数：'+('long_path_component_'.repeat(30)):''}`})));
await new Promise(resolve=>fixture.server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'msedge',headless:true});
const check=(name,condition)=>{assert.ok(condition,name);checks.push(name);};
try {
 for(const width of [1440,1100,820,390]) {
  const page=await browser.newPage({viewport:{width,height:900}}),frame=page.frameLocator('iframe');
  page.on('pageerror',error=>errors.push({width,error:error.message}));
  await page.goto(`http://127.0.0.1:${fixture.server.address().port}/host`);
  await frame.locator('.project-folder-open[data-project-id="project_a1"]').click();
  await frame.locator('.project-task-row[data-task-id="task_a1"]').click();
  await frame.locator('.project-task-detail h2').waitFor();
  const prefix=`${width}px: `;
  check(prefix+'selected task has no repeated task selector',await frame.locator('.project-task-list').count()===0);
  check(prefix+'task detail fills the project pane',await frame.locator('.project-task-layout').evaluate(el=>Math.abs(el.clientWidth-el.querySelector('.project-task-detail').getBoundingClientRect().width)<2));
  check(prefix+'plan comes first and mid-task settings follow the timeline',await frame.locator('.project-task-detail').evaluate(el=>el.querySelector('section')?.matches('.project-task-plan')&&el.lastElementChild.matches('.project-task-controls')&&el.lastElementChild.previousElementSibling.matches('.task-message-timeline')));
  check(prefix+'guidance and budget actions are grouped below messages',await frame.getByRole('region',{name:'途中设置'}).locator('#project-guidance,[data-project-action="steer"],[data-project-action="task-budget"]').count()===3);
  check(prefix+'all supplied messages remain available',await frame.locator('.task-message-timeline article').count()===24);
  await frame.locator('.main').evaluate(el=>el.scrollTop=0);
  await page.screenshot({path:path.join(out,`task-${width}.png`)});

  const timeline=frame.locator('.task-message-timeline'),scroll=frame.getByRole('region',{name:'任务消息内容'});
  await scroll.scrollIntoViewIfNeeded();
  check(prefix+'timeline has a bounded scroll region',await scroll.evaluate(el=>el.clientHeight<=420&&el.scrollHeight>el.clientHeight+500&&getComputedStyle(el).overflowY==='auto'));
  await scroll.evaluate(el=>el.scrollTop=0);
  await scroll.hover();
  const outerScroll=await frame.locator('.main').evaluate(el=>el.scrollTop);
  await page.mouse.wheel(0,260);
  await page.waitForTimeout(180);
  check(prefix+'wheel scrolls messages without scrolling the page',await scroll.evaluate(el=>el.scrollTop)>0&&Math.abs(await frame.locator('.main').evaluate(el=>el.scrollTop)-outerScroll)<2);
  const savedScroll=await scroll.evaluate(el=>el.scrollTop);
  await timeline.locator('summary').click();
  check(prefix+'timeline collapses to its header',!(await timeline.getAttribute('open'))&&await timeline.evaluate(el=>el.getBoundingClientRect().height)<62);
  await frame.getByRole('button',{name:'刷新',exact:true}).click();
  check(prefix+'collapsed state survives task refresh',await timeline.getAttribute('open')===null);
  await timeline.locator('summary').focus();
  await page.keyboard.press('Enter');
  check(prefix+'keyboard expands messages and restores reading position',await timeline.getAttribute('open')!==null&&Math.abs(await scroll.evaluate(el=>el.scrollTop)-savedScroll)<2);
  await scroll.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,`messages-${width}.png`)});
  check(prefix+'long messages do not overflow horizontally',await scroll.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await frame.locator('.project-task-controls').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,`controls-${width}.png`)});

  await frame.getByRole('button',{name:'返回任务列表'}).click();
  check(prefix+'full task list remains reachable',await frame.locator('.project-task-row').count()===2&&await frame.locator('.project-task-detail').count()===0);
  await frame.locator('.project-task-row[data-task-id="task_a2"]').click();
  check(prefix+'archived task also opens directly',await frame.locator('.project-detail-top code').innerText()==='task_a2'&&await frame.locator('.project-task-list').count()===0);
  await frame.getByRole('button',{name:'开发保护',exact:true}).click();
  const settings=frame.getByRole('region',{name:'运行设置'});
  await settings.locator('#execution-mode').waitFor();
  const fields=await settings.locator('.project-settings-grid label').evaluateAll(labels=>labels.map(label=>{
   const field=label.querySelector('input,select,textarea'),r=label.getBoundingClientRect(),f=field.getBoundingClientRect();
   return {row:r.top,controlTop:f.top,height:f.height,kind:field.tagName};
  }));
  check(prefix+'fields on each row have aligned control tops',fields.every(a=>fields.filter(b=>Math.abs(a.row-b.row)<2).every(b=>Math.abs(a.controlTop-b.controlTop)<2)));
  check(prefix+'numeric inputs have a consistent height',fields.filter(f=>f.kind==='INPUT').every(f=>Math.abs(f.height-44)<1));
  check(prefix+'permission selector matches the adjacent textareas',await settings.locator('.project-permission-grid').evaluate(el=>{
   const controls=[...el.querySelectorAll('select,textarea')].slice(0,3).map(n=>n.getBoundingClientRect());
   return controls.every(r=>Math.abs(r.height-80)<1&&Math.abs(r.width-controls[0].width)<1);
  }));
  if(width>1050)check(prefix+'permission fields fill the row without an empty column',await settings.locator('.project-permission-grid').evaluate(el=>Math.abs(el.children[2].getBoundingClientRect().right-el.getBoundingClientRect().right)<2));
  check(prefix+'task guidance spans the settings grid',await settings.locator('.project-field-wide').evaluate(el=>Math.abs(el.getBoundingClientRect().width-el.parentElement.clientWidth)<2));
  check(prefix+'save action has a consistent icon and button size',await settings.locator('[data-project-action="save-execution"]').evaluate(el=>el.querySelector('svg')&&el.getBoundingClientRect().height>=40));
  check(prefix+'settings fit the available width',await settings.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await frame.locator('.main').evaluate(el=>el.scrollTop=0);
  await page.screenshot({path:path.join(out,`settings-${width}.png`)});
  await page.close();
 }
 check('no browser exceptions',errors.length===0);
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));
 console.log(JSON.stringify({passed:checks.length,errors,out},null,2));
} finally {
 await browser.close();
 fixture.server.close();
}
