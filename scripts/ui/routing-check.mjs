import {build} from 'esbuild';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const bundled=await build({entryPoints:[path.join(root,'pages/agent-lab/connections.js')],bundle:true,format:'esm',write:false});
const {routeEdge,pathHits}=await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const box=(x,y,w=220,h=160)=>({x,y,w,h});
const cases=[
 {name:'straight forward',source:{x:220,y:80},target:{x:660,y:80}},
 {name:'forward Z',source:{x:220,y:80},target:{x:660,y:320}},
 {name:'middle obstacle',source:{x:220,y:80},target:{x:880,y:80},boxes:[box(380,0)]},
 {name:'reverse same row',source:{x:880,y:80},target:{x:220,y:80},boxes:[box(660,0),box(220,0)]},
 {name:'retry left to right entry',source:{x:660,y:80,leftExit:true},target:{x:440,y:320,rightEntry:true},boxes:[box(660,0),box(220,240)]},
 {name:'dense staggered obstacles',source:{x:220,y:80},target:{x:1100,y:400},boxes:[box(350,0),box(600,180),box(850,350)]},
];
const checks=[];
for(const entry of cases){
 const result=routeEdge(entry),p=result.points;
 assert(p.length>=2&&p.flat().every(Number.isFinite)&&!result.d.includes('NaN'),entry.name+': finite geometry');
 assert(p.slice(1).every((v,i)=>v[0]===p[i][0]||v[1]===p[i][1]),entry.name+': orthogonal segments');
 assert(p[1][1]===entry.source.y&&Math.sign(p[1][0]-entry.source.x)===(entry.source.leftExit?-1:1),entry.name+': leaves actual source side');
 assert(p.at(-2)[1]===entry.target.y&&Math.sign(p.at(-2)[0]-entry.target.x)===(entry.target.rightEntry?1:-1),entry.name+': enters actual target side');
 assert(!pathHits(p.slice(1,-1),entry.boxes||[]),entry.name+': inner route clears obstacles');
 checks.push({name:entry.name,points:p});
}
const out=path.join(root,'_preview/after-026');fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(out,'routing.json'),JSON.stringify({passed:checks.length,assertions:checks.length*5,checks},null,2));
console.log(`Routing passed: ${checks.length} scenarios, ${checks.length*5} assertions.`);
