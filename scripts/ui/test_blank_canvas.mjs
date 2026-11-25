// Actual app module in the existing local browser fixture; no production calls.
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {createFixture} from './fixture.mjs';

const fixture=createFixture();
const blank={...structuredClone(fixture.state.agents[0]),agent_id:'blank',name:'Blank fixture',
  workflow_nodes:[],workflow_edges:[],default_task_budget:{}};
fixture.state.agents.push(blank);
await new Promise(resolve=>fixture.server.listen(0,'127.0.0.1',resolve));
let browser;
try {
  browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route(/raw\.githubusercontent\.com|fonts\.googleapis|githubusercontent/,route=>route.abort());
  await page.route(/\/app\.js(?:\?|$)/,async route=>{
    const response=await route.fetch();
    const source=await response.text();
    await route.fulfill({response,body:source+`
      window.__blankTest={canvasKind,ensureAgent,defaultAgentDraft,applyBlueprintToDraft,
        openPreset,openPresetRules,savePresetSettings,getAgent:()=>currentAgent,
        setDraft:()=>{currentAgent.workflow_nodes=[{id:'UNSAVED_DRAFT',title:'Unsubmitted',x:991,y:992}];}};
    `});
  });
  let submitted;
  await page.route('**/api/agents',async route=>{
    submitted=route.request().postDataJSON();
    const agent={...structuredClone(blank),...submitted};
    await route.fulfill({json:{ok:true,agent}});
  });
  await page.goto(`http://127.0.0.1:${fixture.server.address().port}/host`);
  const ui=page.frameLocator('iframe');
  await ui.locator('.project-workspace').waitFor();
  const frame=page.frames().find(frame=>frame.url().includes('/index.html'));
  const result=await frame.evaluate(()=>{
    const t=window.__blankTest;
    const draft=t.applyBlueprintToDraft(t.defaultAgentDraft(),'blank');
    const old=t.ensureAgent({default_task_budget:{max_total_tool_calls:240,max_total_seconds:3600}});
    const fresh=t.ensureAgent({});
    return {nodes:draft.workflow_nodes,edges:draft.workflow_edges,budget:draft.default_task_budget,
      fresh:fresh.default_task_budget,old:old.default_task_budget,
      kinds:[t.canvasKind({workflow_nodes:[]}),t.canvasKind({workflow_nodes:[null,{},'junk',{x:1}]}),
        t.canvasKind({workflow_nodes:[{title:'x',action:'run_tools'}]})]};
  });
  assert.deepEqual(result.nodes,[]);assert.deepEqual(result.edges,[]);
  assert.deepEqual(result.kinds,['blank','blank','workflow']);
  for(const budget of [result.budget,result.fresh]){
    assert.equal(budget.max_total_tool_calls,0);assert.equal(budget.max_total_seconds,0);
  }
  assert.equal(result.old.max_total_tool_calls,240);assert.equal(result.old.max_total_seconds,3600);
  await ui.locator('[data-route="presets"]').first().click();
  assert.match(await ui.locator('.preset-row').filter({hasText:'Blank fixture'}).innerText(),/空白画布.*无画布运行/s);
  await frame.evaluate(()=>window.__blankTest.openPreset('blank'));
  assert.match(await ui.locator('.workflow-page-status').innerText(),/空白画布.*无画布运行/s);
  assert.equal(await ui.locator('.flow-node').count(),0);
  await frame.evaluate(()=>window.__blankTest.openPresetRules('blank'));
  assert.match(await ui.locator('.preset-rules-page').innerText(),/空白画布.*无画布运行/s);
  await frame.evaluate(()=>window.__blankTest.setDraft());
  await ui.locator('.scheme-guidance summary').click();
  await ui.locator('#global-system-prompt').fill('Custom blank behavior');
  await ui.locator('#global-task-prompt').fill('Custom blank guidance');
  await frame.evaluate(()=>window.__blankTest.savePresetSettings());
  assert.equal(submitted.action,'save_settings');
  assert.equal(submitted.system_prompt,'Custom blank behavior');
  assert.equal(submitted.task_prompt,'Custom blank guidance');
  for(const key of ['workflow_nodes','workflow_edges','workflow_trigger','default_task_budget','_make_default'])
    assert.equal(Object.hasOwn(submitted,key),false,key);
  assert.equal(await frame.evaluate(()=>window.__blankTest.getAgent().workflow_nodes[0].id),'UNSAVED_DRAFT');
  assert.deepEqual(errors,[]);
  console.log('Blank UI: schema, labels, budgets and isolated settings payload passed.');
} finally {
  if(browser)await browser.close();
  await new Promise(resolve=>fixture.server.close(resolve));
}
