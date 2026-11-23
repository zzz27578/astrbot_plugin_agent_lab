// Focused state round-trip, without a browser or production API.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('../../pages/agent-lab/app.js',import.meta.url),'utf8');
const start=source.indexOf('function workflowGlobalEditor()');
const end=source.indexOf('function renderMemoryPage()',start);
const boxes=[{dataset:{globalPluginBlacklist:'example'},checked:true},{dataset:{globalPluginBlacklist:'host-off'},checked:true,disabled:true}];
const context={currentAgent:{plugin_overrides:{},enabled_skills:[]},state:{skills:[],plugins:[{name:'example',activated:true},{name:'host-off',activated:false}]},
  ensureAgent:a=>a,esc:s=>String(s||''),document:{getElementById:()=>null,querySelectorAll:selector=>selector.includes('blacklist')?boxes:[]}};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
let html=vm.runInContext('workflowGlobalEditor()',context);
assert.ok(html.includes('保存方案设置'));
assert.match(html,/data-global-plugin-blacklist="host-off" checked disabled/);
vm.runInContext('applyWorkflowGlobalRules()',context);
assert.equal(context.currentAgent.plugin_overrides.example,false);
context.currentAgent=JSON.parse(JSON.stringify(context.currentAgent));
html=vm.runInContext('workflowGlobalEditor()',context);
assert.match(html,/data-global-plugin-blacklist="example" checked/);
boxes[0].checked=false;
vm.runInContext('applyWorkflowGlobalRules()',context);
assert.equal(context.currentAgent.plugin_overrides.example,undefined);
assert.equal(context.currentAgent.plugin_blacklist,undefined);
assert.equal(context.currentAgent.plugin_overrides['host-off'],undefined);
assert.ok(!source.includes('workflowGlobalOpen'));
assert.ok(source.includes('if (route === "preset-settings") renderPresetRulesPage();'));
const navigation=fs.readFileSync(new URL('../../pages/agent-lab/navigation.js',import.meta.url),'utf8');
assert.ok(navigation.includes('data-nav-action="preset-rules"'));
const {Navigation}=await import('data:text/javascript;base64,'+Buffer.from(navigation).toString('base64'));
const nav=Object.create(Navigation.prototype);nav.esc=s=>String(s||'');nav.presetQuery='';
const container={};nav.renderPresets(container,[{agent_id:'a',name:'A',description:'Test'}]);
assert.ok(container.innerHTML.includes('data-nav-action="preset-rules"'));
console.log('Full-access UI smoke passed: independent scheme page, plugin disable/save/uncheck round-trip and host-off boundary.');
