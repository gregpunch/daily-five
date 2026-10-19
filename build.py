#!/usr/bin/env python3
"""The Daily Five static site generator. See FORMAT.md.
Run: SITE_URL=https://readdailyfive.com python3 build.py
Reads editions/*.json; fetches real prices (Yahoo Finance chart API, Polymarket Gamma + CLOB APIs)
for live P/L, sparklines and the Scoreboard; writes site/ and scoreboard.csv; freezes exits in data/exits.json."""
import time, json, os, glob, html, shutil, datetime, csv, re, urllib.request
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
        d=datetime.date.fromtimestamp(t)
        # Today's daily bar is still forming until the close: never freeze an intraday price as an exit.
        if d==TODAY and NOW.time()<datetime.time(16,15): return None,None
        if c and d>=on: return round(c,4),d.isoformat()
    return None,None
def pmarket(slug):
    def f():
        r=get(f"https://gamma-api.polymarket.com/markets?slug={slug}")
        # Gamma drops closed markets from the default query; ask again for closed ones so resolved picks settle.
        if not r: r=get(f"https://gamma-api.polymarket.com/markets?slug={slug}&closed=true")
        m=r[0]
        return {'outcomes':json.loads(m['outcomes']),'prices':[float(x) for x in json.loads(m['outcomePrices'])],'closed':bool(m.get('closed')),'tokens':json.loads(m.get('clobTokenIds') or '[]'),'volume':float(m.get('volume') or 0),'start':m.get('gameStartTime')}
    return memo(('pm',slug),f)
GAME_RE=re.compile(r'^(nfl|mlb|nba|nhl|wnba|cfb|cbb)-[a-z]+-[a-z]+-\d{4}-\d{2}-\d{2}$')
def pgame(slug):
    """Live game state for a Polymarket game event (score is 'away-home', period NS / Q1..Q4 / HT / VFT)."""
    if not GAME_RE.match(slug or ''): return None
    def f():
        r=get(f"https://gamma-api.polymarket.com/events?slug={slug}") or get(f"https://gamma-api.polymarket.com/events?slug={slug}&closed=true")
        e=r[0]; tm=e.get('teams') or []
        return {'score':e.get('score') or '','period':e.get('period') or '','elapsed':e.get('elapsed') or '','live':bool(e.get('live')),'ended':bool(e.get('ended')),
                'teams':sorted([{'ab':(t.get('abbreviation') or '').upper(),'al':t.get('alias') or '','nm':t.get('name') or '','o':t.get('ordering')} for t in tm],key=lambda t:0 if t['o']=='away' else 1)}
    return memo(('pg',slug),f)
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
            else:  # horizon ended on a weekend/holiday: no exit close yet, so mark to the latest price until the next close
                o=today_open_stock(p['symbol']); p['cur'],p['note']=((o or {}).get('last') or (s['last'] if s else None)),'live (exits at next close)'
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
            p['cur']=m['prices'][p['outcome']] if m else None; p['final']=bool(m and m['closed'] and p['cur'] is not None and (p['cur']>=0.99 or p['cur']<=0.01)); p['note']='resolved' if p['final'] else ('closed, awaiting resolution' if m and m['closed'] else 'live')
            if p['final'] and p['cur'] is not None: exits[key]={'price':p['cur'],'note':'resolved'}
            elif m and GAME_RE.match(p.get('slug') or ''):
                # Game over but the market hasn't resolved on-chain yet (UMA can take hours): settle provisionally on the final score.
                # Not written to exits, so the official resolution still overrides it once the market closes.
                g=pgame(p['slug']); d=final_margin(p,g,m)
                if d: p['cur'],p['final'],p['note']=(1.0 if d>0 else 0.0),True,'final score, awaiting resolution'
        midnight=datetime.datetime.combine(TODAY,datetime.time()).timestamp()
        tp=[v for t,v in p['pts'] if t>=midnight]; p['open']=tp[0] if tp else None; p['qt']=int(NOW.timestamp())
        p['ret']=None if p['cur'] is None else (p['cur']-p['entry'])/p['entry']
        p['id']=p.get('pid') or f"{ed['date']}-{slugify(p['label']+'-'+p['market'])[:60].strip('-')}"; p['tslug']=p['slug'][:70]; p['tname']=p['market'].split(',')[0]; p['kind']='Sports'
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
    return f'<form class="kform {cls}" action="{KIT}" method="post" target="_self" onsubmit="var b=this.querySelector(&quot;button&quot;);b.textContent=&quot;Subscribing...&quot;;b.disabled=true"><label class="sr" for="em-{cls or "x"}">Email address</label><input id="em-{cls or "x"}" type="email" name="email_address" required autocomplete="email" placeholder="you@email.com"><button type="submit">Subscribe free →</button></form>'
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
<nav><a href="{BASE}/#finance">Money</a><a href="{BASE}/track-record/">Track record</a><a href="{BASE}/#ai">AI</a><a href="{BASE}/#sports">Sports</a><a class="xl" href="https://x.com/ReadDailyFive" rel="me noopener" target="_blank" aria-label="The Daily Five on X"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.8 7.8L23 22h-6.2l-4.8-6.3L6.4 22H3.3l7.3-8.3L1 2h6.3l4.4 5.8zm-1.1 18h1.7L6.3 3.9H4.5z"/></svg><span class="sr">X</span></a><a href="{BASE}/scoreboard/" class="pill-nav">Scoreboard</a></nav></div></header>
{hero}<main class="wrap">{body}
<section class="signup" id="subscribe"><div><h2>Five ideas. Every morning. Free.</h2><p>Get the Daily Five in your inbox before the opening bell.</p></div>
{sform('cta')}</section>
</main><footer><div class="wrap"><div class="fbrand">{LOGO}<b>The Daily Five</b></div><div class="fsub"><b>Get it daily</b>{sform('foot')}</div><p class="disc"><strong>Disclaimer:</strong> {DISC}</p><p class="fl"><a href="{BASE}/track-record/">Track record</a> · <a href="{BASE}/best-stocks-to-buy-today/">Best stocks</a> · <a href="{BASE}/polymarket-picks-today/">Polymarket picks</a> · <a href="{BASE}/nfl-picks-this-week/">NFL picks</a> · {f'<a href="{BASE}/nfl-results/">NFL results</a> · ' if NFLWK else ''}<a href="{BASE}/how-we-rank/">How we rank</a> · <a href="{BASE}/scoreboard/">Scoreboard</a> · <a href="{BASE}/archive/">Archive</a> · <a class="xl" href="https://x.com/ReadDailyFive" rel="me noopener" target="_blank" aria-label="The Daily Five on X"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.8 7.8L23 22h-6.2l-4.8-6.3L6.4 22H3.3l7.3-8.3L1 2h6.3l4.4 5.8zm-1.1 18h1.7L6.3 3.9H4.5z"/></svg>@ReadDailyFive</a> · <a href="{BASE}/feed.xml">RSS</a> · © {TODAY.year} {BRAND}</p></div></footer><script src="{BASE}/live.js" defer></script></body></html>"""
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
GLBL={'nfl':'\u23f1 Kickoff','cfb':'\u23f1 Kickoff','mlb':'\u26be First pitch','nba':'\u23f1 Tip-off','wnba':'\u23f1 Tip-off','cbb':'\u23f1 Tip-off','nhl':'\u23f1 Puck drop'}
def _left(sec):
    m=max(0,round(sec/60)); d,h,mm=m//1440,m%1440//60,m%60
    return f'{d}d {h}h' if d>=2 else (f'{h+24*d}h {mm}m' if m>=60 else f'{mm}m')
def pick_side(p,g,m):
    """'a' or 'h': which team in the game our picked outcome is."""
    aw,hm=g['teams']; pn=(m.get('outcomes') or [p['label']])[p['outcome']] if m.get('outcomes') else p['label']
    hit=lambda t: pn.lower() in (t['al']+' '+t['nm']).lower() or (t['al'] and t['al'].lower() in pn.lower())
    return 'h' if (hit(hm) and not hit(aw)) else ('a' if hit(aw) else ('a' if p['outcome']==0 else 'h'))
def final_margin(p,g,m):
    """Our side's final margin once the game has ended (None if not over, unscored, or not a 2-team game). BUY only."""
    if not g or len(g['teams'])!=2 or p.get('action','BUY')!='BUY' or not (g['ended'] or g['period'] in ('VFT','FT','F')): return None
    if not re.fullmatch(r'\d+-\d+',g['score']): return None
    a,h=[int(x) for x in g['score'].split('-')]; return (a-h) if pick_side(p,g,m)=='a' else (h-a)
def gd(p,cls=''):
    """Game-day status line for a sports pick on a real game: countdown, then live score, then final.
    Server renders the state at build time; live.js polls Polymarket's events API every minute near and during the game."""
    g=pgame(p.get('slug')); m=p.get('m') or {}
    if not g or len(g['teams'])!=2: return ''
    ko=kickoff(p)
    if not ko: return ''
    aw,hm=g['teams']; pn=(m.get('outcomes') or [p['label']])[p['outcome']] if m.get('outcomes') else p['label']
    ps=pick_side(p,g,m)
    sp=p['slug'].split('-')[0]; lb=GLBL.get(sp,'\u23f1 Starts'); kt=ko.strftime('%a %-I:%M %p ET')
    B_=lambda t,sd: f'<b class="pk">{E(t)}</b>' if sd==ps else E(t)
    sc=[int(x) for x in g['score'].split('-')] if re.fullmatch(r'\d+-\d+',g['score']) else None
    fin=g['ended'] or g['period'] in ('VFT','FT','F'); now=datetime.datetime.now().astimezone()
    live=(not fin) and (g['live'] or (sc is not None and now>=ko and g['period'] not in ('','NS')))
    if (fin or live) and sc:
        me,op=(sc[0],sc[1]) if ps=='a' else (sc[1],sc[0]); d=me-op
        mt=f'{B_(aw["ab"],"a")} {sc[0]}<i>\u2013</i>{sc[1]} {B_(hm["ab"],"h")}'
        if fin: st='fin '+('won' if d>0 else 'lost' if d<0 else ''); bd='FINAL'; xt=f'{pn} won \u2705' if d>0 else (f'{pn} lost' if d<0 else 'Tied')
        else:
            per={'HT':'Halftime'}.get(g['period'],g['period'])
            st='on '+('ahead' if d>0 else 'behind' if d<0 else ''); bd='\U0001F534 LIVE'+(f' \u00b7 {per}' if per else '')+(f' {g["elapsed"]}' if g['elapsed'] else ''); xt=f'{pn} up {d}' if d>0 else (f'{pn} down {-d}' if d<0 else 'Tied')
    else:
        st='pre'; bd=lb; mt=f'{B_(aw["ab"],"a")} @ {B_(hm["ab"],"h")}'; left=(ko-now).total_seconds(); xt=f'{kt} \u00b7 '+(f'in {_left(left)}' if left>0 else 'starting now')
    pn=p['label']; xt=xt.replace((m.get('outcomes') or [pn])[p['outcome']] if m.get('outcomes') else pn,pn,1)
    data=(f' data-ev="{E(p["slug"])}" data-ko="{int(ko.timestamp())}" data-aw="{E(aw["ab"])}" data-hm="{E(hm["ab"])}" data-ps="{ps}" data-pn="{E(pn)}" data-lb="{E(lb)}" data-kt="{E(kt)}"'
          f' data-sc="{E(g["score"])}" data-pe="{E(g["period"])}" data-el="{E(g["elapsed"])}" data-lv="{int(g["live"])}" data-en="{int(g["ended"])}"')
    return f'<div class="gd {st} {cls}"{data} aria-live="polite"><span class="gdb">{E(bd)}</span><span class="gdm">{mt}</span><span class="gdx">{E(xt)}</span></div>'
def gd_board(ps,title='Game day'):
    """Compact live board: one row per picked game (deduped by market, latest call wins), sorted by start time."""
    seen=set(); rows=[]
    for p in ps:
        if p.get('slug') in seen: continue
        g=gd(p,'row')
        if not g: continue
        seen.add(p['slug']); rows.append((kickoff(p),f'<a class="gdr" href="{BASE}/picks/{p["id"]}/"><span class="gdp"><span class="act buy">BUY</span> {E(p["label"])}</span>{g}</a>'))
    if not rows: return ''
    rows.sort(key=lambda r:r[0])
    return (f'<div class="gdboard"><div class="gdh"><span class="live"></span><b>{E(title)}</b><small>Countdown, live score and final for every game we picked. Scores from Polymarket, updated every minute.</small></div>'
            f'<div class="gdl">{"".join(r for _,r in rows)}</div></div>')
def share(p):
    """Share button: X intent link (static fallback); live.js swaps in live P/L and uses the native share sheet on mobile."""
    k=p['kind']; what=f"{p['action']} {p['label']}"+(f" ({p['market']})" if k=='Sports' else f" ({p['horizon']})")
    txt=f"{what} at {money(k,p['entry'])}, a call from The Daily Five"
    u=f"{SITE}/picks/{p['id']}/"
    href='https://x.com/intent/post?'+urllib.parse.urlencode({'text':txt,'url':u,'via':'ReadDailyFive'})
    return f'<a class="shr" href="{E(href)}" target="_blank" rel="noopener" data-share-id="{p["id"]}" data-share-what="{E(what)}" data-share-url="{E(u)}" aria-label="Share {E(what)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.8 7.8L23 22h-6.2l-4.8-6.3L6.4 22H3.3l7.3-8.3L1 2h6.3l4.4 5.8zm-1.1 18h1.7L6.3 3.9H4.5z"/></svg>Share</a>'
def fin_card(p,rank):
    a=p['action'].lower()
    return f"""<article class="card fc {a}"><div class="ctop">{f'<span class="rank">#{rank}</span>' if rank else ''}<span class="hz">⏱ {E(p['horizon'])}</span>{badge(p)}</div>
<div class="crow"><span class="act {a}">{p['action']}</span><a class="tk" href="{BASE}/ticker/{p['tslug']}/">{E(p['label'])}</a>{spark(p.get('pts'),110,32)}</div>{livebox(p)}{breakdown(p)}
<p class="why"><b>Why {p['action']}:</b> {E(p['why'])}</p><p class="risk">⚠ {E(p['risk'])}</p><div class="cfoot"><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a><span class="cfr">{share(p)}<a class="more" href="{BASE}/picks/{p['id']}/">Details →</a></span></div></article>"""
def sp_card(p,rank):
    m=p.get('m'); bars=''
    if m:
        bars='<div class="match">'+''.join(f'<div class="team {"pick" if i==p["outcome"] else ""}"><span class="tn">{E(o)}</span><span class="tp" {"data-k=pp" if i==p["outcome"] else ""}>{pr*100:.0f}%</span></div>' for i,(o,pr) in enumerate(zip(m['outcomes'],m['prices'])))+'</div>'
        if len(m['prices'])==2: bars+=f'<div class="pbar" role="img" aria-label="{E(m["outcomes"][0])} {m["prices"][0]*100:.0f}%, {E(m["outcomes"][1])} {m["prices"][1]*100:.0f}%"><span style="width:{m["prices"][0]*100:.1f}%"></span></div>'
    ko=kickoff(p)
    when=('Tonight' if ko and ko.hour>=17 else 'Today') if p.get('event_date')==TODAY.isoformat() else ('Event '+datetime.date.fromisoformat(p['event_date']).strftime('%b %-d') if p.get('event_date') else 'Futures')
    vol=f'<span class="vol">${m["volume"]/1e6:.1f}M vol</span>' if m and m['volume']>=1e5 else ''
    return f"""<article class="card sc"><div class="ctop">{f'<span class="rank">#{rank}</span>' if rank else ''}<span class="hz">🏟 {E(when)}</span>{badge(p)}</div>
<a class="mkt" href="{BASE}/ticker/{p['tslug']}/">{E(p['market'])}</a>{bars}{gd(p)}
<div class="crow"><span class="act buy">BUY</span><span class="tk sm">{E(p['label'])}</span>{vol}{spark(p.get('pts'),100,30)}</div>{livebox(p)}{breakdown(p)}
<p class="why"><b>Why BUY:</b> {E(p['why'])}</p><div class="cfoot"><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a><span class="cfr">{share(p)}<a class="more" href="{BASE}/picks/{p['id']}/">Details →</a></span></div></article>"""
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
    if not prev: return '<div class="recap"><div><span class="kicker">📬 Yesterday\'s results</span><p>This is our first edition, so results start tomorrow. Every pick is tracked on the <a href="'+BASE+'/track-record/">Track record</a>.</p></div><div class="tmr">⏰ Come back tomorrow at <b>7 AM ET</b> for the next five.<span class="tmc">Next edition in <b class="nxc">a few hours</b></span></div></div>'
    ps=prev['finance']+prev['sports']; rs=[p['ret'] for p in ps if p.get('ret') is not None]
    items=''.join(f'<a href="{BASE}/picks/{p["id"]}/" class="rc"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} {chip(p.get("ret"),p.get("final"))}</a>' for p in ps)
    summ=f'{sum(r>0 for r in rs)}/{len(rs)} winning · avg {pct(sum(rs)/len(rs)) if rs else "—"}'
    return f'<div class="recap"><div><span class="kicker">📬 Yesterday\'s results ({prev["date"]})</span><p><b>{summ}</b></p><div class="rcs">{items}</div></div><div class="tmr">⏰ Come back tomorrow at <b>7 AM ET</b> for the next five.<span class="tmc">Next edition in <b class="nxc">a few hours</b></span></div></div>'
def today_strip(ps,where='home',settled=None):
    """'Today so far' running P/L strip for open picks. live.js recomputes it every minute."""
    op=[p for p in ps if not p.get('final')]; rs=[p for p in op if p.get('ret') is not None]
    up=sum(p['ret']>0 for p in rs); dn=sum(p['ret']<0 for p in rs); avg=sum(p['ret'] for p in rs)/len(rs) if rs else None
    so=[p['so'] for p in op if p.get('so') is not None]; aso=sum(so)/len(so) if so else None
    best=max(rs,key=lambda p:p['ret']) if rs else None; worst=min(rs,key=lambda p:p['ret']) if rs else None
    ids=json.dumps({p['id']:p['label'] for p in op})
    lab=lambda p: f'{E(p["label"])} {chip(p["ret"])}' if p else '—'
    st=[p for p in (settled or []) if p.get('final') and p.get('ret') is not None]
    sett=(f'<span class="tsc set"><small>settled</small> '+' '.join(f'<a href="{BASE}/picks/{p["id"]}/">{E(p["label"])} {chip(p["ret"],True)}</a>' for p in st)+'</span>') if st else ''
    return (f'<div class="tsf {where}" id="tsf" data-picks="{E(ids)}" aria-live="polite"><span class="tsl"><span class="live"></span><span data-t="lbl">Today so far</span></span>'
            f'<span class="tsc"><b class="up" data-t="up">▲ {up}</b> up <b class="dn" data-t="dn">▼ {dn}</b> down <small>of {len(op)} open</small></span>'
            f'<span class="tsc"><small>avg since pick</small> <span data-t="avg">{mv(avg)}</span></span>'
            f'<span class="tsc"><small>avg today</small> <span data-t="so">{mv(aso)}</span></span>'
            f'<span class="tsc"><small>best</small> <span data-t="best">{lab(best)}</span></span>'
            f'<span class="tsc"><small>worst</small> <span data-t="worst">{lab(worst)}</span></span>{sett}'
            f'<span class="tsc nx"><small>next edition</small> <b class="nxc">7 AM ET</b></span><span class="tsc mk" data-t="mk" hidden></span></div>')
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
    return recap(prev)+f"""<p class="stamp"><span class="live"></span>Live prices · last updated <b id="upd">{upd}</b> · <span class="dl">delayed: stocks via Yahoo Finance (may lag up to ~15 min), sports via Polymarket</span></p>{today_strip(ed["finance"]+ed["sports"],"home",ed["finance"]+ed["sports"])}<p class="disc-bar">⚠️ <b>Not financial or betting advice.</b> Entry prices are real snapshots at publish time; P/L updates with each rebuild.</p>
<section class="sec fin" id="finance"><div class="sh"><span class="si">💰</span><div><h2>Money moves</h2><p class="sub">The best ideas from AI agents, analysts and public sources, by horizon.</p></div></div>{bd}{fin}</section>
<section class="sec ai" id="ai"><div class="sh"><span class="si">🤖</span><div><h2>AI that matters</h2><p class="sub">The five stories most likely to shape what's next.</p></div></div><div class="newsgrid">{ai}</div></section>
<section class="sec sp" id="sports"><div class="sh"><span class="si">🏟</span><div><h2>Sports market plays</h2><p class="sub">Live Polymarket odds: big moves, big volume, and lines that look off. <a href="{BASE}/polymarket-picks-today/">Every Polymarket pick, graded →</a> · <a href="{BASE}/nfl-picks-this-week/">NFL picks this week →</a></p></div></div>{gd_board(ed["sports"])}<div class="grid g3">{sp}</div></section>"""
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
FAQS=[
 ("What is the Daily Five Score?","Every finance and sports pick gets a 0–100 score from four components worth 25 points each: source credibility, consensus, edge vs fair value, and risk/reward. The Top 5 in each section are ordered by it. We only use real data; when a component can't be computed, it gets a neutral 12.5 and we say so on the card."),
 ("How does source credibility work?","Credibility is the source's historical hit rate on our own track record: closed picks from that source that made money. Until a source has at least 5 closed picks it gets a neutral 12.5, labeled new source."),
 ("What is consensus in the score?","Consensus measures how many independent, credible sources we found agreeing with the call versus dissenting. The formula is 12.5 + 12.5 × (agree − dissent)/(agree + dissent), scaled down when there are fewer than four sources. With no sources checked, it stays a neutral 12.5."),
 ("How is edge vs fair value calculated?","For stocks, edge is the % gap between the live price and the consensus analyst mean price target (Yahoo Finance), signed for BUY or SELL: 12.5 + 50 × gap. Peer valuation isn't computed yet. For sports and markets, it's the sportsbook's no-vig implied probability minus the Polymarket price, in points: 12.5 + 1.25 × points."),
 ("How often do prices and scores update?","Scores recompute every time live prices refresh. Stock quotes come from Yahoo Finance (may lag up to ~15 minutes). Sports-market odds come from Polymarket. The site rebuilds on a schedule during market hours and less often off-hours; the live strip marks prices stale when the rebuild is behind."),
 ("Is The Daily Five financial or betting advice?","No. A high score isn't a guarantee. The Daily Five Score and every pick are for information and education only — not financial, investment, or betting advice."),
]
HOWTO=("<section class='sbhero'><span class='kicker'>🧮 Methodology</span><h1 class='pt'>How we rank: the Daily Five Score</h1><p class='sub'>Every finance and sports pick gets a 0–100 score from four components worth 25 points each. The Top 5 in each section are ordered by it. We only use real data; when a component can't be computed, it gets a neutral 12.5 and we say so on the card.</p></section>"
 "<div class='how'><div class='hw'><h2>1 · Source credibility (0–25)</h2><p>The source's historical hit rate on our own <a href='/track-record/'>track record</a>: closed picks from that source that made money. Until a source has at least 5 closed picks it gets a neutral 12.5, labeled <b>new source</b>.</p></div>"
 "<div class='hw'><h2>2 · Consensus (0–25)</h2><p>How many independent, credible sources we found agreeing with the call versus dissenting. 12.5 + 12.5 × (agree − dissent)/(agree + dissent), scaled down when there are fewer than four sources. With no sources checked, it's a neutral 12.5.</p></div>"
 "<div class='hw'><h2>3 · Edge vs fair value (0–25)</h2><p><b>Stocks:</b> % gap between the live price and the consensus analyst mean price target (Yahoo Finance), signed for BUY or SELL: 12.5 + 50 × gap. Peer valuation isn't computed yet. <b>Sports and markets:</b> the sportsbook's no-vig implied probability minus the Polymarket price, in points: 12.5 + 1.25 × points.</p></div>"
 "<div class='hw'><h2>4 · Risk/reward (0–25)</h2><p><b>Stocks:</b> the horizon-scaled share of the target gap divided by the horizon's volatility (60-day daily volatility × √trading days): 12.5 + 12.5 × tanh(ratio). <b>Markets:</b> expected value per $1 at the fair probability: 12.5 + 12.5 × tanh(5 × EV).</p></div></div>"
 "<p class='sub'>Scores recompute every time live prices refresh. A high score isn't a guarantee. Not financial or betting advice.</p>"
 "<h2 class='h2s'>FAQ</h2><div class='faq'>"+''.join(f"<details class='fq'><summary>{E(q)}</summary><p>{E(a)}</p></details>" for q,a in FAQS)+"</div>")

def ogimage(ed,nice):
    fin=ed['finance'][:4]
    rowsvg=''.join(f'<g transform="translate(70,{330+i*62})"><rect width="128" height="48" rx="24" fill="{"#16c784" if p["action"]=="BUY" else "#ff4d5e"}"/><text x="64" y="33" text-anchor="middle" font-size="24" font-weight="800" fill="#06130c">{p["action"]}</text><text x="150" y="36" font-family="monospace" font-size="38" font-weight="700" fill="#fff">{E(p["label"])}</text><text x="380" y="36" font-family="monospace" font-size="30" fill="#9ba3ba">${p["entry"]:,.2f}</text><text x="640" y="36" font-size="24" fill="#c9cede">{E(p["horizon"])}</text></g>' for i,p in enumerate(fin))
    import textwrap
    hl=''.join(f'<text x="70" y="{240+i*40}" font-size="32" font-weight="700" fill="#fff">{E(l)}</text>' for i,l in enumerate(textwrap.wrap(ed['headline'],58)[:2]))
    logo=LOGO.replace('class="mark" ','').replace(' width="34" height="34"','').replace('<svg ','<svg width="40" height="40" ')
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><defs><radialGradient id="a" cx=".15" cy=".1" r=".7"><stop offset="0" stop-color="#16c784" stop-opacity=".45"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient><radialGradient id="b" cx=".9" cy=".2" r=".7"><stop offset="0" stop-color="#7c5cff" stop-opacity=".55"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient></defs>'
         f'<rect width="1200" height="630" fill="#07080d"/><rect width="1200" height="630" fill="url(#a)"/><rect width="1200" height="630" fill="url(#b)"/><g font-family="Inter,Helvetica,Arial,sans-serif">'
         f'<g transform="translate(70,60) scale(1.6)">{logo}</g><text x="160" y="112" font-size="44" font-weight="800" fill="#fff">The Daily Five</text>'
         f'<text x="70" y="200" font-size="26" font-weight="700" fill="#ffb020" letter-spacing="3">{E(nice.upper())}</text>{hl}{rowsvg}'
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
            picks[p['id']]={'cur':p.get('cur'),'open':p.get('open'),'so':p.get('so'),'ret':p.get('ret'),'final':p.get('final'),'kind':p['kind'],'qt':p.get('qt'),'label':p['label']}
    w('data/live.json',json.dumps({'updated':NOW.astimezone().isoformat(timespec='seconds'),'ts':int(NOW.timestamp()),'updated_et':NOW.strftime('%-I:%M %p ET'),'picks':picks}))
def _render_png(svgp,pngp):
    chrome=shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    if not chrome: return False
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as ud:
        try: subprocess.run([chrome,'--headless=new','--no-sandbox','--hide-scrollbars','--disable-gpu',f'--user-data-dir={ud}','--window-size=1200,630',f'--screenshot={pngp}','file://'+svgp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        except Exception: return False
    return os.path.exists(pngp)
PICK_OG_JOBS=[]
def pick_og(p,ed):
    """Per-pick share card (1200x630) with the live-at-build P/L, so shared pick links unfurl as a scorecard.
    Only for recent/open picks (keeps build time flat); others fall back to the edition image."""
    age=(TODAY-datetime.date.fromisoformat(ed['date'])).days
    if age>7 and p.get('final'): return None
    k=p['kind']; r=p.get('ret'); fin=p.get('final')
    col='#16c784' if (r or 0)>0 else '#ff4d5e' if (r or 0)<0 else '#9ba3ba'
    big=pct(r) if r is not None else 'Pending'
    act=p['action']; acol='#16c784' if act=='BUY' else '#ff4d5e'
    import textwrap
    lab=p['label'] if k=='Finance' else p['label']
    sub=p['horizon']+' pick' if k=='Finance' else p['market']
    subl=textwrap.wrap(sub,52)[:2]
    stat='FINAL' if fin else 'LIVE'
    when=NOW.strftime('%b %-d, %-I:%M %p ET')
    status_txt=('Final result' if fin else f'Marked {when}')
    logo=LOGO.replace('class="mark" ','').replace(' width="34" height="34"','').replace('<svg ','<svg width="40" height="40" ')
    lsz=88 if len(lab)<=8 else 64 if len(lab)<=14 else 48
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><defs><radialGradient id="a" cx=".12" cy=".1" r=".75"><stop offset="0" stop-color="{acol}" stop-opacity=".40"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient><radialGradient id="b" cx=".92" cy=".85" r=".7"><stop offset="0" stop-color="#7c5cff" stop-opacity=".5"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient></defs>'
         f'<rect width="1200" height="630" fill="#07080d"/><rect width="1200" height="630" fill="url(#a)"/><rect width="1200" height="630" fill="url(#b)"/><g font-family="Inter,Helvetica,Arial,sans-serif">'
         f'<g transform="translate(70,56) scale(1.4)">{logo}</g><text x="146" y="101" font-size="38" font-weight="800" fill="#fff">The Daily Five</text>'
         f'<text x="1130" y="101" text-anchor="end" font-size="24" font-weight="700" fill="#ffb020" letter-spacing="3">CALLED {E(datetime.date.fromisoformat(ed["date"]).strftime("%b %-d").upper())}</text>'
         f'<rect x="70" y="160" width="150" height="58" rx="29" fill="{acol}"/><text x="145" y="199" text-anchor="middle" font-size="30" font-weight="800" fill="#06130c">{act}</text>'
         f'<text x="244" y="{205 if lsz>=64 else 202}" font-family="monospace" font-size="{lsz}" font-weight="700" fill="#fff">{E(lab)}</text>'
         +''.join(f'<text x="70" y="{268+i*36}" font-size="28" fill="#c9cede">{E(l)}</text>' for i,l in enumerate(subl))+
         f'<text x="70" y="{455}" font-size="150" font-weight="800" fill="{col}" font-family="Space Grotesk,Inter,Helvetica,Arial,sans-serif">{E(big)}</text>'
         f'<text x="70" y="510" font-size="28" fill="#9ba3ba">since the call · entry {E(money(k,p["entry"]))} → {"exit" if fin else "now"} {E(money(k,p.get("cur")))}</text>'
         f'<rect x="900" y="340" width="230" height="64" rx="16" fill="#11131c" stroke="{col}" stroke-width="3"/><text x="1015" y="383" text-anchor="middle" font-size="28" font-weight="800" fill="{col}" letter-spacing="4">{stat}</text>'
         f'<text x="1015" y="440" text-anchor="middle" font-size="22" fill="#9ba3ba">Score {int(round(p.get("score") or 0))}/100</text>'
         f'<text x="70" y="590" font-size="22" fill="#9ba3ba">{E(status_txt)}</text><text x="1130" y="590" text-anchor="end" font-size="22" fill="#9ba3ba">readdailyfive.com · Not advice</text></g></svg>')
    rel=f"og/picks/{p['id']}"; w(rel+'.svg',svg)
    PICK_OG_JOBS.append((os.path.join(OUT,rel+'.svg'),os.path.join(OUT,rel+'.png')))
    v=f"{(r or 0)*10000:.0f}{'f' if fin else ''}"
    return f"/{rel}.png?v={v}"
def render_pick_ogs():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex: ok=list(ex.map(lambda j:_render_png(*j),PICK_OG_JOBS))
    print(f"pick share cards: {sum(ok)}/{len(ok)} rendered")
_SUFX=re.compile(r'(,?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|Co\.|Company|Holdings)|,\s*Series \d+|\s+ETF)$')
def cname(sym):
    """Company / fund name for SEO titles (Yahoo chart meta), suffixes stripped: 'Netflix, Inc.' -> 'Netflix'."""
    def f():
        m=get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d")['chart']['result'][0]['meta']
        n=(m.get('longName') or m.get('shortName') or '').strip()
        for _ in range(3): n=_SUFX.sub('',n).strip()
        return n if n and n.upper()!=sym.upper() else None
    return memo(('nm',sym),f)
def pick_seo(p,ed):
    """Search-intent title/H1 for a pick page: '<Company> (<SYM>) Stock Prediction ...' or '<Away> vs. <Home> Prediction & Pick ...'.
    Returns (seo_headline, title_suffix, description, schema 'about')."""
    k=p['kind']; dd=datetime.date.fromisoformat(ed['date']).strftime('%b %-d, %Y')
    if k=='Finance':
        sym=p['symbol'].upper(); nm=cname(sym); who=f"{nm} ({sym})" if nm else sym
        hz={'1 Day':'1-Day','1 Month':'1-Month','1 Year':'1-Year'}.get(p['horizon'],p['horizon'])
        h=f"{who} Stock Prediction: {p['action']}, {hz} Call"
        d=f"{who} {hz} stock pick from {dd}: {p['action']} at {money(k,p['entry'])}. Why: {p['why']}"
        ab={"@type":"Corporation","name":nm or sym,"tickerSymbol":sym}
        return h,dd,d,ab
    g=pgame(p.get('slug')); ko=kickoff(p); pre=p['market'].split(':')[0].strip(); sp=(p.get('slug') or '').split('-')[0]
    if g and len(g['teams'])==2 and ko:
        aw,hm=g['teams']; an,hn=aw['al'] or aw['nm'],hm['al'] or hm['nm']
        lg=(sp.upper()+' ') if sp in ('nfl','nba','nhl','wnba') and not pre.upper().startswith(sp.upper()) else ''
        h=f"{an} vs. {hn} Prediction & Pick: {p['label']} to Win"
        when=ko.strftime('%b %-d, %Y')
        d=f"Our {aw['nm']} vs. {hm['nm']} pick ({lg}{pre}, {ko.strftime('%a %b %-d, %-I:%M %p ET')}): {p['label']} at {money(k,p['entry'])} on Polymarket. Why: {p['why']}"
        sport={'nfl':'American football','cfb':'American football','mlb':'Baseball','nba':'Basketball','wnba':'Basketball','cbb':'Basketball','nhl':'Ice hockey'}.get(sp,'Sports')
        ab={"@type":"SportsEvent","name":f"{aw['nm']} vs. {hm['nm']}","startDate":ko.isoformat(),"sport":sport,
            "awayTeam":{"@type":"SportsTeam","name":aw['nm']},"homeTeam":{"@type":"SportsTeam","name":hm['nm']},"url":f"{SITE}/picks/{p['id']}/"}
        return h,f"{lg}{pre}, {when}",d,ab
    h=f"{p['market']}? Odds & Prediction: {p['action']} {p['label']}"
    d=f"{p['market']} odds and our pick from {dd}: {p['action']} {p['label']} at {money(k,p['entry'])} on Polymarket. Why: {p['why']}"
    return h,dd,d,{"@type":"Thing","name":p['tname']}
def move_chart(p,ed,h):
    """'Since our pick' line-movement chart + factual summary + FAQ entries for a pick page (real Yahoo / Polymarket CLOB history only)."""
    k=p['kind']; d0=datetime.date.fromisoformat(ed['date']); dd=d0.strftime('%b %-d')
    t0=datetime.datetime.combine(d0,datetime.time(7,0)).timestamp()
    pts=[(t,v) for t,v in (p.get('pts') or []) if t>=t0 and v is not None]
    ent,cur=p['entry'],p.get('cur'); fmt=lambda v: money(k,v)
    if k=='Sports': fmt=lambda v: f"{v*100:.1f}\u00a2".replace('.0\u00a2','\u00a2')
    if cur is not None and (not pts or pts[-1][1]!=cur): pts=pts+[(max(int(NOW.timestamp()),(pts[-1][0]+1) if pts else 0),cur)]
    nm=p['label']
    if k=='Sports':
        if p.get('final') and cur is not None:
            res='won' if cur>=0.5 else 'lost'
            txt=f"When we published on {dd}, Polymarket priced {nm} at {fmt(ent)}, a {ent*100:.1f}% implied chance. Our {nm} pick {res}, settling at {fmt(cur)} ({pct(p.get('ret'))} on the entry price){' on the final score, pending official resolution' if str(p.get('note','')).startswith('final score') else ''}."
        elif cur is not None:
            mv=(cur-ent)*100; dirn=(f'up {abs(mv):.1f}\u00a2' if mv>0 else f'down {abs(mv):.1f}\u00a2' if mv<0 else 'unchanged')
            txt=f"When we published on {dd}, Polymarket priced {nm} at {fmt(ent)}, a {ent*100:.1f}% implied chance. It's now {fmt(cur)} ({cur*100:.1f}%), {dirn} since the pick."
        else: txt=f"When we published on {dd}, Polymarket priced {nm} at {fmt(ent)}, a {ent*100:.1f}% implied chance."
    else:
        sym=p['symbol'].upper()
        if cur is not None:
            txt=f"{sym} was {fmt(ent)} when we published the {p['action']} call on {dd}. It's {'closed at' if p.get('final') else 'now'} {fmt(cur)}, {pct(p.get('ret'))} for the {p['action']} side."
        else: txt=f"{sym} was {fmt(ent)} when we published the {p['action']} call on {dd}."
    ys=[v for _,v in pts]
    if len(ys)>=2:
        lo,hi=min(ys+[ent]),max(ys+[ent]); txt+=f" Range since the pick: {fmt(min(ys))} to {fmt(max(ys))}."
    faq=[]
    g=pgame(p.get('slug')) if k=='Sports' else None
    if k=='Sports' and g and len(g['teams'])==2:
        aw,hm=g['teams']; an,hn=aw['al'] or aw['nm'],hm['al'] or hm['nm']
        faq.append((f"Who will win {an} vs. {hn}?",f"The Daily Five's pick is {nm} to win, bought at {fmt(ent)} on Polymarket on {dd}. Why: {p['why']}"))
        faq.append((f"What are the {an} vs. {hn} odds now?",txt))
    elif k=='Sports':
        faq.append((f"{p['market']}?",f"The Daily Five's pick is {p['action']} {nm} at {fmt(ent)} on Polymarket ({dd}). Why: {p['why']}"))
        faq.append((f"How has the {nm} pick moved?",txt))
    else:
        nmc=cname(sym) or sym
        faq.append((f"Is {nmc} ({sym}) stock a {p['action'].lower()}?",f"The Daily Five's {p['horizon']} call from {dd} is {p['action']} {sym} at {fmt(ent)}. Why: {p['why']} Not financial advice."))
        faq.append((f"How has the {sym} {p['action']} call done?",txt))
    svg=''
    if len(ys)>=2:
        W,H,L,R,T,B=520,220,6,112,16,28; ts=[t for t,_ in pts]; x0,x1=ts[0],ts[-1]; span=(x1-x0) or 1; rng=(hi-lo) or (abs(hi)*.02 or .01)
        X=lambda t: L+(t-x0)/span*(W-L-R); Y=lambda v: T+(hi-v)/rng*(H-T-B)
        good=(p.get('ret') or 0)>=0; col='#16c784' if good else '#ff4d5e'
        line=' '.join(f"{X(t):.1f},{Y(v):.1f}" for t,v in pts)
        area=f"{X(x0):.1f},{H-B} "+line+f" {X(x1):.1f},{H-B}"
        ticks=''
        for i in range(4):
            tt=x0+span*i/3; lab=datetime.datetime.fromtimestamp(tt).strftime('%a %-I %p' if span<6*86400 else '%b %-d')
            ticks+=f'<text x="{X(tt):.0f}" y="{H-8}" text-anchor="{"start" if i==0 else "end" if i==3 else "middle"}">{lab}</text>'
        svg=(f'<svg class="mvchart" viewBox="0 0 {W} {H}" role="img" aria-label="{E(nm)} price since the pick: {E(fmt(ent))} entry, {E(fmt(cur))} now">'
             f'<defs><linearGradient id="mvg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{col}" stop-opacity=".35"/><stop offset="1" stop-color="{col}" stop-opacity="0"/></linearGradient></defs>'
             f'<polygon points="{area}" fill="url(#mvg)"/>'
             f'<line x1="{L}" x2="{W-R}" y1="{Y(ent):.1f}" y2="{Y(ent):.1f}" class="mvent"/><text x="{W-R+6}" y="{Y(ent)+4:.1f}" class="mvlab">entry {E(fmt(ent))}</text>'
             f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
             f'<circle cx="{X(x1):.1f}" cy="{Y(ys[-1]):.1f}" r="4.5" fill="{col}"/><text x="{W-R+6}" y="{min(max(Y(ys[-1])+4,T+8),H-B):.1f}" class="mvlab now" fill="{col}">{"final" if p.get("final") else "now"} {E(fmt(ys[-1]))}</text>'
             f'{ticks}</svg>')
    src='Polymarket CLOB price history' if k=='Sports' else 'Yahoo Finance prices'
    html_=(f'<section class="mvbox"><h2>Since our pick</h2><p class="mvtxt">{E(txt)}</p>{svg}'
           f'<p class="mvsrc">Source: {src}, updated {NOW.strftime("%b %-d, %-I:%M %p")} ET.</p>'
           f'<div class="mvfaq">'+''.join(f'<details><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faq)+'</div></section>')
    return html_,faq
def hub_of(p):
    """(name, path) of the hub page a pick belongs to, for breadcrumbs."""
    if p['kind']=='Finance': return ('Stock picks','/best-stocks-to-buy-today/')
    if (p.get('slug') or '').startswith('nfl-'): return ('NFL picks','/nfl-picks-this-week/')
    return ('Polymarket picks','/polymarket-picks-today/')
def crumbs(trail):
    """trail: [(name, path)], last item is the current page. Returns (visible nav html, BreadcrumbList schema)."""
    nav='<nav class="crumbs" aria-label="Breadcrumb"><ol>'+''.join((f'<li><a href="{BASE}{u}">{E(n)}</a></li>' if i<len(trail)-1 else f'<li aria-current="page">{E(n)}</li>') for i,(n,u) in enumerate(trail))+'</ol></nav>'
    sch={"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":i+1,"name":n,"item":SITE+u} for i,(n,u) in enumerate(trail)]}
    return nav,sch
def lastmod(p,ed):
    """Honest sitemap lastmod for a pick page: today while it is still marked to live prices, else the day it settled."""
    if not p.get('final'): return TODAY.isoformat()
    m=re.search(r'\d{4}-\d{2}-\d{2}',p.get('note') or '')
    if m: d=m.group(0)
    elif p.get('pts'): d=datetime.datetime.fromtimestamp(p['pts'][-1][0]).date().isoformat()
    elif kickoff(p): d=kickoff(p).date().isoformat()
    else: d=ed['date']
    return min(max(d,ed['date']),TODAY.isoformat())
def related(p,ed,allp):
    """Internal links for a pick page: other picks from the same kickoff window (sports, within 45 min) or else the same edition, max 4."""
    ko=kickoff(p); hub=hub_of(p)[1]; dot=' \u00b7 '
    win=[(q,e) for q,e in allp if q is not p and ko and kickoff(q) and abs((kickoff(q)-ko).total_seconds())<=2700]
    if len(win)>=2:
        win.sort(key=lambda x:(kickoff(x[0]),-x[0].get('score',0))); out=win[:4]
        head=f"More {ko.strftime('%a %-I:%M %p').replace(':00','')} ET kickoff picks"
    else:
        fill=[(q,e) for q,e in allp if e is ed and q is not p and all(q is not w_ for w_,_ in win)]
        fill.sort(key=lambda x:(hub_of(x[0])[1]!=hub,-x[0].get('score',0))); out=(win+fill)[:4]
        head=f"More picks from the {ed['date']} edition" if not win else "Related picks"
    if not out: return ''
    def row(q,e):
        mk=(dot+E((q['market'].split(':',1)[1] if ':' in q['market'] else q['market']).split(',')[0].strip())) if q['kind']=='Sports' else ''
        return f'<a class="rc" href="{BASE}/picks/{q["id"]}/"><b class="{q["action"].lower()}">{q["action"]}</b> {E(q["label"])}{mk}{dot}{e["date"]} {chip(q.get("ret"),q.get("final"))}</a>'
    return f'<section class="relbox"><h2 class="h2s">{E(head)}</h2><div class="rcs col">{"".join(row(q,e) for q,e in out)}</div><p class="relmore"><a href="{BASE}/picks/">All picks by day \u2192</a></p></section>'
def pick_page(p,ed,allp=()):
    k=p['kind']; t=f"{p['action']} {p['label']}"+(f" ({p['market']})" if k=='Sports' else f" \u00b7 {p['horizon']} pick")
    h,suf,desc,about=pick_seo(p,ed)
    title=f"{h} ({suf}) | {BRAND}"; desc=desc if len(desc)<=155 else desc[:154].rsplit(' ',1)[0]+'\u2026'
    card=fin_card(p,'') if k=='Finance' else sp_card(p,'')
    kick="\U0001F4B0 Finance pick" if k=="Finance" else "\U0001F3DF Sports market pick"
    note=(' \u00b7 '+E(p.get('entry_note'))) if p.get('entry_note') else ''
    mvh,faq=move_chart(p,ed,h)
    hn,hu=hub_of(p); cnav,csch=crumbs([('Home','/'),(hn,hu),(p['tname'],f"/ticker/{p['tslug']}/"),(f"{p['action']} {p['label']}",f"/picks/{p['id']}/")])
    det=(f'{cnav}<section class="sbhero"><span class="kicker">{kick} \u00b7 {ed["date"]}</span><h1 class="pt">{E(h)}</h1><p class="sub">{E(t)}{"" if k=="Sports" else " \u00b7 "+E(suf)}</p></section><div class="pickwrap">{card}<div class="pinfo">'
         f'<h2>Pick details</h2><dl><dt>Published</dt><dd>{ed["date"]} in <a href="{BASE}/{ed["date"]}/">that day\'s edition</a></dd><dt>Entry</dt><dd>{money(k,p["entry"])}{note}</dd>'
         f'<dt>Status</dt><dd>{"Final" if p.get("final") else "Open"} \u00b7 {E(p.get("note",""))}</dd><dt>Source</dt><dd><a href="{E(p["source"]["url"])}" rel="nofollow noopener" target="_blank">{E(p["source"]["name"])}</a></dd></dl>'
         f'<p><a href="{BASE}/ticker/{p["tslug"]}/">All picks on {E(p["tname"])} \u2192</a><br><a href="{BASE}/track-record/">Full track record \u2192</a></p></div></div>'+mvh+related(p,ed,allp))
    sch={"@context":"https://schema.org","@type":"Article","headline":h[:110],"datePublished":ed['date'],"description":desc,"author":{"@type":"Organization","name":BRAND},"publisher":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/picks/{p['id']}/","about":about}
    og=pick_og(p,ed)
    if og: sch['image']=SITE+og.split('?')[0]
    sch.pop('@context'); sch={"@context":"https://schema.org","@graph":[sch,csch]}
    if faq:
        sch['@graph'].append({"@type":"FAQPage","url":f"{SITE}/picks/{p['id']}/","mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faq]})
    w(f"picks/{p['id']}/index.html",shell(title,desc,f"/picks/{p['id']}/",det,sch,og=og))
def best_stocks_hub(eds):
    """Evergreen SEO hub: /best-stocks-to-buy-today/ from real BUY finance picks only."""
    buys=[]
    for ed in eds:
        for p in ed['finance']:
            if p['action']=='BUY': buys.append((p,ed))
    if not buys and not eds:
        bodyh=('<section class="sbhero"><span class="kicker">📈 Stocks</span><h1 class="pt">Best stocks to buy today</h1>'
               '<p class="sub">No BUY picks yet. Check back after the next 7 AM ET edition.</p></section>')
        w('best-stocks-to-buy-today/index.html',shell(
            f'Best Stocks to Buy Today | {BRAND}',
            'AI-ranked stock BUY ideas from The Daily Five, with Daily Five Scores and live performance since each pick.',
            '/best-stocks-to-buy-today/',bodyh,
            {"@context":"https://schema.org","@type":"CollectionPage","name":"Best Stocks to Buy Today","url":SITE+"/best-stocks-to-buy-today/"}))
        return '/best-stocks-to-buy-today/'
    latest=eds[0]['date'] if eds else TODAY.isoformat()
    today=[(p,ed) for p,ed in buys if ed['date']==latest]
    today.sort(key=lambda x:-x[0].get('score',0))
    # Track-record stats for all BUY finance picks
    with_ret=[p for p,_ in buys if p.get('ret') is not None]
    wins=sum(p['ret']>0 for p in with_ret); avg=(sum(p['ret'] for p in with_ret)/len(with_ret)) if with_ret else None
    open_n=sum(1 for p,_ in buys if not p.get('final'))
    closed_n=sum(1 for p,_ in buys if p.get('final'))
    def tile(name,val,sub):
        return f'<div class="tile"><span class="h">{name}</span><b class="{"up" if isinstance(val,str) and val.startswith("+") else ("dn" if isinstance(val,str) and val.startswith("-") else "")}">{val}</b><span class="s">{sub}</span></div>'
    wr=f'{wins/len(with_ret)*100:.0f}%' if with_ret else '—'
    tiles=(tile('BUY win rate',wr,f'{wins}/{len(with_ret)} graded')+
           tile('Avg since pick',pct(avg) if avg is not None else '—','all BUY finance picks')+
           tile("Today's BUYs",str(len(today)),f'edition {latest}')+
           tile('Open / closed',f'{open_n} / {closed_n}','still tracking'))
    # Today's cards
    if today:
        cards=''.join(fin_card(p,i+1) for i,(p,_) in enumerate(today))
        today_block=f'<h2 class="h2s">Today\'s BUY calls · {latest}</h2><p class="sub hub-lead">Ranked by <a href="{BASE}/how-we-rank/">Daily Five Score</a>. Entry prices are real quotes at publish; P/L marks to live Yahoo Finance data.</p><div class="grid">{cards}</div>'
    else:
        today_block=f'<h2 class="h2s">Today\'s BUY calls</h2><p class="sub">No BUY finance picks in the latest edition. See the <a href="{BASE}/">homepage</a> for SELLs and sports markets.</p>'
    # By horizon: 1 Day first (SEO intent), then 1 Month, 1 Year — show recent BUYs
    hz_blocks=''
    for h,ic in [('1 Day','⚡'),('1 Month','📅'),('1 Year','🌱')]:
        lst=[(p,ed) for p,ed in buys if p['horizon']==h]
        if not lst: continue
        # most recent date first; within a date, highest Daily Five Score first
        lst=sorted(lst,key=lambda x:(x[1]['date'],x[0].get('score',0)),reverse=True)
        rows=''.join(
            f'<a class="hubrow" href="{BASE}/picks/{p["id"]}/">'
            f'<span class="act buy">BUY</span>'
            f'<span class="hubtk">{E(p["label"])}</span>'
            f'<span class="hubhz">{E(h)}</span>'
            f'<span class="hubsc">{p.get("score","—")}</span>'
            f'<span class="hubent">{money("Finance",p["entry"])}</span>'
            f'{chip(p.get("ret"),p.get("final"))}'
            f'<span class="hubdt">{ed["date"]}</span></a>'
            for p,ed in lst[:12])
        hz_blocks+=f'<div class="hzblock"><h3 class="hzh">{ic} {h} BUY track record</h3><div class="hublist">{rows}</div></div>'
    # Past BUYs not in today (for "recent" section if we want extra)
    links=(f'<div class="hubcta"><a class="pill" href="{BASE}/how-we-rank/">How we rank →</a>'
           f'<a class="pill ghost" href="{BASE}/scoreboard/">Full scoreboard →</a>'
           f'<a class="pill ghost" href="{BASE}/track-record/">Track record →</a></div>')
    faqs=[
        ("How do you pick the best stocks to buy today?",
         "Every morning we pull public analyst notes, upgrades, and market ideas, then score each BUY with the Daily Five Score: source credibility, consensus, edge vs analyst targets, and risk/reward. The highest-scoring calls make the page."),
        ("Are these financial advice?",
         "No. Entry prices are real snapshots at publish time and P/L updates with live market data, but nothing here is financial, investment, or trading advice. You can lose money."),
        ("Where does performance come from?",
         "We mark every pick to Yahoo Finance from the published entry until the horizon ends (1 Day, 1 Month, or 1 Year). Wins, losses, and averages are public on the Scoreboard."),
    ]
    faq_html='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(
        f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
    nice=datetime.date.fromisoformat(latest).strftime('%A, %B %-d, %Y') if eds else ''
    bodyh=(f'<section class="sbhero hubhero"><span class="kicker">📈 Best stocks to buy</span>'
           f'<h1 class="pt">Best stocks to buy today</h1>'
           f'<p class="sub">AI-ranked BUY ideas from The Daily Five — with Daily Five Scores, real entry prices, and live performance since each pick. Updated {nice}.</p>'
           f'{links}</section>'
           f'<div class="tiles">{tiles}</div>'
           f'<p class="disc-bar">⚠️ <b>Not financial advice.</b> These are public ideas we score and track — not a recommendation to buy or sell. Past results don\'t guarantee future returns.</p>'
           f'{today_block}{hz_blocks}{faq_html}'
           f'<p class="sub hub-foot">Want SELLs, AI news, and sports markets too? See <a href="{BASE}/">today\'s full edition</a>.</p>')
    title=f'Best Stocks to Buy Today (Live Scores & Track Record) | {BRAND}'
    desc=(f'Today\'s best stocks to buy, ranked by the Daily Five Score: real entry prices, live Yahoo Finance performance, and a public BUY track record. Updated {latest}.')[:155]
    sch={"@context":"https://schema.org","@graph":[
        {"@type":"CollectionPage","name":"Best Stocks to Buy Today","description":desc,"url":SITE+"/best-stocks-to-buy-today/","isPartOf":{"@type":"WebSite","name":BRAND,"url":SITE+"/"}},
        {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]},
    ]}
    w('best-stocks-to-buy-today/index.html',shell(title,desc,'/best-stocks-to-buy-today/',bodyh,sch))
    return '/best-stocks-to-buy-today/'

def polymarket_hub(eds):
    """Evergreen SEO hub: /polymarket-picks-today/ from real sports prediction-market picks only."""
    P='/polymarket-picks-today/'
    allp=[(p,ed) for ed in eds for p in ed['sports']]
    latest=eds[0]['date'] if eds else TODAY.isoformat()
    today=sorted([(p,ed) for p,ed in allp if ed['date']==latest],key=lambda x:-x[0].get('score',0))
    graded=[p for p,_ in allp if p.get('ret') is not None]
    settled=[p for p,_ in allp if p.get('final') and p.get('ret') is not None]
    sw=sum(p['ret']>0 for p in settled); savg=sum(p['ret'] for p in settled)/len(settled) if settled else None
    oavg=(lambda o: sum(o)/len(o) if o else None)([p['ret'] for p in graded if not p.get('final')])
    def tile(name,val,sub):
        cls='up' if val.startswith('+') else ('dn' if val.startswith('-') else '')
        return f'<div class="tile"><span class="h">{name}</span><b class="{cls}">{val}</b><span class="s">{sub}</span></div>'
    tiles=(tile('Settled win rate',f'{sw/len(settled)*100:.0f}%' if settled else '\u2014',f'{sw}/{len(settled)} resolved markets')+
           tile('Avg settled return',pct(savg),'per $1 staked at entry')+
           tile('Open markets avg',pct(oavg),'marked to live Polymarket odds')+
           tile("Today's plays",str(len(today)),f'edition {latest}'))
    if today:
        cards=''.join(sp_card(p,i+1) for i,(p,_) in enumerate(today))
        tb=(f'<h2 class="h2s">Today\'s Polymarket plays \u00b7 {latest}</h2><p class="sub hub-lead">Ranked by <a href="{BASE}/how-we-rank/">Daily Five Score</a>. '
            f'Entry is the real Polymarket price at publish; odds and P/L update live from Polymarket.</p><div class="grid g3">{cards}</div>')
    else:
        tb=f'<h2 class="h2s">Today\'s Polymarket plays</h2><p class="sub">No sports markets in the latest edition. Check back after 7 AM ET.</p>'
    hist=sorted(allp,key=lambda x:(x[1]['date'],x[0].get('score',0)),reverse=True)
    res=lambda p: ('Won' if p['ret']>0 else 'Lost') if p.get('final') else 'Open'
    rows=''.join(f'<a class="hubrow" href="{BASE}/picks/{p["id"]}/"><span class="act buy">BUY</span><span class="hubtk">{E(p["label"])}</span>'
                 f'<span class="hubhz">{E(p["market"])}</span><span class="hubsc">{p.get("score","\u2014")}</span><span class="hubent">{money("Sports",p["entry"])}</span>'
                 f'{chip(p.get("ret"),p.get("final"))}<span class="hubdt">{res(p)} \u00b7 {ed["date"]}</span></a>' for p,ed in hist[:30])
    hb=f'<div class="hzblock"><h3 class="hzh">\U0001F3C6 Every Polymarket pick, graded</h3><div class="hublist">{rows}</div></div>' if rows else ''
    links=(f'<div class="hubcta"><a class="pill" href="{BASE}/#sports">Today\'s edition \u2192</a>'
           f'<a class="pill ghost" href="{BASE}/scoreboard/">Full scoreboard \u2192</a>'
           f'<a class="pill ghost" href="{BASE}/how-we-rank/">How we rank \u2192</a></div>')
    faqs=[
        ("What are today's best Polymarket sports picks?",
         "Each morning we scan Polymarket sports markets for big moves, heavy volume, and prices that look off versus sportsbook lines and public previews, then rank every BUY by the Daily Five Score. The top plays are listed above with live odds."),
        ("How is performance calculated?",
         "We record the real Polymarket price of the outcome we pick at publish time, then mark it to the live Polymarket price. When a market resolves, the pick settles at 100 cents (won) or 0 cents (lost), so returns are per $1 staked at the entry price."),
        ("Is this betting advice?",
         "No. These are public prediction-market ideas we score and track transparently. Nothing here is betting, financial, or investment advice, prediction markets may not be legal where you live, and you can lose your entire stake."),
    ]
    fq='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
    nice=datetime.date.fromisoformat(latest).strftime('%A, %B %-d, %Y')
    bodyh=(f'<section class="sbhero hubhero"><span class="kicker">\U0001F3DF Polymarket picks</span><h1 class="pt">Polymarket sports picks today</h1>'
           f'<p class="sub">AI-ranked prediction-market plays from The Daily Five, with live Polymarket odds, real entry prices, and every result graded in public. Updated {nice}.</p>{links}</section>'
           f'<div class="tiles">{tiles}</div>'
           f'<p class="disc-bar">\u26a0\ufe0f <b>Not betting advice.</b> Prices are real Polymarket snapshots; check local laws before trading prediction markets.</p>'
           f'{tb}{hb}{fq}<p class="sub hub-foot">Betting Sunday? See <a href="{BASE}/nfl-picks-this-week/">NFL picks this week</a>. Want stock picks too? See <a href="{BASE}/best-stocks-to-buy-today/">best stocks to buy today</a>.</p>')
    title=f'Polymarket Sports Picks Today (Live Odds & Results) | {BRAND}'
    desc=f'Today\'s best Polymarket sports picks, ranked by the Daily Five Score, with live odds, real entry prices, and a public win/loss record. Updated {latest}.'[:155]
    sch={"@context":"https://schema.org","@graph":[
        {"@type":"CollectionPage","name":"Polymarket Sports Picks Today","description":desc,"url":SITE+P,"isPartOf":{"@type":"WebSite","name":BRAND,"url":SITE+"/"}},
        {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]}]}
    w('polymarket-picks-today/index.html',shell(title,desc,P,bodyh,sch))
    return P

def kickoff(p):
    st=(p.get('m') or {}).get('start')
    if not st: return None
    try: return datetime.datetime.fromisoformat(st.replace(' ','T')).astimezone()
    except Exception: return None
def nfl_hub(eds):
    """Evergreen SEO hub: /nfl-picks-this-week/ from real NFL Polymarket picks only, grouped by kickoff."""
    P='/nfl-picks-this-week/'
    allp=[(p,ed) for ed in eds for p in ed['sports'] if p['slug'].startswith('nfl-')]
    seen=set(); slate=[]
    for p,ed in allp:  # eds are newest-first: keep the latest call on each game
        if p.get('final') or p['slug'] in seen: continue
        seen.add(p['slug']); slate.append((p,ed))
    far=datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
    slate.sort(key=lambda x:(kickoff(x[0]) or far, -x[0].get('score',0)))
    wk=next((m.group(1) for p,_ in slate for m in [re.search(r'Week (\d+)',p['market'])] if m),None)
    settled=[p for p,_ in allp if p.get('final') and p.get('ret') is not None]
    sw=sum(p['ret']>0 for p in settled); savg=sum(p['ret'] for p in settled)/len(settled) if settled else None
    oavg=(lambda o: sum(o)/len(o) if o else None)([p['ret'] for p,_ in slate if p.get('ret') is not None])
    _now=datetime.datetime.now().astimezone(); nk=next((k for k in (kickoff(p) for p,_ in slate) if k and k>_now),None); live_n=sum(1 for p,_ in slate if (kickoff(p) or far)<=_now)
    def tile(name,val,sub):
        cls='up' if val.startswith('+') else ('dn' if val.startswith('-') else '')
        return f'<div class="tile"><span class="h">{name}</span><b class="{cls}">{val}</b><span class="s">{sub}</span></div>'
    tiles=(tile('Games on the board',str(len(slate)),f'Week {wk}' if wk else 'open NFL plays')+
           tile('Next kickoff',nk.strftime('%a %-I:%M %p') if nk else ('Live' if live_n else '\u2014'),'ET' if nk else (f'{live_n} game(s) in progress' if live_n else 'none scheduled'))+
           tile('Open plays avg',pct(oavg),'marked to live Polymarket odds')+
           tile('NFL record',f'{sw}-{len(settled)-sw}' if settled else '0-0',f'avg settled {pct(savg)}' if settled else 'first games settle this week'))
    if slate:
        out=''; cur=None; rank=0
        for p,ed in slate:
            k=kickoff(p); g=k.strftime('%A, %b %-d \u00b7 %-I:%M %p ET') if k else 'Kickoff TBA'
            if g!=cur:
                if cur is not None: out+='</div>'
                out+=f'<h3 class="hzh">\U0001F3C8 {g}</h3><div class="grid g3">'; cur=g
            rank+=1; out+=sp_card(p,rank)
        out+='</div>'
        tb=(f'<h2 class="h2s">This week\'s NFL plays{f" \u00b7 Week {wk}" if wk else ""}</h2><p class="sub hub-lead">Grouped by kickoff (Eastern). '
            f'Entry is the real Polymarket price when we published; odds and P/L update live. Scored with the <a href="{BASE}/how-we-rank/">Daily Five Score</a>.</p>{out}')
    else:
        tb='<h2 class="h2s">This week\'s NFL plays</h2><p class="sub">No open NFL plays right now. New picks drop with the 7 AM ET edition.</p>'
    res=lambda p: ('Won' if p['ret']>0 else 'Lost') if p.get('final') else 'Open'
    rows=''.join(f'<a class="hubrow" href="{BASE}/picks/{p["id"]}/"><span class="act buy">BUY</span><span class="hubtk">{E(p["label"])}</span>'
                 f'<span class="hubhz">{E(p["market"])}</span><span class="hubsc">{p.get("score","\u2014")}</span><span class="hubent">{money("Sports",p["entry"])}</span>'
                 f'{chip(p.get("ret"),p.get("final"))}<span class="hubdt">{res(p)} \u00b7 {ed["date"]}</span></a>' for p,ed in allp[:40])
    hb=f'<div class="hzblock"><h3 class="hzh">\U0001F3C6 Every NFL pick, graded</h3><div class="hublist">{rows}</div></div>' if rows else ''
    links=(f'<div class="hubcta"><a class="pill" href="{BASE}/#sports">Today\'s edition \u2192</a>'
           f'<a class="pill ghost" href="{BASE}/polymarket-picks-today/">All Polymarket picks \u2192</a>'
           f'<a class="pill ghost" href="{BASE}/scoreboard/">Scoreboard \u2192</a>{nfl_results_links()}</div>')
    faqs=[
        ("What are the best NFL picks this week?",
         "We scan Polymarket's NFL game markets for big moves, heavy volume, and prices that look off versus sportsbook lines and public previews, then rank each BUY with the Daily Five Score. This week's plays are listed above by kickoff, with live odds."),
        ("Why use Polymarket odds instead of a point spread?",
         "A Polymarket price is the market's implied win probability: 55 cents means about a 55% chance. That makes every pick gradable to the cent, so our record is a real return per $1 staked, not a claimed win rate."),
        ("When do NFL picks settle?",
         "Each pick settles when its Polymarket game market resolves after the final whistle, at 100 cents if our side wins or 0 if it loses. Until then the P/L is marked to the live price."),
        ("Is this betting advice?",
         "No. These are public prediction-market ideas we score and track in the open. Nothing here is betting, financial, or investment advice; prediction markets may not be legal where you live, and you can lose your entire stake."),
    ]
    fq='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
    latest=eds[0]['date'] if eds else TODAY.isoformat(); nice=datetime.date.fromisoformat(latest).strftime('%A, %B %-d, %Y')
    wl=f' (Week {wk})' if wk else ''
    o=NFLWK[0] if NFLWK else None; lvx=(f" ({o['n_open']} still live)" if o and o['n_open'] else '')
    wkban=(f'<a class="wkban" href="{BASE}{o["url"]}"><span class="kicker">\U0001F3C1 Week {o["wk"]} results</span><b>We went {o["w"]}-{o["l"]} in NFL Week {o["wk"]}, {pct(o["avg"])} avg return{lvx}.</b><span>Every pick graded, with entry price, final score and return \u2192</span></a>') if o else ''
    bodyh=(f'<section class="sbhero hubhero"><span class="kicker">\U0001F3C8 NFL picks</span><h1 class="pt">NFL picks this week{wl}</h1>'
           f'<p class="sub">AI-ranked NFL plays from The Daily Five, priced on Polymarket, sorted by kickoff, and graded in public after every game. Updated {nice}.</p>{links}</section>'
           f'<div class="tiles">{tiles}</div>{wkban}'
           f'<p class="disc-bar">\u26a0\ufe0f <b>Not betting advice.</b> Prices are real Polymarket snapshots; check local laws before trading prediction markets.</p>'
           f'{gd_board([p for p,_ in slate],"NFL game day")}{tb}{hb}{fq}<p class="sub hub-foot">Trade stocks too? See <a href="{BASE}/best-stocks-to-buy-today/">best stocks to buy today</a>.</p>')
    title=f'NFL Picks This Week{wl}: Live Polymarket Odds & Results | {BRAND}'
    desc=(f'This week\'s NFL picks{wl}, ranked by the Daily Five Score, with live Polymarket odds, kickoff times, and a public win/loss record. Updated {latest}.')[:155]
    evs=[{"@type":"SportsEvent","name":(p.get('m') or {}).get('outcomes') and ' vs. '.join(p['m']['outcomes']) or p['market'],"startDate":kickoff(p).isoformat(),"sport":"American football","url":f"{SITE}/picks/{p['id']}/"} for p,_ in slate if kickoff(p)]
    sch={"@context":"https://schema.org","@graph":[
        {"@type":"CollectionPage","name":f"NFL Picks This Week{wl}","description":desc,"url":SITE+P,"isPartOf":{"@type":"WebSite","name":BRAND,"url":SITE+"/"}},
        {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]}]
        +([{"@type":"ItemList","name":"NFL games we picked","itemListElement":[{"@type":"ListItem","position":i+1,"item":e} for i,e in enumerate(evs)]}] if evs else [])}
    w('nfl-picks-this-week/index.html',shell(title,desc,P,bodyh,sch))
    return P

NFLWK=[]  # weekly NFL results pages, newest first: dicts with wk, url, w, l, n_open, avg (filled by nfl_results)
def _wk_start(d):
    """NFL weeks run Tuesday to Monday (TNF ... MNF): the Tuesday on or before d."""
    return d-datetime.timedelta(days=(d.weekday()-1)%7)
def _ko_or_date(p):
    k=kickoff(p)
    if k: return k
    if p.get('event_date'): return datetime.datetime.combine(datetime.date.fromisoformat(p['event_date']),datetime.time(13,0)).astimezone()
    return None
def _window(k):
    """Kickoff-window heading for a results page."""
    t=k.strftime('%-I:%M %p').replace(':00',''); dd=k.strftime('%b %-d')
    wd=k.weekday()
    if wd==3: return f"Thursday Night Football \u00b7 Thu {dd}, {t} ET"
    if wd==0: return f"Monday Night Football \u00b7 Mon {dd}, {t} ET"
    if wd==6 and k.hour<12: return f"International game \u00b7 Sun {dd}, {t} ET"
    if wd==6 and k.hour<16: return f"Sunday early window \u00b7 {dd}, {t} ET"
    if wd==6 and k.hour<19: return f"Sunday late window \u00b7 {dd}, {t} ET"
    if wd==6: return f"Sunday Night Football \u00b7 {dd}, {t} ET"
    return k.strftime('%A %b %-d, ')+t+' ET'
def nfl_weeks(eds):
    """Group NFL picks into weeks by kickoff (Tue..Mon) and fill NFLWK (newest first) with each week that has a settled pick.
    The week number comes from the 'Week N' in our market text, so a Week 7 game picked early never lands in Week 6."""
    groups={}
    for ed in eds:
        for p in ed['sports']:
            if not (p.get('slug') or '').startswith('nfl-'): continue
            k=_ko_or_date(p)
            if k: groups.setdefault(_wk_start(k.date()),[]).append((p,ed,k))
    NFLWK.clear()
    for ws,lst in sorted(groups.items(),reverse=True):
        wk=next((m.group(1) for p,_,_ in lst for m in [re.search(r'Week (\d+)',p['market'])] if m),None)
        st=[(p,ed,k) for p,ed,k in lst if p.get('final') and p.get('ret') is not None]
        if not wk or not st: continue
        lst.sort(key=lambda x:(x[2],x[1]['date']))
        w_=sum(p['ret']>0 for p,_,_ in st); avg=sum(p['ret'] for p,_,_ in st)/len(st)
        op=[(p,ed,k) for p,ed,k in lst if not p.get('final')]
        d1,d2=lst[0][2].date(),lst[-1][2].date()
        rng=(f"{d1.strftime('%b %-d')}\u2013{d2.strftime('%-d')}" if d1.month==d2.month else f"{d1.strftime('%b %-d')}\u2013{d2.strftime('%b %-d')}")+f", {d2.year}"
        NFLWK.append(dict(wk=wk,ws=ws,url=f'/nfl-results/week-{wk}/',w=w_,l=len(st)-w_,n_open=len(op),avg=avg,rng=rng,n=len(lst),lst=lst,st=st,op=op))
def nfl_results(eds):
    """Weekly NFL results recap pages (/nfl-results/week-N/) + an /nfl-results/ index, from real settled picks only.
    A week is every NFL pick whose game kicks off Tue..Mon; its number comes from the 'Week N' in our market text.
    A page appears once at least one game of that week has settled. Returns sitemap (url, lastmod) pairs."""
    urls=[]
    for o in NFLWK:
        wk,ws,lst,st,w_,l_,avg,op,P,rng=o['wk'],o['ws'],o['lst'],o['st'],o['w'],o['l'],o['avg'],o['op'],o['url'],o['rng']
        best=max(st,key=lambda x:x[0]['ret']); worst=min(st,key=lambda x:(x[0]['ret'],-x[0]['entry']))
        def score_of(p):
            g=pgame(p.get('slug'))
            if not g or len(g['teams'])!=2 or not re.fullmatch(r'\d+-\d+',g['score'] or ''): return None
            a,h=g['score'].split('-'); aw,hm=g['teams']; ps=pick_side(p,g,p.get('m') or {})
            B_=lambda t,sd: f'<b>{E(t)}</b>' if sd==ps else E(t)
            return f"{B_(aw['ab'],'a')} {a}\u2013{h} {B_(hm['ab'],'h')}", f"{aw['ab']} {a}, {hm['ab']} {h}"
        def mtch(p):
            mk=p['market'].split(':',1)[1] if ':' in p['market'] else p['market']
            return mk.split(',')[0].replace('(London)','').strip()
        def row(p,ed,k):
            fin=p.get('final'); cls='open' if not fin else ('won' if p['ret']>0 else 'lost'); res={'open':'LIVE','won':'WON','lost':'LOST'}[cls]
            sc=score_of(p) if fin else None
            sub=(f"{sc[0]} \u00b7 Final" if sc else f"{E(mtch(p))} \u00b7 Final") if fin else f"{E(mtch(p))} \u00b7 {k.strftime('%a %-I:%M %p ET')}"
            ext=money('Sports',p.get('cur'))
            return (f'<a class="wkrow {cls}" href="{BASE}/picks/{p["id"]}/"><span class="wkres">{res}</span>'
                    f'<span class="wkpk"><b>{E(p["label"])}</b><small>{sub}</small></span>'
                    f'<span class="wkent"><small>entry</small>{money("Sports",p["entry"])} <i>\u2192</i> {ext}{"" if fin else " now"}</span>'
                    f'{chip(p.get("ret"),fin)}<span class="wkdt">picked {datetime.date.fromisoformat(ed["date"]).strftime("%b %-d")}</span></a>')
        secs=''; cur=None; buf=[]
        def flush():
            nonlocal secs
            if not buf: return
            s_=[p for p,_,_ in buf if p.get('final') and p.get('ret') is not None]; ww=sum(p['ret']>0 for p in s_)
            rec=f'<small class="mut">{ww}-{len(s_)-ww}</small>' if s_ else '<small class="mut">live</small>'
            secs_=f'<h3 class="hzh">\U0001F3C8 {E(_window(buf[0][2]))} {rec}</h3><div class="wklist">'+''.join(row(*x) for x in buf)+'</div>'
            secs+=secs_
        for x in lst:
            if cur is None or abs((x[2]-cur).total_seconds())>2700: flush(); buf=[]; cur=x[2]
            buf.append(x)
        flush()
        tot=sum(p['ret'] for p,_,_ in st)*100
        fav=[p for p,_,_ in st if p['entry']>=0.6]; dog=[p for p,_,_ in st if p['entry']<0.6]
        rec_=lambda ps_: f"{sum(p['ret']>0 for p in ps_)}-{sum(p['ret']<=0 for p in ps_)}"
        nxt=int(wk)+1
        lv=''.join(f" Still live: {E(p['label'])} ({E(mtch(p))}, {k.strftime('%a %-I:%M %p ET')}) at {money('Sports',p.get('cur'))}, entry {money('Sports',p['entry'])}." for p,_,k in op)
        summ=(f"The Daily Five made {len(lst)} NFL Week {wk} picks on Polymarket ({rng}). {len(st)} have settled: {w_} won and {l_} lost ({w_/len(st)*100:.0f}%), "
              f"an average return of {pct(avg)} per $1 staked at our entry price. $100 on every settled pick would be {'up' if tot>=0 else 'down'} ${abs(tot):,.0f}. "
              f"Best call: {best[0]['label']} at {money('Sports',best[0]['entry'])} ({pct(best[0]['ret'])}). "
              +(f"Toughest loss: {worst[0]['label']}, a {money('Sports',worst[0]['entry'])} favorite. " if worst[0]['ret']<0 and worst[0]['entry']>=0.5 else '')
              +(f"Favorites (entry 60\u00a2+) went {rec_(fav)}; closer games (under 60\u00a2) went {rec_(dog)}." if fav and dog else ''))
        sumh=E(summ)+lv
        tiles=(f'<div class="wkbig"><div><span class="k">Week {wk} record</span><b class="{"up" if w_>=l_ else "dn"}">{w_}\u2013{l_}</b><span class="s">{len(st)} settled{f" \u00b7 {len(op)} still live" if op else ""}</span></div>'
               f'<div><span class="k">Avg return</span><b class="{"up" if avg>=0 else "dn"}">{pct(avg)}</b><span class="s">per $1 at entry</span></div>'
               f'<div><span class="k">$100 a pick</span><b class="{"up" if tot>=0 else "dn"}">{"+" if tot>=0 else "\u2212"}${abs(tot):,.0f}</b><span class="s">on ${len(st)*100:,} staked</span></div>'
               f'<div><span class="k">Best call</span><b class="up">{pct(best[0]["ret"])}</b><span class="s">{E(best[0]["label"])} at {money("Sports",best[0]["entry"])}</span></div></div>')
        ask=(f'<section class="signup wksign"><div><span class="kicker">\U0001F4EC Week {nxt} picks</span><h2>Get our Week {nxt} NFL picks before kickoff.</h2>'
             f'<p>Every play lands in the free 7 AM ET email with the entry price and the why, then gets graded here in public, wins and losses. No spam, unsubscribe anytime.</p></div>{sform("wk")}</section>')
        cnav,csch=crumbs([('Home','/'),('NFL picks','/nfl-picks-this-week/'),('NFL results','/nfl-results/'),(f'Week {wk} results',P)])
        others=''.join(f'<a class="pill ghost" href="{BASE}{o2["url"]}">Week {o2["wk"]}: {o2["w"]}-{o2["l"]} \u2192</a>' for o2 in NFLWK if o2['wk']!=wk)
        h1=f"NFL Week {wk} Results: Our Picks Went {w_}-{l_}"
        bodyh=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">\U0001F3C8 NFL Week {wk} results \u00b7 {rng}</span><h1 class="pt">{E(h1)}</h1>'
               f'<p class="sub wksum">{sumh}</p><div class="hubcta"><a class="pill" href="{BASE}/nfl-picks-this-week/">This week\'s NFL picks \u2192</a>'
               f'<a class="pill ghost" href="{BASE}/track-record/">Full track record \u2192</a><a class="pill ghost" href="{BASE}/picks/">All picks by day \u2192</a>{others}</div></section>'
               f'{tiles}{ask}'
               f'<h2 class="h2s">Every Week {wk} pick, graded</h2><p class="sub hub-lead">Entry is the real Polymarket price of our side when we published. A win settles at 100\u00a2, a loss at 0\u00a2; return is per $1 staked at entry. Tap any pick for its line-movement chart.</p>{secs}'
               +(f'<h2 class="h2s">Still live</h2><div class="grid g3">{"".join(sp_card(p,"") for p,_,_ in op)}</div>' if op else '')+
               f'<p class="disc-bar">\u26a0\ufe0f <b>Not betting advice.</b> Results use real Polymarket prices; prediction markets may not be legal where you live, and you can lose your entire stake.</p>')
        title=f"NFL Week {wk} Results & Picks Recap: {w_}-{l_}, {pct(avg)} Avg Return | {BRAND}"
        desc=f"Our NFL Week {wk} picks graded ({rng}): {w_}-{l_} on {len(st)} settled Polymarket plays, {pct(avg)} average return. Every pick with entry, result and return."[:155]
        modified=TODAY.isoformat() if op else max(lastmod(p,ed) for p,ed,_ in lst)
        pub=min(TODAY,ws+datetime.timedelta(days=6)).isoformat()
        art={"@type":"Article","headline":h1,"description":desc,"datePublished":pub,"dateModified":modified,"author":{"@type":"Organization","name":BRAND},
             "publisher":{"@type":"Organization","name":BRAND,"logo":{"@type":"ImageObject","url":SITE+"/favicon.svg"}},"mainEntityOfPage":SITE+P,
             "about":{"@type":"SportsOrganization","name":"National Football League"},
             "mentions":[{"@type":"SportsEvent","name":mtch(p),"startDate":k.isoformat(),"sport":"American football","url":f"{SITE}/picks/{p['id']}/"} for p,_,k in lst]}
        if OGIMG['v']: art['image']=SITE+OGIMG['v']
        w(P.strip('/')+'/index.html',shell(title,desc,P,bodyh,{"@context":"https://schema.org","@graph":[art,csch]}))
        urls.append((P,modified))
    if NFLWK:
        cnav,csch=crumbs([('Home','/'),('NFL picks','/nfl-picks-this-week/'),('NFL results','/nfl-results/')])
        rows=''.join(f'<a class="wkrow {"won" if o["w"]>=o["l"] else "lost"}" href="{BASE}{o["url"]}"><span class="wkres">WK {o["wk"]}</span><span class="wkpk"><b>Week {o["wk"]}: {o["w"]}-{o["l"]}</b><small>{o["rng"]} \u00b7 {o["n"]} picks{f" \u00b7 {o['n_open']} live" if o["n_open"] else ""}</small></span><span class="wkent"><small>avg</small>{pct(o["avg"])}</span>{chip(o["avg"])}<span class="wkdt">recap \u2192</span></a>' for o in NFLWK)
        tw=sum(o['w'] for o in NFLWK); tl=sum(o['l'] for o in NFLWK)
        b=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">\U0001F3C8 NFL results</span><h1 class="pt">NFL picks results, week by week</h1><p class="sub">Every NFL play The Daily Five has made on Polymarket, graded by week: {tw}-{tl} so far. Each recap lists every pick with its entry price, final score and return.</p>'
           f'<div class="hubcta"><a class="pill" href="{BASE}/nfl-picks-this-week/">This week\'s NFL picks \u2192</a><a class="pill ghost" href="{BASE}/track-record/">Track record \u2192</a></div></section><div class="wklist">{rows}</div>')
        w('nfl-results/index.html',shell(f"NFL Picks Results by Week: {tw}-{tl} on Polymarket | {BRAND}",f"Week-by-week results of every Daily Five NFL pick on Polymarket: {tw}-{tl} so far, with entry prices, final scores and returns.",'/nfl-results/',b,
              {"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":"NFL picks results by week","url":SITE+"/nfl-results/"},csch]}))
        urls.insert(0,('/nfl-results/',max(u[1] for u in urls)))
    return urls
def nfl_results_links(cls='pill ghost'):
    return ''.join(f'<a class="{cls}" href="{BASE}{o["url"]}">Week {o["wk"]} results: {o["w"]}-{o["l"]} \u2192</a>' for o in NFLWK[:3])
def seo_pages(eds,rows,tiles):
    urls=[]; by={}
    allp=[(p,ed) for ed in eds for p in ed['finance']+ed['sports']]
    for ed in eds:
        for p in ed['finance']+ed['sports']:
            pick_page(p,ed,allp); urls.append((f"/picks/{p['id']}/",lastmod(p,ed))); by.setdefault(p['tslug'],[]).append((p,ed))
    for slug,lst in by.items():
        p0=lst[0][0]; nm=p0['tname']; k=p0['kind']
        title=(f"{nm} Stock: Daily Five Picks, Live Price & Track Record" if k=='Finance' else f"{nm}: Prediction Market Odds & Daily Five Picks")+f" | {BRAND}"
        desc=f"Every Daily Five pick on {nm}: entry prices, live {'price' if k=='Finance' else 'odds'}, and returns since each pick. Latest: {p0['action']} {p0['label']} on {lst[0][1]['date']}."[:155]
        li=''.join(f'<a class="rc" href="{BASE}/picks/{p["id"]}/"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} \u00b7 {ed["date"]} \u00b7 entry {money(p["kind"],p["entry"])} {chip(p.get("ret"),p.get("final"))}</a>' for p,ed in lst)
        rs=[p['ret'] for p,_ in lst if p.get('ret') is not None]
        cardf=fin_card if k=="Finance" else sp_card
        hn,hu=hub_of(p0); cnav,csch=crumbs([('Home','/'),(hn,hu),(nm,f"/ticker/{slug}/")])
        bodyh=f'{cnav}<section class="sbhero"><span class="kicker">{"\U0001F4C8 Ticker" if k=="Finance" else "\U0001F3DF Market"}</span><h1 class="pt">{E(nm)}</h1><p class="sub">{len(lst)} pick(s) \u00b7 avg return since pick {pct(sum(rs)/len(rs)) if rs else "\u2014"}</p></section><div class="pickwrap">{cardf(p0,"")}<div class="pinfo"><h2>All picks</h2><div class="rcs col">{li}</div><p><a href="{BASE}/track-record/">Full track record \u2192</a></p></div></div>'
        sch={"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":title,"description":desc,"url":f"{SITE}/ticker/{slug}/"},csch]}
        w(f"ticker/{slug}/index.html",shell(title,desc,f"/ticker/{slug}/",bodyh,sch)); urls.append((f"/ticker/{slug}/",max(lastmod(p,ed) for p,ed in lst)))
    allp=''.join(f'<a class="rc" href="{BASE}/picks/{r["id"]}/"><b class="{r["action"].lower()}">{r["action"]}</b> {E(r["pick"])} \u00b7 {E(r["horizon"])} \u00b7 {r["date"]} {chip(r["ret"],r["final"])}</a>' for r in rows)
    tk=''.join(f'<a class="tkchip" href="{BASE}/ticker/{s}/">{E(l[0][0]["tname"])}</a>' for s,l in by.items())
    tb=(f'<section class="sbhero"><span class="kicker">\U0001F3C6 Track record</span><h1 class="pt">Every pick, graded in public</h1><p class="sub">We publish an entry price from a real quote for every pick, then mark it to live market data until its horizon ends (1 Day, 1 Month, 1 Year) or its market resolves. Nothing gets deleted. SELL returns are short-side. See the <a href="{BASE}/scoreboard/">Scoreboard</a> for charts.</p>{('<div class="hubcta">'+nfl_results_links('pill')+'<a class="pill ghost" href="'+BASE+'/nfl-results/">All NFL weeks \u2192</a></div>') if NFLWK else ''}</section>'
        f'<div class="tiles">{tiles}</div><h2 class="h2s">Tickers &amp; markets</h2><div class="tks">{tk}</div><h2 class="h2s">All picks</h2><div class="rcs col">{allp}</div>')
    w('track-record/index.html',shell(f"Track Record: Win Rate & Returns of Every Pick | {BRAND}","The Daily Five's public track record: win rate and average return by horizon for every stock and sports-market pick, marked to real prices.",'/track-record/',tb,{"@context":"https://schema.org","@type":"CollectionPage","name":"Daily Five Track Record","url":SITE+"/track-record/"}))
    # /picks/ index: every pick page, newest edition first (the parent of every /picks/<id>/ URL used to 404)
    byd={}
    for r in rows: byd.setdefault(r['date'],[]).append(r)
    rec=lambda rs: f"{sum(r['ret']>0 for r in rs if r['final'] and r['ret'] is not None)}-{sum(r['ret']<=0 for r in rs if r['final'] and r['ret'] is not None)}"
    secs=''.join(f'<h2 class="h2s"><a href="{BASE}/{d}/">{datetime.date.fromisoformat(d).strftime("%A, %B %-d")}</a> <small class="mut">{len(rs)} picks \u00b7 settled {rec(rs)}</small></h2><div class="rcs col">'+''.join(f'<a class="rc" href="{BASE}/picks/{r["id"]}/"><b class="{r["action"].lower()}">{r["action"]}</b> {E(r["pick"])} \u00b7 {E(r["horizon"])} {chip(r["ret"],r["final"])}</a>' for r in rs)+'</div>' for d,rs in sorted(byd.items(),reverse=True))
    cnav,csch=crumbs([('Home','/'),('All picks','/picks/')])
    pb=(f'{cnav}<section class="sbhero"><span class="kicker">\U0001F5C2 All picks</span><h1 class="pt">Every Daily Five pick, by day</h1><p class="sub">{len(rows)} stock and prediction-market picks since {min(byd)}, each with its entry price, live mark and result. Hubs: <a href="{BASE}/best-stocks-to-buy-today/">stock picks</a>, <a href="{BASE}/nfl-picks-this-week/">NFL picks</a>, <a href="{BASE}/polymarket-picks-today/">Polymarket picks</a>.</p>{('<div class="hubcta">'+nfl_results_links('pill')+'</div>') if NFLWK else ''}</section>{secs}')
    w('picks/index.html',shell(f"All Picks: Every Stock & Prediction-Market Call, by Day | {BRAND}",f"All {len(rows)} Daily Five picks by day: stock BUY/SELL calls and Polymarket sports plays with entry prices, live marks and settled results.",'/picks/',pb,{"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":"All Daily Five picks","url":SITE+"/picks/"},csch]}))
    urls.insert(0,('/picks/',TODAY.isoformat()))
    return urls
INDEXNOW_KEY='fcd40c5d2b89f9aed9ee904f5baee9f2'
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
    nfl_weeks(eds)
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
        w('index.html',shell(f"The Daily Five: Today's Best Stock Picks, AI News & Sports Market Plays",f"{TAG} Today: {desc}",'/',body(ed,eds[1] if len(eds)>1 else None),{"@context":"https://schema.org","@type":"WebSite","name":BRAND,"url":SITE+"/","description":TAG,"sameAs":["https://x.com/ReadDailyFive"]},hr))
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
    sbstrip=today_strip([p for e in eds for p in e['finance']+e['sports']],'sb',max(eds,key=lambda e:e['date'])['finance']+max(eds,key=lambda e:e['date'])['sports'])
    sb=f'''<section class="sbhero"><span class="kicker">📊 Scoreboard</span><h1 class="pt">If you traded it immediately</h1><p class="sub">Every pick at its published entry price, marked to real market data from Yahoo Finance (stocks) and Polymarket (markets). SELL returns are short-side. Picks close at the end of their horizon or when the market resolves. Updated {upd}.</p>{sbstrip}</section>
<div class="tiles">{tiles}</div>{bar_chart(rows)}<div class="tbl"><table><thead><tr><th>Date</th><th>Pick</th><th>Horizon</th><th>Entry</th><th>Now / exit</th><th>Trend</th><th>P/L</th><th>Result</th><th></th></tr></thead><tbody>{tr}</tbody></table></div>'''
    w('scoreboard/index.html',shell(f"Scoreboard: Track Record of Every Pick | {BRAND}","If you traded every Daily Five pick immediately: entry, current price, % return, win rate and average return by horizon.",'/scoreboard/',sb,{"@context":"https://schema.org","@type":"Dataset","name":f"{BRAND} Scoreboard","description":"Track record of featured picks","url":SITE+"/scoreboard/"}))
    hub=best_stocks_hub(eds); pmh=polymarket_hub(eds); nfr=nfl_results(eds); nfh=nfl_hub(eds); extra=seo_pages(eds,rows,tiles); render_pick_ogs(); write_live(eds); w('live.js',open(os.path.join(ROOT,'live.js')).read())
    faq_ents=[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in FAQS]
    how_sch={'@context':'https://schema.org','@graph':[
        {'@type':'Article','headline':'How we rank: the Daily Five Score','author':{'@type':'Organization','name':BRAND},'publisher':{'@type':'Organization','name':BRAND},'mainEntityOfPage':SITE+'/how-we-rank/','description':'How the 0-100 Daily Five Score ranks every stock and sports-market pick.'},
        {'@type':'FAQPage','mainEntity':faq_ents,'url':SITE+'/how-we-rank/'},
    ]}
    w('how-we-rank/index.html',shell(f'How We Rank Picks: The Daily Five Score Methodology | {BRAND}','How the 0-100 Daily Five Score ranks every stock and sports-market pick: source credibility, consensus, edge vs analyst targets and sportsbook odds, and risk/reward.','/how-we-rank/',HOWTO,how_sch))
    # lastmod: hubs today; an edition page changes until all its picks settle; pick/ticker pages from lastmod()
    edlm=lambda e: max([lastmod(p,e) for p in e['finance']+e['sports']]+[e['date']])
    urls=[(u,TODAY.isoformat()) for u in ['/','/scoreboard/','/track-record/','/how-we-rank/',hub,pmh,nfh,'/archive/']]+[(f"/{e['date']}/",edlm(e)) for e in eds]+nfr+extra
    w('sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{SITE}{u}</loc><lastmod>{lm}</lastmod></url>" for u,lm in urls)+'</urlset>')
    w('googlef258d1e6972b7938.html','google-site-verification: googlef258d1e6972b7938.html')
    w(INDEXNOW_KEY+'.txt',INDEXNOW_KEY)  # IndexNow key file (Bing, Yandex, Seznam, Naver); indexnow.py pings after deploy
    w('robots.txt',f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    os.makedirs(os.path.join(OUT,'email'),exist_ok=True)
    for f in glob.glob(os.path.join(ROOT,'email','*.html')): shutil.copy(f,os.path.join(OUT,'email'))
    rfc=lambda d: datetime.datetime.fromisoformat(d+'T09:00:00-04:00').strftime('%a, %d %b %Y %H:%M:%S %z')
    w('feed.xml','<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'+f"<title>{BRAND}</title><link>{SITE}/</link><description>{E(TAG)}</description>"+''.join(f"<item><title>{E(t)}</title><link>{SITE}/{d}/</link><guid>{SITE}/{d}/</guid><pubDate>{rfc(d)}</pubDate><description>{E(ds)}</description></item>" for d,_,t,ds,_,_ in items)+'</channel></rss>')
    w('404.html',shell(f"Not found | {BRAND}","Page not found",'/404.html',f'<h1 class="pt">Not found</h1><p><a href="{BASE}/">Go to today\'s edition →</a></p>'))
    try:
        import email_build; print('email ->',email_build.write(eds[0]))
    except Exception as ex: print('email build skipped:',ex)
    print(f"built {len(items)} editions, {len(rows)} scoreboard rows -> {OUT}")
if __name__=='__main__': main()
