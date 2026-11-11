import {getSmoothStepPath,Position} from './vendor/connectors.js?v=026';

const simplify=points=>points.filter((p,i)=>!i||p[0]!==points[i-1][0]||p[1]!==points[i-1][1]).filter((p,i,a)=>!i||i===a.length-1||!((a[i-1][0]===p[0]&&p[0]===a[i+1][0])||(a[i-1][1]===p[1]&&p[1]===a[i+1][1])));
const hits=(a,b,boxes)=>boxes.some(o=>Math.min(a[0],b[0])<o.x+o.w&&Math.max(a[0],b[0])>o.x&&Math.min(a[1],b[1])<o.y+o.h&&Math.max(a[1],b[1])>o.y);
export function pathHits(points,boxes){return points.slice(1).some((b,i)=>hits(points[i],b,boxes));}
export function roundPath(points,radius=12){
 let d=`M ${points[0].join(' ')}`;
 for(let i=1;i<points.length-1;i++){
  const a=points[i-1],b=points[i],c=points[i+1],r=Math.min(radius,Math.hypot(b[0]-a[0],b[1]-a[1])/2,Math.hypot(c[0]-b[0],c[1]-b[1])/2);
  d+=` L ${b[0]-Math.sign(b[0]-a[0])*r} ${b[1]-Math.sign(b[1]-a[1])*r} Q ${b.join(' ')} ${b[0]+Math.sign(c[0]-b[0])*r} ${b[1]+Math.sign(c[1]-b[1])*r}`;
 }
 return d+` L ${points.at(-1).join(' ')}`;
}
export function routeEdge({source,target,boxes=[],laneIndex=0}){
 const s=[source.x,source.y],t=[target.x,target.y],dir=source.leftExit?-1:1,entry=target.rightEntry?1:-1;
 const stub=36+Math.min(laneIndex,4)*12,a=[s[0]+dir*stub,s[1]],b=[t[0]+entry*stub,t[1]];
 const snap=n=>Math.round(n/16)*16;
 const candidates=[];
 const add=inner=>{const points=simplify([s,...inner,t]);if(pathHits(inner,boxes))return;const length=points.slice(1).reduce((n,p,i)=>n+Math.abs(p[0]-points[i][0])+Math.abs(p[1]-points[i][1]),0);candidates.push({points,score:length+(points.length-2)*28});};
 const center=snap((a[0]+b[0])/2)+Math.min(laneIndex,4)*16;
 const xs=[center,...boxes.flatMap(o=>[snap(o.x-24),snap(o.x+o.w+24)])];
 const ys=[snap((a[1]+b[1])/2),...boxes.flatMap(o=>[snap(o.y-24),snap(o.y+o.h+24)])];
 const ranked=(values,near)=>[...new Set(values)].sort((x,y)=>Math.abs(x-near)-Math.abs(y-near)).slice(0,28);
 // Straight stubs always leave/enter the side on which the real port sits.
 if(dir===1&&entry===-1&&a[0]<=b[0]){
  for(const x of ranked(xs,center).filter(x=>x>=a[0]&&x<=b[0]))add([a,[x,a[1]],[x,b[1]],b]);
 }
 for(const y of ranked(ys,(a[1]+b[1])/2))add([a,[a[0],y],[b[0],y],b]);
 if(!candidates.length){
  for(const x of ranked(xs,center))for(const y of ranked(ys,a[1]))add([a,[a[0],y],[x,y],[x,b[1]],b]);
 }
 // Explicit outer lane is a bounded fallback for dense diagrams.
 if(!candidates.length){
  const y=Math.min(a[1],b[1],...boxes.map(o=>o.y))-48;
  add([a,[a[0],y],[b[0],y],b]);
 }
 const points=candidates.sort((x,y)=>x.score-y.score)[0]?.points||simplify([s,a,[a[0],b[1]],b,t]);
 const mid=Math.floor(points.length/2),p=points[Math.max(0,mid-1)],q=points[mid];
 let d=roundPath(points);
 // XYFlow computes the common clean Z route; custom obstacle detours use the
 // same orthogonal segments and corner radius, without installing a UI stack.
 if(dir===1&&entry===-1&&points.length===4&&points[1][0]===points[2][0]){
  d=getSmoothStepPath({sourceX:s[0],sourceY:s[1],targetX:t[0],targetY:t[1],sourcePosition:Position.Right,targetPosition:Position.Left,centerX:points[1][0],borderRadius:12,offset:stub})[0];
 }
 return {d,points,label:{x:(p[0]+q[0])/2,y:(p[1]+q[1])/2}};
}
