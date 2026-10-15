#!/usr/bin/env python3
"""The Daily Five static site generator. See FORMAT.md.
Run: SITE_URL=https://readdailyfive.com python3 build.py
Reads editions/*.json; fetches real prices (Yahoo Finance chart API, Polymarket Gamma + CLOB APIs)
for live P/L, sparklines and the Scoreboard; writes site/ and scoreboard.csv; freezes exits in data/exits.json."""
import json, os, glob, html, shutil, datetime, csv, urllib.request
from urllib.parse import urlparse
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
        else: p['cur'],p['final'],p['note']=(s['last'] if s else None),False,'live'
        p['ret']=None if p['cur'] is None else (p['cur']-p['entry'])/p['entry']*(-1 if p['action']=='SELL' else 1)
    for i,p in enumerate(ed['sports']):
        key=f"{ed['date']}/s{i}"; m=pmarket(p['slug']); p['m']=m
        tok=m['tokens'][p['outcome']] if m and len(m['tokens'])>p['outcome'] else None
        p['pts']=phistory(tok) if tok else []
        if key in exits: p['cur'],p['final'],p['note']=exits[key]['price'],True,'resolved'
        else:
            p['cur']=m['prices'][p['outcome']] if m else None; p['final']=bool(m and m['closed']); p['note']='resolved' if p['final'] else 'live'
            if p['final'] and p['cur'] is not None: exits[key]={'price':p['cur'],'note':'resolved'}
        p['ret']=None if p['cur'] is None else (p['cur']-p['entry'])/p['entry']
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
def shell(title,desc,path,body,schema=None,hero=''):
    url=SITE+path; s=f'<script type="application/ld+json">{json.dumps(schema)}</script>' if schema else ''
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><meta name="description" content="{E(desc)}"><link rel="canonical" href="{url}"><meta name="theme-color" content="#07080d">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website"><meta property="og:site_name" content="{BRAND}"><meta name="twitter:card" content="summary">
<link rel="icon" href="{BASE}/favicon.svg" type="image/svg+xml"><link rel="alternate" type="application/rss+xml" title="{BRAND}" href="{BASE}/feed.xml">{FONTS}<link rel="stylesheet" href="{BASE}/style.css">{s}</head><body>
<header class="top"><div class="wrap nav"><a class="logo" href="{BASE}/" aria-label="{BRAND} home">{LOGO}<span class="word"><span class="the">The</span> Daily Five</span></a>
<nav><a href="{BASE}/#finance">Money</a><a href="{BASE}/#ai">AI</a><a href="{BASE}/#sports">Sports</a><a href="{BASE}/scoreboard/" class="pill-nav">Scoreboard</a></nav></div></header>
{hero}<main class="wrap">{body}
<section class="signup" id="subscribe"><div><h2>Five ideas. Every morning. Free.</h2><p>Get the Daily Five in your inbox before the opening bell.</p></div>
{sform('cta')}</section>
</main><footer><div class="wrap"><div class="fbrand">{LOGO}<b>The Daily Five</b></div><div class="fsub"><b>Get it daily</b>{sform('foot')}</div><p class="disc"><strong>Disclaimer:</strong> {DISC}</p><p class="fl"><a href="{BASE}/scoreboard/">Track record</a> · <a href="{BASE}/archive/">Archive</a> · <a href="{BASE}/feed.xml">RSS</a> · © {TODAY.year} {BRAND}</p></div></footer></body></html>"""
def w(rel,txt):
    p=os.path.join(OUT,rel); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'w').write(txt)
def fin_card(p,rank):
    a=p['action'].lower()
    return f"""<article class="card fc {a}"><div class="ctop"><span class="rank">#{rank}</span><span class="hz">⏱ {E(p['horizon'])}</span></div>
<div class="crow"><span class="act {a}">{p['action']}</span><span class="tk">{E(p['label'])}</span></div>
<div class="crow2"><div><span class="lbl">Entry</span><span class="price">${p['entry']:,.2f}</span></div>{spark(p.get('pts'))}<div class="right"><span class="lbl">Since pick</span>{chip(p.get('ret'),p.get('final'))}</div></div>
<p class="why">{E(p['why'])}</p><p class="risk">⚠ {E(p['risk'])}</p><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a></article>"""
def sp_card(p,rank):
    m=p.get('m'); bars=''
    if m:
        cols=['#16c784','#7c5cff'] if len(m['outcomes'])==2 else ['#16c784']*len(m['outcomes'])
        bars='<div class="match">'+''.join(f'<div class="team {"pick" if i==p["outcome"] else ""}"><span class="tn">{E(o)}</span><span class="tp">{pr*100:.0f}%</span></div>' for i,(o,pr) in enumerate(zip(m['outcomes'],m['prices'])))+'</div>'
        if len(m['prices'])==2: bars+=f'<div class="pbar" role="img" aria-label="{E(m["outcomes"][0])} {m["prices"][0]*100:.0f}%, {E(m["outcomes"][1])} {m["prices"][1]*100:.0f}%"><span style="width:{m["prices"][0]*100:.1f}%"></span></div>'
    when='Tonight' if p.get('event_date')==TODAY.isoformat() else ('Event '+datetime.date.fromisoformat(p['event_date']).strftime('%b %-d') if p.get('event_date') else 'Futures')
    vol=f'<span class="vol">${m["volume"]/1e6:.1f}M vol</span>' if m and m['volume']>=1e5 else ''
    return f"""<article class="card sc"><div class="ctop"><span class="rank">#{rank}</span><span class="hz">🏟 {E(when)}</span></div>
<p class="mkt">{E(p['market'])}</p>{bars}
<div class="crow"><span class="act buy">BUY</span><span class="tk sm">{E(p['label'])}</span><span class="at">@ {p['entry']*100:.1f}¢</span></div>
<div class="crow2"><div><span class="lbl">7-day odds</span>{spark(p.get('pts'))}</div>{vol}<div class="right"><span class="lbl">Since pick</span>{chip(p.get('ret'),p.get('final'))}</div></div>
<p class="why">{E(p['why'])}</p><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a></article>"""
def tape(ed):
    it=''.join(f'<span class="ti"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} <i>${p["entry"]:,.2f}</i> {chip(p.get("ret"))}</span>' for p in ed['finance'])
    it+=''.join(f'<span class="ti"><b class="buy">BUY</b> {E(p["label"])} <i>{p["entry"]*100:.1f}¢</i></span>' for p in ed['sports'])
    return f'<div class="tape" aria-label="Today\'s picks"><div class="track">{it}{it}</div></div>'
def hero(ed,nice):
    top=ed['finance'][2] if len(ed['finance'])>2 else ed['finance'][0]
    return f"""<section class="hero"><div class="mesh" aria-hidden="true"></div><div class="wrap hgrid"><div>
<p class="date"><span class="live"></span>{nice}</p><h1>{E(ed.get('top_call') or ed['headline'])}</h1><p class="tag">{E(TAG)}</p>
{sform('hero')}<div class="jump"><a href="#finance">💰 Money moves</a><a href="#ai">🤖 AI</a><a href="#sports">🏟 Sports markets</a></div></div>
<aside class="topcall {top['action'].lower()}"><span class="tlbl">Top call today</span><div class="crow"><span class="act {top['action'].lower()}">{top['action']}</span><span class="tk">{E(top['label'])}</span></div>
<span class="price">${top['entry']:,.2f}</span>{spark(top.get('pts'),220,56)}<p>{E(top['why'])}</p>{chip(top.get('ret'))}</aside></div>{tape(ed)}</section>"""
def body(ed):
    rank=0; fin=''
    for h,ic in [('1 Day','⚡'),('1 Month','📅'),('1 Year','🌱')]:
        ps=[p for p in ed['finance'] if p['horizon']==h]
        if not ps: continue
        cards=''
        for p in ps: rank+=1; cards+=fin_card(p,rank)
        fin+=f'<div class="hzblock"><h3 class="hzh">{ic} {h}</h3><div class="grid">{cards}</div></div>'
    ai=''.join(f'<a class="news {"lead" if i==0 else ""}" href="{E(n["source"]["url"])}" rel="nofollow noopener" target="_blank"><span class="cat">{E(n.get("category","AI"))}</span><h3>{E(n["headline"])}</h3><p>{E(n["why"])}</p><span class="via">{E(n["source"]["name"])} ↗</span></a>' for i,n in enumerate(ed['ai']))
    sp=''.join(sp_card(p,i+1) for i,p in enumerate(ed['sports']))
    bd=f'<p class="backdrop">📉 <b>Backdrop:</b> {E(ed["backdrop"])} <a href="{E(ed["backdrop_source"]["url"])}" rel="nofollow noopener" target="_blank">{E(ed["backdrop_source"]["name"])} ↗</a></p>' if ed.get('backdrop') else ''
    return f"""<p class="disc-bar">⚠️ <b>Not financial or betting advice.</b> Entry prices are real snapshots at publish time; P/L updates with each rebuild.</p>
<section class="sec fin" id="finance"><div class="sh"><span class="si">💰</span><div><h2>Money moves</h2><p class="sub">The best ideas from AI agents, analysts and public sources, by horizon.</p></div></div>{bd}{fin}</section>
<section class="sec ai" id="ai"><div class="sh"><span class="si">🤖</span><div><h2>AI that matters</h2><p class="sub">The five stories most likely to shape what's next.</p></div></div><div class="newsgrid">{ai}</div></section>
<section class="sec sp" id="sports"><div class="sh"><span class="si">🏟</span><div><h2>Sports market plays</h2><p class="sub">Live Polymarket odds: big moves, big volume, and lines that look off.</p></div></div><div class="grid g3">{sp}</div></section>"""
def bar_chart(rows):
    rs=[r for r in rows if r['ret'] is not None]
    if not rs: return ''
    mx=max(abs(r['ret']) for r in rs) or 1; bw=34; h=140; mid=h/2; W=len(rs)*(bw+10)+10
    bars=''.join(f'<g><rect x="{10+i*(bw+10)}" y="{mid-max(r["ret"],0)/mx*(mid-14):.1f}" width="{bw}" height="{max(abs(r["ret"])/mx*(mid-14),1.5):.1f}" rx="4" fill="{"#16c784" if r["ret"]>=0 else "#ff4d5e"}"/><text x="{10+i*(bw+10)+bw/2}" y="{h-2}" text-anchor="middle">{E(r["short"])}</text></g>' for i,r in enumerate(rs))
    return f'<figure class="chart"><svg viewBox="0 0 {W} {h+12}" width="100%" height="{h+12}" preserveAspectRatio="xMinYMid meet" role="img" aria-label="Return by pick"><line x1="0" x2="{W}" y1="{mid}" y2="{mid}" stroke="#2a3048"/>{bars}</svg><figcaption>Return since pick, by pick</figcaption></figure>'
def main():
    shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
    w('style.css',open(os.path.join(ROOT,'style.css')).read()); w('.nojekyll','')
    w('favicon.svg',LOGO.replace('class="mark" ','xmlns="http://www.w3.org/2000/svg" ').replace(' width="34" height="34"',''))
    host=urlparse(SITE).hostname
    if host and not host.endswith('github.io'): w('CNAME',host+'\n')
    eds=[json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT,'editions','*.json')),reverse=True)]
    for ed in eds: enrich(ed)
    items=[]
    for ed in eds:
        d=ed['date']; dd=datetime.date.fromisoformat(d); nice=dd.strftime('%A, %B %-d, %Y')
        picks=", ".join(f"{p['action']} {p['label']}" for p in ed['finance'][:4])
        title=f"{ed['headline']} | Daily Five, {dd.strftime('%b %-d')}"
        desc=f"{nice}: {picks}, plus the top AI news and sports prediction-market plays."
        sch={"@context":"https://schema.org","@type":"NewsArticle","headline":ed['headline'][:110],"datePublished":d,"dateModified":d,"description":desc,"publisher":{"@type":"Organization","name":BRAND,"url":SITE,"logo":{"@type":"ImageObject","url":SITE+"/favicon.svg"}},"author":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/{d}/"}
        hr=hero(ed,nice); w(f'{d}/index.html',shell(title,desc,f'/{d}/',body(ed),sch,hr)); items.append((d,nice,title,desc,ed,hr))
    if items:
        d,nice,title,desc,ed,hr=items[0]
        w('index.html',shell(f"The Daily Five: Today's Best Stock Picks, AI News & Sports Market Plays",f"{TAG} Today: {desc}",'/',body(ed),{"@context":"https://schema.org","@type":"WebSite","name":BRAND,"url":SITE+"/","description":TAG},hr))
    w('archive/index.html',shell(f"Archive | {BRAND}","Every past edition of The Daily Five.",'/archive/','<h1 class="pt">Archive</h1><div class="arch">'+''.join(f'<a href="{BASE}/{d}/"><span class="ad">{n}</span><b>{E(e["headline"])}</b></a>' for d,n,_,_,e,_ in items)+'</div>'))
    rows=[]
    for ed in eds:
        for p in ed['finance']: rows.append(dict(date=ed['date'],kind='Finance',horizon=p['horizon'],action=p['action'],pick=p['label'],short=p['label'],entry=p['entry'],cur=p['cur'],final=p['final'],note=p['note'],ret=p['ret'],src=p['source']['url'],pts=p['pts']))
        for p in ed['sports']: rows.append(dict(date=ed['date'],kind='Sports',horizon='Sports',action='BUY',pick=f"{p['label']} · {p['market']}",short=p['label'].split()[0][:7],entry=p['entry'],cur=p['cur'],final=p['final'],note=p['note'],ret=p['ret'],src=p['source']['url'],pts=p['pts']))
    with open(os.path.join(ROOT,'scoreboard.csv'),'w',newline='') as f:
        cw=csv.writer(f); cw.writerow(['date','kind','horizon','action','pick','entry','current_or_exit','status','return_pct','source'])
        for r in rows: cw.writerow([r['date'],r['kind'],r['horizon'],r['action'],r['pick'],r['entry'],r['cur'] if r['cur'] is not None else 'pending','final' if r['final'] else 'open',f"{r['ret']*100:.2f}" if r['ret'] is not None else 'pending',r['src']])
    def tile(name,rs_all):
        rs=[r for r in rs_all if r['ret'] is not None]; wins=sum(r['ret']>0 for r in rs); avg=sum(r['ret'] for r in rs)/len(rs) if rs else None
        wr=f"{wins/len(rs)*100:.0f}%" if rs else '—'
        return f'<div class="tile"><span class="h">{name}</span><b class="{"up" if (avg or 0)>=0 else "dn"}">{pct(avg)}</b><span class="s">avg return</span><div class="wr"><span style="width:{(wins/len(rs)*100) if rs else 0:.0f}%"></span></div><span class="s">{wr} win rate · {wins}/{len(rs)} · {sum(r["final"] for r in rs_all)} closed</span></div>'
    tiles=tile('All picks',rows)+''.join(tile(h,[r for r in rows if r['horizon']==h]) for h in ['1 Day','1 Month','1 Year','Sports'] if any(r['horizon']==h for r in rows))
    fmt=lambda r,v: (f"{v*100:.1f}¢" if r['kind']=='Sports' else f"${v:,.2f}") if v is not None else 'pending'
    tr=''.join(f'<tr><td class="mono">{r["date"][5:]}</td><td><span class="mini {r["action"].lower()}">{r["action"]}</span> <b>{E(r["pick"])}</b></td><td>{E(r["horizon"])}</td><td class="mono">{fmt(r,r["entry"])}</td><td class="mono">{fmt(r,r["cur"])} <small>{E(r["note"])}</small></td><td>{spark(r["pts"],90,26)}</td><td>{chip(r["ret"],r["final"])}</td><td>{("Win" if r["ret"]>0 else "Loss" if r["ret"]<0 else "Flat") if r["ret"] is not None else "Pending"}{"" if r["final"] else " <small>open</small>"}</td><td><a href="{E(r["src"])}" rel="nofollow noopener" target="_blank" aria-label="source">↗</a></td></tr>' for r in rows)
    upd=datetime.datetime.now().strftime('%b %-d, %Y · %-I:%M %p ET')
    sb=f'''<section class="sbhero"><span class="kicker">📊 Scoreboard</span><h1 class="pt">If you traded it immediately</h1><p class="sub">Every pick at its published entry price, marked to real market data from Yahoo Finance (stocks) and Polymarket (markets). SELL returns are short-side. Picks close at the end of their horizon or when the market resolves. Updated {upd}.</p></section>
<div class="tiles">{tiles}</div>{bar_chart(rows)}<div class="tbl"><table><thead><tr><th>Date</th><th>Pick</th><th>Horizon</th><th>Entry</th><th>Now / exit</th><th>Trend</th><th>P/L</th><th>Result</th><th></th></tr></thead><tbody>{tr}</tbody></table></div>'''
    w('scoreboard/index.html',shell(f"Scoreboard: Track Record of Every Pick | {BRAND}","If you traded every Daily Five pick immediately: entry, current price, % return, win rate and average return by horizon.",'/scoreboard/',sb,{"@context":"https://schema.org","@type":"Dataset","name":f"{BRAND} Scoreboard","description":"Track record of featured picks","url":SITE+"/scoreboard/"}))
    urls=['/','/scoreboard/','/archive/']+[f'/{d}/' for d,*_ in items]
    w('sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{SITE}{u}</loc><lastmod>{TODAY}</lastmod></url>" for u in urls)+'</urlset>')
    w('robots.txt',f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    rfc=lambda d: datetime.datetime.fromisoformat(d+'T09:00:00-04:00').strftime('%a, %d %b %Y %H:%M:%S %z')
    w('feed.xml','<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'+f"<title>{BRAND}</title><link>{SITE}/</link><description>{E(TAG)}</description>"+''.join(f"<item><title>{E(t)}</title><link>{SITE}/{d}/</link><guid>{SITE}/{d}/</guid><pubDate>{rfc(d)}</pubDate><description>{E(ds)}</description></item>" for d,_,t,ds,_,_ in items)+'</channel></rss>')
    w('404.html',shell(f"Not found | {BRAND}","Page not found",'/404.html',f'<h1 class="pt">Not found</h1><p><a href="{BASE}/">Go to today\'s edition →</a></p>'))
    print(f"built {len(items)} editions, {len(rows)} scoreboard rows -> {OUT}")
if __name__=='__main__': main()
