(()=>{const $=s=>document.querySelectorAll(s);const T=document.getElementById('tsf');if(!$('.lv').length&&!T)return;
const pct=x=>(x>0?'+':'')+(x*100).toFixed(2)+'%';
const chip=(x,fin)=>x==null?'<span class="chip pend">—</span>':`<span class="chip ${x>0?'up':x<0?'dn':'flat'}">${x>0?'▲':x<0?'▼':'■'} ${pct(x)}${fin?' final':''}</span>`;
const money=(k,v)=>v==null?'—':k==='Sports'?(v*100).toFixed(1)+'¢':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const et=d=>d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'})+' ET';
function paint(el,d){const k=el.dataset.kind,e=+el.dataset.entry,s=el.dataset.side;
 if(d.cur!=null){el.querySelector('[data-k=cur]').textContent=money(k,d.cur);const r=d.ret=(d.cur-e)/e*(s==='SELL'&&k==='Finance'?-1:1);el.querySelector('[data-k=ret]').innerHTML=chip(r,d.final);
  if(d.open){d.so=(d.cur-d.open)/d.open;el.querySelector('[data-k=so]').innerHTML=chip(d.so);}
  const pp=el.closest('.card')&&el.closest('.card').querySelector('[data-k=pp]');if(pp&&k==='Sports')pp.textContent=Math.round(d.cur*100)+'%';}}
const state={};
function strip(){if(!T)return;let L={};try{L=JSON.parse(T.dataset.picks)}catch(e){}
 const rs=[],so=[];for(const id in L){const d=state[id];if(!d||d.final)continue;if(d.ret!=null)rs.push([d.ret,L[id]]);if(d.so!=null)so.push(d.so);}
 if(!rs.length)return;const q=k=>T.querySelector('[data-t='+k+']'),avg=a=>a.reduce((x,y)=>x+y,0)/a.length;rs.sort((a,b)=>b[0]-a[0]);
 q('up').textContent='▲ '+rs.filter(r=>r[0]>0).length;q('dn').textContent='▼ '+rs.filter(r=>r[0]<0).length;
 q('avg').innerHTML=chip(avg(rs.map(r=>r[0])));if(so.length)q('so').innerHTML=chip(avg(so));
 const esc=t=>t.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 q('best').innerHTML=esc(rs[0][1])+' '+chip(rs[0][0]);q('worst').innerHTML=esc(rs[rs.length-1][1])+' '+chip(rs[rs.length-1][0]);}
function stale(ts){const u=document.getElementById('upd');if(!u||!ts)return;let n=document.getElementById('stale');
 const age=(Date.now()/1000-ts)/60,h=+new Date().toLocaleString('en-US',{hour:'numeric',hour12:false,timeZone:'America/New_York'}),wd=!/Sat|Sun/.test(new Date().toLocaleString('en-US',{weekday:'short',timeZone:'America/New_York'}));
 if(age>((wd&&h>=9&&h<17)?25:50)){if(!n){n=document.createElement('span');n.id='stale';n.className='stale';u.after(n);}
  n.textContent='⚠ stock prices from '+et(new Date(ts*1000))+' · stale, refreshing soon';}else if(n)n.remove();}
async function tick(){let stamp=null;
 try{const j=await (await fetch((document.querySelector('link[rel=stylesheet][href$="style.css"]').getAttribute('href').replace('style.css',''))+'data/live.json?t='+Date.now(),{cache:'no-store'})).json();
  for(const id in j.picks){state[id]=Object.assign(state[id]||{},j.picks[id]);}
  for(const el of $('.lv')){const d=state[el.dataset.id];if(d)paint(el,d);}stamp=j.updated_et;stale(j.ts);}catch(e){}
 const sp=[...$('.lv[data-slug]')];
 await Promise.all(sp.map(async el=>{try{if(state[el.dataset.id]&&state[el.dataset.id].final)return;
  const m=(await (await fetch('https://gamma-api.polymarket.com/markets?slug='+encodeURIComponent(el.dataset.slug))).json())[0];
  const d=state[el.dataset.id]=Object.assign(state[el.dataset.id]||{},{cur:+JSON.parse(m.outcomePrices)[+el.dataset.oc]});paint(el,d);stamp=et(new Date());}catch(e){}}));
 const u=document.getElementById('upd');if(u&&stamp)u.textContent=stamp;strip();}
function clock(){const p={};for(const x of new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short',hour:'numeric',minute:'numeric',hourCycle:'h23'}).formatToParts(new Date()))p[x.type]=x.value;
 const h=+p.hour%24,m=+p.minute,wk=!/Sat|Sun/.test(p.weekday),mins=h*60+m,left=(mins<420?420-mins:1860-mins),txt=(left>=60?Math.floor(left/60)+'h ':'')+(left%60)+'m';
 for(const el of $('.nxc'))el.textContent='in '+txt+' · 7 AM ET';
 if(!T)return;const L=T.querySelector('[data-t=lbl]'),M=T.querySelector('[data-t=mk]');if(!L)return;
 const after=wk&&mins>=960,pre=wk&&mins<570,we=!wk;T.classList.toggle('bell',after||we);
 L.textContent=after?'🔔 Closing bell':pre?'Pre-market':we?'Weekend':'Today so far';
 if(M){M.hidden=!(after||pre||we);M.textContent=after?'stocks closed for the day · sports still live':pre?'stocks open 9:30 AM ET':we?'stocks closed · sports live':'';}}
tick();clock();setInterval(tick,60000);setInterval(clock,30000);})();
(()=>{const u=new URL(location.href);if(u.searchParams.get('subscribed')!=='1')return;
const b=document.createElement('div');b.className='subok';b.setAttribute('role','status');
b.innerHTML='<span class="subi">🎉</span><div><b>You\'re in!</b> Check your inbox to confirm. Your first Daily Five arrives tomorrow at 7 AM ET.</div><button aria-label="Dismiss">×</button>';
b.querySelector('button').onclick=()=>b.remove();document.body.prepend(b);setTimeout(()=>b.classList.add('show'),30);
u.searchParams.delete('subscribed');history.replaceState(null,'',u.pathname+(u.search||'')+u.hash);})();
