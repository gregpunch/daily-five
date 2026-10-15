#!/usr/bin/env python3
"""The Daily Five static site generator. See FORMAT.md.
Run: SITE_URL=https://readdailyfive.com python3 build.py
Reads editions/*.json; fetches real prices (Yahoo Finance chart API, Polymarket Gamma + CLOB APIs)
for live P/L, sparklines and the Scoreboard; writes site/ and scoreboard.csv; freezes exits in data/exits.json."""
import time, json, os, glob, html, shutil, datetime, csv, urllib.request
from urllib.parse import urlparse
os.environ['TZ']='America/New_York'; time.tzset()
ROOT=os.path.dirname(os.path.abspath(__file__)); OUT=os.path.join(ROOT,'site')
SITE=os.environ.get('SITE_URL','https://readdailyfive.com').rstrip('/'); BASE=urlparse(SITE).path.rstrip('/')
BRAND="The Daily Five"; TAG="The best money-making ideas on the web, ranked every morning."
DISC="Not financial, investment, or betting advice. The Daily Five aggregates public ideas and market prices for information and entertainment only. Past results don't guarantee future returns. You can lose money."
TODAY=datetime.date.today(); E=lambda s: html.escape(str(s))
EX=os.path.join(ROOT,'data','exits.json'); os.makedirs(os.path.dirname(EX),exist_ok=True)
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=15) as r: return json.load(r)
_c={}
def memo(k,f):
    if k not in _c:
        try: _c[k]=f()
        except Exception: _c[k]=None
    return _c[k]
def yseries(sym,since):
    days=(TODAY-since).days
    rng,iv=('5d','15m') if days<4 else ('1mo','1d') if days<25 else ('2y','1d')
    def f():
        r=get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={iv}&range={rng}")['chart']['result'][0]
        pts=[(t,c) for t,c in zip(r.get('timestamp',[]),r['indicators']['quote'][0]['close']) if c is not None]
        return {'last':r['meta']['regularMarketPrice'],'pts':pts}
    return memo(('y',sym,rng),f)
def stock_close_on(sym,on):
    s=memo(('yd',sym),lambda: get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2y")['chart']['result'][0])
    if not s: return None,None
    for t,c in zip(s['timestamp'],s['indicators']['quote'][0]['close']):
        if c and datetime.date.fromtimestamp(t)>=on: return round(c,4),datetime.date.fromtimestamp(t).isoformat()
    return None,None
def pmarket(slug):
    def f():
        m=get(f"https://gamma-api.polymarket.com/markets?slug={slug}")[0]
        return {'outcomes':json.loads(m['outcomes']),'prices':[float(x) for x in json.loads(m['outcomePrices'])],'closed':bool(m.get('closed')),'tokens':json.loads(m.get('clobTokenIds') or '[]'),'volume':float(m.get('volume') or 0)}
    return memo(('pm',slug),f)
def phistory(token):
    return memo(('ph',token),lambda: [(h['t'],h['p']) for h in get(f"https://clob.polymarket.com/prices-history?market={token}&interval=1w&fidelity=60")['history']])
HZ={'1 Day':1,'1 Month':30,'1 Year':365}
import re
def slugify(x): return re.sub(r'[^a-z0-9]+','-',x.lower()).strip('-')
NOW=datetime.datetime.now()
def today_open_stock(sym):
    def f():
        r=get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=1d")['chart']['result'][0]
        o=[x for x in r['indicators']['quote'][0]['open'] if x is not None]
        return {'open':o[0] if o else None,'last':r['meta']['regularMarketPrice'],'t':r['meta'].get('regularMarketTime')}
    return memo(('yo',sym),f)
def spark(pts,w=120,h=34,up=None):
    if not pts or len(pts)<2: return ''
    ys=[p for _,p in pts]; lo,hi=min(ys),max(ys); rng=(hi-lo) or 1
    step=w/(len(ys)-1); d=' '.join(f"{i*step:.1f},{h-2-(y-lo)/rng*(h-4):.1f}" for i,y in enumerate(ys))
    up=ys[-1]>=ys[0] if up is None else up; col='#16c784' if up else '#ff4d5e'
    return f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true"><polyline fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="{d}"/></svg>'
def enrich(ed):
    """Attach live price, P/L, sparkline pts, final state to every pick."""
    exits=json.load(open(EX)) if os.path.exists(EX) else {}; d0=datetime.date.fromisoformat(ed['date'])
    start=datetime.datetime.combine(d0,datetime.time(9,30)).timestamp()
    for i,p in enumerate(ed['finance']):
        key=f"{ed['date']}/f{i}"; end=d0+datetime.timedelta(days=HZ.get(p['horizon'],1)); s=yseries(p['symbol'],d0)
        p['pts']=[(t,c) for t,c in (s['pts'] if s else []) if t>=start]
        if key in exits: p['cur'],p['final'],p['note']=exits[key]['price'],True,exits[key]['note']
        elif TODAY>end:
            c,dt=stock_close_on(p['symbol'],end); p['cur'],p['final'],p['note']=c,c is not None,f"closed {dt}"
            if c is not None: exits[key]={'price':c,'note':p['note']}
        else:
            o=today_open_stock(p['symbol']); p['cur'],p['final'],p['note']=((o or {}).get('last') or (s['last'] if s else None)),False,'live'
        o=today_open_stock(p['symbol']) if not p['final'] else None
        p['open']=(o or {}).get('open'); p['qt']=(o or {}).get('t')
        p['id']=f"{ed['date']}-{slugify(p['action']+'-'+p['label'])}"; p['tslug']=p['symbol'].upper(); p['tname']=p['symbol'].upper(); p['kind']='Finance'
        p['ret']=None if p['cur'] is None else (p['cur']-p['entry'])/p['entry']*(-1 if p['action']=='SELL' else 1)
    for i,p in enumerate(ed['sports']):
        key=f"{ed['date']}/s{i}"; m=pmarket(p['slug']); p['m']=m
        tok=m['tokens'][p['outcome']] if m and len(m['tokens'])>p['outcome'] else None
        p['pts']=phistory(tok) if tok else []
        if key in exits: p['cur'],p['final'],p['note']=exits[key]['price'],True,'resolved'
        else:
            p['cur']=m['prices'][p['outcome']] if m else None; p['final']=bool(m and m['closed']); p['note']='resolved' if p['final'] else 'live'
            if p['final'] and p['cur'] is not None: exits[key]={'price':p['cur'],'note':'resolved'}
        midnight=datetime.datetime.combine(TODAY,datetime.time()).timestamp()
        tp=[v for t,v in p['pts'] if t>=midnight]; p['open']=tp[0] if tp else None; p['qt']=int(NOW.timestamp())
        p['ret']=None if p['cur'] is None else (p['cur']-p['entry'])/p['entry']
        p['id']=f"{ed['date']}-{slugify(p['label']+'-'+p['market'])[:60].strip('-')}"; p['tslug']=p['slug'][:70]; p['tname']=p['market'].split(',')[0]; p['kind']='Sports'
    for p in ed['finance']+ed['sports']:
        p['so']=None if (p.get('open') in (None,0) or p.get('cur') is None) else (p['cur']-p['open'])/p['open']
    json.dump(exits,open(EX,'w'),indent=1)
def pct(x): return '—' if x is None else f"{x*100:+.2f}%"
def chip(r,final=False):
    if r is None: return '<span class="chip pend">⏳ pending</span>'
    c='up' if r>0 else 'dn' if r<0 else 'flat'; return f'<span class="chip {c}">{"▲" if r>0 else "▼" if r<0 else "■"} {pct(r)}{" final" if final else ""}</span>'
LOGO='''<svg class="mark" viewBox="0 0 40 40" width="34" height="34" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#16c784"/><stop offset=".55" stop-color="#7c5cff"/><stop offset="1" stop-color="#ffb020"/></linearGradient></defs><rect width="40" height="40" rx="11" fill="url(#lg)"/><path d="M27.5 9.5H15.2l-1.6 10.2c1.6-1.2 3.4-1.8 5.4-1.8 4.6 0 7.9 3.2 7.9 7.6 0 4.7-3.6 8-8.6 8-4.1 0-7.2-2.2-8-5.6l4-1.2c.5 1.7 2 2.8 4 2.8 2.4 0 4.1-1.6 4.1-3.9s-1.7-3.9-4.1-3.9c-1.6 0-2.9.6-3.8 1.7l-3.9-.9L13 5.9h14.5z" fill="#fff"/></svg>'''
KIT='https://app.kit.com/forms/10050182/subscriptions'
def sform(cls=''):
    return f'<form class="kform {cls}" action="{KIT}" method="post" target="_blank"><label class="sr" for="em-{cls or "x"}">Email address</label><input id="em-{cls or "x"}" type="email" name="email_address" required autocomplete="email" placeholder="you@email.com"><button type="submit">Subscribe free →</button></form>'
FONTS='<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">'
OGIMG={'v':None}
def shell(title,desc,path,body,schema=None,hero='',og=None):
    og=og or OGIMG['v']; ogm=f'<meta property="og:image" content="{SITE}{og}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:image" content="{SITE}{og}">' if og else ''
    url=SITE+path; s=f'<script type="application/ld+json">{json.dumps(schema)}</script>' if schema else ''
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><meta name="description" content="{E(desc)}"><link rel="canonical" href="{url}"><meta name="theme-color" content="#07080d">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website"><meta property="og:site_name" content="{BRAND}"><meta name="twitter:card" content="summary_large_image">{ogm}
<link rel="icon" href="{BASE}/favicon.svg" type="image/svg+xml"><link rel="alternate" type="application/rss+xml" title="{BRAND}" href="{BASE}/feed.xml">{FONTS}<link rel="stylesheet" href="{BASE}/style.css">{s}</head><body>
<header class="top"><div class="wrap nav"><a class="logo" href="{BASE}/" aria-label="{BRAND} home">{LOGO}<span class="word"><span class="the">The</span> Daily Five</span></a>
<nav><a href="{BASE}/#finance">Money</a><a href="{BASE}/track-record/">Track record</a><a href="{BASE}/#ai">AI</a><a href="{BASE}/#sports">Sports</a><a href="{BASE}/scoreboard/" class="pill-nav">Scoreboard</a></nav></div></header>
{hero}<main class="wrap">{body}
<section class="signup" id="subscribe"><div><h2>Five ideas. Every morning. Free.</h2><p>Get the Daily Five in your inbox before the opening bell.</p></div>
{sform('cta')}</section>
</main><footer><div class="wrap"><div class="fbrand">{LOGO}<b>The Daily Five</b></div><div class="fsub"><b>Get it daily</b>{sform('foot')}</div><p class="disc"><strong>Disclaimer:</strong> {DISC}</p><p class="fl"><a href="{BASE}/track-record/">Track record</a> · <a href="{BASE}/how-we-rank/">How we rank</a> · <a href="{BASE}/scoreboard/">Scoreboard</a> · <a href="{BASE}/archive/">Archive</a> · <a href="{BASE}/feed.xml">RSS</a> · © {TODAY.year} {BRAND}</p></div></footer><script src="{BASE}/live.js" defer></script></body></html>"""
def w(rel,txt):
    p=os.path.join(OUT,rel); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'w').write(txt)
def money(kind,v): return '—' if v is None else (f"{v*100:.1f}¢" if kind=='Sports' else f"${v:,.2f}")
def mv(x):
    if x is None: return '<span class="chip pend">—</span>'
    c='up' if x>0 else 'dn' if x<0 else 'flat'; return f'<span class="chip {c}">{"▲" if x>0 else "▼" if x<0 else "■"} {pct(x)}</span>'
def livebox(p):
    k=p['kind']
    return f"""<div class="lv" data-id="{p['id']}" data-kind="{k}" data-entry="{p['entry']}" data-side="{p['action']}"{f' data-slug="{p["slug"]}" data-oc="{p["outcome"]}"' if k=='Sports' else ''}>
<div><span class="lbl">Entry</span><span class="price">{money(k,p['entry'])}</span></div>
<div><span class="lbl">Live</span><span class="price" data-k="cur">{money(k,p.get('cur'))}</span></div>
<div><span class="lbl">Today</span><span data-k="so">{mv(p.get('so'))}</span></div>
<div><span class="lbl">Since pick</span><span data-k="ret">{chip(p.get('ret'),p.get('final'))}</span></div></div>"""
def fin_card(p,rank):
    a=p['action'].lower()
    return f"""<article class="card fc {a}"><div class="ctop"><span class="rank">#{rank}</span><span class="hz">⏱ {E(p['horizon'])}</span>{badge(p)}</div>
<div class="crow"><span class="act {a}">{p['action']}</span><a class="tk" href="{BASE}/ticker/{p['tslug']}/">{E(p['label'])}</a>{spark(p.get('pts'),110,32)}</div>{livebox(p)}{breakdown(p)}
<p class="why"><b>Why {p['action']}:</b> {E(p['why'])}</p><p class="risk">⚠ {E(p['risk'])}</p><div class="cfoot"><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a><a class="more" href="{BASE}/picks/{p['id']}/">Details →</a></div></article>"""
def sp_card(p,rank):
    m=p.get('m'); bars=''
    if m:
        bars='<div class="match">'+''.join(f'<div class="team {"pick" if i==p["outcome"] else ""}"><span class="tn">{E(o)}</span><span class="tp" {"data-k=pp" if i==p["outcome"] else ""}>{pr*100:.0f}%</span></div>' for i,(o,pr) in enumerate(zip(m['outcomes'],m['prices'])))+'</div>'
        if len(m['prices'])==2: bars+=f'<div class="pbar" role="img" aria-label="{E(m["outcomes"][0])} {m["prices"][0]*100:.0f}%, {E(m["outcomes"][1])} {m["prices"][1]*100:.0f}%"><span style="width:{m["prices"][0]*100:.1f}%"></span></div>'
    when='Tonight' if p.get('event_date')==TODAY.isoformat() else ('Event '+datetime.date.fromisoformat(p['event_date']).strftime('%b %-d') if p.get('event_date') else 'Futures')
    vol=f'<span class="vol">${m["volume"]/1e6:.1f}M vol</span>' if m and m['volume']>=1e5 else ''
    return f"""<article class="card sc"><div class="ctop"><span class="rank">#{rank}</span><span class="hz">🏟 {E(when)}</span>{badge(p)}</div>
<a class="mkt" href="{BASE}/ticker/{p['tslug']}/">{E(p['market'])}</a>{bars}
<div class="crow"><span class="act buy">BUY</span><span class="tk sm">{E(p['label'])}</span>{vol}{spark(p.get('pts'),100,30)}</div>{livebox(p)}{breakdown(p)}
<p class="why"><b>Why BUY:</b> {E(p['why'])}</p><div class="cfoot"><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a><a class="more" href="{BASE}/picks/{p['id']}/">Details →</a></div></article>"""
def tape(ed):
    it=''.join(f'<span class="ti"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} <i>${p["entry"]:,.2f}</i> {chip(p.get("ret"))}</span>' for p in ed['finance'])
    it+=''.join(f'<span class="ti"><b class="buy">BUY</b> {E(p["label"])} <i>{p["entry"]*100:.1f}¢</i></span>' for p in ed['sports'])
    return f'<div class="tape" aria-label="Today\'s picks"><div class="track">{it}{it}</div></div>'
def hero(ed,nice):
    top=ed['finance'][0]
    return f"""<section class="hero"><div class="mesh" aria-hidden="true"></div><div class="wrap hgrid"><div>
<p class="date"><span class="live"></span>{nice}</p><h1>{E(ed.get('top_call') or ed['headline'])}</h1><p class="tag">{E(TAG)}</p>
{sform('hero')}<div class="jump"><a href="#finance">💰 Money moves</a><a href="#ai">🤖 AI</a><a href="#sports">🏟 Sports markets</a></div></div>
<aside class="topcall {top['action'].lower()}"><span class="tlbl">Top call today</span><div class="crow"><span class="act {top['action'].lower()}">{top['action']}</span><span class="tk">{E(top['label'])}</span></div>
<span class="price">${top['entry']:,.2f}</span>{spark(top.get('pts'),220,56)}<p>{E(top['why'])}</p>{chip(top.get('ret'))}</aside></div>{tape(ed)}</section>"""
def recap(prev):
    if not prev: return '<div class="recap"><div><span class="kicker">📬 Yesterday\'s results</span><p>This is our first edition, so results start tomorrow. Every pick is tracked on the <a href="'+BASE+'/track-record/">Track record</a>.</p></div><div class="tmr">⏰ Come back tomorrow at <b>7 AM ET</b> for the next five.</div></div>'
    ps=prev['finance']+prev['sports']; rs=[p['ret'] for p in ps if p.get('ret') is not None]
    items=''.join(f'<a href="{BASE}/picks/{p["id"]}/" class="rc"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} {chip(p.get("ret"),p.get("final"))}</a>' for p in ps)
    summ=f'{sum(r>0 for r in rs)}/{len(rs)} winning · avg {pct(sum(rs)/len(rs)) if rs else "—"}'
    return f'<div class="recap"><div><span class="kicker">📬 Yesterday\'s results ({prev["date"]})</span><p><b>{summ}</b></p><div class="rcs">{items}</div></div><div class="tmr">⏰ Come back tomorrow at <b>7 AM ET</b> for the next five.</div></div>'
def body(ed,prev=None):
    rank=0; fin=''
    for h,ic in [('1 Day','⚡'),('1 Month','📅'),('1 Year','🌱')]:
        ps=[p for p in ed['finance'] if p['horizon']==h]
        if not ps: continue
        cards=''
        for p in ps: cards+=fin_card(p,ed['finance'].index(p)+1)
        fin+=f'<div class="hzblock"><h3 class="hzh">{ic} {h}</h3><div class="grid">{cards}</div></div>'
    ai=''.join(f'<a class="news {"lead" if i==0 else ""}" href="{E(n["source"]["url"])}" rel="nofollow noopener" target="_blank"><span class="cat">{E(n.get("category","AI"))}</span><h3>{E(n["headline"])}</h3><p>{E(n["why"])}</p><span class="via">{E(n["source"]["name"])} ↗</span></a>' for i,n in enumerate(ed['ai']))
    sp=''.join(sp_card(p,i+1) for i,p in enumerate(ed['sports']))
    bd=f'<p class="backdrop">📉 <b>Backdrop:</b> {E(ed["backdrop"])} <a href="{E(ed["backdrop_source"]["url"])}" rel="nofollow noopener" target="_blank">{E(ed["backdrop_source"]["name"])} ↗</a></p>' if ed.get('backdrop') else ''
    upd=NOW.strftime('%-I:%M %p ET')
    return recap(prev)+f"""<p class="stamp"><span class="live"></span>Live prices · last updated <b id="upd">{upd}</b> · <span class="dl">delayed: stocks via Yahoo Finance (may lag up to ~15 min), sports via Polymarket</span></p><p class="disc-bar">⚠️ <b>Not financial or betting advice.</b> Entry prices are real snapshots at publish time; P/L updates with each rebuild.</p>
<section class="sec fin" id="finance"><div class="sh"><span class="si">💰</span><div><h2>Money moves</h2><p class="sub">The best ideas from AI agents, analysts and public sources, by horizon.</p></div></div>{bd}{fin}</section>
<section class="sec ai" id="ai"><div class="sh"><span class="si">🤖</span><div><h2>AI that matters</h2><p class="sub">The five stories most likely to shape what's next.</p></div></div><div class="newsgrid">{ai}</div></section>
<section class="sec sp" id="sports"><div class="sh"><span class="si">🏟</span><div><h2>Sports market plays</h2><p class="sub">Live Polymarket odds: big moves, big volume, and lines that look off.</p></div></div><div class="grid g3">{sp}</div></section>"""
def bar_chart(rows):
    rs=[r for r in rows if r['ret'] is not None]
    if not rs: return ''
    mx=max(abs(r['ret']) for r in rs) or 1; bw=34; h=140; mid=h/2; W=len(rs)*(bw+10)+10
    bars=''.join(f'<g><rect x="{10+i*(bw+10)}" y="{mid-max(r["ret"],0)/mx*(mid-14):.1f}" width="{bw}" height="{max(abs(r["ret"])/mx*(mid-14),1.5):.1f}" rx="4" fill="{"#16c784" if r["ret"]>=0 else "#ff4d5e"}"/><text x="{10+i*(bw+10)+bw/2}" y="{h-2}" text-anchor="middle">{E(r["short"])}</text></g>' for i,r in enumerate(rs))
    return f'<figure class="chart"><svg viewBox="0 0 {W} {h+12}" width="100%" height="{h+12}" preserveAspectRatio="xMinYMid meet" role="img" aria-label="Return by pick"><line x1="0" x2="{W}" y1="{mid}" y2="{mid}" stroke="#2a3048"/>{bars}</svg><figcaption>Return since pick, by pick</figcaption></figure>'
# ---------- Daily Five Score (0-100) ----------
import math, http.cookiejar, urllib.parse
_yop={'op':None,'crumb':None}
def yahoo_target(sym):
    def f():
        if not _yop['op']:
            cj=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)); op.addheaders=[('User-Agent','Mozilla/5.0')]
            try: op.open('https://fc.yahoo.com',timeout=10)
            except Exception: pass
            _yop['crumb']=op.open('https://query2.finance.yahoo.com/v1/test/getcrumb',timeout=10).read().decode(); _yop['op']=op
        d=json.load(_yop['op'].open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules=financialData&crumb={urllib.parse.quote(_yop['crumb'])}",timeout=15))
        fd=d['quoteSummary']['result'][0]['financialData']; g=lambda k:(fd.get(k) or {}).get('raw') if isinstance(fd.get(k),dict) else None
        return {'target':g('targetMeanPrice'),'n':g('numberOfAnalystOpinions'),'rec':fd.get('recommendationKey')}
    return memo(('tgt',sym),f)
def daily_vol(sym):
    def f():
        r=get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=3mo")['chart']['result'][0]
        c=[x for x in r['indicators']['quote'][0]['close'] if x]; rets=[math.log(b/a) for a,b in zip(c,c[1:])][-60:]
        m=sum(rets)/len(rets); return (sum((x-m)**2 for x in rets)/(len(rets)-1))**.5
    return memo(('vol',sym),f)
def am2p(o): return 100/(o+100) if o>0 else -o/(-o+100)
clamp=lambda x:max(0.0,min(25.0,x))
TD={'1 Day':1,'1 Month':21,'1 Year':252}
def source_hits(eds):
    st={}
    for ed in eds:
        for p in ed['finance']+ed['sports']:
            if p.get('final') and p.get('ret') is not None:
                s=st.setdefault(p['source']['name'],[0,0]); s[0]+=p['ret']>0; s[1]+=1
    return st
def score_pick(p,hits):
    b={}; notes=[]
    h=hits.get(p['source']['name'])
    if h and h[1]>=5: b['cred']=round(h[0]/h[1]*25,1); notes.append(f"source hit {h[0]/h[1]*100:.0f}%")
    else: b['cred']=12.5; notes.append("new source")
    c=p.get('consensus')
    if c:
        a,dn=len(c.get('agree',[])),len(c.get('dissent',[])); n=a+dn
        b['cons']=round(clamp(12.5+12.5*((a-dn)/max(n,1))*min(n,4)/4),1); notes.append(f"{a} agree · {dn} dissent")
    else: b['cons']=12.5; notes.append("consensus not checked")
    gap=None; fair=None
    if p['kind']=='Finance':
        t=yahoo_target(p['symbol']); px=p.get('cur') or p['entry']
        if t and t.get('target'):
            gap=(t['target']-px)/px*(1 if p['action']=='BUY' else -1); p['target']=t
            b['edge']=round(clamp(12.5+gap*50),1); notes.insert(0,f"{gap*100:+.0f}% vs analyst target")
        else: b['edge']=12.5; notes.insert(0,"no analyst target")
        v=daily_vol(p['symbol'])
        if v and gap is not None:
            hd=TD.get(p['horizon'],1); ratio=(gap*min(hd/252,1))/(v*math.sqrt(hd)); b['rr']=round(12.5+12.5*math.tanh(ratio),1); p['vol']=v
        else: b['rr']=12.5
    else:
        bk=p.get('book'); px=p.get('cur') or p['entry']
        if bk and bk.get('odds'):
            q=[am2p(o) for o in bk['odds']]; fair=q[0]/sum(q); p['fair']=fair
            pts=(fair-px)*100; b['edge']=round(clamp(12.5+pts*1.25),1); notes.insert(0,f"edge {pts:+.0f} pts vs books")
            ev=(fair-px)/px; b['rr']=round(12.5+12.5*math.tanh(ev*5),1)
        else: b['edge']=12.5; b['rr']=12.5; notes.insert(0,"no sportsbook line")
    p['score']=round(sum(b.values())); p['sb']=b; p['snote']=' · '.join(notes)
def badge(p):
    s=p.get('score')
    if s is None: return ''
    c='hi' if s>=65 else 'mid' if s>=50 else 'lo'
    b=p['sb']; tip=f"Credibility {b['cred']}/25 · Consensus {b['cons']}/25 · Edge {b['edge']}/25 · Risk/reward {b['rr']}/25"
    return f'<a class="score {c}" href="{BASE}/how-we-rank/" title="{tip}" aria-label="Daily Five Score {s} of 100. {tip}"><b>{s}</b><span>D5 score</span></a>'
def breakdown(p):
    b=p.get('sb')
    if not b: return ''
    bars=''.join(f'<span class="sbx" title="{n} {v}/25"><i style="width:{v/25*100:.0f}%"></i><em>{n}</em></span>' for n,v in [('Cred',b['cred']),('Cons',b['cons']),('Edge',b['edge']),('R/R',b['rr'])])
    return f'<div class="sbd"><div class="sbars">{bars}</div><p class="snote">{E(p["snote"])}</p></div>'
HOWTO=("<section class='sbhero'><span class='kicker'>🧮 Methodology</span><h1 class='pt'>How we rank: the Daily Five Score</h1><p class='sub'>Every finance and sports pick gets a 0–100 score from four components worth 25 points each. The Top 5 in each section are ordered by it. We only use real data; when a component can't be computed, it gets a neutral 12.5 and we say so on the card.</p></section>"
 "<div class='how'><div class='hw'><h2>1 · Source credibility (0–25)</h2><p>The source's historical hit rate on our own <a href='/track-record/'>track record</a>: closed picks from that source that made money. Until a source has at least 5 closed picks it gets a neutral 12.5, labeled <b>new source</b>.</p></div>"
 "<div class='hw'><h2>2 · Consensus (0–25)</h2><p>How many independent, credible sources we found agreeing with the call versus dissenting. 12.5 + 12.5 × (agree − dissent)/(agree + dissent), scaled down when there are fewer than four sources. With no sources checked, it's a neutral 12.5.</p></div>"
 "<div class='hw'><h2>3 · Edge vs fair value (0–25)</h2><p><b>Stocks:</b> % gap between the live price and the consensus analyst mean price target (Yahoo Finance), signed for BUY or SELL: 12.5 + 50 × gap. Peer valuation isn't computed yet. <b>Sports and markets:</b> the sportsbook's no-vig implied probability minus the Polymarket price, in points: 12.5 + 1.25 × points.</p></div>"
 "<div class='hw'><h2>4 · Risk/reward (0–25)</h2><p><b>Stocks:</b> the horizon-scaled share of the target gap divided by the horizon's volatility (60-day daily volatility × √trading days): 12.5 + 12.5 × tanh(ratio). <b>Markets:</b> expected value per $1 at the fair probability: 12.5 + 12.5 × tanh(5 × EV).</p></div></div>"
 "<p class='sub'>Scores recompute every time live prices refresh. A high score isn't a guarantee. Not financial or betting advice.</p>")

def ogimage(ed,nice):
    fin=ed['finance'][:4]
    rowsvg=''.join(f'<g transform="translate(70,{300+i*70})"><rect width="128" height="48" rx="24" fill="{"#16c784" if p["action"]=="BUY" else "#ff4d5e"}"/><text x="64" y="33" text-anchor="middle" font-size="24" font-weight="800" fill="#06130c">{p["action"]}</text><text x="150" y="36" font-family="monospace" font-size="38" font-weight="700" fill="#fff">{E(p["label"])}</text><text x="380" y="36" font-family="monospace" font-size="30" fill="#9ba3ba">${p["entry"]:,.2f}</text><text x="640" y="36" font-size="24" fill="#c9cede">{E(p["horizon"])}</text></g>' for i,p in enumerate(fin))
    logo=LOGO.replace('class="mark" ','').replace(' width="34" height="34"','').replace('<svg ','<svg width="40" height="40" ')
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><defs><radialGradient id="a" cx=".15" cy=".1" r=".7"><stop offset="0" stop-color="#16c784" stop-opacity=".45"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient><radialGradient id="b" cx=".9" cy=".2" r=".7"><stop offset="0" stop-color="#7c5cff" stop-opacity=".55"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient></defs>'
         f'<rect width="1200" height="630" fill="#07080d"/><rect width="1200" height="630" fill="url(#a)"/><rect width="1200" height="630" fill="url(#b)"/><g font-family="Inter,Helvetica,Arial,sans-serif">'
         f'<g transform="translate(70,60) scale(1.6)">{logo}</g><text x="160" y="112" font-size="44" font-weight="800" fill="#fff">The Daily Five</text>'
         f'<text x="70" y="200" font-size="26" font-weight="700" fill="#ffb020" letter-spacing="3">{E(nice.upper())}</text><text x="70" y="250" font-size="34" font-weight="700" fill="#fff">{E(ed["headline"][:60])}</text>{rowsvg}'
         f'<text x="1130" y="600" text-anchor="end" font-size="22" fill="#9ba3ba">readdailyfive.com \u00b7 Not financial advice</text></g></svg>')
    rel=f"og/{ed['date']}.png"; w(f"og/{ed['date']}.svg",svg); svgp=os.path.join(OUT,f"og/{ed['date']}.svg")
    chrome=shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    if chrome:
        import subprocess
        try: subprocess.run([chrome,'--headless=new','--no-sandbox','--hide-scrollbars','--window-size=1200,630',f'--screenshot={os.path.join(OUT,rel)}','file://'+svgp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        except Exception: pass
    return '/'+rel if os.path.exists(os.path.join(OUT,rel)) else f"/og/{ed['date']}.svg"
def write_live(eds):
    picks={}
    for ed in eds:
        for p in ed['finance']+ed['sports']:
            picks[p['id']]={'cur':p.get('cur'),'open':p.get('open'),'so':p.get('so'),'ret':p.get('ret'),'final':p.get('final'),'kind':p['kind'],'qt':p.get('qt')}
    w('data/live.json',json.dumps({'updated':NOW.isoformat(timespec='seconds'),'updated_et':NOW.strftime('%-I:%M %p ET'),'picks':picks}))
def pick_page(p,ed):
    k=p['kind']; t=f"{p['action']} {p['label']}"+(f" ({p['market']})" if k=='Sports' else f" \u00b7 {p['horizon']} pick")
    title=f"{t}: {ed['date']} | {BRAND}"; desc=f"{t} at {money(k,p['entry'])} on {ed['date']}. Why: {p['why']}"[:155]
    card=fin_card(p,'') if k=='Finance' else sp_card(p,'')
    kick="\U0001F4B0 Finance pick" if k=="Finance" else "\U0001F3DF Sports market pick"
    note=(' \u00b7 '+E(p.get('entry_note'))) if p.get('entry_note') else ''
    det=(f'<section class="sbhero"><span class="kicker">{kick} \u00b7 {ed["date"]}</span><h1 class="pt">{E(t)}</h1></section><div class="pickwrap">{card}<div class="pinfo">'
         f'<h2>Pick details</h2><dl><dt>Published</dt><dd>{ed["date"]} in <a href="{BASE}/{ed["date"]}/">that day\'s edition</a></dd><dt>Entry</dt><dd>{money(k,p["entry"])}{note}</dd>'
         f'<dt>Status</dt><dd>{"Final" if p.get("final") else "Open"} \u00b7 {E(p.get("note",""))}</dd><dt>Source</dt><dd><a href="{E(p["source"]["url"])}" rel="nofollow noopener" target="_blank">{E(p["source"]["name"])}</a></dd></dl>'
         f'<p><a href="{BASE}/ticker/{p["tslug"]}/">All picks on {E(p["tname"])} \u2192</a><br><a href="{BASE}/track-record/">Full track record \u2192</a></p></div></div>')
    sch={"@context":"https://schema.org","@type":"Article","headline":t[:110],"datePublished":ed['date'],"description":desc,"author":{"@type":"Organization","name":BRAND},"publisher":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/picks/{p['id']}/","about":{"@type":"Thing","name":p['tname']}}
    w(f"picks/{p['id']}/index.html",shell(title,desc,f"/picks/{p['id']}/",det,sch))
def seo_pages(eds,rows,tiles):
    urls=[]; by={}
    for ed in eds:
        for p in ed['finance']+ed['sports']:
            pick_page(p,ed); urls.append(f"/picks/{p['id']}/"); by.setdefault(p['tslug'],[]).append((p,ed))
    for slug,lst in by.items():
        p0=lst[0][0]; nm=p0['tname']; k=p0['kind']
        title=(f"{nm} Stock: Daily Five Picks, Live Price & Track Record" if k=='Finance' else f"{nm}: Prediction Market Odds & Daily Five Picks")+f" | {BRAND}"
        desc=f"Every Daily Five pick on {nm}: entry prices, live {'price' if k=='Finance' else 'odds'}, and returns since each pick. Latest: {p0['action']} {p0['label']} on {lst[0][1]['date']}."[:155]
        li=''.join(f'<a class="rc" href="{BASE}/picks/{p["id"]}/"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} \u00b7 {ed["date"]} \u00b7 entry {money(p["kind"],p["entry"])} {chip(p.get("ret"),p.get("final"))}</a>' for p,ed in lst)
        rs=[p['ret'] for p,_ in lst if p.get('ret') is not None]
        cardf=fin_card if k=="Finance" else sp_card
        bodyh=f'<section class="sbhero"><span class="kicker">{"\U0001F4C8 Ticker" if k=="Finance" else "\U0001F3DF Market"}</span><h1 class="pt">{E(nm)}</h1><p class="sub">{len(lst)} pick(s) \u00b7 avg return since pick {pct(sum(rs)/len(rs)) if rs else "\u2014"}</p></section><div class="pickwrap">{cardf(p0,"")}<div class="pinfo"><h2>All picks</h2><div class="rcs col">{li}</div><p><a href="{BASE}/track-record/">Full track record \u2192</a></p></div></div>'
        sch={"@context":"https://schema.org","@type":"CollectionPage","name":title,"description":desc,"url":f"{SITE}/ticker/{slug}/"}
        w(f"ticker/{slug}/index.html",shell(title,desc,f"/ticker/{slug}/",bodyh,sch)); urls.append(f"/ticker/{slug}/")
    allp=''.join(f'<a class="rc" href="{BASE}/picks/{r["id"]}/"><b class="{r["action"].lower()}">{r["action"]}</b> {E(r["pick"])} \u00b7 {E(r["horizon"])} \u00b7 {r["date"]} {chip(r["ret"],r["final"])}</a>' for r in rows)
    tk=''.join(f'<a class="tkchip" href="{BASE}/ticker/{s}/">{E(l[0][0]["tname"])}</a>' for s,l in by.items())
    tb=(f'<section class="sbhero"><span class="kicker">\U0001F3C6 Track record</span><h1 class="pt">Every pick, graded in public</h1><p class="sub">We publish an entry price from a real quote for every pick, then mark it to live market data until its horizon ends (1 Day, 1 Month, 1 Year) or its market resolves. Nothing gets deleted. SELL returns are short-side. See the <a href="{BASE}/scoreboard/">Scoreboard</a> for charts.</p></section>'
        f'<div class="tiles">{tiles}</div><h2 class="h2s">Tickers &amp; markets</h2><div class="tks">{tk}</div><h2 class="h2s">All picks</h2><div class="rcs col">{allp}</div>')
    w('track-record/index.html',shell(f"Track Record: Win Rate & Returns of Every Pick | {BRAND}","The Daily Five's public track record: win rate and average return by horizon for every stock and sports-market pick, marked to real prices.",'/track-record/',tb,{"@context":"https://schema.org","@type":"CollectionPage","name":"Daily Five Track Record","url":SITE+"/track-record/"}))
    return urls
def main():
    shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
    w('style.css',open(os.path.join(ROOT,'style.css')).read()); w('.nojekyll','')
    w('favicon.svg',LOGO.replace('class="mark" ','xmlns="http://www.w3.org/2000/svg" ').replace(' width="34" height="34"',''))
    host=urlparse(SITE).hostname
    if host and not host.endswith('github.io'): w('CNAME',host+'\n')
    eds=[json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT,'editions','*.json')),reverse=True)]
    for ed in eds: enrich(ed)
    hits=source_hits(eds)
    for ed in eds:
        for p in ed['finance']+ed['sports']: score_pick(p,hits)
        ed['finance'].sort(key=lambda p:-p['score']); ed['sports'].sort(key=lambda p:-p['score'])
    items=[]
    for i,ed in enumerate(eds):
        prev=eds[i+1] if i+1<len(eds) else None
        d=ed['date']; dd=datetime.date.fromisoformat(d); nice=dd.strftime('%A, %B %-d, %Y')
        picks=", ".join(f"{p['action']} {p['label']}" for p in ed['finance'][:4])
        title=f"{ed['headline']} | Daily Five, {dd.strftime('%b %-d')}"
        desc=f"{nice}: {picks}, plus the top AI news and sports prediction-market plays."
        sch={"@context":"https://schema.org","@type":"NewsArticle","headline":ed['headline'][:110],"datePublished":d,"dateModified":d,"description":desc,"publisher":{"@type":"Organization","name":BRAND,"url":SITE,"logo":{"@type":"ImageObject","url":SITE+"/favicon.svg"}},"author":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/{d}/"}
        og=ogimage(ed,nice); sch['image']=SITE+og
        if i==0: OGIMG['v']=og
        hr=hero(ed,nice); w(f'{d}/index.html',shell(title,desc,f'/{d}/',body(ed,prev),sch,hr,og)); items.append((d,nice,title,desc,ed,hr))
    if items:
        d,nice,title,desc,ed,hr=items[0]
        w('index.html',shell(f"The Daily Five: Today's Best Stock Picks, AI News & Sports Market Plays",f"{TAG} Today: {desc}",'/',body(ed,eds[1] if len(eds)>1 else None),{"@context":"https://schema.org","@type":"WebSite","name":BRAND,"url":SITE+"/","description":TAG},hr))
    w('archive/index.html',shell(f"Archive | {BRAND}","Every past edition of The Daily Five.",'/archive/','<h1 class="pt">Archive</h1><div class="arch">'+''.join(f'<a href="{BASE}/{d}/"><span class="ad">{n}</span><b>{E(e["headline"])}</b></a>' for d,n,_,_,e,_ in items)+'</div>'))
    rows=[]
    for ed in eds:
        for p in ed['finance']: rows.append(dict(id=p['id'],date=ed['date'],kind='Finance',horizon=p['horizon'],action=p['action'],pick=p['label'],short=p['label'],entry=p['entry'],cur=p['cur'],final=p['final'],note=p['note'],ret=p['ret'],src=p['source']['url'],pts=p['pts']))
        for p in ed['sports']: rows.append(dict(id=p['id'],date=ed['date'],kind='Sports',horizon='Sports',action='BUY',pick=f"{p['label']} · {p['market']}",short=p['label'].split()[0][:7],entry=p['entry'],cur=p['cur'],final=p['final'],note=p['note'],ret=p['ret'],src=p['source']['url'],pts=p['pts']))
    with open(os.path.join(ROOT,'scoreboard.csv'),'w',newline='') as f:
        cw=csv.writer(f); cw.writerow(['date','kind','horizon','action','pick','entry','current_or_exit','status','return_pct','source'])
        for r in rows: cw.writerow([r['date'],r['kind'],r['horizon'],r['action'],r['pick'],r['entry'],r['cur'] if r['cur'] is not None else 'pending','final' if r['final'] else 'open',f"{r['ret']*100:.2f}" if r['ret'] is not None else 'pending',r['src']])
    def tile(name,rs_all):
        rs=[r for r in rs_all if r['ret'] is not None]; wins=sum(r['ret']>0 for r in rs); avg=sum(r['ret'] for r in rs)/len(rs) if rs else None
        wr=f"{wins/len(rs)*100:.0f}%" if rs else '—'
        return f'<div class="tile"><span class="h">{name}</span><b class="{"up" if (avg or 0)>=0 else "dn"}">{pct(avg)}</b><span class="s">avg return</span><div class="wr"><span style="width:{(wins/len(rs)*100) if rs else 0:.0f}%"></span></div><span class="s">{wr} win rate · {wins}/{len(rs)} · {sum(r["final"] for r in rs_all)} closed</span></div>'
    tiles=tile('All picks',rows)+''.join(tile(h,[r for r in rows if r['horizon']==h]) for h in ['1 Day','1 Month','1 Year','Sports'] if any(r['horizon']==h for r in rows))
    fmt=lambda r,v: (f"{v*100:.1f}¢" if r['kind']=='Sports' else f"${v:,.2f}") if v is not None else 'pending'
    tr=''.join(f'<tr><td class="mono">{r["date"][5:]}</td><td><span class="mini {r["action"].lower()}">{r["action"]}</span> <a href="{BASE}/picks/{r['id']}/"><b>{E(r["pick"])}</b></a></td><td>{E(r["horizon"])}</td><td class="mono">{fmt(r,r["entry"])}</td><td class="mono">{fmt(r,r["cur"])} <small>{E(r["note"])}</small></td><td>{spark(r["pts"],90,26)}</td><td>{chip(r["ret"],r["final"])}</td><td>{("Win" if r["ret"]>0 else "Loss" if r["ret"]<0 else "Flat") if r["ret"] is not None else "Pending"}{"" if r["final"] else " <small>open</small>"}</td><td><a href="{E(r["src"])}" rel="nofollow noopener" target="_blank" aria-label="source">↗</a></td></tr>' for r in rows)
    upd=datetime.datetime.now().strftime('%b %-d, %Y · %-I:%M %p ET')
    sb=f'''<section class="sbhero"><span class="kicker">📊 Scoreboard</span><h1 class="pt">If you traded it immediately</h1><p class="sub">Every pick at its published entry price, marked to real market data from Yahoo Finance (stocks) and Polymarket (markets). SELL returns are short-side. Picks close at the end of their horizon or when the market resolves. Updated {upd}.</p></section>
<div class="tiles">{tiles}</div>{bar_chart(rows)}<div class="tbl"><table><thead><tr><th>Date</th><th>Pick</th><th>Horizon</th><th>Entry</th><th>Now / exit</th><th>Trend</th><th>P/L</th><th>Result</th><th></th></tr></thead><tbody>{tr}</tbody></table></div>'''
    w('scoreboard/index.html',shell(f"Scoreboard: Track Record of Every Pick | {BRAND}","If you traded every Daily Five pick immediately: entry, current price, % return, win rate and average return by horizon.",'/scoreboard/',sb,{"@context":"https://schema.org","@type":"Dataset","name":f"{BRAND} Scoreboard","description":"Track record of featured picks","url":SITE+"/scoreboard/"}))
    extra=seo_pages(eds,rows,tiles); write_live(eds); w('live.js',open(os.path.join(ROOT,'live.js')).read())
    w('how-we-rank/index.html',shell(f'How We Rank Picks: The Daily Five Score Methodology | {BRAND}','How the 0-100 Daily Five Score ranks every stock and sports-market pick: source credibility, consensus, edge vs analyst targets and sportsbook odds, and risk/reward.','/how-we-rank/',HOWTO,{'@context':'https://schema.org','@type':'Article','headline':'How we rank: the Daily Five Score','author':{'@type':'Organization','name':BRAND}}))
    urls=['/','/scoreboard/','/track-record/','/how-we-rank/','/archive/']+[f'/{d}/' for d,*_ in items]+extra
    w('sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{SITE}{u}</loc><lastmod>{TODAY}</lastmod></url>" for u in urls)+'</urlset>')
    w('robots.txt',f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    rfc=lambda d: datetime.datetime.fromisoformat(d+'T09:00:00-04:00').strftime('%a, %d %b %Y %H:%M:%S %z')
    w('feed.xml','<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'+f"<title>{BRAND}</title><link>{SITE}/</link><description>{E(TAG)}</description>"+''.join(f"<item><title>{E(t)}</title><link>{SITE}/{d}/</link><guid>{SITE}/{d}/</guid><pubDate>{rfc(d)}</pubDate><description>{E(ds)}</description></item>" for d,_,t,ds,_,_ in items)+'</channel></rss>')
    w('404.html',shell(f"Not found | {BRAND}","Page not found",'/404.html',f'<h1 class="pt">Not found</h1><p><a href="{BASE}/">Go to today\'s edition →</a></p>'))
    print(f"built {len(items)} editions, {len(rows)} scoreboard rows -> {OUT}")
if __name__=='__main__': main()
