// Small damped spring waves. No idle loop, WebGL context, or model calls.
const reduce=matchMedia('(prefers-reduced-motion: reduce)');
let wave=null,frame=0,last=0;
function stop(){cancelAnimationFrame(frame);frame=0;wave=null;}
function draw(time){
 if(!wave||!wave.canvas.isConnected||document.hidden||reduce.matches){stop();return;}
 const {canvas,ctx,h,v,width}=wave,dt=Math.min(2,(time-last)/16.67||1);last=time;
 let energy=0;
 const acceleration=h.map((value,i)=>-.035*value+.14*((h[i-1]||0)+(h[i+1]||0)-2*value));
 for(let i=0;i<h.length;i++){v[i]=(v[i]+acceleration[i]*dt)*.92;h[i]+=v[i]*dt;energy+=Math.abs(h[i])+Math.abs(v[i]);}
 ctx.clearRect(0,0,width,36);ctx.beginPath();ctx.moveTo(0,26);
 h.forEach((value,i)=>ctx.lineTo(i/(h.length-1)*width,26+value));
 ctx.lineTo(width,36);ctx.lineTo(0,36);ctx.closePath();
 const fill=ctx.createLinearGradient(0,0,0,36);fill.addColorStop(0,'rgba(40,131,91,.10)');fill.addColorStop(1,'rgba(40,131,91,.015)');ctx.fillStyle=fill;ctx.fill();ctx.strokeStyle='rgba(40,131,91,.21)';ctx.lineWidth=1;ctx.stroke();
 if(energy>.1){frame=requestAnimationFrame(draw);}else{ctx.clearRect(0,0,width,36);stop();}
}
document.addEventListener('pointermove',event=>{
 if(reduce.matches||event.pointerType==='touch')return;
 const card=event.target.closest('.project-folder-card,.identity-option,.preset-row');
 if(card){const r=card.getBoundingClientRect();card.style.setProperty('--pointer-x',`${event.clientX-r.x}px`);card.style.setProperty('--pointer-y',`${event.clientY-r.y}px`);}
 const header=event.target.closest('.project-header');if(!header)return;
 const rect=header.getBoundingClientRect();
 if(!wave||wave.canvas.parentElement!==header){
  stop();let canvas=header.querySelector('.workspace-fluid');if(!canvas){canvas=document.createElement('canvas');canvas.className='workspace-fluid';canvas.setAttribute('aria-hidden','true');header.append(canvas);}
  canvas.width=Math.ceil(rect.width);canvas.height=36;
  wave={canvas,ctx:canvas.getContext('2d'),h:Array(48).fill(0),v:Array(48).fill(0),width:rect.width};
 }
 const index=Math.max(1,Math.min(46,Math.round((event.clientX-rect.x)/rect.width*47)));
 wave.v[index]=Math.max(-3,Math.min(3,wave.v[index]+Math.min(2,Math.abs(event.movementX)*.15)));
 if(!frame){last=0;frame=requestAnimationFrame(draw);}
},{passive:true});
document.addEventListener('pointerdown',event=>{
 if(reduce.matches||!event.target.closest('.button,.identity-card,.nav button,.project-options button'))return;
 const ripple=document.createElement('span');ripple.className='touch-ripple';ripple.style.left=`${event.clientX}px`;ripple.style.top=`${event.clientY}px`;document.body.append(ripple);
 while(document.querySelectorAll('.touch-ripple').length>3)document.querySelector('.touch-ripple').remove();
 ripple.animate([{opacity:.22,transform:'translate(-50%,-50%) scale(.2)'},{opacity:0,transform:'translate(-50%,-50%) scale(1)'}],{duration:450,easing:'cubic-bezier(.2,.7,.2,1)'}).finished.then(()=>ripple.remove(),()=>ripple.remove());
},{passive:true});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
reduce.addEventListener('change',()=>{if(reduce.matches)stop();});
