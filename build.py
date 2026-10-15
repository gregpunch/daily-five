#!/usr/bin/env python3
"""The Daily Five static site generator. See FORMAT.md.
Run: SITE_URL=https://readdailyfive.com python3 build.py
Reads editions/*.json, fetches live prices (Yahoo Finance, Polymarket Gamma API) for the
Scoreboard, writes site/ and scoreboard.csv. Final exits are frozen in data/exits.json."""
import json, os, glob, html, shutil, datetime, csv, urllib.request
from urllib.parse import urlparse
ROOT=os.path.dirname(os.path.abspath(__file__)); OUT=os.path.join(ROOT,'site')
SITE=os.environ.get('SITE_URL','https://readdailyfive.com').rstrip('/'); BASE=urlparse(SITE).path.rstrip('/')
BRAND="The Daily Five"; TAG="The best money-making ideas on the web, ranked daily: stocks, AI, and sports markets."
DISC="Not financial, investment, or betting advice. The Daily Five aggregates public ideas and market prices for information and entertainment only. Past results don't guarantee future returns. You can lose money."
TODAY=datetime.date.today()
E=lambda s: html.escape(str(s))
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=15) as r: return json.load(r)
_cache={}
def stock_price(sym, on=None):
    """Latest price, or the first daily close on/after `on` (a date)."""
    try:
        if on:
            d=get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2y")['chart']['result'][0]
            for t,c in zip(d['timestamp'],d['indicators']['quote'][0]['close']):
                if c and datetime.date.fromtimestamp(t)>=on: return round(c,4),datetime.date.fromtimestamp(t).isoformat()
            return None,None
        if sym not in _cache: _cache[sym]=get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d")['chart']['result'][0]['meta']['regularMarketPrice']
        return _cache[sym],None
    except Exception: return None,None
def market_price(slug,idx):
    try:
        m=get(f"https://gamma-api.polymarket.com/markets?slug={slug}")[0]
        return float(json.loads(m['outcomePrices'])[idx]), bool(m.get('closed'))
    except Exception: return None,False
HZ={'1 Day':1,'1 Month':30,'1 Year':365}
def score(ed):
    exits=json.load(open(EX)) if os.path.exists(EX) else {}; rows=[]
    d0=datetime.date.fromisoformat(ed['date'])
    for i,p in enumerate(ed['finance']):
        key=f"{ed['date']}/f{i}"; end=d0+datetime.timedelta(days=HZ.get(p['horizon'],1)); final=TODAY>end
        if key in exits: cur,final,note=exits[key]['price'],True,exits[key]['note']
        elif final:
            cur,dt=stock_price(p['symbol'],end); note=f"close {dt}"
            if cur is not None: exits[key]={'price':cur,'note':note}
        else: cur,_=stock_price(p['symbol']); note="live"
        rows.append(dict(date=ed['date'],kind='Finance',horizon=p['horizon'],action=p['action'],pick=p['label'],entry=p['entry'],cur=cur,final=final,note=note,src=p['source']['url']))
    for i,p in enumerate(ed['sports']):
        key=f"{ed['date']}/s{i}"
        if key in exits: cur,final,note=exits[key]['price'],True,'resolved'
        else:
            cur,final=market_price(p['slug'],p['outcome']); note='resolved' if final else 'live'
            if final and cur is not None: exits[key]={'price':cur,'note':note}
        rows.append(dict(date=ed['date'],kind='Sports',horizon='Sports market',action=p['action'],pick=p['label']+' · '+p['market'],entry=p['entry'],cur=cur,final=final,note=note,src=p['source']['url']))
    json.dump(exits,open(EX,'w'),indent=1)
    for r in rows:
        if r['cur'] is None: r['ret']=None
        else:
            r['ret']=(r['cur']-r['entry'])/r['entry']*(-1 if r['action']=='SELL' and r['kind']=='Finance' else 1)
    return rows
EX=os.path.join(ROOT,'data','exits.json'); os.makedirs(os.path.dirname(EX),exist_ok=True)
CSS=open(os.path.join(ROOT,'style.css')).read()
def fmt_entry(kind,v): return f"{v*100:.1f}¢" if kind=='Sports' else f"${v:,.2f}"
def shell(title,desc,path,body,schema=None,hero=''):
    url=SITE+path; s=f'<script type="application/ld+json">{json.dumps(schema)}</script>' if schema else ''
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><meta name="description" content="{E(desc)}"><link rel="canonical" href="{url}"><meta name="theme-color" content="#0a0c14">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website"><meta property="og:site_name" content="{BRAND}">
<meta name="twitter:card" content="summary"><link rel="alternate" type="application/rss+xml" title="{BRAND}" href="{BASE}/feed.xml"><link rel="stylesheet" href="{BASE}/style.css">{s}</head><body>
<header class="top"><div class="wrap nav"><a class="logo" href="{BASE}/"><span class="five">5</span> The Daily Five</a><nav><a href="{BASE}/">Today</a><a href="{BASE}/scoreboard/">Scoreboard</a><a href="{BASE}/archive/">Archive</a></nav></div></header>
{hero}<main class="wrap">{body}
<section class="signup" id="subscribe"><h2>Get the Daily Five in your inbox</h2><p>Five minutes, every morning before the bell. Free.</p>
<form onsubmit="event.preventDefault();this.innerHTML='<p class=ok>Thanks! Email delivery is launching soon.</p>'"><input type="email" required placeholder="you@email.com" aria-label="Email address"><button>Subscribe</button></form></section>
</main><footer><div class="wrap"><p class="disc"><strong>Disclaimer:</strong> {DISC}</p><p>© {TODAY.year} {BRAND} · <a href="{BASE}/feed.xml">RSS</a> · <a href="{BASE}/scoreboard/">Track record</a></p></div></footer></body></html>"""
def w(rel,txt):
    p=os.path.join(OUT,rel); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'w').write(txt)
def card(p,kind):
    a=p['action']; cls='buy' if a=='BUY' else 'sell'
    meta=p['horizon'] if kind=='Finance' else (p['market'])
    hz=p['horizon'] if kind=='Finance' else ('Event '+datetime.date.fromisoformat(p['event_date']).strftime('%b %-d') if p.get('event_date') else 'Until resolved')
    risk=f'<p class="risk"><b>Risk:</b> {E(p["risk"])}</p>' if p.get('risk') else ''
    return f"""<article class="card {cls}"><div class="badge">{a} {E(p['label'])}</div><div class="px"><span>@ {fmt_entry(kind,p['entry'])}</span><span class="hz">{E(hz)}</span></div>
{'<p class="mkt">'+E(meta)+'</p>' if kind=='Sports' else ''}<p class="why">{E(p['why'])}</p>{risk}<a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a></article>"""
def edition_body(ed):
    fin=''.join(f'<h3 class="hzh">{h}</h3><div class="grid">'+''.join(card(p,'Finance') for p in ed['finance'] if p['horizon']==h)+'</div>' for h in ['1 Day','1 Month','1 Year'] if any(p['horizon']==h for p in ed['finance']))
    ai=''.join(f'<li class="news"><span class="n">{i+1}</span><div><a href="{E(n["source"]["url"])}" rel="nofollow noopener" target="_blank"><h3>{E(n["headline"])}</h3></a><p>{E(n["why"])}</p><span class="via">{E(n["source"]["name"])}</span></div></li>' for i,n in enumerate(ed['ai']))
    sp='<div class="grid">'+''.join(card(p,'Sports') for p in ed['sports'])+'</div>'
    bd=f'<p class="backdrop"><b>Market backdrop:</b> {E(ed["backdrop"])} <a href="{E(ed["backdrop_source"]["url"])}" rel="nofollow noopener" target="_blank">{E(ed["backdrop_source"]["name"])} ↗</a></p>' if ed.get('backdrop') else ''
    return f"""<div class="disc-bar">⚠️ Not financial or betting advice. Prices are entry snapshots; markets move fast.</div>
<section class="sec fin" id="finance"><h2><span class="dot"></span>Money moves</h2><p class="sub">The best ideas surfaced by AI agents, analysts and public sources, by horizon.</p>{bd}{fin}</section>
<section class="sec ai" id="ai"><h2><span class="dot"></span>AI that matters today</h2><ol class="newslist">{ai}</ol></section>
<section class="sec sp" id="sports"><h2><span class="dot"></span>Sports market plays</h2><p class="sub">Polymarket and Kalshi prices: biggest moves, most volume, and lines that look off.</p>{sp}</section>"""
def pct(x): return '—' if x is None else f"{x*100:+.1f}%"
def main():
    shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT); w('style.css',CSS); w('.nojekyll','')
    host=urlparse(SITE).hostname
    if host and not host.endswith('github.io'): w('CNAME',host+'\n')
    eds=[json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT,'editions','*.json')),reverse=True)]
    items=[]
    for ed in eds:
        d=ed['date']; nice=datetime.date.fromisoformat(d).strftime('%A, %B %-d, %Y')
        picks=", ".join(f"{p['action']} {p['label']}" for p in ed['finance'][:3])
        title=f"Daily Five, {datetime.date.fromisoformat(d).strftime('%b %-d, %Y')}: {ed['headline']}"
        desc=f"{nice}: {picks}, plus top AI news and sports prediction-market plays."
        sch={"@context":"https://schema.org","@type":"NewsArticle","headline":title[:110],"datePublished":d,"dateModified":d,"description":desc,"publisher":{"@type":"Organization","name":BRAND,"url":SITE},"author":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/{d}/"}
        hero=f'<section class="hero"><div class="wrap"><p class="date">{nice}</p><h1>{E(ed["headline"])}</h1><p class="tag">{E(TAG)}</p><div class="jump"><a href="#finance" class="j fin">💰 Money</a><a href="#ai" class="j ai">🤖 AI</a><a href="#sports" class="j sp">🏟️ Sports</a></div></div></section>'
        w(f'{d}/index.html',shell(title,desc,f'/{d}/',edition_body(ed),sch,hero)); items.append((d,nice,title,desc,ed,hero))
    if items:
        d,nice,title,desc,ed,hero=items[0]
        w('index.html',shell(f"{BRAND}: Today's Best Stock Ideas, AI News & Sports Market Plays",f"{TAG} Today: {desc}",'/',edition_body(ed),{"@context":"https://schema.org","@type":"WebSite","name":BRAND,"url":SITE+"/","description":TAG},hero))
    w('archive/index.html',shell(f"Archive | {BRAND}","Every past edition of The Daily Five.",'/archive/','<h1 class="pt">Archive</h1><ul class="arch">'+''.join(f'<li><a href="{BASE}/{d}/"><b>{n}</b><span>{E(e["headline"])}</span></a></li>' for d,n,_,_,e,_ in items)+'</ul>'))
    rows=[r for ed in eds for r in score(ed)]
    with open(os.path.join(ROOT,'scoreboard.csv'),'w',newline='') as f:
        cw=csv.writer(f); cw.writerow(['date','kind','horizon','action','pick','entry','current_or_exit','status','return_pct','source'])
        for r in rows: cw.writerow([r['date'],r['kind'],r['horizon'],r['action'],r['pick'],r['entry'],r['cur'] if r['cur'] is not None else 'pending','final' if r['final'] else 'open',f"{r['ret']*100:.2f}" if r['ret'] is not None else 'pending',r['src']])
    stats=''
    for h in ['1 Day','1 Month','1 Year','Sports market']:
        rs=[r for r in rows if r['horizon']==h and r['ret'] is not None]
        if not any(r['horizon']==h for r in rows): continue
        wins=sum(r['ret']>0 for r in rs); avg=sum(r['ret'] for r in rs)/len(rs) if rs else None
        fin=sum(r['final'] for r in rows if r['horizon']==h)
        stats+=f'<div class="stat"><span class="h">{h}</span><b class="{"pos" if (avg or 0)>=0 else "neg"}">{pct(avg)}</b><span>avg return</span><span>{wins}/{len(rs)} winning · {fin} closed</span></div>'
    tr=''.join(f'<tr><td>{r["date"]}</td><td><span class="mini {"buy" if r["action"]=="BUY" else "sell"}">{r["action"]}</span> {E(r["pick"])}</td><td>{E(r["horizon"])}</td><td>{fmt_entry(r["kind"],r["entry"])}</td><td>{fmt_entry(r["kind"],r["cur"]) if r["cur"] is not None else "pending"} <small>{E(r["note"])}</small></td><td class="{"pos" if (r["ret"] or 0)>0 else "neg" if (r["ret"] or 0)<0 else ""}">{pct(r["ret"])}</td><td>{("✅ Win" if r["ret"]>0 else "❌ Loss" if r["ret"]<0 else "➖ Flat") if r["ret"] is not None else "⏳ Pending"}{"" if r["final"] else " <small>(open)</small>"}</td><td><a href="{E(r["src"])}" rel="nofollow noopener" target="_blank">↗</a></td></tr>' for r in rows)
    upd=datetime.datetime.now().strftime('%b %-d, %Y %-I:%M %p ET')
    body=f'''<h1 class="pt">Scoreboard: if you traded it immediately</h1><p class="sub">Every pick at its published entry price, marked to real market data: Yahoo Finance for stocks, the Polymarket API for markets. SELL returns are short-side. Open picks are marked to market; picks close at the end of their horizon (or when the market resolves). Updated {upd}.</p>
<div class="stats">{stats}</div><div class="tbl"><table><thead><tr><th>Date</th><th>Pick</th><th>Horizon</th><th>Entry</th><th>Now / exit</th><th>P/L</th><th>Result</th><th>Src</th></tr></thead><tbody>{tr}</tbody></table></div>'''
    w('scoreboard/index.html',shell(f"Scoreboard: Track Record of Every Pick | {BRAND}","If you traded every Daily Five pick immediately: entry, current price, % return, win rate and average return by horizon.",'/scoreboard/',body,{"@context":"https://schema.org","@type":"Dataset","name":f"{BRAND} Scoreboard","description":"Track record of featured picks","url":SITE+"/scoreboard/"}))
    urls=['/','/scoreboard/','/archive/']+[f'/{d}/' for d,*_ in items]
    w('sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{SITE}{u}</loc><lastmod>{TODAY}</lastmod></url>" for u in urls)+'</urlset>')
    w('robots.txt',f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    rfc=lambda d: datetime.datetime.fromisoformat(d+'T09:00:00-04:00').strftime('%a, %d %b %Y %H:%M:%S %z')
    w('feed.xml','<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'+f"<title>{BRAND}</title><link>{SITE}/</link><description>{E(TAG)}</description>"+''.join(f"<item><title>{E(t)}</title><link>{SITE}/{d}/</link><guid>{SITE}/{d}/</guid><pubDate>{rfc(d)}</pubDate><description>{E(ds)}</description></item>" for d,_,t,ds,_,_ in items)+'</channel></rss>')
    w('404.html',shell(f"Not found | {BRAND}","Page not found",'/404.html',f'<h1 class="pt">Not found</h1><p><a href="{BASE}/">Go to today\'s edition →</a></p>'))
    print(f"built {len(items)} editions, {len(rows)} scoreboard rows -> {OUT}")
if __name__=='__main__': main()
