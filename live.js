(()=>{const $=s=>document.querySelectorAll(s);if(!$('.lv').length)return;
const pct=x=>(x>0?'+':'')+(x*100).toFixed(2)+'%';
const chip=(x,fin)=>x==null?'<span class="chip pend">—</span>':`<span class="chip ${x>0?'up':x<0?'dn':'flat'}">${x>0?'▲':x<0?'▼':'■'} ${pct(x)}${fin?' final':''}</span>`;
const money=(k,v)=>v==null?'—':k==='Sports'?(v*100).toFixed(1)+'¢':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const et=d=>d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'})+' ET';
function paint(el,d){const k=el.dataset.kind,e=+el.dataset.entry,s=el.dataset.side;
 if(d.cur!=null){el.querySelector('[data-k=cur]').textContent=money(k,d.cur);const r=(d.cur-e)/e*(s==='SELL'&&k==='Finance'?-1:1);el.querySelector('[data-k=ret]').innerHTML=chip(r,d.final);
  if(d.open)el.querySelector('[data-k=so]').innerHTML=chip((d.cur-d.open)/d.open);
  const pp=el.closest('.card')&&el.closest('.card').querySelector('[data-k=pp]');if(pp&&k==='Sports')pp.textContent=Math.round(d.cur*100)+'%';}}
const state={};
async function tick(){let stamp=null;
 try{const j=await (await fetch((document.querySelector('link[rel=stylesheet][href$="style.css"]').getAttribute('href').replace('style.css',''))+'data/live.json?t='+Date.now(),{cache:'no-store'})).json();
  for(const el of $('.lv')){const d=j.picks[el.dataset.id];if(d){state[el.dataset.id]=Object.assign(state[el.dataset.id]||{},d);paint(el,state[el.dataset.id]);}}stamp=j.updated_et;}catch(e){}
 const sp=[...$('.lv[data-slug]')];
 await Promise.all(sp.map(async el=>{try{if(state[el.dataset.id]&&state[el.dataset.id].final)return;
  const m=(await (await fetch('https://gamma-api.polymarket.com/markets?slug='+encodeURIComponent(el.dataset.slug))).json())[0];
  const d=state[el.dataset.id]=Object.assign(state[el.dataset.id]||{},{cur:+JSON.parse(m.outcomePrices)[+el.dataset.oc]});paint(el,d);stamp=et(new Date());}catch(e){}}));
 const u=document.getElementById('upd');if(u&&stamp)u.textContent=stamp;}
tick();setInterval(tick,60000);})();
