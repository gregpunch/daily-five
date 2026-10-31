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
        # Right after the close Yahoo's servers can briefly disagree (one says 271.28, the next 271.29): freeze today's bar
        # only when it matches the quote's regularMarketPrice, else wait for the next build.
        if c and d==TODAY and abs(round(c,4)-(s['meta'].get('regularMarketPrice') or 0))>0.005: return None,None
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
ESPN_LG={'nfl':'football/nfl','nba':'basketball/nba','mlb':'baseball/mlb','nhl':'hockey/nhl','wnba':'basketball/wnba'}
BK=os.path.join(ROOT,'data','books.json')
def _am(x):
    x=str(x or '').strip().upper().replace('\u2212','-')
    if x in ('EVEN','EV','PK'): return 100
    try: v=int(float(x)); return v if abs(v)>=100 else None
    except Exception: return None
def espn_line(p):
    """Real sportsbook moneyline for a Polymarket game pick from ESPN's free public scoreboard JSON (no account or key).
    Returns {'name','url','odds':[ours,theirs],'teams':[ours,theirs],'state','at'} or None. Matches on start time (within 4h) and team name."""
    slug=p.get('slug') or ''; m=p.get('m') or {}
    if not GAME_RE.match(slug) or slug.split('-')[0] not in ESPN_LG: return None
    ko=kickoff(p); outs=m.get('outcomes') or []
    if not ko or len(outs)!=2: return None
    lg=ESPN_LG[slug.split('-')[0]]; day=ko.strftime('%Y%m%d')
    sb=memo(('espn',lg,day),lambda: get(f"https://site.api.espn.com/apis/site/v2/sports/{lg}/scoreboard?dates={day}"))
    if not sb: return None
    ours,theirs=outs[p['outcome']].lower(),outs[1-p['outcome']].lower()
    def hit(c,nm):
        t=c.get('team') or {}; full=(t.get('displayName') or '').lower(); short=(t.get('name') or '').lower()
        return bool(full) and (nm in full or (short and short in nm))
    for ev in sb.get('events') or []:
        try: et=datetime.datetime.fromisoformat(ev['date'].replace('Z','+00:00'))
        except Exception: continue
        if abs((et-ko).total_seconds())>4*3600: continue
        c=ev['competitions'][0]; cs=c.get('competitors') or []
        me=[x for x in cs if hit(x,ours)]; op=[x for x in cs if hit(x,theirs)]
        if len(cs)!=2 or len(me)!=1 or len(op)!=1 or me[0] is op[0]: continue
        sides={x.get('homeAway'):x for x in cs}; mys=me[0].get('homeAway'); ops=op[0].get('homeAway')
        for o in c.get('odds') or []:
            ml=o.get('moneyline') or {}
            a,b=[_am(((ml.get(s) or {}).get('close') or {}).get('odds')) for s in (mys,ops)]
            if a is None or b is None:  # older ESPN shape
                a,b=[_am((o.get(f"{s}TeamOdds") or {}).get('moneyLine')) for s in (mys,ops)]
            if a is None or b is None: continue
            # a real two-way line has a vig: implied probabilities sum to more than 100% (guards against bad data)
            if not (1.0<am2p(a)+am2p(b)<1.15): continue
            prov=((o.get('provider') or {}).get('name') or 'Sportsbook').replace('Draft Kings','DraftKings')
            url=next((l['href'] for l in ev.get('links') or [] if 'summary' in (l.get('rel') or [])),f"https://www.espn.com/{lg.split('/')[1]}/game/_/gameId/{ev['id']}")
            ab=lambda x:(x.get('team') or {}).get('abbreviation') or ''
            return {'name':f"{prov} via ESPN",'url':url,'odds':[a,b],'teams':[ab(me[0]),ab(op[0])],'state':(ev.get('status') or {}).get('type',{}).get('state',''),
                    'at':NOW.astimezone().isoformat(timespec='minutes')}
    return None
def attach_books(eds):
    """Sportsbook line used for each sports pick's Edge score.
    Open game, not started: the live ESPN moneyline (DraftKings), refreshed every build, vs the live Polymarket price.
    Started or settled: the line at publish (edition `book`) vs our entry; if there was none, the last pre-game ESPN line
    we stored in data/books.json (committed by local/edition builds, not by CI) vs our entry. Futures keep the edition `book` vs the live price."""
    bk=json.load(open(BK)) if os.path.exists(BK) else {}; now=NOW.astimezone(); fresh=set()
    for ed in eds:
        for i,p in enumerate(ed['sports']):
            key=f"{ed['date']}/s{i}"; ko=kickoff(p); started=bool(p.get('final') or (ko and ko<=now))
            if p.get('book'): p['book0']=dict(p['book'],at=ed['date'],pub=True)
            if not started:
                ln=memo(('line',key),lambda: espn_line(p))
                if ln and ln['state']=='pre':
                    ln=dict(ln); ln.pop('state',None); ln['pm']=p.get('cur'); bk[key]=ln; fresh.add(key)
            esp=dict(bk[key],auto=True,closing=started,fresh=key in fresh) if key in bk else None
            p['espn']=esp
            if not started and esp: p['book'],p['bmode']=esp,'live'
            elif started: p['book'],p['bmode']=(p.get('book0') or esp),'entry'
            else: p['bmode']='live'; p['book']=p.get('book0') or p.get('book')
    json.dump(bk,open(BK,'w'),indent=1)
def phistory(token):
    return memo(('ph',token),lambda: [(h['t'],h['p']) for h in get(f"https://clob.polymarket.com/prices-history?market={token}&interval=1w&fidelity=60")['history']])
HZ={'1 Day':1,'1 Month':30,'3 Month':91,'1 Year':365}
LAUNCH='2026-10-25'  # Max Edge Day 1: main records start here; earlier picks live on /beta-archive/
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
        elif TODAY>=end:
            c,dt=stock_close_on(p['symbol'],end); p['cur'],p['final'],p['note']=c,c is not None,f"closed {dt}"
            if c is not None: exits[key]={'price':c,'note':p['note']}
            else:  # exit session still forming (before 4:15 PM ET) or horizon ended on a weekend/holiday: mark live until that close is final
                o=today_open_stock(p['symbol']); p['cur'],p['note']=((o or {}).get('last') or (s['last'] if s else None)),('live (exits at today\'s close)' if end==TODAY else 'live (exits at next close)')
        else:
            o=today_open_stock(p['symbol']); p['cur'],p['final'],p['note']=((o or {}).get('last') or (s['last'] if s else None)),False,'live'
        o=today_open_stock(p['symbol']) if not p['final'] else None
        p['open']=(o or {}).get('open'); p['qt']=(o or {}).get('t')
        p['id']=f"{ed['date']}-{slugify(p['action']+'-'+p['label'])}"; p['tslug']=p['symbol'].upper(); p['tname']=p['symbol'].upper(); p['kind']='Finance'
        p['ret']=None if p['cur'] is None else (p['cur']-p['entry'])/p['entry']*(-1 if p['action']=='SELL' else 1)
        if p['horizon']=='3 Month' and p.get('spy_entry') and p['ret'] is not None:
            # Win condition: beat the S&P 500 (SPY) over the same window. ret = our return minus SPY's.
            sk=key+'/spy'
            if sk in exits: sc=exits[sk]['price']
            elif p['final']:
                sc,_=stock_close_on('SPY',end)
                if sc is not None: exits[sk]={'price':sc,'note':'SPY at exit'}
            else: sc=(today_open_stock('SPY') or {}).get('last')
            if sc:
                p['abs_ret']=p['ret']; p['spy_ret']=(sc-p['spy_entry'])/p['spy_entry']; p['ret']=p['abs_ret']-p['spy_ret']
                p['note']=(p['note'] or '')+f" · stock {p['abs_ret']*100:+.1f}% vs S&P {p['spy_ret']*100:+.1f}%"
    for i,p in enumerate(ed['sports']):
        key=f"{ed['date']}/s{i}"; m=pmarket(p['slug']); p['m']=m
        tok=m['tokens'][p['outcome']] if m and len(m['tokens'])>p['outcome'] else None
        p['pts']=(phistory(tok) if tok else None) or []  # phistory returns None on a failed fetch
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
    enrich_lean(ed,exits)
    json.dump(exits,open(EX,'w'),indent=1)
def enrich_lean(ed,exits):
    """Max's lean (FORMAT.md): on a no-Bold-Bet day, the closest-to-qualifying edge play. Priced and settled exactly like a
    sports pick (Polymarket resolution, or the final score while UMA catches up), but kept OUT of ed['sports'] so it never
    touches the sports / Bold Bet record. Graded only on the separate Leans record (exits key '<date>/lean')."""
    p=ed.get('lean')
    if not p or ed['sports']: ed['lean']=None if ed['sports'] else p; return
    key=f"{ed['date']}/lean"; m=pmarket(p['slug']); p['m']=m; p['kind']='Sports'; p.setdefault('action','BUY')
    if key in exits: p['cur'],p['final'],p['note']=exits[key]['price'],True,'resolved'
    else:
        p['cur']=m['prices'][p['outcome']] if m else None
        p['final']=bool(m and m['closed'] and p['cur'] is not None and (p['cur']>=0.99 or p['cur']<=0.01)); p['note']='resolved' if p['final'] else 'live'
        if p['final']: exits[key]={'price':p['cur'],'note':'resolved'}
        elif m and GAME_RE.match(p.get('slug') or ''):
            d=final_margin(p,pgame(p['slug']),m)
            if d: p['cur'],p['final'],p['note']=(1.0 if d>0 else 0.0),True,'final score, awaiting resolution'
    p['ret']=None if p['cur'] is None else (p['cur']-p['entry'])/p['entry']; p['so']=None; p['open']=None
    p['id']=f"{ed['date']}-lean-{slugify(p['label'])}"
def leans(eds=None):
    """Every Max's lean, newest first, as (edition, lean)."""
    return [(e,e['lean']) for e in (eds if eds is not None else ALLEDS) if e.get('lean') and e['date']>=LAUNCH]
def lean_rec(eds=None):
    st=[p for _,p in leans(eds) if p.get('final') and p.get('ret') is not None]
    w_=sum(p['ret']>0 for p in st); avg=sum(p['ret'] for p in st)/len(st) if st else None
    return w_,len(st)-w_,avg,len(leans(eds))-len(st)
def lean_rec_txt(eds=None):
    w_,l_,avg,op=lean_rec(eds)
    if not w_+l_: return "Leans record: no settled leans yet."
    return f"Leans record: {w_}-{l_}, {avg*100:+.0f}% avg per $1" + (f", {op} open" if op else '') + ". Separate from the Bold Bet and sports record."
def lean_box(ed):
    """'Max's lean' card on a no-Bold-Bet day. Clearly NOT a Bold Bet, and graded on its own Leans record."""
    p=ed.get('lean')
    if not p or ed['sports'] or ed['date']<LAUNCH: return ''
    res=''
    if p.get('final') and p.get('ret') is not None:
        fl=final_line(p); res=f'<p class="lean-res"><b>{"✅ Lean cashed" if p["ret"]>0 else "❌ Lean missed"}</b>{(" · "+fl[0]) if fl else ""} · {p["ret"]*100:+.0f}% per $1 at {p["entry"]*100:.1f}¢{" (final score, awaiting resolution)" if "awaiting" in (p.get("note") or "") else ""}</p>'
    bk=p.get('book') or {}
    bl=(f'📒 {E(bk.get("name","Sportsbook"))} no-vig line put this side about <b>{p["edge"]:+.1f} pts</b> above the Polymarket price'+(f' ({E(p["edge_at"])})' if p.get('edge_at') else '')+(f' · <a href="{E(bk["url"])}" rel="nofollow noopener" target="_blank">line ↗</a>' if bk.get('url') else '')+'. Our bar for a real pick is +2.5.') if p.get('edge') is not None else ''
    bf=f'<p class="lean-fine">🗂 {E(p["backfill"])}</p>' if p.get('backfill') else ''
    return (f'<div class="lean" id="lean"><span class="lean-tag">🤏 Max\'s lean · not a Bold Bet · not a pick</span>'
            f'<h3><span class="mini buy">LEAN</span> {E(p["label"])} <small>at {p["entry"]*100:.1f}¢</small></h3><p class="lean-mkt">{E(p["market"])}</p>'
            f'<p class="lean-why">🤖 <b>Max Edge (AI host):</b> {E(p["why"])}</p>'
            f'<p class="lean-book">{bl}</p>{livebox(p)}{gd(p)}{res}'
            f'<p class="lean-fine">Leans are the closest miss on a day nothing clears our bar. They are graded in public on a separate <a href="{BASE}/scoreboard/#leans">Leans record</a> and never count toward the Bold Bet or sports record. {E(lean_rec_txt())} Not betting advice.</p>{bf}'
            f'<a class="lean-src" href="{E(p["source"]["url"])}" rel="nofollow noopener" target="_blank">{E(p["source"]["name"])} ↗</a></div>')
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
def refer_bar():
    """'Know someone who trades?' share row under every signup box: X intent, SMS and copy-link, each to the subscribe form with its own UTM tags."""
    q=urllib.parse.quote
    hook='Max Edge\'s Bold Bet, the sports plays that clear our bar, and 3-month stock calls vs the S&P 500, graded in public'
    if SPR: hook+=f" (sports {SPR['w']}-{SPR['l']} so far)"
    txt=f'The Daily Five: {hook}. Free 7 AM email:'
    u=lambda m: f'{SITE}/?utm_source=site_share&utm_medium={m}&utm_campaign=refer#subscribe'
    cp=u('copy')
    return (f'<div class="refer"><span class="rtxt"><b>Know someone who trades or bets?</b> Send them the free signup.</span><span class="rbtns">'
            f'<a class="rb rx" href="https://x.com/intent/tweet?text={q(txt)}&amp;url={q(u("x"))}" target="_blank" rel="noopener">Post on X</a>'
            f'<a class="rb" href="sms:?&amp;body={q(txt+" "+u("sms"))}">Text it</a>'
            f'<button type="button" class="rb" data-copy="{E(cp)}" onclick="var b=this,u=b.dataset.copy;(navigator.clipboard?navigator.clipboard.writeText(u):Promise.reject()).then(function(){{b.textContent=&quot;Link copied \u2713&quot;}},function(){{window.prompt(&quot;Copy this link&quot;,u)}})">Copy link</button></span></div>')
def recent_win(days=2,floor=0.25):
    """Best real settled sports winner from the last `days` days (by game date), if it returned at least `floor`; else None."""
    c=[(p,_sp_when(p,ed).date()) for p,ed in (SPR.get('st') or []) if p['ret']>=floor]
    c=[x for x in c if 0<=(TODAY-x[1]).days<=days]
    return max(c,key=lambda x:x[0]['ret']) if c else None
def hook():
    """Signup hook from tonight's best open sports Value pick (game only, never the side; the pick itself is in the email). Fallback: None."""
    c=[p for p,ed in (SPR.get('op') or []) if vkey(p)=='val' and (p.get('event_date') or '')>=TODAY.isoformat()]
    if not c: return None
    t=[p for p in c if p.get('event_date')==TODAY.isoformat()]
    p=max(t or c,key=lambda p:p.get('score') or 0)
    return (p['market'].split(',')[0],bool(t))
def hook_copy():
    g=hook()
    if g:
        w="tonight's" if g[1] else "our next"
        return (f"Get {w} best value play + tomorrow's five at 7 AM, free.",f"Our top-scored value pick for {g[0]} is priced under the sportsbooks. The side is in the email.")
    return ("Get tomorrow's five at 7 AM, free.","Max Edge\'s Bold Bet of the Day plus every pick graded in public, before the opening bell.")
def stickybar():
    """Dismissible sticky signup bar: shown by live.js after the reader scrolls past the first screen, hidden while any other signup form is on screen, after a signup, or for 7 days once dismissed."""
    rec=f" Sports {SPR['w']}-{SPR['l']} so far." if SPR else ''
    bw=recent_win()
    hot=(f'<a class="sbw" href="{BASE}/picks/{bw[0]["id"]}/">\U0001F525 {"Today" if bw[1]==TODAY else "Last night" if (TODAY-bw[1]).days==1 else bw[1].strftime("%a")}: {E(bw[0]["action"])} {E(bw[0]["label"])} settled {pct(bw[0]["ret"])}</a>' if bw else '')
    return (f'<div class="sbar" id="sbar" hidden role="region" aria-label="Get The Daily Five by email"><div class="sbin"><p class="sbt">{hot}<b>{E(hook_copy()[0])}</b><span> {E(hook_copy()[1])}{rec}</span></p>'
            f'{sform("bar")}<button type="button" class="sbclose" aria-label="Dismiss">\u00d7</button></div></div>')
def shell(title,desc,path,body,schema=None,hero='',og=None):
    og=og or OGIMG['v']; ogm=f'<meta property="og:image" content="{SITE}{og}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:image" content="{SITE}{og}">' if og else ''
    url=SITE+path; s=f'<script type="application/ld+json">{json.dumps(schema)}</script>' if schema else ''
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><meta name="description" content="{E(desc)}"><link rel="canonical" href="{url}"><meta name="theme-color" content="#07080d">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website"><meta property="og:site_name" content="{BRAND}"><meta name="twitter:card" content="summary_large_image">{ogm}
<link rel="icon" href="{BASE}/favicon.svg" type="image/svg+xml"><link rel="alternate" type="application/rss+xml" title="{BRAND}" href="{BASE}/feed.xml">{FONTS}<link rel="stylesheet" href="{BASE}/style.css">{s}</head><body>
<header class="top"><div class="wrap nav"><a class="logo" href="{BASE}/" aria-label="{BRAND} home">{LOGO}<span class="word"><span class="the">The</span> Daily Five</span></a>
<nav><a href="{BASE}/#finance">Money</a><a href="{BASE}/track-record/">Track record</a><a href="{BASE}/#ai">AI</a><a href="{BASE}/#sports">Sports</a><a class="ncta" href="#subscribe" data-sub="nav" aria-label="Get The Daily Five free by email"><span class="nd">Free 7 AM email</span><span class="nm">Get it free</span></a><a href="{BASE}/scoreboard/" class="pill-nav">Scoreboard</a></nav></div></header>
{hero}<main class="wrap">{body}
<section class="signup" id="subscribe"><div><h2>{E(hook_copy()[0])}</h2><p>{E(hook_copy()[1])}</p></div>
{sform('cta')}{refer_bar()}</section>
</main><footer><div class="wrap"><div class="fbrand">{LOGO}<b>The Daily Five</b></div><div class="fsub"><b>Get it daily</b>{sform('foot')}</div><p class="disc"><strong>Disclaimer:</strong> {DISC}</p><p class="fl"><a href="{BASE}/track-record/">Track record</a> · <a href="{BASE}/best-stocks-to-buy-today/">Best stocks</a> · <a href="{BASE}/3-month-stock-picks/">3-month stock picks</a> · <a href="{BASE}/polymarket-picks-today/">Polymarket picks</a> · <a href="{BASE}/nfl-picks-this-week/">NFL picks</a> · {f'<a href="{BASE}/nfl-results/">NFL results</a> · ' if NFLWK else ''}{f'<a href="{BASE}/stock-results/">Stock results</a> · ' if STK else ''}{f'<a href="{BASE}/sports-results/">Sports results</a> · ' if SPR else ''}{''.join(f'<a href="{BASE}{u}">{n.split(" picks")[0]} picks</a> · ' for n,u in LGHUBS.values())}<a href="{BASE}/max-edge/">Max Edge videos</a> · {f'<a href="{BASE}/earnings/">Earnings calendar</a> · ' if any(p.get("catalyst") for p in open3()) else ''}<a href="{BASE}/how-we-rank/">How we rank</a> · <a href="{BASE}/scoreboard/">Scoreboard</a> · <a href="{BASE}/archive/">Archive</a> · <a href="{BASE}/beta-archive/">Beta archive (Oct 2026)</a> · <a href="{BASE}/feed.xml">RSS</a> · © {TODAY.year} {BRAND}</p></div></footer>{stickybar()}<script src="{BASE}/live.js" defer></script></body></html>"""
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
<div><span class="lbl">Since pick</span><span data-k="ret">{chip(p.get('ret'),p.get('final'))}</span></div></div>{linemove(p)}"""
def linemove(p):
    """Sports only, before settlement: did the market move toward or away from Max's price since the call?
    Beating the closing line is a better signal than one game's W/L. live.js repaints [data-lm] every minute."""
    if p.get('kind')!='Sports' or p.get('action','BUY')!='BUY': return ''
    return f'<p class="lm" data-lm="{p["id"]}" data-entry="{p["entry"]}"{"" if (p.get("cur") is not None and not p.get("final")) else " hidden"}>{lm_txt(p["entry"],p.get("cur"))}</p>'
def lm_txt(e,c):
    if c is None: return ''
    d=round((c-e)*100,1)
    if d>=0.5: return f'📈 <b class="up">Line moved our way</b> · {e*100:.1f}¢ → {c*100:.1f}¢ (+{d:.1f}¢) since Max called it. The market agrees, for now.'
    if d<=-0.5: return f'📉 <b class="dn">Line moved against us</b> · {e*100:.1f}¢ → {c*100:.1f}¢ ({d:.1f}¢) since Max called it. We show this one too.'
    return f'↔ <b>Line hasn\'t budged</b> · still {c*100:.1f}¢, same as Max\'s price.'
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
    href='https://x.com/intent/post?'+urllib.parse.urlencode({'text':txt,'url':u})
    return f'<a class="shr" href="{E(href)}" target="_blank" rel="noopener" data-share-id="{p["id"]}" data-share-what="{E(what)}" data-share-url="{E(u)}" aria-label="Share {E(what)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.8 7.8L23 22h-6.2l-4.8-6.3L6.4 22H3.3l7.3-8.3L1 2h6.3l4.4 5.8zm-1.1 18h1.7L6.3 3.9H4.5z"/></svg>Share</a>'
def ext_quote(sym):
    """Latest pre-market or after-hours trade vs the last regular-session close (Yahoo includePrePost), or None
    during regular hours / when nothing has traded outside the session yet. Used for earnings-night reaction lines."""
    def f():
        r=get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=1d&includePrePost=true")['chart']['result'][0]
        m=r['meta']; tp=m.get('currentTradingPeriod') or {}; reg=tp.get('regular') or {}
        pts=[(t,c) for t,c in zip(r.get('timestamp',[]),r['indicators']['quote'][0]['close']) if c is not None]
        if not pts or not reg: return None
        t,c=pts[-1]
        if t>=reg['end']: kind='After hours'
        elif t<reg['start']: kind='Pre-market'
        else: return None
        base=m.get('regularMarketPrice') if kind=='After hours' else (m.get('chartPreviousClose') or m.get('previousClose'))
        if not base: return None
        return {'kind':kind,'px':c,'base':base,'t':t,'chg':(c-base)/base}
    return memo(('yx',sym),f)
def reaction(p):
    """Post-earnings reaction for an open call: the after-hours / next-morning pre-market move right after the print
    (Yahoo extended hours), else the move since the report-day close once regular trading resumes. Same math as the
    Catalyst watch box. Returns {'kind','px','base','chg','schg','edge','t'} or None (no report yet / no data)."""
    c=p.get('catalyst')
    if not c or p.get('final'): return None
    d=datetime.date.fromisoformat(c['date']); n=(d-TODAY).days; after='after' in c.get('when',''); sym=p['symbol'].upper()
    pre=NOW.time()<datetime.time(9,30)
    if (n==0 and ((after and NOW.time()>=datetime.time(16,0)) or (not after and pre))) or (n==-1 and after and pre and NOW.weekday()<5):
        x=ext_quote(sym); xs=ext_quote('SPY')
        if x and abs(x['chg'])>0.0001:
            sc=(xs or {}).get('chg') or 0
            return {'kind':x['kind'],'px':x['px'],'base':x['base'],'chg':x['chg'],'schg':sc,'edge':x['chg']-sc,'t':x['t']}
    if n<0:
        base=d if after else d-datetime.timedelta(days=1)
        pc,_=stock_close_on(sym,base); sc,_=stock_close_on('SPY',base)
        cur=p.get('cur'); spy=(today_open_stock('SPY') or {}).get('last')
        if pc and sc and cur and spy:
            m=(cur-pc)/pc; sm=(spy-sc)/sc
            return {'kind':'Since the report','px':cur,'base':pc,'chg':m,'schg':sm,'edge':m-sm,'t':None}
    return None
def print_line(c):
    """'The print' line: headline results typed in from a cited source (catalyst.result), never computed."""
    r=(c or {}).get('result')
    if not r: return ''
    v=r.get('verdict','').upper(); vc={'BEAT':'up','MISS':'dn'}.get(v,'')
    src=r.get('source') or {}
    return (f'<p class="cxpost cxprint {vc}"><span class="cxl">\U0001F4CA The print{f" · {E(v)}" if v else ""}:</span> {E(r["line"])}'
            +(f' <a href="{E(src["url"])}" rel="nofollow noopener" target="_blank">{E(src.get("name","Source"))} ↗</a>' if src.get('url') else '')+'</p>')
def catalyst_box(p):
    """Earnings/catalyst watch on an open stock call: date countdown, what makes the call right or wrong, and once the
    report is out, the real post-report move vs the S&P 500 (from the report-day close), so results can be posted fast."""
    c=p.get('catalyst')
    if not c or p.get('final'): return ''
    d=datetime.date.fromisoformat(c['date']); n=(d-TODAY).days; day=d.strftime('%a %b %-d'); wh=c.get('when','')
    sym=p['symbol'].upper(); after='after' in wh
    post=print_line(c) if n<=0 else ''
    if n>0: cd='tomorrow' if n==1 else f'in {n} days'; st=f'{day} {wh} \u00b7 {cd}'
    elif n==0: st=f'Today {wh}' if not (after and NOW.time()>=datetime.time(16,0)) else f'Out now ({day} {wh}) \u00b7 the reaction trades at tomorrow\'s open'
    else:
        st=f'Reported {day} {wh}'
        base=d if after else d-datetime.timedelta(days=1)
        pc,_=stock_close_on(sym,base); sc,_=stock_close_on('SPY',base)
        cur=p.get('cur'); spy=(today_open_stock('SPY') or {}).get('last')
        if pc and sc and cur and spy:
            m=(cur-pc)/pc; sm=(spy-sc)/sc; e=m-sm; cls='up' if e>=0 else 'dn'
            post=(f'<p class="cxpost {cls}"><span class="cxl">Since the report:</span> {sym} ${pc:,.2f} \u2192 ${cur:,.2f} ({m*100:+.1f}%) vs the S&amp;P {sm*100:+.1f}% '
                  f'= <b>{e*100:+.1f} pts</b>. The 3-month grade is still the one that counts.</p>')
    # Earnings-night reaction: the after-hours (or next-morning pre-market) move right after the print, vs SPY's own
    # extended-hours move. Unofficial; the 3-month grade is untouched.
    pre=NOW.time()<datetime.time(9,30)
    if (n==0 and ((after and NOW.time()>=datetime.time(16,0)) or (not after and pre))) or (n==-1 and after and pre and NOW.weekday()<5):
        x=ext_quote(sym); xs=ext_quote('SPY')
        if x and abs(x['chg'])>0.0001:
            e=x['chg']-((xs or {}).get('chg') or 0); cls='up' if e>=0 else 'dn'
            ref="today's" if x['kind']=='After hours' else "the last"
            post+=(f'<p class="cxpost cxah {cls}"><span class="cxl">\u26A1 {x["kind"]} reaction</span> ({datetime.datetime.fromtimestamp(x["t"]).strftime("%-I:%M %p ET")}): '
                   f'{sym} ${x["px"]:,.2f} ({x["chg"]*100:+.1f}% vs {ref} ${x["base"]:,.2f} close)'
                   +(f', S&amp;P {xs["chg"]*100:+.1f}%, so <b>{e*100:+.1f} pts</b>' if xs else f' <b>{x["chg"]*100:+.1f}%</b>')
                   +'. Thin extended-hours trading, so this can swing a lot by the open; updates every 30 minutes.</p>')
    li=lambda xs: ''.join(f'<li>{E(x)}</li>' for x in xs)
    return (f'<section class="cx"><div class="cxh"><span class="cxk">\U0001F4C5 Catalyst watch</span><b>{E(c["event"])}</b><span class="cxd">{E(st)}</span></div>{post}'
            f'<div class="cxg"><div class="cxr"><h4>\u2705 Right if</h4><ul>{li(c.get("right",[]))}</ul></div><div class="cxw"><h4>\u274C Wrong if</h4><ul>{li(c.get("wrong",[]))}</ul></div></div>'
            +(f'<p class="cxm"><b>Max Edge:</b> {E(c["max"])}</p>' if c.get('max') else '')+'</section>')
def fin_card(p,rank):
    a=p['action'].lower()
    return f"""<article class="card fc {a}"><div class="ctop">{f'<span class="rank">#{rank}</span>' if rank else ''}<span class="hz">⏱ {E(p['horizon'])}</span>{badge(p)}</div>
<div class="crow"><span class="act {a}">{p['action']}</span><a class="tk" href="{BASE}/ticker/{p['tslug']}/">{E(p['label'])}</a>{spark(p.get('pts'),110,32)}</div>{livebox(p)}{breakdown(p)}
{f'<p class="why"><b>Buy and hold 3 months</b> · entry ${p["entry"]:,.2f} · target ${p["target_price"]:,.2f} · graded vs the S&amp;P 500 at {(datetime.date.fromisoformat(p["id"][:10])+datetime.timedelta(days=91)).strftime("%b %-d")}</p>' if p['horizon']=='3 Month' and p.get("target_price") else ''}<p class="why"><b>Why {p['action']}:</b> {E(p['why'])}</p><p class="risk">⚠ {E(p['risk'])}</p>{catalyst_box(p)}<div class="cfoot"><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a><span class="cfr">{share(p)}<a class="more" href="{BASE}/picks/{p['id']}/">Details →</a></span></div></article>"""
def sp_card(p,rank):
    m=p.get('m'); bars=''
    if m:
        bars='<div class="match">'+''.join(f'<div class="team {"pick" if i==p["outcome"] else ""}"><span class="tn">{E(o)}</span><span class="tp" {"data-k=pp" if i==p["outcome"] else ""}>{pr*100:.0f}%</span></div>' for i,(o,pr) in enumerate(zip(m['outcomes'],m['prices'])))+'</div>'
        if len(m['prices'])==2: bars+=f'<div class="pbar" role="img" aria-label="{E(m["outcomes"][0])} {m["prices"][0]*100:.0f}%, {E(m["outcomes"][1])} {m["prices"][1]*100:.0f}%"><span style="width:{m["prices"][0]*100:.1f}%"></span></div>'
    ko=kickoff(p)
    when=('Tonight' if ko and ko.hour>=17 else 'Today') if p.get('event_date')==TODAY.isoformat() else ('Event '+datetime.date.fromisoformat(p['event_date']).strftime('%b %-d') if p.get('event_date') else 'Futures')
    vol=f'<span class="vol">${m["volume"]/1e6:.1f}M vol</span>' if m and m['volume']>=1e5 else ''
    return f"""<article class="card sc"><div class="ctop">{f'<span class="rank">#{rank}</span>' if rank else ''}<span class="hz">🏟 {E(when)}</span>{badge(p)}</div>
{'<p class="bold-bet" style="margin:4px 0;font-weight:900;color:#ffb020">🔥 Max Edge\'s Bold Bet of the Day</p>' if p.get('bold') else ''}<a class="mkt" href="{BASE}/ticker/{p['tslug']}/">{E(p['market'])}</a>{bars}{gd(p)}
<div class="crow"><span class="act buy">BUY</span><span class="tk sm">{E(p['label'])}</span>{vol}{spark(p.get('pts'),100,30)}</div>{livebox(p)}{breakdown(p)}{verdict(p)}{book_line(p)}
<p class="why"><b>Why BUY:</b> {E(p['why'])}</p><div class="cfoot"><a class="src" href="{E(p['source']['url'])}" rel="nofollow noopener" target="_blank">{E(p['source']['name'])} ↗</a><span class="cfr">{share(p)}<a class="more" href="{BASE}/picks/{p['id']}/">Details →</a></span></div></article>"""
def tape(ed):
    it=''.join(f'<span class="ti"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} <i>${p["entry"]:,.2f}</i> {chip(p.get("ret"))}</span>' for p in ed['finance'])
    it+=''.join(f'<span class="ti"><b class="buy">BUY</b> {E(p["label"])} <i>{p["entry"]*100:.1f}¢</i></span>' for p in ed['sports'])
    return f'<div class="tape" aria-label="Today\'s picks"><div class="track">{it}{it}</div></div>'
def open3(upto=None):
    return [p for e in ALLEDS if e['date']>=LAUNCH and (upto is None or e['date']<=upto) for p in e['finance'] if p['horizon']=='3 Month' and not p.get('final')]
def hero(ed,nice):
    oc=[p for p in open3(ed['date']) if p.get('ret') is not None]
    best=None if ed['finance'] or not oc else max(oc,key=lambda p:p['ret'])
    top=(ed['finance'] or ([best] if best else open3(ed['date'])) or [None])[0]
    if top is None: return f'<section class="hero"><div class="mesh" aria-hidden="true"></div><div class="wrap hgrid"><div><p class="date"><span class="live"></span>{nice}</p><h1>{E(ed.get("top_call") or ed["headline"])}</h1><p class="tag">{E(TAG)}</p>{sform("hero")}</div></div>{tape(ed)}</section>'
    return f"""<section class="hero"><div class="mesh" aria-hidden="true"></div><div class="wrap hgrid"><div>
<p class="date"><span class="live"></span>{nice}</p><h1>{E(ed.get('top_call') or ed['headline'])}</h1><p class="tag">{E(TAG)}</p>
{sform('hero')}<div class="jump"><a href="#finance">💰 Money moves</a><a href="#ai">🤖 AI</a><a href="#sports">🏟 Sports markets</a></div></div>
<aside class="topcall {top['action'].lower()}"><span class="tlbl">{'Top call today' if not best else 'Best open call · no new call today'}</span><div class="crow"><span class="act {top['action'].lower()}">{top['action']}</span><span class="tk">{E(top['label'])}</span></div>
{f'<span class="price"><b class="{"up" if best["ret"]>=0 else "dn"}" data-edge="{best["id"]}">{best["ret"]*100:+.1f} pts</b></span><p class="tsub">vs the S&amp;P 500 · day {min(91,(datetime.date.fromisoformat(ed["date"])-datetime.date.fromisoformat(best["id"][:10])).days+1)} of 91 · entry ${best["entry"]:,.2f}</p>' if best else f'<span class="price">${top["entry"]:,.2f}</span>'}{spark(top.get('pts'),220,56)}<p>{E(top['why'])}</p>{'<a class="tsa" href="'+BASE+'/3-month-stock-picks/">All open 3-month calls vs the S&amp;P →</a>' if best else chip(top.get('ret'))}</aside></div>{tape(ed)}</section>"""
def recap(prev):
    if not prev: return '<div class="recap"><div><span class="kicker">📬 Yesterday\'s results</span><p>Day 1 of Max Edge, our AI handicapper. Every pick is graded in public from today; results start tomorrow. Every pick is tracked on the <a href="'+BASE+'/track-record/">Track record</a>.</p></div><div class="tmr">⏰ Come back tomorrow at <b>7 AM ET</b> for the next five.<span class="tmc">Next edition in <b class="nxc">a few hours</b></span></div></div>'
    ps=prev['finance']+prev['sports']; rs=[p['ret'] for p in ps if p.get('ret') is not None]
    items=''.join(f'<a href="{BASE}/picks/{p["id"]}/" class="rc"><b class="{p["action"].lower()}">{p["action"]}</b> {E(p["label"])} {chip(p.get("ret"),p.get("final"))}</a>' for p in ps)
    summ=f'{sum(r>0 for r in rs)}/{len(rs)} winning · avg {pct(sum(rs)/len(rs)) if rs else "—"}' if ps else 'No picks (nothing cleared our bar)'
    ln=prev.get('lean') if not prev['sports'] else None
    if ln: items+=f'<a href="{BASE}/scoreboard/#leans" class="rc"><b class="buy">LEAN</b> Max\'s lean (not a pick): {E(ln["label"])} {chip(ln.get("ret"),ln.get("final"))}</a>'
    return f'<div class="recap"><div><span class="kicker">📬 Yesterday\'s results ({prev["date"]})</span><p><b>{summ}</b></p><div class="rcs">{items}</div></div><div class="tmr">⏰ Come back tomorrow at <b>7 AM ET</b> for the next five.<span class="tmc">Next edition in <b class="nxc">a few hours</b></span></div></div>'
def today_strip(ps,where='home',settled=None):
    """'Today so far' running P/L strip for open picks. live.js recomputes it every minute."""
    op=[p for p in ps if not p.get('final')]; rs=[p for p in op if p.get('ret') is not None]
    st=[p for p in (settled or []) if p.get('final') and p.get('ret') is not None]
    if not op:  # no open same-day picks: show the open 3-month calls' live edge vs the S&P instead of "0 up 0 down of 0 open"
        oc=sorted([p for p in open3() if p.get('ret') is not None],key=lambda p:-p['ret'])
        if not oc and not st: return ''
        if oc: return today3(oc,where,st)
    up=sum(p['ret']>0 for p in rs); dn=sum(p['ret']<0 for p in rs); avg=sum(p['ret'] for p in rs)/len(rs) if rs else None
    so=[p['so'] for p in op if p.get('so') is not None]; aso=sum(so)/len(so) if so else None
    best=max(rs,key=lambda p:p['ret']) if rs else None; worst=min(rs,key=lambda p:p['ret']) if rs else None
    ids=json.dumps({p['id']:p['label'] for p in op})
    lab=lambda p: f'{E(p["label"])} {chip(p["ret"])}' if p else '—'
    sett=(f'<span class="tsc set"><small>settled</small> '+' '.join(f'<a href="{BASE}/picks/{p["id"]}/">{E(p["label"])} {chip(p["ret"],True)}</a>' for p in st)+'</span>') if st else ''
    return (f'<div class="tsf {where}" id="tsf" data-picks="{E(ids)}" aria-live="polite"><span class="tsl"><span class="live"></span><span data-t="lbl">Today so far</span></span>'
            f'<span class="tsc"><b class="up" data-t="up">▲ {up}</b> up <b class="dn" data-t="dn">▼ {dn}</b> down <small>of {len(op)} open</small></span>'
            f'<span class="tsc"><small>avg since pick</small> <span data-t="avg">{mv(avg)}</span></span>'
            f'<span class="tsc"><small>avg today</small> <span data-t="so">{mv(aso)}</span></span>'
            f'<span class="tsc"><small>best</small> <span data-t="best">{lab(best)}</span></span>'
            f'<span class="tsc"><small>worst</small> <span data-t="worst">{lab(worst)}</span></span>{sett}'
            f'<span class="tsc nx"><small>next edition</small> <b class="nxc">7 AM ET</b></span><span class="tsc mk" data-t="mk" hidden></span></div>')
def today3(oc,where,st=()):
    """No-pick-day fallback for the 'Today so far' strip: open 3-month calls vs the S&P 500 (live.js repaints #tsf3 from live.json)."""
    ah=sum(p['ret']>0 for p in oc); b,w=oc[0],oc[-1]
    pts=lambda p: f'<a href="{BASE}/picks/{p["id"]}/">{E(p["label"])} <b class="{"up" if p["ret"]>=0 else "dn"}" data-edge="{p["id"]}">{p["ret"]*100:+.1f} pts</b></a>'
    quip=('No fresh picks today, so the 3-month calls get the mic. They\'re handling it.' if ah*2>len(oc) else 'No fresh picks today. The 3-month calls are building character.')
    sett=(f'<span class="tsc set"><small>settled</small> '+' '.join(f'<a href="{BASE}/picks/{p["id"]}/">{E(p["label"])} {chip(p["ret"],True)}</a>' for p in st)+'</span>') if st else ''
    ids=json.dumps({p['id']:p['label'] for p in oc})
    return (f'<div class="tsf t3 {where}" id="tsf3" data-ids="{E(ids)}" data-base="{BASE}" aria-live="polite"><span class="tsl"><span class="live"></span><span>📈 3-month calls vs the S&amp;P</span></span>'
            f'<span class="tsc"><b class="{"up" if ah else "dn"}" data-t3="ah">{ah} of {len(oc)}</b> open calls beating the S&amp;P</span>'
            f'<span class="tsc"><small>best</small> <span data-t3="best">{pts(b)}</span></span>'
            +(f'<span class="tsc"><small>worst</small> <span data-t3="worst">{pts(w)}</span></span>' if len(oc)>1 else '')+sett+
            f'<span class="tsc q"><i data-t3="q">{quip}</i></span>'
            f'<span class="tsc"><a class="t3a" href="{BASE}/3-month-stock-picks/">All calls →</a></span>'
            f'<span class="tsc nx"><small>next edition</small> <b class="nxc">7 AM ET</b></span></div>')
ALLEDS=[]  # all editions, newest first (set in main before pages render)
def _cb_show(ed):
    """Closing-bell recap shows on the newest edition once today's stock session is over (4:15 PM ET, when exits freeze),
    and stays up overnight until the next 7 AM edition replaces it."""
    if not ALLEDS or ed is not ALLEDS[0]: return False
    d=datetime.date.fromisoformat(ed['date'])
    if d<TODAY: return True
    return d==TODAY and NOW.time()>=datetime.time(16,15)
def closing_bell(ed):
    """'How today's picks finished': picks that settled on this edition's day (stock exits at that close + sports games
    that went final), today's stock calls marked at the close, games still to play, and tomorrow's 7 AM hook + signup.
    Real settled exits / final scores and real Yahoo/Polymarket marks only."""
    if not _cb_show(ed): return ''
    S=ed['date']; sd=datetime.date.fromisoformat(S); trade=sd.weekday()<5
    st_s=[(p,e) for e in ALLEDS for p in e['finance'] if p.get('final') and p.get('ret') is not None and p.get('note')==f'closed {S}']
    st_g=[(p,e) for e in ALLEDS for p in e['sports'] if p.get('final') and p.get('ret') is not None and kickoff(p) and kickoff(p).date()==sd]
    st=st_s+st_g
    todo=[p for p in ed['sports']+[q for e in ALLEDS[1:] for q in e['sports']] if not p.get('final') and kickoff(p) and kickoff(p).date()==sd]
    seen=set(); todo=sorted([p for p in todo if not (p['slug'] in seen or seen.add(p['slug']))],key=kickoff)
    mk=[p for p in ed['finance'] if p.get('ret') is not None] if trade else []
    for p in mk:  # mark today's calls at the real daily close bar (same Yahoo read that freezes exits), not the last intraday quote
        c,cd=stock_close_on(p['symbol'],sd) if not p.get('final') else (None,None)
        if c is not None and cd==S: p['cb_cur']=c; p['cb_ret']=(c-p['entry'])/p['entry']*(-1 if p['action']=='SELL' else 1)
    if not st and not mk and not todo: return ''
    def row(p,e,kind):
        a=p['action'].lower()
        if kind=='s': det=f'<small>{money("F",p["entry"])} \u2192 <b>{money("F",p["cur"])}</b> close \u00b7 {E(p["horizon"])} call from {datetime.date.fromisoformat(e["date"]).strftime("%b %-d")}</small>'
        elif kind=='g':
            fl=final_line(p); det=f'<small>{"Final " + fl[0] + " \u00b7 " if fl else ""}{money("Sports",p["entry"])} \u2192 {money("Sports",p["cur"])}</small>'
        else: det=f'<small>{money("F",p["entry"])} \u2192 <b>{money("F",p.get("cb_cur",p["cur"]))}</b> at the close \u00b7 {"exits at the next close" if p["horizon"]=="1 Day" else "open, "+E(p["horizon"])}</small>'
        res=('<i class="wl w">W</i>' if p['ret']>0 else '<i class="wl l">L</i>' if p['ret']<0 else '<i class="wl">P</i>') if kind!='m' else ''
        return f'<a class="cbr" href="{BASE}/picks/{p["id"]}/">{res}<b class="act {a}">{p["action"]}</b><span class="cbn">{E(p["label"])}{det}</span>{chip(p.get("cb_ret",p["ret"]) if kind=="m" else p["ret"],kind!="m")}</a>'
    w_=sum(p['ret']>0 for p,_ in st); l_=sum(p['ret']<0 for p,_ in st); avg=sum(p['ret'] for p,_ in st)/len(st) if st else None
    R=lambda p: p.get('cb_ret',p['ret']); up=sum(R(p)>0 for p in mk); dn=sum(R(p)<0 for p in mk); mavg=sum(R(p) for p in mk)/len(mk) if mk else None
    tl=lambda v: 'up' if (v or 0)>0 else 'dn' if (v or 0)<0 else ''
    tiles=''
    if st: tiles+=f'<div class="cbt"><span>Settled {"today" if sd==TODAY else sd.strftime("%b %-d")}</span><b class="{tl(avg)}">{w_}-{l_}</b><small>avg {pct(avg)} per pick</small></div>'
    if mk: tiles+=f'<div class="cbt"><span>Today\'s stock calls at the close</span><b class="{tl(mavg)}">{up}\u25b2 {dn}\u25bc</b><small>avg {pct(mavg)} since pick</small></div>'
    if STK: tiles+=f'<a class="cbt" href="{BASE}/stock-results/"><span>Stocks, all settled</span><b class="{tl(STK["avg"])}">{STK["w"]}-{STK["l"]}</b><small>avg {pct(STK["avg"])} \u2192</small></a>'
    if SPR: tiles+=f'<a class="cbt" href="{BASE}/sports-results/"><span>Sports, all settled</span><b class="{tl(SPR["avg"])}">{SPR["w"]}-{SPR["l"]}</b><small>avg {pct(SPR["avg"])} \u2192</small></a>'
    cols=''
    if st: cols+='<div class="cbc"><h3>\u2705 Settled '+('today' if sd==TODAY else sd.strftime('%b %-d'))+'</h3>'+''.join(row(p,e,'s') for p,e in st_s)+''.join(row(p,e,'g') for p,e in st_g)+'</div>'
    if mk: cols+='<div class="cbc"><h3>\U0001F4C8 Today\'s stock calls at the close</h3>'+''.join(row(p,ed,'m') for p in mk)+'</div>'
    if todo: cols+='<div class="cbc"><h3>\U0001F3DF Still playing tonight</h3>'+''.join(f'<a class="cbr" href="{BASE}/picks/{p["id"]}/"><b class="act buy">BUY</b><span class="cbn">{E(p["label"])}<small>{E(p["market"].split(",")[0])} \u00b7 {"\U0001F534 live now" if kickoff(p)<=datetime.datetime.now().astimezone() else kickoff(p).strftime("%-I:%M %p ET")} \u00b7 now {money("Sports",p.get("cur"))}</small></span>{chip(p.get("ret"))}</a>' for p in todo)+'<p class="cbn2">These settle on the final score overnight; the scores update live on the cards below.</p></div>'
    when=sd.strftime('%A, %b %-d')
    return (f'<section class="cbell" id="closing-bell" aria-labelledby="cbh"><div class="cbhd"><span class="kicker">\U0001F514 Closing bell \u00b7 {when}</span>'
            f'<h2 id="cbh">How {"today" if sd==TODAY else when.split(",")[0]}\u2019s picks finished</h2>'
            f'<p class="sub">Real closing prices from Yahoo Finance and final scores from Polymarket. Stock exits freeze at 4:15 PM ET; nothing is hand-entered.</p></div>'
            f'<div class="cbts">{tiles}</div><div class="cbcols">{cols}</div>'
            f'<div class="cbcta"><div><b>\u23f0 Tomorrow\'s five drop at 7 AM ET.</b><span class="tmc">Next edition <b class="nxc">at 7 AM ET</b></span><p>Get them before the opening bell, with yesterday\'s results graded, free.</p></div>{sform("bell")}</div></section>')
def mp4_secs(path):
    """Duration in seconds from the MP4 mvhd atom (no ffprobe needed in CI)."""
    try:
        import struct
        b=open(path,'rb').read(); i=b.find(b'mvhd')
        if i<0: return None
        ver=b[i+4]
        if ver==1: ts,du=struct.unpack('>IQ',b[i+24:i+36])
        else: ts,du=struct.unpack('>II',b[i+16:i+24])
        return du/ts if ts else None
    except Exception: return None
def clip_transcript(d):
    """[(banner, line)] from the clip's script (video/script-<d>.json), or [] if none was saved."""
    f=os.path.join(ROOT,'video',f'script-{d}.json')
    try: return [(g.get('banner',''),g['line']) for g in json.load(open(f)).get('segments',[]) if g.get('line')]
    except Exception: return []
CLIP_EDS={}  # date -> edition, filled by max_edge_hub so clip titles can name the day's story
def clip_meta(d):
    """(video title, description, watch-page path) for a Max Edge clip, specific to that day's edition when known."""
    ed=CLIP_EDS.get(d) or {}; nice=datetime.date.fromisoformat(d).strftime('%a %b %-d')
    hl=(ed.get('headline') or '').strip(); story=re.split(r',\s| and no Bold Bet| \| ',hl)[0].strip() if hl else ''
    if len(story)>110: story=story[:107].rsplit(' ',1)[0].rstrip(':,;')+'…'
    bb=next((p for p in ed.get('sports',[]) if p.get('bold')),None); ln=ed.get('lean')
    extra=(f" Bold Bet: {bb.get('label') or bb.get('outcome') or ''} at {money('Sports',bb.get('entry'))}." if bb
           else (f" No Bold Bet; Max's lean (not a bet): {ln.get('label','')} at {money('Sports',ln.get('entry'))}." if ln else ''))
    title=f"Max Edge, {nice}: {story}" if story else f"Max Edge: The Daily Five picks for {nice}"
    desc=(f"Max Edge, The Daily Five's AI-generated host, in under a minute. {(story.rstrip('.')+'.') if story else 'Today\'s calls.'}{extra} "
          f"3-month stock calls graded vs the S&P 500. Not financial advice. 21+.")
    return title,desc,f'/max-edge/{d}/'
def clip_html(d):
    v=os.path.join(ROOT,'clips',f'max-{d}.mp4')
    if not os.path.exists(v): return ''
    os.makedirs(os.path.join(OUT,'video'),exist_ok=True)
    for x in ('mp4','jpg'):
        f=os.path.join(ROOT,'clips',f'max-{d}.{x}')
        if os.path.exists(f): shutil.copy(f,os.path.join(OUT,'video',f'max-{d}.{x}'))
    dur=mp4_secs(v); iso=f'PT{round(dur)//60}M{round(dur)%60}S' if dur else None
    vt,vdsc,vp=clip_meta(d)
    vo={'@context':'https://schema.org','@type':'VideoObject','name':vt,'description':vdsc,'url':SITE+vp,
        'thumbnailUrl':[f'{SITE}/video/max-{d}.jpg'],'uploadDate':f'{d}T07:00:00-04:00','contentUrl':f'{SITE}/video/max-{d}.mp4',
        'publisher':{'@type':'Organization','name':'The Daily Five','url':SITE}}
    if iso: vo['duration']=iso
    tr=clip_transcript(d)
    if tr: vo['transcript']=' '.join(l for _,l in tr)
    ld='<script type="application/ld+json">'+json.dumps(vo).replace('</','<\\/')+'</script>'
    secs=f'{round(dur)}-second ' if dur else ''
    # muted preview autoplays only while the clip is on screen; one tap turns sound on and restarts it
    js=("<script>(function(){var v=document.getElementById('mxv'),b=document.getElementById('mxs');if(!v)return;"
        "if('IntersectionObserver'in window&&!matchMedia('(prefers-reduced-motion: reduce)').matches){new IntersectionObserver(function(e){e.forEach(function(x){if(x.isIntersecting&&x.intersectionRatio>=.6){if(v.muted)v.play().catch(function(){})}else if(v.muted)v.pause()})},{threshold:[0,.6]}).observe(v)}"
        "b.onclick=function(){v.muted=false;v.currentTime=0;v.play();b.style.display='none'};v.addEventListener('volumechange',function(){if(!v.muted)b.style.display='none'})})()</script>")
    return ld+(f'<figure class="maxclip" style="margin:16px auto;max-width:360px;text-align:center"><h2 style="font-size:1.05em;margin:0 0 8px">🎙️ Max Edge\'s {secs}rundown: today\'s calls + the Bold Bet</h2>'
            f'<div style="position:relative"><video id="mxv" controls playsinline muted loop preload="metadata" poster="{BASE}/video/max-{d}.jpg" style="width:100%;border-radius:14px;background:#000;display:block" src="{BASE}/video/max-{d}.mp4"></video>'
            f'<button type="button" id="mxs" style="position:absolute;top:10px;right:10px;border:0;border-radius:999px;padding:6px 12px;font-weight:700;background:rgba(0,0,0,.7);color:#fff;cursor:pointer">🔊 Tap for sound</button></div>'
            f'<figcaption class="sub" style="font-size:.85em">Max Edge, {d}. AI-generated host. Not financial advice. 21+. <a href="{BASE}{vp}">Share this clip</a> \u00b7 <a href="{BASE}/max-edge/">Every Max Edge clip \u2192</a></figcaption>'
            +(('<details class="mxtr" style="text-align:left;margin-top:8px;font-size:.9em"><summary style="cursor:pointer;font-weight:700">📝 Read the transcript (sound off? no problem)</summary>'
               +''.join(f'<p style="margin:8px 0"><b style="font-size:.8em;letter-spacing:.04em;opacity:.75">{E(b)}</b><br>{E(l)}</p>' for b,l in tr)+'</details>') if tr else '')
            +'</figure>'+js)
def clip_og(d):
    """Per-clip share card (1200x630) for /max-edge/<date>/: the clip's thumbnail with a play badge, the day's story and the Bold Bet or lean."""
    thumb=os.path.join(ROOT,'clips',f'max-{d}.jpg')
    if not os.path.exists(thumb): return None
    import base64, textwrap, hashlib
    b64=base64.b64encode(open(thumb,'rb').read()).decode()
    ed=CLIP_EDS.get(d) or {}; vt,_,_=clip_meta(d); story=vt.split(': ',1)[-1]
    dur=mp4_secs(os.path.join(ROOT,'clips',f'max-{d}.mp4'))
    lines=textwrap.wrap(story,30)
    if len(lines)>4: lines=lines[:4]; lines[3]=lines[3].rstrip('.,;: ')+'…'
    fs=46 if len(lines)<=3 else 40
    bb=next((p for p in ed.get('sports',[]) if p.get('bold')),None); ln=ed.get('lean')
    if bb: tag,tc,tx=('BOLD BET','#ffb020',f"{bb.get('label') or bb.get('outcome') or ''} at {money('Sports',bb.get('entry'))}")
    elif ln: tag,tc,tx=("MAX'S LEAN",'#a48bff',f"{ln.get('label','')} at {money('Sports',ln.get('entry'))} (not a bet)")
    else: tag,tc,tx=('3-MONTH CALLS','#16c784','graded vs the S&P 500')
    logo=LOGO.replace('class="mark" ','').replace(' width="34" height="34"','').replace('<svg ','<svg width="40" height="40" ')
    tw=298; th=530; x0=70; y0=50
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1200" height="630" viewBox="0 0 1200 630"><defs><radialGradient id="a" cx=".12" cy=".1" r=".75"><stop offset="0" stop-color="#7c5cff" stop-opacity=".45"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient><radialGradient id="b" cx=".92" cy=".85" r=".7"><stop offset="0" stop-color="#ffb020" stop-opacity=".3"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient>'
         f'<clipPath id="c"><rect x="{x0}" y="{y0}" width="{tw}" height="{th}" rx="22"/></clipPath></defs>'
         f'<rect width="1200" height="630" fill="#07080d"/><rect width="1200" height="630" fill="url(#a)"/><rect width="1200" height="630" fill="url(#b)"/>'
         f'<image href="data:image/jpeg;base64,{b64}" xlink:href="data:image/jpeg;base64,{b64}" x="{x0}" y="{y0}" width="{tw}" height="{th}" preserveAspectRatio="xMidYMid slice" clip-path="url(#c)"/>'
         f'<rect x="{x0}" y="{y0}" width="{tw}" height="{th}" rx="22" fill="none" stroke="#2b3046" stroke-width="3"/>'
         f'<circle cx="{x0+tw/2}" cy="{y0+th/2}" r="52" fill="rgba(0,0,0,.6)" stroke="#fff" stroke-width="4"/><path d="M{x0+tw/2-16},{y0+th/2-28} L{x0+tw/2+30},{y0+th/2} L{x0+tw/2-16},{y0+th/2+28} Z" fill="#fff"/>'
         +(f'<rect x="{x0+tw-96}" y="{y0+th-50}" width="82" height="36" rx="10" fill="rgba(0,0,0,.75)"/><text x="{x0+tw-55}" y="{y0+th-25}" text-anchor="middle" font-family="Inter,Helvetica,Arial,sans-serif" font-size="20" font-weight="700" fill="#fff">{round(dur)//60}:{round(dur)%60:02d}</text>' if dur and dur<600 else '')+
         f'<g font-family="Inter,Helvetica,Arial,sans-serif"><g transform="translate(420,56) scale(1.4)">{logo}</g><text x="496" y="101" font-size="36" font-weight="800" fill="#fff">The Daily Five</text>'
         f'<text x="420" y="170" font-size="24" font-weight="700" fill="#ffb020" letter-spacing="3">MAX EDGE \u00b7 {E(datetime.date.fromisoformat(d).strftime("%a %b %-d").upper())}</text>'
         +''.join(f'<text x="420" y="{232+i*(fs+12)}" font-size="{fs}" font-weight="800" fill="#fff">{E(l)}</text>' for i,l in enumerate(lines))+
         f'<rect x="420" y="468" width="{18*len(tag)+40}" height="44" rx="22" fill="{tc}"/><text x="{440+9*len(tag)}" y="498" text-anchor="middle" font-size="22" font-weight="800" fill="#07080d" letter-spacing="1">{E(tag)}</text>'
         f'<text x="{450+18*len(tag)+20}" y="499" font-size="26" font-weight="700" fill="#e7e9f2">{E(tx[:46])}</text>'
         f'<text x="420" y="590" font-size="22" fill="#9ba3ba">AI-generated host \u00b7 Not advice</text><text x="1130" y="590" text-anchor="end" font-size="22" fill="#9ba3ba">readdailyfive.com</text></g></svg>')
    rel=f'og/max-edge/{d}'; w(rel+'.svg',svg)
    PICK_OG_JOBS.append((os.path.join(OUT,rel+'.svg'),os.path.join(OUT,rel+'.png')))
    return f"/{rel}.png?v={hashlib.sha1(svg.encode()).hexdigest()[:8]}"
def clip_now(d):
    """'Where Max's calls stand now' on a clip watch page: live boxes for the 3-month calls open as of that clip, plus that day's Bold Bet or lean.
    Keeps an old clip honest when its morning story goes stale (live.js repaints every .lv each minute)."""
    ed=CLIP_EDS.get(d) or {}; rows=''
    for p in open3(d):
        rows+=(f'<div class="cnow"><div class="cnh"><span class="mini {p["action"].lower()}">{p["action"]}</span> <a href="{BASE}/picks/{p["id"]}/"><b>{E(p["label"])}</b></a>'
               f' <small>3-month call from {datetime.date.fromisoformat(p["id"][:10]).strftime("%b %-d")} · graded vs the S&amp;P 500</small></div>{livebox(p)}</div>')
    bb=next((p for p in ed.get('sports',[]) if p.get('bold')),None); ln=None if ed.get('sports') else ed.get('lean'); sp=bb or ln
    if sp:
        tag='BOLD BET' if bb else "MAX'S LEAN · not a bet"; href=f'{BASE}/picks/{sp["id"]}/' if bb and sp.get('id') else f'{BASE}/scoreboard/#leans'
        if sp.get('final') and sp.get('ret') is not None:
            fl=final_line(sp); res=f'<p class="cnres">{"✅ Cashed" if sp["ret"]>0 else "❌ Missed"}{(" · "+fl[0]) if fl else ""} · {sp["ret"]*100:+.0f}% per $1 at {sp["entry"]*100:.1f}¢</p>'
        else: res=livebox(sp) if sp.get('id') else ''
        rows+=(f'<div class="cnow"><div class="cnh"><span class="mini buy">{tag}</span> <a href="{href}"><b>{E(sp.get("label",""))}</b></a> <small>at {sp["entry"]*100:.1f}¢</small></div>{res}</div>')
    if not rows: return ''
    return (f'<section class="clipnow" id="now"><h2>📡 Where Max\'s calls stand now</h2><p class="sub">This clip was recorded the morning of {datetime.date.fromisoformat(d).strftime("%b %-d")}. Markets moved since. '
            f'Live prices, last updated <b id="upd">{NOW.strftime('%-I:%M %p ET')}</b> (stocks via Yahoo Finance, may lag ~15 min; sports via Polymarket).</p>{rows}'
            f'<p class="sub"><a href="{BASE}/scoreboard/">Full scoreboard →</a></p></section>')
def max_edge_watch_pages(ds):
    """/max-edge/<date>/: one watch page per clip, the video as the main content (better for Google video results)."""
    for i,d in enumerate(ds):
        ed=CLIP_EDS.get(d) or {}; vt,vdsc,vp=clip_meta(d); nice=datetime.date.fromisoformat(d).strftime('%A, %B %-d, %Y')
        newer=ds[i-1] if i>0 else None; older=ds[i+1] if i+1<len(ds) else None
        cnav,csch=crumbs([('Home','/'),('Max Edge videos','/max-edge/'),(datetime.date.fromisoformat(d).strftime('%b %-d, %Y'),vp)])
        nav=('<div class="hubcta">'+(f'<a class="pill ghost" href="{BASE}/max-edge/{older}/">\u2190 Older clip</a>' if older else '')
             +f'<a class="pill" href="{BASE}/{d}/">Read the full {datetime.date.fromisoformat(d).strftime("%b %-d")} edition \u2192</a>'
             +(f'<a class="pill ghost" href="{BASE}/max-edge/{newer}/">Newer clip \u2192</a>' if newer else '')
             +f'<a class="pill ghost" href="{BASE}/scoreboard/">Scoreboard</a></div>')
        bodyh=(cnav+f'<section class="sbhero hubhero"><span class="kicker">\U0001F399\ufe0f Max Edge \u00b7 {nice}</span><h1 class="pt">{E(vt.split(": ",1)[-1])}</h1>'
               f'<p class="sub">{E(ed.get("top_call") or vdsc)}</p></section>'+clip_html(d)+clip_now(d)+nav
               +'<p class="disc-bar">\u26a0\ufe0f <b>Not financial or betting advice.</b> Max Edge is AI-generated. 21+.</p>')
        sch={'@context':'https://schema.org','@graph':[{'@type':'WebPage','name':vt,'url':SITE+vp,'isPartOf':{'@type':'WebSite','name':BRAND,'url':SITE+'/'}},csch]}
        og=clip_og(d) or (f'/og/{d}.png' if os.path.exists(os.path.join(OUT,'og',f'{d}.png')) else None)
        w(f'max-edge/{d}/index.html',shell(vt if len(vt)>62 else f'{vt} (60-sec video) | {BRAND}',vdsc[:160],vp,bodyh,sch,og=og))
def max_edge_hub(eds):
    """/max-edge/: every Max Edge daily clip in one place (latest playable on top, past clips linked to their editions)."""
    P='/max-edge/'; byd={e['date']:e for e in eds}; CLIP_EDS.update(byd)
    ds=sorted((os.path.basename(f)[4:14] for f in glob.glob(os.path.join(ROOT,'clips','max-*.mp4'))),reverse=True)
    if not ds: return None
    max_edge_watch_pages(ds)
    rows=''; items=[]
    for i,d in enumerate(ds):
        ed=byd.get(d) or {}; dur=mp4_secs(os.path.join(ROOT,'clips',f'max-{d}.mp4'))
        bb=next((p for p in ed.get('sports',[]) if p.get('bold')),None)
        nice=datetime.date.fromisoformat(d).strftime('%a, %b %-d, %Y')
        bbh=f'<span class="sub"> · Bold Bet: {E(bb.get("outcome") or "")} ({E(bb["market"])}) at {money("Sports",bb.get("entry"))}</span>' if bb else ''
        rows+=(f'<li style="display:flex;gap:12px;align-items:center;margin:10px 0"><a href="{BASE}/max-edge/{d}/"><img src="{BASE}/video/max-{d}.jpg" alt="Max Edge clip thumbnail, {nice}" width="72" height="128" loading="lazy" style="border-radius:8px;object-fit:cover;background:#000"></a>'
               f'<div><a href="{BASE}/max-edge/{d}/"><b>{nice}</b></a>{f" · {round(dur)} s" if dur else ""} · <a href="{BASE}/{d}/">edition</a><br>{E(ed.get("headline",""))}{bbh}</div></li>')
        vt,vdsc,vp=clip_meta(d)
        vo={'@type':'VideoObject','name':vt,'description':vdsc,
            'thumbnailUrl':[f'{SITE}/video/max-{d}.jpg'],'uploadDate':f'{d}T07:00:00-04:00','contentUrl':f'{SITE}/video/max-{d}.mp4','url':SITE+vp}
        if dur: vo['duration']=f'PT{round(dur)//60}M{round(dur)%60}S'
        items.append({'@type':'ListItem','position':i+1,'item':vo})
    desc=f'Watch Max Edge, The Daily Five\'s AI-generated host, call a 3-month stock pick and the Bold Bet of the Day in under a minute. New clip every morning; {len(ds)} so far, every call graded in public.'[:155]
    bodyh=(f'<section class="sbhero hubhero"><span class="kicker">🎙️ Max Edge</span><h1 class="pt">Max Edge: daily stock & sports picks in 60 seconds</h1>'
           f'<p class="sub">An AI-generated host (yes, clearly a bot, and proud of it) reads the day\'s 3-month stock calls and the Bold Bet of the Day. Every pick he says out loud lands on the <a href="{BASE}/scoreboard/">public scoreboard</a>, wins and faceplants alike.</p></section>'
           f'{clip_html(ds[0])}<h2>Every Max Edge clip</h2><ul style="list-style:none;padding:0">{rows}</ul>'
           f'<p class="disc-bar">⚠️ <b>Not financial or betting advice.</b> Max Edge is AI-generated. 21+.</p>')
    sch={'@context':'https://schema.org','@graph':[{'@type':'CollectionPage','name':'Max Edge daily picks videos','description':desc,'url':SITE+P,'isPartOf':{'@type':'WebSite','name':BRAND,'url':SITE+'/'}},
         {'@type':'ItemList','name':'Max Edge clips','itemListElement':items}]}
    w('max-edge/index.html',shell(f'Max Edge: Daily AI Stock & Sports Picks Video (60 Seconds) | {BRAND}',desc,P,bodyh,sch))
    return P
def verdict_svg(ops,rep):
    """Post-earnings verdict card (1200x630): per reported call, the headline result (BEAT/MISS from catalyst.result)
    and the reaction vs the S&P 500 (after hours / pre-market / since the report), then the live 3-month edge."""
    logo=LOGO.replace('class="mark" ','').replace(' width="34" height="34"','').replace('<svg ','<svg width="40" height="40" ')
    rows=''; y=236; best=None
    for p in ops[:3]:
        sym=p['symbol'].upper(); c=p.get('catalyst') or {}; x=rep.get(sym); res=c.get('result') or {}; r=p.get('ret')
        h=104 if x else 64
        rows+=f'<g transform="translate(70,{y})"><rect width="1060" height="{h-12}" rx="18" fill="#11131c" stroke="#232738" stroke-width="2"/>'
        rows+=f'<text x="24" y="{50 if x else 38}" font-family="monospace" font-size="38" font-weight="700" fill="#fff">{E(sym)}</text>'
        if x:
            v=(res.get('verdict') or '').upper(); vcol={'BEAT':'#16c784','MISS':'#ff4d5e'}.get(v,'#ffb020')
            if v: rows+=f'<rect x="150" y="18" width="{24+15*len(v)}" height="36" rx="18" fill="{vcol}"/><text x="{162+7.5*len(v)}" y="44" text-anchor="middle" font-size="20" font-weight="800" fill="#06130c">{E(v)}</text>'
            sh=res.get('short') or c.get('event','')
            rows+=f'<text x="{150+(40+15*len(v) if v else 0)}" y="44" font-size="24" font-weight="700" fill="#e6e9f2">{E(sh[:44])}</text>'
            ecol='#16c784' if x['edge']>=0 else '#ff4d5e'
            lab={'After hours':'After hours','Pre-market':'Pre-market','Since the report':'Since the report'}[x['kind']]
            rows+=(f'<text x="24" y="80" font-size="21" fill="#9ba3ba">{lab}: {sym} {x["chg"]*100:+.1f}% vs S&amp;P {x["schg"]*100:+.1f}%'
                   +(f' · 3-month edge {r*100:+.1f} pts' if r is not None else '')+'</text>')
            rows+=f'<text x="1036" y="62" text-anchor="end" font-size="40" font-weight="800" fill="{ecol}">{x["edge"]*100:+.1f} pts</text>'
            if best is None or x['edge']>best[1]: best=(sym,x['edge'])
        else:
            ecol='#16c784' if (r or 0)>0 else '#ff4d5e' if (r or 0)<0 else '#9ba3ba'
            rows+=f'<text x="150" y="38" font-size="22" font-weight="800" fill="#9ba3ba" letter-spacing="2">NO REPORT DUE</text><text x="1036" y="40" text-anchor="end" font-size="28" font-weight="800" fill="{ecol}">{(f"{r*100:+.1f} pts vs S&amp;P") if r is not None else "edge pending"}</text>'
        rows+='</g>'; y+=h
    nrep=len(rep); kinds={x['kind'] for x in rep.values()}
    es=[x['edge'] for x in rep.values()]
    quip=(f'"{best[0]} showed up with receipts. Victory lap pending (3 months to go)."' if best and best[1]>=0.02 else
          '"Well, that was educational. Good thing the grade is 3 months, not 3 hours."' if max(es)<=-0.02 else
          '"The market heard the numbers and shrugged. Rude, honestly."')
    head=('THE PRINTS ARE IN' if nrep>1 else 'THE PRINT IS IN')
    sub=('Reaction vs the S&amp;P 500 in after-hours trading' if kinds=={'After hours'} else 'Reaction vs the S&amp;P 500 in pre-market trading' if kinds=={'Pre-market'} else 'Move vs the S&amp;P 500 since the report')+f' · as of {E(NOW.strftime("%-I:%M %p ET"))}'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><defs><radialGradient id="a" cx=".12" cy=".1" r=".75"><stop offset="0" stop-color="#16c784" stop-opacity=".28"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient><radialGradient id="b" cx=".92" cy=".85" r=".7"><stop offset="0" stop-color="#7c5cff" stop-opacity=".5"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient></defs>'
         f'<rect width="1200" height="630" fill="#07080d"/><rect width="1200" height="630" fill="url(#a)"/><rect width="1200" height="630" fill="url(#b)"/><g font-family="Inter,Helvetica,Arial,sans-serif">'
         f'<g transform="translate(70,48) scale(1.4)">{logo}</g><text x="146" y="93" font-size="38" font-weight="800" fill="#fff">The Daily Five</text>'
         f'<text x="1130" y="93" text-anchor="end" font-size="24" font-weight="700" fill="#ffb020" letter-spacing="3">POST-EARNINGS VERDICT</text>'
         f'<text x="70" y="166" font-size="54" font-weight="800" fill="#fff">{E(head)}</text>'
         f'<text x="70" y="208" font-size="24" fill="#c9cede">{sub}</text>{rows}'
         +(f'<text x="70" y="{y+34}" font-size="24" font-style="italic" fill="#e6e9f2"><tspan font-weight="800" fill="#ffb020">Max Edge: </tspan>{E(quip)}</text>' if y+34<570 else '')+
         f'<text x="70" y="606" font-size="22" fill="#9ba3ba">One print doesn\'t settle a 3-month call · readdailyfive.com/earnings</text><text x="1130" y="606" text-anchor="end" font-size="22" fill="#9ba3ba">Not advice</text></g></svg>')
def reported(ops):
    """{SYM: reaction} for open calls whose report is out (report day after the print, or up to 5 days after)."""
    out={}
    for p in ops:
        c=p.get('catalyst')
        if not c: continue
        n=(datetime.date.fromisoformat(c['date'])-TODAY).days
        if -5<=n<=0:
            x=reaction(p)
            if x: out[p['symbol'].upper()]=x
    return out
def verdict_box(ops):
    """/earnings/ top box once a print is out: headline result + reaction vs the S&P per reported call."""
    rep=reported(ops)
    if not rep: return ''
    li=''
    for p in ops:
        sym=p['symbol'].upper(); x=rep.get(sym)
        if not x: continue
        res=(p.get('catalyst') or {}).get('result') or {}; cls='up' if x['edge']>=0 else 'dn'
        li+=(f'<li><b>{E(sym)}</b>'+(f' · {E(res.get("verdict","").upper())}: {E(res.get("short",""))}' if res else '')
             +f' · {x["kind"].lower()}: <span class="{cls}"><b>{x["edge"]*100:+.1f} pts</b></span> vs the S&amp;P ({x["chg"]*100:+.1f}% vs {x["schg"]*100:+.1f}%)</li>')
    return (f'<section class="cx vdbox"><div class="cxh"><span class="cxk">\U0001F9FE Post-earnings verdict</span><b>{"The prints are in" if len(rep)>1 else "The print is in"}</b>'
            f'<span class="cxd">as of {E(NOW.strftime("%-I:%M %p ET"))}</span></div><ul>{li}</ul>'
            f'<p class="cxm"><b>Max Edge:</b> One night of trading doesn\'t grade a 3-month call. It does decide whether I get to be insufferable at breakfast.</p>'
            f'<p class="why"><a href="{BASE}/og/verdict.png">Share the verdict card →</a></p></section>')
def earnings_og(ops):
    """Share card for /earnings/ (1200x630): each open call's next report date (TONIGHT / tomorrow / in N days / reported)
    and live edge vs the S&P 500, so links to the earnings page unfurl as an earnings-night scorecard, not the daily card."""
    logo=LOGO.replace('class="mark" ','').replace(' width="34" height="34"','').replace('<svg ','<svg width="40" height="40" ')
    rows=''
    for i,p in enumerate(ops[:4]):
        c=p.get('catalyst'); sym=p['symbol'].upper(); r=p.get('ret')
        if c:
            d=datetime.date.fromisoformat(c['date']); n=(d-TODAY).days
            tag=('TONIGHT' if 'after' in c.get('when','') else 'TODAY') if n==0 else 'TOMORROW' if n==1 else f'{d.strftime("%a %b %-d").upper()}' if n>1 else 'REPORTED'
            tcol='#ffb020' if n in (0,1) else '#c9cede'
            x=ext_quote(sym) if (n==0 and NOW.time()>=datetime.time(16,0)) or (n==-1 and NOW.time()<datetime.time(9,30)) else None
            if x and abs(x['chg'])>0.0001: tag=f'REPORTED · {"AH" if x["kind"]=="After hours" else "PRE"} {x["chg"]*100:+.1f}%'
        else: tag,tcol='NO REPORT DUE','#9ba3ba'
        ecol='#16c784' if (r or 0)>0 else '#ff4d5e' if (r or 0)<0 else '#9ba3ba'
        et=f'{r*100:+.1f} pts vs S&amp;P' if r is not None else 'edge pending'
        y=262+i*84
        rows+=(f'<g transform="translate(70,{y})"><rect width="1060" height="68" rx="18" fill="#11131c" stroke="#232738" stroke-width="2"/>'
               f'<rect x="14" y="12" width="104" height="44" rx="22" fill="{"#16c784" if p["action"]=="BUY" else "#ff4d5e"}"/><text x="66" y="42" text-anchor="middle" font-size="22" font-weight="800" fill="#06130c">{p["action"]}</text>'
               f'<text x="140" y="47" font-family="monospace" font-size="38" font-weight="700" fill="#fff">{E(sym)}</text>'
               f'<text x="330" y="45" font-size="26" font-weight="800" fill="{tcol}" letter-spacing="2">{E(tag)}</text>'
               f'<text x="1040" y="46" text-anchor="end" font-size="30" font-weight="800" fill="{ecol}">{et}</text></g>')
    nt=sum(1 for p in ops if p.get('catalyst') and p['catalyst']['date']==TODAY.isoformat())
    head=(f'{nt} OF OUR CALLS REPORT TODAY' if nt>1 else 'EARNINGS DAY FOR OUR CALL' if nt==1 else 'EARNINGS WATCH')
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><defs><radialGradient id="a" cx=".12" cy=".1" r=".75"><stop offset="0" stop-color="#ffb020" stop-opacity=".35"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient><radialGradient id="b" cx=".92" cy=".85" r=".7"><stop offset="0" stop-color="#7c5cff" stop-opacity=".5"/><stop offset="1" stop-color="#07080d" stop-opacity="0"/></radialGradient></defs>'
         f'<rect width="1200" height="630" fill="#07080d"/><rect width="1200" height="630" fill="url(#a)"/><rect width="1200" height="630" fill="url(#b)"/><g font-family="Inter,Helvetica,Arial,sans-serif">'
         f'<g transform="translate(70,56) scale(1.4)">{logo}</g><text x="146" y="101" font-size="38" font-weight="800" fill="#fff">The Daily Five</text>'
         f'<text x="1130" y="101" text-anchor="end" font-size="24" font-weight="700" fill="#ffb020" letter-spacing="3">{E(TODAY.strftime("%a %b %-d").upper())}</text>'
         f'<text x="70" y="180" font-size="54" font-weight="800" fill="#fff">{E(head)}</text>'
         f'<text x="70" y="226" font-size="26" fill="#c9cede">Open 3-month calls, graded vs the S&amp;P 500 · live edge as of {E(NOW.strftime("%-I:%M %p ET"))}</text>{rows}'
         f'<text x="70" y="600" font-size="22" fill="#9ba3ba">What makes us right or wrong: readdailyfive.com/earnings</text><text x="1130" y="600" text-anchor="end" font-size="22" fill="#9ba3ba">Not advice</text></g></svg>')
    rep=reported(ops)
    if rep:
        svg=verdict_svg(sorted(ops,key=lambda p:(p['symbol'].upper() not in rep,p['symbol'])),rep)
        w('og/verdict.svg',svg); PICK_OG_JOBS.append((os.path.join(OUT,'og/verdict.svg'),os.path.join(OUT,'og/verdict.png')))
    rel='og/earnings'; w(rel+'.svg',svg)
    PICK_OG_JOBS.append((os.path.join(OUT,rel+'.svg'),os.path.join(OUT,rel+'.png')))
    import hashlib; return f"/{rel}.png?v={hashlib.sha1(svg.encode()).hexdigest()[:8]}"
def earnings_hub():
    """/earnings/: next earnings date (or catalyst) for every open 3-month call, with right-if/wrong-if and the live edge vs the S&P 500."""
    P='/earnings/'; ops=[p for p in open3()]
    if not ops: return None
    dd=lambda p: (p.get('catalyst') or {}).get('date') or '9999'
    ops=sorted(ops,key=dd)
    def card(p):
        c=p.get('catalyst'); sym=p['symbol'].upper(); nm=E((cname(sym) or sym)); r=p.get('ret')
        edge=(f'<span class="{"up" if r>=0 else "dn"}"><b>{r*100:+.1f} pts</b> vs the S&amp;P 500</span>' if r is not None else 'edge pending')
        if c:
            d=datetime.date.fromisoformat(c['date']); n=(d-TODAY).days
            when=f"{d.strftime('%A, %B %-d, %Y')} {E(c.get('when',''))}"+(' (tomorrow)' if n==1 else ' (today)' if n==0 else f' (in {n} days)' if n>1 else ' (reported)')
            head=f'<h3 class="hzh">📅 {nm} ({sym}) earnings: {when}</h3>'
        else:
            head=f'<h3 class="hzh">📅 {nm} ({sym}): no scheduled catalyst inside the window</h3>'
        return (f'<article class="card">{head}<p class="why"><b>Our call:</b> {p["action"]} {sym} at ${p["entry"]:,.2f}, 3-month hold, currently {edge}. '
                f'<a href="{BASE}/picks/{p["id"]}/">Full pick, chart and the why →</a></p>{catalyst_box(p)}</article>')
    nxt=[p for p in ops if p.get('catalyst') and p['catalyst']['date']>=TODAY.isoformat()]
    lead=(f"{len(nxt)} of our {len(ops)} open 3-month stock calls report earnings in the next stretch: "+', '.join(f"{(cname(p['symbol'].upper()) or p['symbol'].upper())} ({p['symbol'].upper()}) on {datetime.date.fromisoformat(p['catalyst']['date']).strftime('%a %b %-d')} {p['catalyst'].get('when','')}" for p in nxt)+'. ' if nxt else '')+\
         "Each call is graded against the S&P 500 over 3 months, so one report doesn't settle it, but it's the night the thesis gets tested. Here's exactly what would make us right or wrong, decided before the numbers come out."
    faqs=[(f"When does {(cname(p['symbol'].upper()) or p['symbol'].upper())} ({p['symbol'].upper()}) report earnings?",
           f"{(cname(p['symbol'].upper()) or p['symbol'].upper())} reports {p['catalyst']['event']} on {datetime.date.fromisoformat(p['catalyst']['date']).strftime('%A, %B %-d, %Y')} {p['catalyst'].get('when','')}. The Daily Five holds an open 3-month {p['action']} call on {p['symbol'].upper()} from ${p['entry']:,.2f}.")
          for p in ops if p.get('catalyst')]+[("How does The Daily Five grade stock calls around earnings?","Every call is a 3-month hold graded against the S&P 500 from the day we publish. After a report we also show the move since the report-day close versus the index, but only the 3-month result counts toward the record.")]
    faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
    cnav,csch=crumbs([('Home','/'),('Stock picks','/best-stocks-to-buy-today/'),('Earnings calendar','/earnings/')])
    syms=', '.join(p['symbol'].upper() for p in nxt) or ', '.join(p['symbol'].upper() for p in ops)
    h1='Earnings Calendar for Our Open Stock Calls'
    bodyh=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">📅 Earnings watch · updated {TODAY.strftime("%b %-d, %Y")}</span><h1 class="pt">{h1}</h1><p class="sub wksum">{E(lead)}</p>'
           f'<div class="hubcta"><a class="pill" href="{BASE}/best-stocks-to-buy-today/">Today\'s stock picks →</a><a class="pill ghost" href="{BASE}/scoreboard/">Scoreboard →</a><a class="pill ghost" href="{BASE}/max-edge/">Max Edge videos →</a></div></section>'
           +verdict_box(ops)+''.join(card(p) for p in ops)+f'<section class="signup wksign"><div><span class="kicker">📬 The morning after</span><h2>Get the post-earnings verdict at 7 AM ET.</h2><p>The free email grades our calls the morning after each report, wins and losses. No spam, unsubscribe anytime.</p></div>{sform("wk")}</section>'
           f'{faqh}<p class="disc-bar">⚠️ <b>Not financial advice.</b> Earnings dates come from company investor-relations pages and can change. Past results don\'t guarantee future returns.</p>')
    title=f"Earnings Dates This Week: {syms} | What Would Make Our Calls Right or Wrong | {BRAND}"
    desc=(f"Next earnings dates for every open Daily Five stock call ({syms}), with what would make each call right or wrong and the live edge vs the S&P 500.")[:155]
    sch={"@context":"https://schema.org","@graph":[{"@type":"Article","headline":h1,"description":desc,"dateModified":TODAY.isoformat(),"author":{"@type":"Organization","name":BRAND},"publisher":{"@type":"Organization","name":BRAND},"mainEntityOfPage":SITE+P},csch,
         {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]}]}
    w('earnings/index.html',shell(title,desc,P,bodyh,sch,og=earnings_og(ops)))
    return P
def latest_clip():
    fs=sorted(glob.glob(os.path.join(ROOT,'clips','max-*.mp4')))
    return clip_html(os.path.basename(fs[-1])[4:14]) if fs else ''
def body(ed,prev=None,home=False):
    rank=0; fin=''
    for h,ic in [('3 Month','📅'),('1 Day','⚡'),('1 Month','📅'),('1 Year','🌱')]:
        ps=[p for p in ed['finance'] if p['horizon']==h]
        if not ps: continue
        cards=''
        for p in ps: cards+=fin_card(p,ed['finance'].index(p)+1)
        fin+=f'<div class="hzblock"><h3 class="hzh">{ic} {h}</h3><div class="grid">{cards}</div></div>'
    if ed['date']>=LAUNCH:
        new={id(p) for p in ed['finance']}; oc=[p for p in open3(ed['date']) if id(p) not in new]
        if oc: fin+='<div class="hzblock"><h3 class="hzh">📂 Open 3-month calls, marked live vs the S&amp;P 500</h3><div class="grid">'+''.join(fin_card(p,0) for p in oc)+'</div></div>'
        elif not ed['finance']: fin+='<p class="sub">No new stock call today. We make 1–2 buy-and-hold 3-month calls a week.</p>'
        fin+=three_strip()
    ai=''.join(f'<a class="news {"lead" if i==0 else ""}" href="{E(n["source"]["url"])}" rel="nofollow noopener" target="_blank"><span class="cat">{E(n.get("category","AI"))}</span><h3>{E(n["headline"])}</h3><p>{E(n["why"])}</p><span class="via">{E(n["source"]["name"])} ↗</span></a>' for i,n in enumerate(ed['ai']))
    sp=''.join(sp_card(p,i+1) for i,p in enumerate(ed['sports']))
    bd=f'<p class="backdrop">📉 <b>Backdrop:</b> {E(ed["backdrop"])} <a href="{E(ed["backdrop_source"]["url"])}" rel="nofollow noopener" target="_blank">{E(ed["backdrop_source"]["name"])} ↗</a></p>' if ed.get('backdrop') else ''
    upd=NOW.strftime('%-I:%M %p ET')
    beta=(f'<p class="disc-bar">🧪 <b>Beta edition (pre-launch).</b> This is from our October 2026 beta, before Max Edge\'s Day 1 on Oct 25. Its picks are graded on the <a href="{BASE}/beta-archive/">Beta archive</a>, not the main scoreboard.</p>' if ed['date']<LAUNCH else '')
    return beta+(latest_clip() if home else clip_html(ed['date']))+closing_bell(ed)+recap(prev)+(wins_wall(3,7,'home') or wins_wall(3,None,'home'))+f"""<p class="stamp"><span class="live"></span>Live prices · last updated <b id="upd">{upd}</b> · <span class="dl">delayed: stocks via Yahoo Finance (may lag up to ~15 min), sports via Polymarket</span></p>{today_strip(ed["finance"]+ed["sports"],"home",ed["finance"]+ed["sports"])}<p class="disc-bar">⚠️ <b>Not financial or betting advice.</b> Entry prices are real snapshots at publish time; P/L updates with each rebuild.</p>
<section class="sec fin" id="finance"><div class="sh"><span class="si">💰</span><div><h2>Money moves</h2><p class="sub">{'Buy-and-hold 3-month calls (1–2 a week), graded against the S&amp;P 500.' if ed['date']>=LAUNCH else 'The best ideas from AI agents, analysts and public sources, by horizon.'}</p></div></div>{bd}{fin}</section>
<section class="sec ai" id="ai"><div class="sh"><span class="si">🤖</span><div><h2>AI that matters</h2><p class="sub">The five stories most likely to shape what's next.</p></div></div><div class="newsgrid">{ai}</div></section>
<section class="sec sp" id="sports"><div class="sh"><span class="si">🏟</span><div><h2>Sports market plays</h2><p class="sub">Live Polymarket odds: big moves, big volume, and lines that look off. <a href="{BASE}/polymarket-picks-today/">Every Polymarket pick, graded →</a> · <a href="{BASE}/nfl-picks-this-week/">NFL picks this week →</a>{''.join(f' · <a href="{BASE}{u}">{n[:1].upper()+n[1:]} →</a>' for n,u in LGHUBS.values())}</p></div></div>{verdict_summary(ed["sports"])}{gd_board(ed["sports"])}<div class="grid g3">{sp}</div>{nobets(ed)}</section>"""
def nobets(ed):
    if ed['sports'] or ed['date']<LAUNCH: return ''
    note=ed.get('no_bets_note') or ''
    return f'<p class="sub" style="font-size:1.05em;margin:10px 0"><b>🚫 No bets today: nothing cleared our bar.</b> A pick needs a real sportsbook line, Polymarket between 40¢ and 70¢, and at least +2.5 points of edge. No Bold Bet of the Day, either. {E(note)}</p>'+lean_box(ed)
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
TD={'1 Day':1,'1 Month':21,'3 Month':63,'1 Year':252}
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
        bk=p.get('book')
        # started/settled game picks are graded at our entry (vs the line at publish); open picks at the live Polymarket price
        px=p['entry'] if (p.get('final') or p.get('bmode')=='entry') else (p.get('cur') or p['entry'])
        if bk and bk.get('odds'):
            q=[am2p(o) for o in bk['odds']]; fair=q[0]/sum(q); p['fair']=fair; p['vig']=sum(q)-1; p['bpx']=px
            pts=(fair-px)*100; p['edge_pts']=pts; b['edge']=round(clamp(12.5+pts*1.25),1)
            notes.insert(0,f"edge {pts:+.1f} pts vs {bk['name'].split(' via ')[0].split(' (')[0]}")
            ev=(fair-px)/px; b['rr']=round(12.5+12.5*math.tanh(ev*5),1)
        else: b['edge']=12.5; b['rr']=12.5; notes.insert(0,"no sportsbook line")
    p['score']=round(sum(b.values())); p['sb']=b; p['snote']=' · '.join(notes)
def _fo(o): return f"+{o}" if o>0 else f"\u2212{-o}"
def _bwhen(bk):
    if bk.get('pub'): return 'at publish'
    try: return datetime.datetime.fromisoformat(bk['at']).astimezone().strftime('%b %-d %-I:%M %p ET')
    except Exception: return ''
def _bteams(p,bk):
    oc=(p.get('m') or {}).get('outcomes') or []
    if bk.get('teams'): return bk['teams']
    if len(oc)==2 and {o.lower() for o in oc}=={'yes','no'}:
        return [p['label'],re.sub(r'\bYES\b','NO',p['label']) if 'YES' in p['label'] else 'the other side']
    return [oc[p['outcome']],oc[1-p['outcome']]] if len(oc)==2 else [p['label'],'the other side']
def book_line(p,full=False):
    """Transparent sportsbook check: real moneyline, de-vigged fair probability, vs the Polymarket price, edge in points."""
    bk=p.get('book'); fair=p.get('fair')
    if p.get('kind')!='Sports' or not bk or fair is None: return ''
    tm=_bteams(p,bk); o=bk['odds']; pts=p['edge_pts']; px=p['bpx']; when=_bwhen(bk)
    lab='Pre-game line' if (bk.get('auto') and bk.get('closing')) else ('Line at publish' if bk.get('pub') else ('Books now' if bk.get('fresh') else 'Last line read'))
    vs='our entry' if p.get('bmode')=='entry' else 'Polymarket'
    cls='up' if pts>=1 else 'dn' if pts<=-1 else 'flat'
    src=f'<a href="{E(bk["url"])}" rel="nofollow noopener" target="_blank">{E(bk["name"])}{(" · "+when) if when else ""} ↗</a>'
    if not full:
        return (f'<p class="bk"><span class="bkl">\U0001F4D2 {lab}</span> {E(tm[0])} {_fo(o[0])} / {E(tm[1])} {_fo(o[1])} → no-vig <b>{fair*100:.1f}%</b> vs {vs} <b>{px*100:.1f}¢</b> '
                f'<span class="chip {cls}">{pts:+.1f} pts</span><small>{src}</small></p>')
    q=[am2p(x) for x in o]
    verdict=('Polymarket was cheaper than the books' if pts>=1 else 'Polymarket was pricier than the books' if pts<=-1 else 'Polymarket and the books agreed') if p.get('bmode')=='entry' else \
            ('Polymarket is cheaper than the books' if pts>=1 else 'Polymarket is pricier than the books' if pts<=-1 else 'Polymarket and the books agree')
    out=(f'<dt>Sportsbook check</dt><dd>{src}: {E(tm[0])} {_fo(o[0])} ({q[0]*100:.1f}% implied), {E(tm[1])} {_fo(o[1])} ({q[1]*100:.1f}%). '
         f'The {p["vig"]*100:.1f}% vig comes out, so the no-vig fair chance is <b>{fair*100:.1f}%</b>. {"Our entry" if p.get("bmode")=="entry" else "Polymarket now"}: {px*100:.1f}¢, '
         f'edge <b>{pts:+.1f} pts</b> ({E(verdict)}). Edge score {p["sb"]["edge"]}/25 = 12.5 + 1.25 × points.</dd>')
    for e in (p.get('book0'),p.get('espn')):  # the other real line(s) we have, for comparison
        if not e or e is bk: continue
        q2=[am2p(x) for x in e['odds']]; t2=_bteams(p,e)
        nm='Line at publish' if e.get('pub') else ('Pre-game line' if e.get('closing') else ('Books now' if e.get('fresh') else 'Last line read'))
        out+=(f'<dt>{nm}</dt><dd><a href="{E(e["url"])}" rel="nofollow noopener" target="_blank">{E(e["name"])} · {_bwhen(e)} ↗</a>: '
              f'{E(t2[0])} {_fo(e["odds"][0])} / {E(t2[1])} {_fo(e["odds"][1])}, no-vig {q2[0]/sum(q2)*100:.1f}%.</dd>')
    return out
VAL_PTS=2.0  # value threshold in points vs the no-vig sportsbook line (FORMAT.md: prefer plays >= 2 pts under the books)
VV={'val':('\U0001F4B0','Value','cheaper than the books'),'flip':('\U0001FA99','Coin flip','fair price, no edge on the books'),
    'pricey':('\u26A0\uFE0F','Pricey','pricier than the books'),'nl':('\u2754','Unchecked','no sportsbook line')}
def vkey(p):
    """Plain value verdict key from the edge vs the no-vig sportsbook line: val / flip / pricey / nl (no real line)."""
    pts=p.get('edge_pts') if p.get('kind')=='Sports' else None
    if pts is None: return 'nl'
    return 'val' if pts>=VAL_PTS else ('pricey' if pts<=-VAL_PTS else 'flip')
def _bkname(p):
    n=((p.get('book') or {}).get('name') or 'the books').split(' via ')[0].split(' (')[0]
    return n+("'" if n.endswith('s') else "'s")  # possessive: DraftKings', FanDuel's
def vrec_txt(k):
    """Our settled record for a verdict bucket (graded at entry), e.g. '8-6, -5.47% avg' or ''."""
    ps=(SPR.get('vb') or {}).get(k) or []
    return f"{sum(q['ret']>0 for q in ps)}-{sum(q['ret']<=0 for q in ps)}, {pct(sum(q['ret'] for q in ps)/len(ps))} avg" if ps else ''
def verdict(p,full=False):
    """Honest one-line value verdict for a sports pick (card strip; full=True gives the pick-page sentence)."""
    if p.get('kind')!='Sports': return ''
    k=vkey(p); ic,lab,sub=VV[k]; pts=p.get('edge_pts'); past=p.get('bmode')=='entry' or p.get('final')
    is_=('was' if past else 'is'); bn=_bkname(p); px=p.get('bpx')
    if k=='nl':
        txt=("We had no real sportsbook line for this market, so we can't say whether the price "+('was' if past else 'is')+" fair.")
    elif k=='val':
        txt=(f"Polymarket {is_} {pts:.1f} pts under {bn} no-vig line ({p['fair']*100:.1f}% fair vs {px*100:.1f}\u00a2"+(" at our entry" if past else "")+"). That's the price gap we look for.")
    elif k=='flip':
        txt=(f"Polymarket {is_} within {VAL_PTS:.0f} pts of {bn} no-vig line ({pts:+.1f} pts), so the price {is_} fair: a coin flip at the market's own odds, with no edge on the books.")
    else:
        txt=(f"Polymarket {is_} {-pts:.1f} pts over {bn} no-vig line: the books {'had' if past else 'have'} this side cheaper.")
    rec=vrec_txt(k)
    if rec and k!='nl': txt+=f" Our settled {lab.lower()} picks: {rec}."
    if full: return f'<dt>Value verdict</dt><dd><b class="vvt {k}">{ic} {E(lab)}</b> {E(txt)}</dd>'
    return f'<p class="vv {k}"><b>{ic} {E(lab)}</b><span><em>{E(sub)}</em> {E(txt)}</span></p>'
def verdict_summary(ps):
    """Home/edition sports header: how many of today's plays beat the books, honestly."""
    ps=[p for p in ps if p.get('kind')=='Sports' and not p.get('final')]
    if not ps: return ''
    b={k:[p for p in ps if vkey(p)==k] for k in VV}
    def nm(k): return ', '.join(f"{E(p['label'])} {p['edge_pts']:+.1f}" if p.get('edge_pts') is not None else E(p['label']) for p in b[k])
    parts=[]
    if b['val']: parts.append(f'<span class="vvs val">\U0001F4B0 {len(b["val"])} cheaper than the books <small>({nm("val")})</small></span>')
    if b['flip']: parts.append(f'<span class="vvs flip">\U0001FA99 {len(b["flip"])} coin flip{"s" if len(b["flip"])>1 else ""} at a fair price <small>({nm("flip")})</small></span>')
    if b['pricey']: parts.append(f'<span class="vvs pricey">\u26A0\uFE0F {len(b["pricey"])} pricier than the books <small>({nm("pricey")})</small></span>')
    if b['nl']: parts.append(f'<span class="vvs nl">\u2754 {len(b["nl"])} with no line to check</span>')
    rec=vrec_txt('flip')
    tail=(f' Fair-priced picks have gone {rec} for us so far, so we only call it value at {VAL_PTS:.0f}+ pts under the books.' if rec else '')
    return f'<div class="vvsum"><b class="vvh">Value check vs the sportsbooks</b>{"".join(parts)}<p>Edge in points = no-vig sportsbook chance minus the Polymarket price.{E(tail)} <a href="{BASE}/how-we-rank/#value">How it works \u2192</a></p></div>'
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
 ("How is edge vs fair value calculated?","For stocks, edge is the % gap between the live price and the consensus analyst mean price target (Yahoo Finance), signed for BUY or SELL: 12.5 + 50 × gap. Peer valuation isn't computed yet. For sports and markets, it's the sportsbook's no-vig implied probability minus the Polymarket price, in points: 12.5 + 1.25 × points. Before an NFL, NBA, MLB or NHL game starts we use DraftKings' live moneyline from ESPN's public scoreboard against the live Polymarket price; once it starts we grade the line at publish (or the last pre-game line we read) against our entry. Every sports card shows the line, the vig-free chance and the gap."),
 ("What does coin flip at a fair price mean?","It means the Polymarket price is within 2 points of the sportsbook's no-vig chance, so the market and the books agree on the odds. A fair-priced pick can still win, but over many picks you only make money by paying less than the true chance. We call a sports play value only when Polymarket is at least 2 points cheaper than the no-vig DraftKings line, and we say so plainly on every card."),
 ("How often do prices and scores update?","Scores recompute every time live prices refresh. Stock quotes come from Yahoo Finance (may lag up to ~15 minutes). Sports-market odds come from Polymarket. The site rebuilds on a schedule during market hours and less often off-hours; the live strip marks prices stale when the rebuild is behind."),
 ("Is The Daily Five financial or betting advice?","No. A high score isn't a guarantee. The Daily Five Score and every pick are for information and education only — not financial, investment, or betting advice."),
]
HOWTO=("<section class='sbhero'><span class='kicker'>🧮 Methodology</span><h1 class='pt'>How we rank: the Daily Five Score</h1><p class='sub'>Every finance and sports pick gets a 0–100 score from four components worth 25 points each. The Top 5 in each section are ordered by it. We only use real data; when a component can't be computed, it gets a neutral 12.5 and we say so on the card.</p></section>"
 "<div class='how'><div class='hw'><h2>1 · Source credibility (0–25)</h2><p>The source's historical hit rate on our own <a href='/track-record/'>track record</a>: closed picks from that source that made money. Until a source has at least 5 closed picks it gets a neutral 12.5, labeled <b>new source</b>.</p></div>"
 "<div class='hw'><h2>2 · Consensus (0–25)</h2><p>How many independent, credible sources we found agreeing with the call versus dissenting. 12.5 + 12.5 × (agree − dissent)/(agree + dissent), scaled down when there are fewer than four sources. With no sources checked, it's a neutral 12.5.</p></div>"
 "<div class='hw'><h2>3 · Edge vs fair value (0–25)</h2><p><b>Stocks:</b> % gap between the live price and the consensus analyst mean price target (Yahoo Finance), signed for BUY or SELL: 12.5 + 50 × gap. Peer valuation isn't computed yet. <b>Sports and markets:</b> the sportsbook's no-vig implied probability minus the Polymarket price, in points: 12.5 + 1.25 × points. Example: Patriots +124 / Bears −148 imply 44.6% and 59.7% (104.3% total, the extra 4.3% is the book's vig); removing it gives the Patriots a 42.8% fair chance, so a 39.5¢ Polymarket price is a +3.3-point edge. Before an NFL, NBA, MLB or NHL game starts we use DraftKings' live moneyline from ESPN's public scoreboard against the live Polymarket price, refreshed every build; once it starts we grade the line at publish (or the last pre-game line we read) against our entry. Every sports card shows the line, the vig-free chance and the gap. Futures use a published line when we find one; with none, Edge stays a neutral 12.5.</p></div>"
 "<div class='hw' id='value'><h2>Value verdict: value, coin flip or pricey</h2><p>Every sports pick also gets a plain verdict from that same edge number. <b>💰 Value:</b> Polymarket is at least 2 points cheaper than the no-vig sportsbook line. <b>🪙 Coin flip:</b> within 2 points either way, so the price is fair and there's no edge on the books; the pick can still win, but you're paying what it's worth. <b>⚠️ Pricey:</b> Polymarket is 2+ points over the line. <b>❔ Unchecked:</b> no real sportsbook line to compare. Settled picks keep the verdict they had at our entry, and <a href='/sports-results/#value'>sports results</a> show our record for each. Why 2 points: small gaps come from how the vig is split and from prices moving minute to minute, and our early fair-priced picks lost money despite a winning record.</p></div>"
 "<div class='hw'><h2>4 · Risk/reward (0–25)</h2><p><b>Stocks:</b> the horizon-scaled share of the target gap divided by the horizon's volatility (60-day daily volatility × √trading days): 12.5 + 12.5 × tanh(ratio). <b>Markets:</b> expected value per $1 at the fair probability: 12.5 + 12.5 × tanh(5 × EV).</p></div></div>"
 "<p class='sub'>Scores recompute every time live prices refresh. A high score isn't a guarantee. Not financial or betting advice.</p>"
 "<h2 class='h2s'>FAQ</h2><div class='faq'>"+''.join(f"<details class='fq'><summary>{E(q)}</summary><p>{E(a)}</p></details>" for q,a in FAQS)+"</div>")

def ed_desc(ed,nice,picks):
    """Meta description for an edition (~160 chars for search snippets). On days with no new stock call,
    lead with the open 3-month calls and their live edge vs the S&P 500 so the snippet shows the record."""
    if picks: lead=f"{nice}: {picks}"
    else:
        oc=open3(ed['date']) if ed['date']>=LAUNCH else []
        def edge(p):
            r=p.get('ret')
            return f"{p['action']} {p['label']}"+(f" ({r*100:+.1f}% vs S&P)" if r is not None and p.get('spy_ret') is not None else "")
        if oc: lead=f"{nice}: open 3-month calls "+", ".join(edge(p) for p in oc[:3])
        else:
            sp=", ".join(f"{p['action']} {p['label']}" for p in ed.get('sports',[])[:2])
            lead=f"{nice}: {sp}" if sp else f"{nice}: {ed['headline']}"
    tail=". Plus Max Edge's Bold Bet and sports market plays." if not picks and ed['date']>=LAUNCH else ", plus the top AI news and sports prediction-market plays."
    d=lead+tail
    if len(d)>165: d=lead if len(lead)<=165 else lead[:160].rsplit(' ',1)[0].rstrip(',:;(')+"…"
    return d

def ogimage(ed,nice):
    fin=ed['finance'][:4]
    oc=open3(ed['date'])[:4] if not fin and ed['date']>=LAUNCH else []
    def vs(p):
        r=p.get('ret')
        if r is None or p.get('spy_ret') is None: return '<text x="640" y="36" font-size="24" fill="#c9cede">3 Month · open</text>'
        return f'<text x="640" y="36" font-size="28" font-weight="800" fill="{"#16c784" if r>0 else "#ff4d5e" if r<0 else "#9ba3ba"}">{r*100:+.1f}% vs S&amp;P</text>'
    def hz(p): return '<text x="640" y="36" font-size="24" fill="#c9cede">'+E(p["horizon"])+'</text>'
    if oc:
        fin=oc
    rowsvg=('<text x="70" y="315" font-size="22" font-weight="700" fill="#9ba3ba" letter-spacing="2">OPEN 3-MONTH CALLS · LIVE</text>' if oc else '')+''.join(f'<g transform="translate(70,{(345 if oc else 330)+i*62})"><rect width="128" height="48" rx="24" fill="{"#16c784" if p["action"]=="BUY" else "#ff4d5e"}"/><text x="64" y="33" text-anchor="middle" font-size="24" font-weight="800" fill="#06130c">{p["action"]}</text><text x="150" y="36" font-family="monospace" font-size="38" font-weight="700" fill="#fff">{E(p["label"])}</text><text x="380" y="36" font-family="monospace" font-size="30" fill="#9ba3ba">${p["entry"]:,.2f}</text>{vs(p) if oc else hz(p)}</g>' for i,p in enumerate(fin))
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
    # Cache-bust: version = short hash of the card's SVG (live edge numbers, headline, picks), so X/Slack/iMessage
    # re-fetch the image when the numbers change but keep their cache while nothing on the card moved.
    import hashlib; v=hashlib.sha1(svg.encode()).hexdigest()[:8]
    return ('/'+rel if os.path.exists(os.path.join(OUT,rel)) else f"/og/{ed['date']}.svg")+f"?v={v}"
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
    tm=k=='Finance' and p.get('horizon')=='3 Month' and p.get('spy_ret') is not None
    if tm: big=f"{r*100:+.1f} pts"  # 3-month calls are graded vs the S&P 500: show the edge, not the raw return
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
         +(f'<text x="70" y="510" font-size="28" fill="#c9cede">vs the S&amp;P 500 · {E(p["label"])} {p["abs_ret"]*100:+.1f}% vs S&amp;P {p["spy_ret"]*100:+.1f}% · {E(money(k,p["entry"]))} → {E(money(k,p.get("cur")))}</text>' if tm else
           f'<text x="70" y="510" font-size="28" fill="#9ba3ba">since the call · entry {E(money(k,p["entry"]))} → {"exit" if fin else "now"} {E(money(k,p.get("cur")))}</text>')+
         f'<rect x="900" y="340" width="230" height="64" rx="16" fill="#11131c" stroke="{col}" stroke-width="3"/><text x="1015" y="383" text-anchor="middle" font-size="28" font-weight="800" fill="{col}" letter-spacing="4">{stat}</text>'
         +(f'<text x="1015" y="440" text-anchor="middle" font-size="22" fill="#9ba3ba">{"Day 91 of 91" if fin else "Day "+str(min(91,(TODAY-datetime.date.fromisoformat(ed["date"])).days+1))+" of 91"}</text>' if tm else
           f'<text x="1015" y="440" text-anchor="middle" font-size="22" fill="#9ba3ba">Score {int(round(p.get("score") or 0))}/100</text>')+
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
        c=p.get('catalyst')
        if c and not p.get('final'):
            cd=datetime.date.fromisoformat(c['date'])
            faq.append((f"When does {nmc} ({sym}) report earnings?" if 'earnings' in c['event'].lower() else f"What's the next catalyst for {sym}?",
                        f"{c['event']}: {cd.strftime('%A, %B %-d, %Y')} {c.get('when','')}. The call looks right if: {'; '.join(c.get('right',[]))}. It looks wrong if: {'; '.join(c.get('wrong',[]))}."))
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
    lg=league_of(p)
    if lg in LGHUBS: n,u=LGHUBS[lg]; return (n[:1].upper()+n[1:],u)
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
def three_strip(cur=None):
    """Internal-link strip to /3-month-stock-picks/ with the live edge vs the S&P 500 for every open 3-month call (live.js repaints [data-edge])."""
    oc=[p for p in open3() if p.get('ret') is not None]
    if not oc: return ''
    oc=sorted(oc,key=lambda p:-p['ret']); ah=sum(p['ret']>0 for p in oc)
    def it(p):
        c='up' if p['ret']>=0 else 'dn'; me=' me' if cur and p.get('id')==cur else ''
        return f'<a class="tsi{me}" href="{BASE}/picks/{p["id"]}/">{E(p["label"])} <b class="{c}" data-edge="{p["id"]}">{p["ret"]*100:+.1f} pts</b></a>'
    quip=('Max is winning and will not shut up about it.' if ah*2>len(oc) else 'Max is behind and pretending it\'s a long game. (It is: 91 days.)')
    return (f'<aside class="tmstrip"><div class="tsh"><span class="tsk">📈 Every open 3-month call vs the S&amp;P 500</span>'
            f'<span class="tss">{ah} of {len(oc)} ahead right now · {quip}</span></div>'
            f'<div class="tsl">{"".join(it(p) for p in oc)}</div>'
            f'<a class="tsa" href="{BASE}/3-month-stock-picks/">See all open 3-month calls vs the S&amp;P →</a></aside>')
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
         f'<dt>Status</dt><dd>{"Final" if p.get("final") else "Open"} \u00b7 {E(p.get("note",""))}</dd>{verdict(p,True)}{book_line(p,True)}<dt>Source</dt><dd><a href="{E(p["source"]["url"])}" rel="nofollow noopener" target="_blank">{E(p["source"]["name"])}</a></dd></dl>'
         f'<p><a href="{BASE}/ticker/{p["tslug"]}/">All picks on {E(p["tname"])} \u2192</a><br><a href="{BASE}/track-record/">Full track record \u2192</a></p></div></div>'+mvh+related(p,ed,allp)+(three_strip(p['id']) if k=='Finance' and p.get('horizon')=='3 Month' else ''))
    sch={"@context":"https://schema.org","@type":"Article","headline":h[:110],"datePublished":ed['date'],"description":desc,"author":{"@type":"Organization","name":BRAND},"publisher":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/picks/{p['id']}/","about":about}
    og=pick_og(p,ed)
    if og: sch['image']=SITE+og.split('?')[0]
    sch.pop('@context'); sch={"@context":"https://schema.org","@graph":[sch,csch]}
    if faq:
        sch['@graph'].append({"@type":"FAQPage","url":f"{SITE}/picks/{p['id']}/","mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faq]})
    w(f"picks/{p['id']}/index.html",shell(title,desc,f"/picks/{p['id']}/",det,sch,og=og))
def three_month_hub(eds):
    """Evergreen SEO page /3-month-stock-picks/: every 3-month stock call since the relaunch, open ones marked live vs the S&P 500,
    with the thesis, risk, source, days left and the grading rule. Targets 'stock picks for the next 3 months' style searches."""
    calls=[(p,ed) for ed in eds for p in ed['finance'] if p['horizon']=='3 Month']
    if not calls: return None
    P='/3-month-stock-picks/'; d=datetime.date.fromisoformat
    op=[(p,ed) for p,ed in calls if not p.get('final')]; cl=[(p,ed) for p,ed in calls if p.get('final') and p.get('ret') is not None]
    gr=[p for p,_ in calls if p.get('ret') is not None]; ahead=sum(p['ret']>0 for p in gr); avg=sum(p['ret'] for p in gr)/len(gr) if gr else None
    wins=sum(p['ret']>0 for p,_ in cl)
    def t(h,v,s,c=''): return f'<div class="tile"><span class="h">{h}</span><b class="{c}">{v}</b><span class="s">{s}</span></div>'
    tiles=(t('Open calls',str(len(op)),'marked to live prices')+
           t('Ahead of the S&P',f'{ahead}/{len(gr)}','right now, all calls')+
           t('Avg edge vs S&P',(f'{avg*100:+.1f} pts' if avg is not None else '—'),'stock return minus SPY','up' if (avg or 0)>=0 else 'dn')+
           t('Closed record',f'{wins}-{len(cl)-wins}' if cl else '0-0',f'first exits {(d(calls[-1][1]["date"])+datetime.timedelta(days=91)).strftime("%b %-d")}' if not cl else 'beat the S&P = win'))
    def card(p,ed):
        end=d(ed['date'])+datetime.timedelta(days=91); left=(end-TODAY).days; src=p.get('source') or {}
        vs=(f'<p class="tm-vs">Stock <b>{p["abs_ret"]*100:+.1f}%</b> vs S&amp;P 500 <b>{p["spy_ret"]*100:+.1f}%</b> since the pick, an edge of <b class="{"up" if p["ret"]>=0 else "dn"}">{p["ret"]*100:+.1f} pts</b>.</p>' if p.get('abs_ret') is not None and p.get('spy_ret') is not None else '')
        st=(f'Closed {end.strftime("%b %-d, %Y")}: <b>{"WIN" if p["ret"]>0 else "LOSS"}</b>' if p.get('final') else f'Day {(TODAY-d(ed["date"])).days+1} of 91 · exits at the {end.strftime("%b %-d, %Y")} close ({left} days left)')
        return (f'<article class="tmc"><div class="cnh"><span class="mini {p["action"].lower()}">{p["action"]}</span> <a href="{BASE}/picks/{p["id"]}/"><b>{E(p["label"])}</b></a>'
                f' <small>called {d(ed["date"]).strftime("%a %b %-d")} in <a href="{BASE}/{ed["date"]}/">that morning\'s edition</a> · {st}</small></div>'
                f'{livebox(p) if not p.get("final") else ""}{vs}'
                f'<p><b>Why:</b> {E(p.get("why",""))}</p><p><b>What could go wrong:</b> {E(p.get("risk",""))}</p>'
                +(f'<p class="sub">Source: <a href="{E(src["url"])}" rel="nofollow noopener" target="_blank">{E(src.get("name","link"))}</a></p>' if src.get('url') else '')
                +catalyst_box(p)+'</article>')
    clip=sorted(glob.glob(os.path.join(ROOT,'clips','max-*.mp4')))
    clipl=f' Or watch <a href="{BASE}/max-edge/{os.path.basename(clip[-1])[4:14]}/">Max Edge explain today\'s calls in under a minute</a>.' if clip else ''
    best=max([(p,ed) for p,ed in op if p.get('ret') is not None],key=lambda x:x[0]['ret'],default=None)
    if best and best[0]['ret']>0:
        bp,bed=best; bd=(TODAY-d(bed['date'])).days+1
        h2=(f'{E(bp["label"])} is beating the S&amp;P by <b class="up" data-edge="{bp["id"]}">{bp["ret"]*100:+.1f} pts</b> on day {bd} of 91. Get the next call the morning we make it.')
    else:
        h2='Get the next 3-month call the morning we make it.'
    tm_ask=(f'<section class="signup wksign"><div><span class="kicker">\U0001F4EC Next 3-month call</span><h2>{h2}</h2>'
            f'<p>One or two new stock calls a week in the free 7 AM email, each graded against the S&amp;P 500 in public, misses included. Unsubscribe anytime.</p></div>{sform("tm")}</section>')
    faqs=[('How long is each stock pick held?','Every stock call is a 3-month call: 91 days from the morning it is published. It closes at the market close on day 91, no matter what happens in between.'),
          ('How are the picks graded?','Against the S&P 500 (SPY) over the exact same window. Edge = the stock\'s return minus SPY\'s return since our entry price. A call wins if the edge is positive at the exit close, and loses otherwise. A stock that rises 5% while the S&P rises 7% is a loss.'),
          ('What price do you use as the entry?','The real pre-market price from Yahoo Finance at publish time, shown on each pick page, so the record reflects what a reader could actually have done that morning.'),
          ('How many new calls do you make?','One or two a week, only when the evidence is strong. Days with no new call just mark the open ones to market.'),
          ('Is this financial advice?','No. These are published, graded opinions for entertainment and education. Do your own research; past results do not predict future ones.')]
    faqh='<div class="faq">'+''.join(f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
    body=(f'<section class="sbhero"><span class="kicker">📈 3-month stock picks</span><h1 class="pt">3-month stock picks vs the S&amp;P 500</h1>'
          f'<p class="sub">Our only stock call format: pick a stock that beats the market over the next 3 months, say why, and grade it in public. '
          f'Every call below is marked to real prices (Yahoo Finance, may lag ~15 min), last updated <b id="upd">{NOW.strftime("%b %-d, %-I:%M %p ET")}</b>.{clipl}</p></section>'
          f'<div class="tiles">{tiles}</div>'+tm_ask
          +(f'<h2 class="hzh">Open calls</h2>'+''.join(card(p,ed) for p,ed in op) if op else '')
          +(f'<h2 class="hzh">Closed calls</h2>'+''.join(card(p,ed) for p,ed in cl) if cl else '')
          +f'<h2 class="hzh">How the 3-month calls work</h2>{faqh}'
          f'<p class="sub"><a href="{BASE}/scoreboard/">Full scoreboard →</a> · <a href="{BASE}/stock-results/">Stock results →</a> · <a href="{BASE}/earnings/">Earnings calendar for open calls →</a></p>')
    names=', '.join(p['label'] for p,_ in op[:4])
    desc=(f'Our 3-month stock picks graded live against the S&P 500: {len(op)} open call{"s" if len(op)!=1 else ""}'+(f' ({names})' if names else '')+', with entry price, edge vs SPY, thesis and exit date.')[:155]
    sch={"@context":"https://schema.org","@graph":[
        {"@type":"CollectionPage","name":"3-Month Stock Picks vs the S&P 500","url":SITE+P,"description":desc,"dateModified":TODAY.isoformat(),
         "mainEntity":{"@type":"ItemList","itemListElement":[{"@type":"ListItem","position":i+1,"url":f"{SITE}/picks/{p['id']}/","name":f"{p['action']} {p['label']} (3-month call, {ed['date']})"} for i,(p,ed) in enumerate(calls)]}},
        {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]}]}
    w('3-month-stock-picks/index.html',shell(f'3-Month Stock Picks vs the S&P 500, Graded Live | {BRAND}',desc,P,body,sch))
    return P
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
           f'<a class="pill ghost" href="{BASE}/track-record/">Track record →</a>{stock_results_link()}</div>')
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
    _ld=datetime.date.fromisoformat(latest) if eds else TODAY
    if _ld.weekday()>=5:  # weekend edition: searchers look for next session's buys
        _mon=_ld+datetime.timedelta(days=7-_ld.weekday())
        title=f'Best Stocks to Buy Monday ({_mon.strftime("%b %-d")}): Live Scores & Track Record | {BRAND}'
    else:
        title=f'Best Stocks to Buy Today ({_ld.strftime("%a, %b %-d")}): Live Scores & Track Record | {BRAND}'
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
           f'<a class="pill ghost" href="{BASE}/how-we-rank/">How we rank \u2192</a>{sports_results_link()}{league_links()}</div>')
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
           f'{tb}{hb}{fq}<p class="sub hub-foot">Betting Sunday? See <a href="{BASE}/nfl-picks-this-week/">NFL picks this week</a>.{''.join(f' {n[:1].upper()+n[1:]}: <a href="{BASE}{u}">{n} today</a>.' for n,u in LGHUBS.values())} Want stock picks too? See <a href="{BASE}/best-stocks-to-buy-today/">best stocks to buy today</a>.</p>')
    title=f'Polymarket Sports Picks Today{datetime.date.fromisoformat(latest).strftime(" (%a, %b %-d)")}: Live Odds & Results | {BRAND}'
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
           f'<a class="pill ghost" href="{BASE}/scoreboard/">Scoreboard \u2192</a>{nfl_results_links()}{sports_results_link()}</div>')
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
    _gd=nk or next((k for k in (kickoff(p) for p,_ in slate) if k),None)  # next NFL game day, for a visibly current title
    _tl=', '.join(x for x in ((f'Week {wk}' if wk else ''),(_gd.astimezone().strftime('%a %b %-d') if _gd else '')) if x)
    title=f'NFL Picks This Week{f" ({_tl})" if _tl else ""}: Live Polymarket Odds & Results | {BRAND}'
    desc=(f'This week\'s NFL picks{wl}, ranked by the Daily Five Score, with live Polymarket odds, kickoff times, and a public win/loss record. Updated {latest}.')[:155]
    evs=[{"@type":"SportsEvent","name":(p.get('m') or {}).get('outcomes') and ' vs. '.join(p['m']['outcomes']) or p['market'],"startDate":kickoff(p).isoformat(),"sport":"American football","url":f"{SITE}/picks/{p['id']}/"} for p,_ in slate if kickoff(p)]
    sch={"@context":"https://schema.org","@graph":[
        {"@type":"CollectionPage","name":f"NFL Picks This Week{wl}","description":desc,"url":SITE+P,"isPartOf":{"@type":"WebSite","name":BRAND,"url":SITE+"/"}},
        {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]}]
        +([{"@type":"ItemList","name":"NFL games we picked","itemListElement":[{"@type":"ListItem","position":i+1,"item":e} for i,e in enumerate(evs)]}] if evs else [])}
    w('nfl-picks-this-week/index.html',shell(title,desc,P,bodyh,sch))
    return P

_FUT=re.compile(r'world-series|league-championship|american-league|national-league|\balcs\b|\bnlcs\b',re.I)
def league_of(p):
    """'nfl'/'mlb'/'nba'/'nhl' for a sports pick (game slugs by prefix, MLB series futures by slug text), else None."""
    s=p.get('slug') or ''; m=re.match(r'(nfl|mlb|nba|nhl|cfb)-',s)
    if m: return m.group(1)
    if _FUT.search(s): return 'mlb'
    return None
POST=re.compile(r'ALCS|NLCS|ALDS|NLDS|World Series|Wild Card|League Championship',re.I)
LEAGUES={
 'mlb':dict(P='/mlb-picks-today/',emo='\u26be',name='MLB',sport='Baseball',start='First pitch',board='MLB game day',fut='Series futures'),
 'nba':dict(P='/nba-picks-today/',emo='\U0001F3C0',name='NBA',sport='Basketball',start='Tip-off',board='NBA game day',fut='Futures'),
 'nhl':dict(P='/nhl-picks-today/',emo='\U0001F3D2',name='NHL',sport='Ice hockey',start='Puck drop',board='NHL game day',fut='Futures'),
 'cfb':dict(P='/college-football-picks/',emo='\U0001F3C8',name='College football',sport='American football',start='Kickoff',board='College football Saturday',fut='Futures'),
}
LGHUBS={}  # league -> hub path, filled by league_hubs() before pick pages render
def league_label(lg,eds):
    """Hub name: 'MLB playoff picks' while any of our MLB picks is a postseason game or series market."""
    post=lg=='mlb' and any(POST.search(p['market']) for ed in eds[:3] for p in ed['sports'] if league_of(p)=='mlb')
    return f"{LEAGUES[lg]['name']} {'playoff ' if post else ''}picks"
def league_hubs(eds):
    """Evergreen SEO hubs per league (/mlb-picks-today/, /nba-picks-today/, /nhl-picks-today/) from real Polymarket picks only.
    Built for a league once we have published at least one pick on it."""
    out=[]; LGHUBS.clear()
    for lg,c in LEAGUES.items():
        allp=[(p,ed) for ed in eds for p in ed['sports'] if league_of(p)==lg]
        if not allp: continue
        LGHUBS[lg]=(league_label(lg,eds),c['P']); out.append(c['P'])
    return out
def league_hub_pages(eds):
    for lg,(hname,P) in LGHUBS.items():
        c=LEAGUES[lg]; allp=[(p,ed) for ed in eds for p in ed['sports'] if league_of(p)==lg]
        seen=set(); slate=[]
        for p,ed in allp:  # newest edition first: keep the latest call on each market
            if p.get('final') or p['slug'] in seen: continue
            seen.add(p['slug']); slate.append((p,ed))
        far=datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
        slate.sort(key=lambda x:(kickoff(x[0]) or far,-x[0].get('score',0)))
        settled=[(p,ed) for p,ed in allp if p.get('final') and p.get('ret') is not None]
        sw=sum(p['ret']>0 for p,_ in settled); savg=sum(p['ret'] for p,_ in settled)/len(settled) if settled else None
        gs=[(p,ed) for p,ed in settled if GAME_RE.match(p['slug'])]; gw=sum(p['ret']>0 for p,_ in gs)
        oavg=(lambda o: sum(o)/len(o) if o else None)([p['ret'] for p,_ in slate if p.get('ret') is not None])
        _now=datetime.datetime.now().astimezone()
        nk=next((k for k in (kickoff(p) for p,_ in slate) if k and k>_now),None)
        live_n=sum(1 for p,_ in slate if kickoff(p) and kickoff(p)<=_now)
        def tile(name,val,sub):
            cls='up' if val.startswith('+') else ('dn' if val.startswith('-') else '')
            return f'<div class="tile"><span class="h">{name}</span><b class="{cls}">{val}</b><span class="s">{sub}</span></div>'
        tiles=(tile('Markets on the board',str(len(slate)),(lambda g_,f_: ', '.join(x for x in [f"{g_} game{'s'*(g_!=1)}" if g_ else '',f"{f_} future{'s'*(f_!=1)}" if f_ else ''] if x) or 'none open')(sum(1 for p,_ in slate if kickoff(p)),sum(1 for p,_ in slate if not kickoff(p))))+
               tile(f"Next {c['start'].lower()}",nk.strftime('%a %-I:%M %p') if nk else ('Live' if live_n else '\u2014'),'ET' if nk else (f'{live_n} game(s) in progress' if live_n else 'none scheduled'))+
               tile('Open plays avg',pct(oavg),'marked to live Polymarket odds')+
               tile(f"{c['name']} record",f'{sw}-{len(settled)-sw}' if settled else '0-0',(f'avg settled {pct(savg)} \u00b7 games {gw}-{len(gs)-gw}' if settled else 'first picks settle soon')))
        if slate:
            o=''; cur=None; rank=0
            for p,ed in slate:
                k=kickoff(p); g=(f"{c['emo']} "+k.strftime('%A, %b %-d')) if k else f"\U0001F3C6 {c['fut']}"
                if g!=cur:
                    if cur is not None: o+='</div>'
                    o+=f'<h3 class="hzh">{g}</h3><div class="grid g3">'; cur=g
                rank+=1; o+=sp_card(p,rank)
            o+='</div>'
            tb=(f'<h2 class="h2s">Open {c["name"]} plays</h2><p class="sub hub-lead">Games by day and start time (Eastern), then futures. Entry is the real Polymarket price when we published; odds and P/L update live. '
                f'Scored with the <a href="{BASE}/how-we-rank/">Daily Five Score</a>.</p>{o}')
        else:
            tb=f'<h2 class="h2s">Open {c["name"]} plays</h2><p class="sub">No open {c["name"]} plays right now. New picks drop with the 7 AM ET edition.</p>'
        def fs(p):
            g=pgame(p.get('slug'))
            return f' \u00b7 {g["teams"][0]["ab"]} {g["score"].replace("-","\u2013")} {g["teams"][1]["ab"]}' if g and p.get('final') and re.fullmatch(r'\d+-\d+',g.get('score') or '') and len(g['teams'])==2 else ''
        res=lambda p: ('Won' if p['ret']>0 else 'Lost') if p.get('final') else 'Open'
        rows=''.join(f'<a class="hubrow" href="{BASE}/picks/{p["id"]}/"><span class="act buy">BUY</span><span class="hubtk">{E(p["label"])}</span>'
                     f'<span class="hubhz">{E(p["market"])}{E(fs(p))}</span><span class="hubsc">{p.get("score","\u2014")}</span><span class="hubent">{money("Sports",p["entry"])}</span>'
                     f'{chip(p.get("ret"),p.get("final"))}<span class="hubdt">{res(p)} \u00b7 {ed["date"]}</span></a>' for p,ed in allp[:40])
        hb=f'<div class="hzblock"><h3 class="hzh">\U0001F3C6 Every {c["name"]} pick, graded</h3><div class="hublist">{rows}</div></div>'
        best=max(settled,key=lambda x:x[0]['ret'],default=None)
        nice=datetime.date.fromisoformat(eds[0]['date']).strftime('%A, %B %-d, %Y')
        post='playoff' in hname
        H1=f"{c['name']} {'playoff ' if post else ''}picks today"
        n_open=sum(1 for p,_ in allp if not p.get('final')); since=datetime.date.fromisoformat(min(ed['date'] for _,ed in allp)).strftime('%b %-d')
        lead=(f"We've made {len(allp)} {c['name']} pick{'s'*(len(allp)!=1)} since {since}: {sw}-{len(settled)-sw} on {len(settled)} settled"+(f" ({pct(savg)} average return per $1 at entry; best call {best[0]['label']} ({best[0]['market'].split(':')[0]}) {pct(best[0]['ret'])})" if best else '')+f", with {n_open} still open." if settled else
              f"Our first {len(allp)} {c['name']} pick(s) are on the board below, graded live against Polymarket.")
        links=(f'<div class="hubcta"><a class="pill" href="{BASE}/#sports">Today\'s edition \u2192</a><a class="pill ghost" href="{BASE}/polymarket-picks-today/">All Polymarket picks \u2192</a>'
               +''.join(f'<a class="pill ghost" href="{BASE}{u}">{E(n.split(" picks")[0])} picks \u2192</a>' for l,(n,u) in LGHUBS.items() if l!=lg)
               +f'<a class="pill ghost" href="{BASE}/nfl-picks-this-week/">NFL picks \u2192</a>{sports_results_link()}<a class="pill ghost" href="{BASE}/track-record/">Track record \u2192</a></div>')
        ask=(f'<section class="signup wksign"><div><span class="kicker">\U0001F4EC Tomorrow\'s {c["name"]} plays</span><h2>Get our next {c["name"]} picks before {c["start"].lower()}.</h2>'
             f'<p>Every play lands in the free 7 AM ET email with the entry price and the why, then gets graded here in public, wins and losses. No spam, unsubscribe anytime.</p></div>{sform("lg")}</section>')
        q1=f"What are the best {c['name']} {'playoff ' if post else ''}picks today?"
        faqs=[
            (q1,f"Each morning we scan Polymarket's {c['name']} markets for big moves, heavy volume, and prices that look off versus sportsbook lines and previews, then rank every BUY with the Daily Five Score. Today's open plays are listed above with live odds and a live score line on game day."),
            (f"How do you grade {c['name']} picks?",f"We record the real Polymarket price of our side at publish time and mark it to the live price. A game pick settles at 100 cents if our side wins and 0 if it loses, as soon as the final score is in; a series or championship future settles when its market resolves. Returns are per $1 staked at entry."),
            ("Do you ever pick both sides?","Yes, and we show it. If the market moves and a later edition prefers the other side, both picks stay on the record and both get graded, so nothing is hidden."),
            ("Is this betting advice?","No. These are public prediction-market ideas we score and track in the open. Nothing here is betting, financial, or investment advice; prediction markets may not be legal where you live, and you can lose your entire stake."),
        ]
        fq='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
        cnav,csch=crumbs([('Home','/'),('Polymarket picks','/polymarket-picks-today/'),(H1[:1].upper()+H1[1:],P)])
        bodyh=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">{c["emo"]} {c["name"]} picks</span><h1 class="pt">{E(H1[:1].upper()+H1[1:])}</h1>'
               f'<p class="sub">AI-ranked {c["name"]} plays from The Daily Five, priced on Polymarket, with a live score line on game day and every result graded in public. {E(lead)} Updated {nice}.</p>{links}</section>'
               f'<div class="tiles">{tiles}</div>'
               f'<p class="disc-bar">\u26a0\ufe0f <b>Not betting advice.</b> Prices are real Polymarket snapshots; check local laws before trading prediction markets.</p>'
               f'{gd_board([p for p,_ in slate],c["board"])}{tb}{ask}{hb}{fq}<p class="sub hub-foot">Trade stocks too? See <a href="{BASE}/best-stocks-to-buy-today/">best stocks to buy today</a>.</p>')
        tag=' (ALCS, NLCS & World Series)' if post else ''
        dtag=datetime.date.fromisoformat(eds[0]['date']).strftime(' (%a, %b %-d)')
        title=f"{H1.title().replace('Mlb','MLB').replace('Nba','NBA').replace('Nhl','NHL')}{tag or dtag}: Live Odds & Results | {BRAND}"
        desc=(f"Today's {c['name']} {'playoff ' if post else ''}picks ranked by the Daily Five Score, with live Polymarket odds, start times, and a public record"+(f" ({sw}-{len(settled)-sw} settled)" if settled else '')+f". Updated {eds[0]['date']}.")[:155]
        evs=[{"@type":"SportsEvent","name":' vs. '.join(p['m']['outcomes']) if (p.get('m') or {}).get('outcomes') else p['market'],"startDate":kickoff(p).isoformat(),"sport":c['sport'],"url":f"{SITE}/picks/{p['id']}/"} for p,_ in slate if kickoff(p)]
        sch={"@context":"https://schema.org","@graph":[
            {"@type":"CollectionPage","name":H1[:1].upper()+H1[1:],"description":desc,"url":SITE+P,"dateModified":TODAY.isoformat(),"isPartOf":{"@type":"WebSite","name":BRAND,"url":SITE+"/"}},
            {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]},csch]
            +([{"@type":"ItemList","name":f"{c['name']} games we picked","itemListElement":[{"@type":"ListItem","position":i+1,"item":e} for i,e in enumerate(evs)]}] if evs else [])}
        w(P.strip('/')+'/index.html',shell(title,desc,P,bodyh,sch))
def league_links(cls='pill ghost'):
    return ''.join(f'<a class="{cls}" href="{BASE}{u}">{E(n[:1].upper()+n[1:])} \u2192</a>' for n,u in LGHUBS.values())

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
           f'<div class="hubcta"><a class="pill" href="{BASE}/nfl-picks-this-week/">This week\'s NFL picks \u2192</a><a class="pill ghost" href="{BASE}/track-record/">Track record \u2192</a>{sports_results_link()}</div></section><div class="wklist">{rows}</div>')
        w('nfl-results/index.html',shell(f"NFL Picks Results by Week: {tw}-{tl} on Polymarket | {BRAND}",f"Week-by-week results of every Daily Five NFL pick on Polymarket: {tw}-{tl} so far, with entry prices, final scores and returns.",'/nfl-results/',b,
              {"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":"NFL picks results by week","url":SITE+"/nfl-results/"},csch]}))
        urls.insert(0,('/nfl-results/',max(u[1] for u in urls)))
    return urls
def nfl_results_links(cls='pill ghost'):
    return ''.join(f'<a class="{cls}" href="{BASE}{o["url"]}">Week {o["wk"]} results: {o["w"]}-{o["l"]} \u2192</a>' for o in NFLWK[:3])
def week_rows(items):
    """Week-by-week (Mon..Sun, by settle date) rows for a results page. items: [(date, ret)] of settled picks only. Newest week first."""
    g={}
    for dd,r in items: g.setdefault(dd-datetime.timedelta(days=dd.weekday()),[]).append(r)
    if len(g)<2: return ''
    out=''
    for ws,rs in sorted(g.items(),reverse=True):
        we=ws+datetime.timedelta(days=6); ww=sum(r>0 for r in rs); a=sum(rs)/len(rs); cur=ws<=TODAY<=we
        rng=f"{ws.strftime('%b %-d')}\u2013{we.strftime('%-d') if we.month==ws.month else we.strftime('%b %-d')}"
        out+=(f'<div class="wkrow {"won" if a>=0 else "lost"}"><span class="wkres">{"THIS WK" if cur else "WK"}</span><span class="wkpk"><b>Week of {rng}: {ww}-{len(rs)-ww}</b>'
              f'<small>{len(rs)} settled{" so far" if cur else ""} \u00b7 $100 a pick {"+" if a>=0 else "\u2212"}${abs(sum(rs))*100:,.0f}</small></span><span class="wkent"><small>avg</small>{pct(a)}</span>{chip(a)}</div>')
    return f'<h2 class="h2s" id="weekly">Week by week</h2><p class="sub hub-lead">Settled picks grouped by the Monday-to-Sunday week they settled in. Average return is per $1 staked at entry.</p><div class="wklist">{out}</div>'
STK={}  # stock results rollup stats (filled by stock_stats before any page renders; empty until a stock pick settles)
def stock_stats(eds):
    """Settled vs open finance picks, per edition, for /stock-results/ and the links to it. Real settled exits only."""
    STK.clear()
    st=[(p,ed) for ed in eds for p in ed['finance'] if p.get('final') and p.get('ret') is not None]
    if not st: return
    w_=sum(p['ret']>0 for p,_ in st); avg=sum(p['ret'] for p,_ in st)/len(st)
    STK.update(url='/stock-results/',st=st,w=w_,l=len(st)-w_,avg=avg,
               op=[(p,ed) for ed in eds for p in ed['finance'] if not p.get('final')])
def stock_results_link(cls='pill ghost'):
    return f'<a class="{cls}" href="{BASE}/stock-results/">Stock results: {STK["w"]}-{STK["l"]} \u2192</a>' if STK else ''
def stock_results(eds):
    """/stock-results/: every settled stock pick graded at its real exit close, grouped by edition, plus open calls marked live."""
    if not STK: return []
    st,w_,l_,avg,op,P=STK['st'],STK['w'],STK['l'],STK['avg'],STK['op'],STK['url']
    n=len(st); tot=sum(p['ret'] for p,_ in st)*100
    best=max(st,key=lambda x:x[0]['ret']); worst=min(st,key=lambda x:x[0]['ret'])
    d=lambda s: datetime.date.fromisoformat(s)
    exitd=lambda p: (re.search(r'\d{4}-\d{2}-\d{2}',p.get('note') or '') or [None])[0]
    def row(p,ed):
        fin=p.get('final'); cls='open' if not fin else ('won' if p['ret']>0 else 'lost'); res={'open':'OPEN','won':'WIN','lost':'LOSS'}[cls]
        xd=exitd(p) if fin else None
        sub=f"{E(p['horizon'])} \u00b7 "+(f"exit at the {d(xd).strftime('%a %b %-d')} close" if xd else ('exits at the next close' if 'next close' in (p.get('note') or '') else f"marked live \u00b7 horizon ends {(lambda x: x.strftime('%b %-d' if x.year==TODAY.year else '%b %-d, %Y'))(d(ed['date'])+datetime.timedelta(days=HZ.get(p['horizon'],1)))}"))
        return (f'<a class="wkrow {cls}" href="{BASE}/picks/{p["id"]}/"><span class="wkres">{res}</span>'
                f'<span class="wkpk"><b>{p["action"]} {E(p["label"])}</b><small>{sub}</small></span>'
                f'<span class="wkent"><small>entry</small>{money("Finance",p["entry"])} <i>\u2192</i> {money("Finance",p.get("cur"))}{"" if fin else " now"}</span>'
                f'{chip(p.get("ret"),fin)}<span class="wkdt">picked {d(ed["date"]).strftime("%b %-d")}</span></a>')
    rec_=lambda ps_: f"{sum(p['ret']>0 for p in ps_)}-{sum(p['ret']<=0 for p in ps_)}"
    byed={}
    for p,ed in st: byed.setdefault(ed['date'],[]).append((p,ed))
    secs=''
    for dt,lst in sorted(byed.items(),reverse=True):
        ps_=[p for p,_ in lst]; a_=sum(p['ret'] for p in ps_)/len(ps_)
        secs+=(f'<h3 class="hzh">\U0001F4C8 <a href="{BASE}/{dt}/">{d(dt).strftime("%A, %B %-d")} edition</a> <small class="mut">{rec_(ps_)} \u00b7 avg {pct(a_)}</small></h3>'
               '<div class="wklist">'+''.join(row(p,ed) for p,ed in sorted(lst,key=lambda x:-x[0]['ret']))+'</div>')
    hz=''
    for h in ['3 Month','1 Day','1 Month','1 Year']:
        s_=[p for p,_ in st if p['horizon']==h]; o_=[p for p,_ in op if p['horizon']==h and p.get('ret') is not None]
        if not s_ and not o_: continue
        val=rec_(s_) if s_ else '\u2014'
        sub=(f"{len(s_)} settled, avg {pct(sum(p['ret'] for p in s_)/len(s_))}" if s_ else 'none settled yet')+(f" \u00b7 {len(o_)} open, avg mark {pct(sum(p['ret'] for p in o_)/len(o_))}" if o_ else '')
        hz+=f'<div class="tile"><span class="h">{h} picks</span><b class="{"up" if s_ and sum(p["ret"]>0 for p in s_)*2>=len(s_) else ("dn" if s_ else "")}">{val}</b><span class="s">{sub}</span></div>'
    bs=[p for p,_ in st if p['action']=='BUY']; ss=[p for p,_ in st if p['action']=='SELL']
    side=(f" BUY calls went {rec_(bs)} and SELL (short-side) calls went {rec_(ss)}." if bs and ss else '')
    first=min(ed['date'] for _,ed in st)
    summ=(f"The Daily Five has published {sum(len(e['finance']) for e in eds)} stock picks since {d(min(e['date'] for e in eds)).strftime('%B %-d')}, each with a real Yahoo Finance entry quote. "
          f"{n} have reached the end of their horizon and settled at a real closing price: {w_} won and {l_} lost ({w_/n*100:.0f}%), an average return of {pct(avg)} per pick. "
          f"$100 on every settled pick would be {'up' if tot>=0 else 'down'} ${abs(tot):,.2f}. Best call: {best[0]['action']} {best[0]['label']} ({best[0]['horizon']}, {pct(best[0]['ret'])}). "
          f"Worst: {worst[0]['action']} {worst[0]['label']} ({pct(worst[0]['ret'])}).{side} The other {len(op)} picks (mostly 1-Month and 1-Year calls) are still open and marked to live prices below.")
    tiles=(f'<div class="wkbig"><div><span class="k">Settled record</span><b class="{"up" if w_>=l_ else "dn"}">{w_}\u2013{l_}</b><span class="s">{n} settled \u00b7 {len(op)} still open</span></div>'
           f'<div><span class="k">Avg return</span><b class="{"up" if avg>=0 else "dn"}">{pct(avg)}</b><span class="s">per settled pick, entry to exit</span></div>'
           f'<div><span class="k">$100 a pick</span><b class="{"up" if tot>=0 else "dn"}">{"+" if tot>=0 else "\u2212"}${abs(tot):,.2f}</b><span class="s">on ${n*100:,} staked</span></div>'
           f'<div><span class="k">Best call</span><b class="up">{pct(best[0]["ret"])}</b><span class="s">{best[0]["action"]} {E(best[0]["label"])} \u00b7 {d(best[1]["date"]).strftime("%b %-d")}</span></div></div>')
    ask=(f'<section class="signup wksign"><div><span class="kicker">\U0001F4EC Tomorrow\'s calls</span><h2>Get tomorrow\'s stock picks before the open.</h2>'
         f'<p>1–2 buy-and-hold 3-month stock calls a week land in the free 7 AM ET email with a real entry price, target and the why, then get graded here against the S&P 500, wins and losses. No spam, unsubscribe anytime.</p></div>{sform("wk")}</section>')
    opn=sorted(op,key=lambda x:(x[1]['date'],x[0].get('ret') or 0),reverse=True)
    faqs=[("How are Daily Five stock picks graded?","Each pick has an entry price from a real Yahoo Finance quote at publish time. It is marked to live prices until its horizon ends (1 day, 30 days or 365 days after the edition), then settles at the first official daily close on or after that date. SELL calls are graded short-side, so a falling stock is a win."),
          ("When does a 1-Day stock pick settle?","At the regular-session close of the next trading day after the edition. Weekend editions settle at Monday's close. We never freeze an intraday price: a pick still in its exit session reads live until the close is final."),
          ("Is this financial advice?","No. The Daily Five aggregates public ideas and grades them in public for information and entertainment. Past results don't guarantee future returns, and you can lose money.")]
    faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
    cnav,csch=crumbs([('Home','/'),('Stock picks','/best-stocks-to-buy-today/'),('Stock results','/stock-results/')])
    h1=f"Stock Picks Results: {w_}-{l_} on {n} Settled Calls"
    bodyh=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">\U0001F4C8 Stock picks results \u00b7 since {d(first).strftime("%b %-d, %Y")}</span><h1 class="pt">{E(h1)}</h1>'
           f'<p class="sub wksum">{E(summ)}</p><div class="hubcta"><a class="pill" href="{BASE}/best-stocks-to-buy-today/">Today\'s stock picks \u2192</a>'
           f'<a class="pill ghost" href="{BASE}/track-record/">Full track record \u2192</a><a class="pill ghost" href="{BASE}/picks/">All picks by day \u2192</a><a class="pill ghost" href="{BASE}/scoreboard/">Scoreboard \u2192</a>{sports_results_link()}</div></section>'
           f'{tiles}<div class="tiles">{hz}</div>{week_rows([(d(exitd(p) or ed["date"]),p["ret"]) for p,ed in st])}{ask}'
           f'<h2 class="h2s">Every settled stock pick, by edition</h2><p class="sub hub-lead">Entry is the real quote when we published; exit is the official close at the end of the horizon. Return is per pick, short-side for SELLs. Tap any pick for its price chart and the original why.</p>{secs}'
           +(f'<h2 class="h2s">Still open: {len(op)} calls marked live</h2><p class="sub hub-lead">Marked to the latest Yahoo Finance price (may lag up to ~15 min in market hours). These settle at the close when their horizon ends.</p><div class="wklist">{"".join(row(p,ed) for p,ed in opn)}</div>' if op else '')+
           f'{faqh}<p class="disc-bar">\u26a0\ufe0f <b>Not financial advice.</b> Results use real Yahoo Finance prices and ignore commissions, slippage and taxes. Past results don\'t guarantee future returns.</p>')
    title=f"Stock Picks Results & Track Record: {w_}-{l_}, {pct(avg)} Avg Return | {BRAND}"
    desc=f"Every Daily Five stock pick graded at its real closing price: {w_}-{l_} on {n} settled calls, {pct(avg)} average return, plus {len(op)} open calls marked live."[:155]
    modified=TODAY.isoformat()
    art={"@type":"Article","headline":h1,"description":desc,"datePublished":TODAY.isoformat() if not STK.get('pub') else STK['pub'],"dateModified":modified,"author":{"@type":"Organization","name":BRAND},
         "publisher":{"@type":"Organization","name":BRAND,"logo":{"@type":"ImageObject","url":SITE+"/favicon.svg"}},"mainEntityOfPage":SITE+P,
         "mentions":[{"@type":"Corporation","name":p['label'],"tickerSymbol":p['symbol'],"url":f"{SITE}/picks/{p['id']}/"} for p,_ in st]}
    if OGIMG['v']: art['image']=SITE+OGIMG['v']
    w('stock-results/index.html',shell(title,desc,P,bodyh,{"@context":"https://schema.org","@graph":[art,csch,{"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]}]}))
    return [(P,modified)]
SPR={}  # sports results rollup stats (filled by sports_stats before any page renders; empty until a sports pick settles)
LGN={'nfl':('NFL','\U0001F3C8'),'mlb':('MLB','\u26be'),'nba':('NBA','\U0001F3C0'),'nhl':('NHL','\U0001F3D2'),'cfb':('College football','\U0001F3C8')}
def _sp_when(p,ed):
    """Sort/settle key for a sports pick: kickoff, else event date, else edition date (futures)."""
    k=kickoff(p)
    if k: return k
    return datetime.datetime.combine(datetime.date.fromisoformat(p.get('event_date') or ed['date']),datetime.time(12,0)).astimezone()
def sports_stats(eds):
    """Settled vs open sports picks for /sports-results/ and the links to it. Real settled results only."""
    SPR.clear()
    allp=[(p,ed) for ed in eds for p in ed['sports']]
    st=[(p,ed) for p,ed in allp if p.get('final') and p.get('ret') is not None]
    if not st: return
    w_=sum(p['ret']>0 for p,_ in st)
    SPR['vb']={k:[p for p,_ in st if vkey(p)==k] for k in ('val','flip','pricey','nl')}  # settled picks by value verdict at entry
    SPR.update(url='/sports-results/',st=st,w=w_,l=len(st)-w_,avg=sum(p['ret'] for p,_ in st)/len(st),op=[(p,ed) for p,ed in allp if not p.get('final')],n=len(allp))
def rec_summary():
    """All-time and latest-week records for the email's track-record row. Real settled picks only; {} if none."""
    out={}
    exitd=lambda p,ed: datetime.date.fromisoformat((re.search(r'\d{4}-\d{2}-\d{2}',p.get('note') or '') or [ed['date']])[0])
    for k,S,when in (('sports',SPR,lambda p,ed:_sp_when(p,ed).date()),('stocks',STK,exitd)):
        if not S: continue
        g={}
        for p,ed in S['st']: dd=when(p,ed); g.setdefault(dd-datetime.timedelta(days=dd.weekday()),[]).append(p['ret'])
        ws=max(g); rs=g[ws]; cur=ws<=TODAY<=ws+datetime.timedelta(days=6)
        out[k]=dict(w=S['w'],l=S['l'],avg=S['avg'],url=S['url'],wk=('This week' if cur else f"Week of {ws.strftime('%b %-d')}"),ww=sum(r>0 for r in rs),wl=sum(r<=0 for r in rs),wavg=sum(rs)/len(rs))
    return out
def safe_rec():
    try: return rec_summary()
    except Exception as ex: print('track record skipped:',ex); return {}
def sports_results_link(cls='pill ghost'):
    return f'<a class="{cls}" href="{BASE}/sports-results/">Sports results: {SPR["w"]}-{SPR["l"]} \u2192</a>' if SPR else ''
def final_line(p):
    """(html, text) final score of a settled game pick, our side in bold; None if no real score."""
    g=pgame(p.get('slug'))
    if not g or len(g['teams'])!=2 or not re.fullmatch(r'\d+-\d+',g.get('score') or ''): return None
    a,h=g['score'].split('-'); aw,hm=g['teams']; ps=pick_side(p,g,p.get('m') or {})
    B_=lambda t,sd: f'<b>{E(t)}</b>' if sd==ps else E(t)
    return f"{B_(aw['ab'],'a')} {a}\u2013{h} {B_(hm['ab'],'h')}", f"{aw['ab']} {a}, {hm['ab']} {h}"
def win_share(p,txt):
    """Share-the-win button: static X intent with the settled result baked in (live.js uses data-share-text as-is)."""
    u=f"{SITE}/picks/{p['id']}/?utm_source=win_share&utm_medium=x&utm_campaign=wins"
    href='https://x.com/intent/post?'+urllib.parse.urlencode({'text':txt,'url':u})
    return f'<a class="shr" href="{E(href)}" target="_blank" rel="noopener" data-share-text="{E(txt)}" data-share-what="{E(p["label"])}" data-share-url="{E(u)}" aria-label="Share this win"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.8 7.8L23 22h-6.2l-4.8-6.3L6.4 22H3.3l7.3-8.3L1 2h6.3l4.4 5.8zm-1.1 18h1.7L6.3 3.9H4.5z"/></svg>Share the win</a>'
def wins_wall(n=6,days=None,where='hub'):
    """'Biggest wins' wall: top real settled winners (sports + stocks) by return, each with a share-the-win button."""
    ws=[]
    for S,kind in ((SPR,'Sports'),(STK,'Stock')):
        for p,ed in (S.get('st') or []):
            if p['ret']<=0: continue
            dd=_sp_when(p,ed).date() if kind=='Sports' else datetime.date.fromisoformat((re.search(r'\d{4}-\d{2}-\d{2}',p.get('note') or '') or [ed['date']])[0])
            if days and (TODAY-dd).days>days: continue
            ws.append((p,ed,kind,dd))
    ws=sorted(ws,key=lambda x:-x[0]['ret'])[:n]
    if not ws: return ''
    def card(p,ed,kind,dd):
        fl=final_line(p) if kind=='Sports' and GAME_RE.match(p.get('slug') or '') else None
        sub=(fl[0]+' \u00b7 Final') if fl else (E(p['market']) if kind=='Sports' else f"{E(p['horizon'])} call \u00b7 closed {dd.strftime('%b %-d')}")
        ent=f"{money('Sports' if kind=='Sports' else 'x',p['entry'])} \u2192 {money('Sports' if kind=='Sports' else 'x',p.get('cur'))}"
        txt=(f"Called it: {p['action']} {p['label']} at {money('Sports' if kind=='Sports' else 'x',p['entry'])} on {datetime.date.fromisoformat(ed['date']).strftime('%b %-d')}, "
             f"settled {pct(p['ret'])}"+(f" ({fl[1]})" if fl else '')+". Every Daily Five pick is graded in public, wins and losses.")
        return (f'<div class="wwc"><a class="wwl" href="{BASE}/picks/{p["id"]}/"><span class="wwp">{pct(p["ret"])}</span>'
                f'<b>{E(p["action"])} {E(p["label"])}</b><small>{sub}</small><small class="mut">{"\U0001F3DF" if kind=="Sports" else "\U0001F4B0"} picked {datetime.date.fromisoformat(ed["date"]).strftime("%b %-d")} \u00b7 {ent}</small></a>{win_share(p,txt)}</div>')
    hd=(f'\U0001F525 Biggest wins, last {days} days' if days else '\U0001F525 Our biggest wins')
    lead=('Real settled picks, graded at our published entry price. Losses stay on the record too: '
          +' \u00b7 '.join(x for x in (f'<a href="{BASE}/sports-results/">sports {SPR["w"]}-{SPR["l"]}</a>' if SPR else '',f'<a href="{BASE}/stock-results/">stocks {STK["w"]}-{STK["l"]}</a>' if STK else '') if x)+'.')
    return f'<section class="wwall {where}" id="wins"><h2 class="h2s">{hd}</h2><p class="sub hub-lead">{lead}</p><div class="wwg">{"".join(card(*x) for x in ws)}</div></section>'
def sports_results(eds):
    """/sports-results/: every settled Polymarket sports pick graded with its real final score and real entry/exit price,
    by league, with a W/L strip, favorites vs underdogs, games vs futures, open picks live, Kit ask, FAQ + JSON-LD."""
    if not SPR: return []
    st,w_,l_,avg,op,P=SPR['st'],SPR['w'],SPR['l'],SPR['avg'],SPR['op'],SPR['url']
    n=len(st); tot=sum(p['ret'] for p,_ in st)*100; staked=n*100
    best=max(st,key=lambda x:x[0]['ret']); worst=min(st,key=lambda x:(x[0]['ret'],-x[0]['entry']))
    lg=lambda p: league_of(p) or 'other'
    mk=lambda p: (p['market'].split(':',1)[1] if ':' in p['market'] else p['market']).split(',')[0].replace('(London)','').replace('(rain-moved)','').strip()
    isgame=lambda p: bool(GAME_RE.match(p.get('slug') or ''))
    rec_=lambda ps_: f"{sum(p['ret']>0 for p in ps_)}-{sum(p['ret']<=0 for p in ps_)}"
    avg_=lambda ps_: sum(p['ret'] for p in ps_)/len(ps_) if ps_ else None
    def row(p,ed):
        fin=p.get('final'); cls='open' if not fin else ('won' if p['ret']>0 else 'lost'); res={'open':'LIVE','won':'WON','lost':'LOST'}[cls]
        k=kickoff(p); g=isgame(p)
        if fin:
            fl=final_line(p) if g else None
            sub=(f"{fl[0]} \u00b7 Final" if fl else f"{E(mk(p))} \u00b7 Final") if g else f"{E(p['market'])} \u00b7 market resolved"
            if p.get('note')=='final score, awaiting resolution': sub+=' \u00b7 awaiting on-chain resolution'
            vk=vkey(p); sub+=f' \u00b7 <span class="vvt {vk}">{VV[vk][0]} {VV[vk][1]}'+(f' {p["edge_pts"]:+.1f}' if p.get('edge_pts') is not None else '')+'</span>'
        else:
            sub=f"{E(mk(p))} \u00b7 "+(k.strftime('%a %b %-d, %-I:%M %p ET') if k else 'series future, settles when the market resolves')
        return (f'<a class="wkrow {cls}" href="{BASE}/picks/{p["id"]}/"><span class="wkres">{res}</span>'
                f'<span class="wkpk"><b>{E(p["label"])}</b><small>{sub}</small></span>'
                f'<span class="wkent"><small>entry</small>{money("Sports",p["entry"])} <i>\u2192</i> {money("Sports",p.get("cur"))}{"" if fin else " now"}</span>'
                f'{chip(p.get("ret"),fin)}<span class="wkdt">picked {datetime.date.fromisoformat(ed["date"]).strftime("%b %-d")}</span></a>')
    # W/L strip in settle order (kickoff / event date), oldest first
    chron=sorted(st,key=lambda x:(_sp_when(*x),x[1]['date']))
    strip=('<div class="wlstrip" role="list" aria-label="Every settled sports pick, oldest first">'+''.join(
        f'<a role="listitem" class="{"w" if p["ret"]>0 else "l"}" href="{BASE}/picks/{p["id"]}/" title="{E(p["label"])} ({E(mk(p))}): {"won" if p["ret"]>0 else "lost"}, entry {money("Sports",p["entry"])}">{"W" if p["ret"]>0 else "L"}</a>' for p,ed in chron)+'</div>')
    # by league
    order=[l for l in ['nfl','cfb','mlb','nba','nhl','other'] if any(lg(p)==l for p,_ in st+op)]
    secs=''; ltiles=''
    for l in order:
        s_=sorted([(p,ed) for p,ed in st if lg(p)==l],key=lambda x:(_sp_when(*x),x[1]['date']),reverse=True)
        o_=[p for p,_ in op if lg(p)==l]
        nm,emo=LGN.get(l,('Other','\U0001F3DF'))
        if s_:
            ps_=[p for p,_ in s_]
            hub=('/nfl-results/' if (l=='nfl' and NFLWK) else (LGHUBS[l][1] if l in LGHUBS else '/polymarket-picks-today/'))
            secs+=(f'<h3 class="hzh">{emo} <a href="{BASE}{hub}">{nm}</a> <small class="mut">{rec_(ps_)} \u00b7 avg {pct(avg_(ps_))}</small></h3>'
                   '<div class="wklist">'+''.join(row(p,ed) for p,ed in s_)+'</div>')
        sub=(f"{len(s_)} settled, avg {pct(avg_([p for p,_ in s_]))}" if s_ else 'none settled yet')+(f" \u00b7 {len(o_)} open" if o_ else '')
        if s_: ltiles+=f'<div class="tile"><span class="h">{emo} {nm} picks</span><b class="{("up" if sum(p["ret"]>0 for p,_ in s_)*2>=len(s_) else "dn") if s_ else ""}">{rec_([p for p,_ in s_]) if s_ else "\u2014"}</b><span class="s">{sub}</span></div>'
    fav=[p for p,_ in st if p['entry']>=0.6]; dog=[p for p,_ in st if p['entry']<0.6]
    gm=[p for p,_ in st if isgame(p)]; fu=[p for p,_ in st if not isgame(p)]
    split=lambda name,ps_,note: f'<div class="tile"><span class="h">{name}</span><b class="{"up" if (avg_(ps_) or 0)>=0 else "dn"}">{rec_(ps_)}</b><span class="s">{note} \u00b7 avg {pct(avg_(ps_))}</span></div>' if ps_ else ''
    ltiles+=split('Favorites (60\u00a2+)',fav,f'{len(fav)} settled')+split('Under 60\u00a2',dog,f'{len(dog)} settled')+(split('Single games',gm,f'{len(gm)} settled')+split('Series futures',fu,f'{len(fu)} settled') if gm and fu else '')
    # sportsbook check at entry: Polymarket price vs the no-vig sportsbook line (real lines only)
    vb=SPR['vb']; ecs,eeq,epr,enl=vb['val'],vb['flip'],vb['pricey'],vb['nl']; eb=ecs+eeq+epr
    vt=lambda k,ps_,note: (f'<div class="tile vvtile {k}"><span class="h">{VV[k][0]} {VV[k][1]}: {VV[k][2]}</span><b class="{"up" if (avg_(ps_) or 0)>=0 else "dn"}">{rec_(ps_)}</b><span class="s">{note} \u00b7 {len(ps_)} settled \u00b7 avg {pct(avg_(ps_))}</span></div>' if ps_ else
                          f'<div class="tile vvtile {k}"><span class="h">{VV[k][0]} {VV[k][1]}: {VV[k][2]}</span><b>0\u20130</b><span class="s">{note} \u00b7 none settled yet</span></div>')
    vtiles=(vt('val',ecs,f'Polymarket \u2265 {VAL_PTS:.0f} pts under the no-vig line')+vt('flip',eeq,f'within {VAL_PTS:.0f} pts of the no-vig line')
            +vt('pricey',epr,f'Polymarket \u2265 {VAL_PTS:.0f} pts over the line')+(vt('nl',enl,'no real sportsbook line at publish') if enl else ''))
    bksum=(f"Against the sportsbooks: {len(eb)} settled picks had a real moneyline at publish, and {len(eeq)} of them were coin flips at a fair price, within {VAL_PTS:.0f} points of the no-vig line at our entry ({rec_(eeq)}, avg {pct(avg_(eeq))}). "
           +("So most of our sports picks have not had a price edge on the books, and from here we only call a play value when Polymarket is at least 2 points cheaper than the books. " if len(eeq)*2>len(eb) else "") if len(eb)>=5 else '')
    # copy
    lgsum=', '.join(f"{LGN.get(l,('Other',''))[0]} {rec_([p for p,_ in st if lg(p)==l])}" for l in order if any(lg(p)==l for p,_ in st))
    since=datetime.date.fromisoformat(min(ed['date'] for ed in eds if ed['sports'])).strftime('%B %-d')
    tonight=[(p,ed) for p,ed in op if kickoff(p) and kickoff(p).date()==TODAY]
    lv=('Tonight: '+'; '.join(f"{p['label']} ({mk(p)}, {kickoff(p).strftime('%-I:%M %p ET')}) at {money('Sports',p.get('cur'))}, entry {money('Sports',p['entry'])}" for p,_ in sorted(tonight,key=lambda x:kickoff(x[0])))+'.') if tonight else ''
    summ=(f"The Daily Five has published {SPR['n']} sports picks on Polymarket since {since}, each with a real entry price at publish. "
          f"{n} have settled: {w_} won and {l_} lost ({w_/n*100:.0f}%), an average return of {pct(avg)} per $1 staked at our entry price. "
          f"$100 on every settled pick would be {'up' if tot>=0 else 'down'} ${abs(tot):,.0f} on ${staked:,} staked. By league: {lgsum}. "
          f"Best call: {best[0]['label']} ({mk(best[0])}) at {money('Sports',best[0]['entry'])}, {pct(best[0]['ret'])}"+''.join(f", tied with {p['label']} ({mk(p)})" for p,_ in st if p is not best[0] and abs(p['ret']-best[0]['ret'])<1e-9)+". "
          +(f"Toughest loss: {worst[0]['label']} ({mk(worst[0])}), a {money('Sports',worst[0]['entry'])} favorite. " if worst[0]['ret']<0 and worst[0]['entry']>=0.5 else '')
          +(f"Favorites (entry 60\u00a2+) went {rec_(fav)}; picks under 60\u00a2 went {rec_(dog)}. " if fav and dog else '')
          +bksum+f"{len(op)} picks are still open and marked to live Polymarket odds below.")
    tiles=(f'<div class="wkbig"><div><span class="k">Settled record</span><b class="{"up" if w_>=l_ else "dn"}">{w_}\u2013{l_}</b><span class="s">{n} settled \u00b7 {len(op)} still open</span></div>'
           f'<div><span class="k">Avg return</span><b class="{"up" if avg>=0 else "dn"}">{pct(avg)}</b><span class="s">per $1 staked at entry</span></div>'
           f'<div><span class="k">$100 a pick</span><b class="{"up" if tot>=0 else "dn"}">{"+" if tot>=0 else "\u2212"}${abs(tot):,.0f}</b><span class="s">on ${staked:,} staked</span></div>'
           f'<div><span class="k">Best call</span><b class="up">{pct(best[0]["ret"])}</b><span class="s">{E(best[0]["label"])} at {money("Sports",best[0]["entry"])}</span></div></div>')
    ask=(f'<section class="signup wksign"><div><span class="kicker">\U0001F4EC Tomorrow\'s plays</span><h2>Get tomorrow\'s sports picks before the first game.</h2>'
         f'<p>Five Polymarket plays (NFL, MLB, NBA) land in the free 7 AM ET email with the real entry price and the why, then get graded here after the final whistle, wins and losses. No spam, unsubscribe anytime.</p></div>{sform("wk")}</section>')
    opn=sorted(op,key=lambda x:(_sp_when(*x),x[1]['date']))
    faqs=[("How are Daily Five sports picks graded?","Each pick records the real Polymarket price of our side when the edition publishes. A game pick settles at 100 cents if our side wins and 0 cents if it loses, as soon as the final score is in (the official market resolution confirms it); a series or championship future settles when its market resolves. Return is per $1 staked at the entry price, so a win at 50 cents is +100% and any loss is -100%."),
          ("Why can the average return be negative with a winning record?","Because price matters. A win on a 75-cent favorite pays about +33%, while every loss costs the full -100%. A record above .500 only makes money if it beats the prices paid, which is why we show the average return and $100-a-pick result next to the win-loss record."),
          ("Do you compare Polymarket prices to sportsbooks?","Yes. Every sports pick with a real sportsbook moneyline shows it: we remove the vig to get the fair win chance and compare it to the Polymarket price, in points. Before a game starts we track DraftKings' live moneyline from ESPN's public scoreboard; once it starts, the pick is graded against the line at publish (or the last pre-game line we read) versus our entry. That gap is the Edge part of the Daily Five Score."),
          ("Do you ever pick both sides of a game?","Yes, and both stay on the record. If the market moves and a later edition prefers the other side, both picks are graded, so nothing gets hidden."),
          ("Is this betting advice?","No. These are public prediction-market ideas we score and grade in the open for information and entertainment. Prediction markets may not be legal where you live, and you can lose your entire stake.")]
    faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in faqs)+'</div>'
    cnav,csch=crumbs([('Home','/'),('Polymarket picks','/polymarket-picks-today/'),('Sports results',P)])
    h1=f"Sports Picks Results: {w_}-{l_} on {n} Settled Polymarket Plays"
    first=min(ed['date'] for _,ed in st)
    cta=(f'<div class="hubcta"><a class="pill" href="{BASE}/polymarket-picks-today/">Today\'s Polymarket picks \u2192</a>'
         +(f'<a class="pill ghost" href="{BASE}/nfl-results/">NFL results by week \u2192</a>' if NFLWK else '')+league_links()
         +f'<a class="pill ghost" href="{BASE}/track-record/">Full track record \u2192</a>{stock_results_link()}</div>')
    bodyh=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">\U0001F3DF Sports picks results \u00b7 since {datetime.date.fromisoformat(first).strftime("%b %-d, %Y")}</span><h1 class="pt">{E(h1)}</h1>'
           f'<p class="sub wksum">{E(summ)}{(" "+E(lv)) if lv else ""}</p>{cta}</section>'
           f'{tiles}{wins_wall(6)}<h2 class="h2s">Every result, in order</h2><p class="sub hub-lead">Oldest first. Tap any square for the pick, its entry price and its line-movement chart.</p>{strip}'
           f'<div class="tiles">{ltiles}</div>{week_rows([(_sp_when(p,ed).date(),p["ret"]) for p,ed in st])}<h2 class="h2s" id="value">Results by value verdict</h2><p class="sub hub-lead">Every settled pick graded at our entry against the no-vig sportsbook moneyline: <b>value</b> means Polymarket was at least {VAL_PTS:.0f} points cheaper than the books, a <b>coin flip</b> was within {VAL_PTS:.0f} points (a fair price, no edge), and <b>pricey</b> was at least {VAL_PTS:.0f} points over. <a href="{BASE}/how-we-rank/#value">How it works \u2192</a></p><div class="tiles">{vtiles}</div>{ask}'
           +gd_board([p for p,_ in opn],'Game day: our open games')+
           f'<h2 class="h2s">Every settled sports pick, by league</h2><p class="sub hub-lead">Entry is the real Polymarket price of our side when we published; exit is 100\u00a2 for a win and 0\u00a2 for a loss. Final scores from Polymarket\'s events API. Newest game first.</p>{secs}'
           +(f'<h2 class="h2s">Still open: {len(op)} picks marked live</h2><p class="sub hub-lead">Marked to the live Polymarket price. Games settle at the final whistle; futures when their market resolves.</p><div class="wklist">{"".join(row(p,ed) for p,ed in opn)}</div>' if op else '')+
           f'{faqh}<p class="disc-bar">\u26a0\ufe0f <b>Not betting advice.</b> Results use real Polymarket prices and ignore fees and slippage; prediction markets may not be legal where you live, and you can lose your entire stake.</p>')
    title=f"Sports Picks Results: {w_}-{l_} on Polymarket, {pct(avg)} Avg Return | {BRAND}"
    desc=f"Every Daily Five sports pick graded with real final scores and Polymarket prices: {w_}-{l_} on {n} settled plays ({lgsum}), {pct(avg)} average return."[:155]
    modified=TODAY.isoformat()
    art={"@type":"Article","headline":h1,"description":desc,"datePublished":TODAY.isoformat(),"dateModified":modified,"author":{"@type":"Organization","name":BRAND},
         "publisher":{"@type":"Organization","name":BRAND,"logo":{"@type":"ImageObject","url":SITE+"/favicon.svg"}},"mainEntityOfPage":SITE+P,
         "mentions":[{"@type":"SportsEvent","name":mk(p),"startDate":kickoff(p).isoformat(),"url":f"{SITE}/picks/{p['id']}/"} for p,_ in chron if kickoff(p)]}
    if OGIMG['v']: art['image']=SITE+OGIMG['v']
    w('sports-results/index.html',shell(title,desc,P,bodyh,{"@context":"https://schema.org","@graph":[art,csch,{"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":q,"acceptedAnswer":{"@type":"Answer","text":a}} for q,a in faqs]}]}))
    return [(P,modified)]
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
    tb=(f'<section class="sbhero"><span class="kicker">\U0001F3C6 Track record</span><h1 class="pt">Every pick, graded in public</h1><p class="sub">We publish an entry price from a real quote for every pick, then mark it to live market data until its horizon ends (1 Day, 1 Month, 1 Year) or its market resolves. Nothing gets deleted. SELL returns are short-side. See the <a href="{BASE}/scoreboard/">Scoreboard</a> for charts.</p>{('<div class="hubcta">'+stock_results_link('pill')+sports_results_link('pill')+nfl_results_links('pill')+('<a class="pill ghost" href="'+BASE+'/nfl-results/">All NFL weeks \u2192</a>' if NFLWK else '')+league_links()+'</div>') if (NFLWK or STK or SPR) else ''}</section>'
        f'<div class="tiles">{tiles}</div><h2 class="h2s">Tickers &amp; markets</h2><div class="tks">{tk}</div><h2 class="h2s">All picks</h2><div class="rcs col">{allp}</div>')
    w('track-record/index.html',shell(f"Track Record: Win Rate & Returns of Every Pick | {BRAND}","The Daily Five's public track record: win rate and average return by horizon for every stock and sports-market pick, marked to real prices.",'/track-record/',tb,{"@context":"https://schema.org","@type":"CollectionPage","name":"Daily Five Track Record","url":SITE+"/track-record/"}))
    # /picks/ index: every pick page, newest edition first (the parent of every /picks/<id>/ URL used to 404)
    byd={}
    for r in rows: byd.setdefault(r['date'],[]).append(r)
    rec=lambda rs: f"{sum(r['ret']>0 for r in rs if r['final'] and r['ret'] is not None)}-{sum(r['ret']<=0 for r in rs if r['final'] and r['ret'] is not None)}"
    secs=''.join(f'<h2 class="h2s"><a href="{BASE}/{d}/">{datetime.date.fromisoformat(d).strftime("%A, %B %-d")}</a> <small class="mut">{len(rs)} picks \u00b7 settled {rec(rs)}</small></h2><div class="rcs col">'+''.join(f'<a class="rc" href="{BASE}/picks/{r["id"]}/"><b class="{r["action"].lower()}">{r["action"]}</b> {E(r["pick"])} \u00b7 {E(r["horizon"])} {chip(r["ret"],r["final"])}</a>' for r in rs)+'</div>' for d,rs in sorted(byd.items(),reverse=True))
    cnav,csch=crumbs([('Home','/'),('All picks','/picks/')])
    pb=(f'{cnav}<section class="sbhero"><span class="kicker">\U0001F5C2 All picks</span><h1 class="pt">Every Daily Five pick, by day</h1><p class="sub">{len(rows)} stock and prediction-market picks since {min(byd)}, each with its entry price, live mark and result. Hubs: <a href="{BASE}/best-stocks-to-buy-today/">stock picks</a>, <a href="{BASE}/nfl-picks-this-week/">NFL picks</a>, <a href="{BASE}/polymarket-picks-today/">Polymarket picks</a>{''.join(f', <a href="{BASE}{u}">{n}</a>' for n,u in LGHUBS.values())}.</p>{('<div class="hubcta">'+stock_results_link('pill')+sports_results_link('pill')+nfl_results_links('pill')+league_links()+'</div>') if (NFLWK or STK or SPR) else ''}</section>{secs}')
    w('picks/index.html',shell(f"All Picks: Every Stock & Prediction-Market Call, by Day | {BRAND}",f"All {len(rows)} Daily Five picks by day: stock BUY/SELL calls and Polymarket sports plays with entry prices, live marks and settled results.",'/picks/',pb,{"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":"All Daily Five picks","url":SITE+"/picks/"},csch]}))
    urls.insert(0,('/picks/',TODAY.isoformat()))
    return urls
INDEXNOW_KEY='fcd40c5d2b89f9aed9ee904f5baee9f2'
def beta_page(BETA,brows):
    """/beta-archive/: every pre-launch (Oct 15-24, 2026) pick, graded honestly. Linked from the footer."""
    def rec(rs):
        st=[r for r in rs if r['final'] and r['ret'] is not None]; w_=sum(r['ret']>0 for r in st)
        return f"{w_}-{len(st)-w_}", (sum(r['ret'] for r in st)/len(st) if st else None)
    sr,sa=rec([r for r in brows if r['kind']=='Sports']); fr,fa=rec([r for r in brows if r['kind']=='Finance'])
    fmt=lambda r,v: (f"{v*100:.1f}¢" if r['kind']=='Sports' else f"${v:,.2f}") if v is not None else 'pending'
    tr=''.join(f'<tr><td class="mono">{r["date"][5:]}</td><td><span class="mini {r["action"].lower()}">{r["action"]}</span> <a href="{BASE}/picks/{r["id"]}/"><b>{E(r["pick"])}</b></a></td><td>{E(r["horizon"])}</td><td class="mono">{fmt(r,r["entry"])}</td><td class="mono">{fmt(r,r["cur"])}</td><td>{chip(r["ret"],r["final"])}</td></tr>' for r in brows)
    wd=[(e,p) for e in ALLEDS_ALL() if e['date']==LAUNCH for p in e.get('withdrawn_finance',[])]
    wdh=('<h2 class="h2s">Withdrawn at relaunch (Oct 25 morning)</h2><p class="sub">These stock calls went out in the Oct 25 morning email under the old 1-day/1-month horizons, then were withdrawn when we moved to 3-month calls only. They are not graded anywhere.</p><ul>'+''.join(f'<li>{E(p["action"])} {E(p["label"])} ({E(p["horizon"])}) at ${p["entry"]:,.2f}</li>' for e,p in wd)+'</ul>') if wd else ''
    ws=[(e,p) for e in ALLEDS_ALL() if e['date']==LAUNCH for p in e.get('withdrawn_sports',[])]
    wdh+=('<h2 class="h2s">Day 1 sports leans, not graded (Oct 25)</h2><p class="sub">These Oct 25 sports picks failed the new rules (under 40¢ longshots or coin flips with a thin edge). We list them for transparency, but they are not graded or counted in any record.</p><ul>'+''.join(f'<li>{E(p["label"])} · {E(p["market"])} at {p["entry"]*100:.1f}¢: {E(p.get("withdrawn_reason",""))}</li>' for e,p in ws)+'</ul>') if ws else ''
    eds_l=''.join(f'<a href="{BASE}/{e["date"]}/"><span class="ad">{e["date"]}</span><b>{E(e["headline"])}</b></a>' for e in BETA)
    bodyh=(f'<section class="sbhero"><span class="kicker">🧪 Beta archive (Oct 2026)</span><h1 class="pt">Our beta: Oct 15–24, 2026</h1>'
           f'<p class="sub">Before Max Edge\'s Day 1 on Oct 25, 2026 we ran a 10-day public beta. We moved its picks here so the main scoreboard starts fresh, but nothing is deleted: every beta pick is below with its real entry and result. Sports went <b>{sr}</b> (avg {pct(sa)} per $1); stock calls went <b>{fr}</b> (avg {pct(fa)}). What we learned changed our rules: no more coin flips or longshots, and stocks are now 3-month calls graded against the S&amp;P 500. See <a href="{BASE}/how-we-rank/">How we rank</a>.</p></section>'
           f'{wdh}<h2 class="h2s">Every beta pick</h2><div class="tbl"><table><thead><tr><th>Date</th><th>Pick</th><th>Horizon</th><th>Entry</th><th>Exit / now</th><th>P/L</th></tr></thead><tbody>{tr}</tbody></table></div>'
           f'<h2 class="h2s">Beta editions</h2><div class="arch">{eds_l}</div>')
    w('beta-archive/index.html',shell(f"Beta archive (Oct 2026) | {BRAND}","Every Daily Five beta pick from Oct 15-24, 2026, graded honestly.",'/beta-archive/',bodyh))
_ALL=[]
def ALLEDS_ALL(): return _ALL
def leans_section(eds):
    """Scoreboard: Max's Leans, a separate record (never mixed into the tiles, sports or Bold Bet record above)."""
    ls=leans(eds)
    if not ls: return ''
    ef=lambda p: f"{p['edge']:+.1f} pts" if p.get('edge') is not None else '—'
    w_,l_,avg,op=lean_rec(eds)
    tr=''.join(f'<tr><td class="mono">{e["date"][5:]}</td><td><span class="mini buy">LEAN</span> <b>{E(p["label"])}</b> <small>{E(p["market"])}</small></td><td class="mono">{p["entry"]*100:.1f}¢</td><td class="mono">{ef(p)}</td><td class="mono">{money("Sports",p.get("cur"))} <small>{E(p.get("note") or "")}</small></td><td>{chip(p.get("ret"),p.get("final"))}</td><td>{("Win" if p["ret"]>0 else "Loss") if p.get("final") and p.get("ret") is not None else "Pending"}</td><td><a href="{BASE}/{e["date"]}/#lean">edition ↗</a></td></tr>' for e,p in ls)
    hd=f"{w_}-{l_}" if w_+l_ else "0-0"
    return (f'<section class="sec leans" id="leans"><div class="sh"><span class="si">🤏</span><div><h2>Max\'s Leans · separate record</h2><p class="sub">On days when no game clears our bar (no Bold Bet), Max Edge, our AI host, names his closest miss as a <b>lean</b>. Leans are graded here in public, one 1-unit buy at the published Polymarket price, and are <b>never</b> counted in the sports or Bold Bet record. Think of it as the bench: it plays, but it doesn\'t get a jersey.</p></div></div>'
            f'<div class="tiles"><div class="tile"><span class="h">Leans</span><b class="{"up" if (avg or 0)>=0 else "dn"}">{hd}</b><span class="s">{(pct(avg)+" avg per $1") if avg is not None else "no settled leans yet"} · {op} open</span></div></div>'
            f'<div class="tbl"><table><thead><tr><th>Date</th><th>Lean</th><th>Entry</th><th>Edge vs books</th><th>Now / exit</th><th>P/L</th><th>Result</th><th></th></tr></thead><tbody>{tr}</tbody></table></div></section>')
def main():
    shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
    w('style.css',open(os.path.join(ROOT,'style.css')).read()); w('.nojekyll','')
    w('favicon.svg',LOGO.replace('class="mark" ','xmlns="http://www.w3.org/2000/svg" ').replace(' width="34" height="34"',''))
    host=urlparse(SITE).hostname
    if host and not host.endswith('github.io'): w('CNAME',host+'\n')
    eds_all=[json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT,'editions','*.json')),reverse=True)]
    CLIP_EDS.update({e['date']:e for e in eds_all})
    for ed in eds_all: enrich(ed)
    _ALL[:]=eds_all
    ALLEDS[:]=eds_all
    attach_books(eds_all)
    hits=source_hits(eds_all)
    for ed in eds_all:
        for p in ed['finance']+ed['sports']: score_pick(p,hits)
        ed['finance'].sort(key=lambda p:-p['score']); ed['sports'].sort(key=lambda p:-p['score'])
    BETA=[e for e in eds_all if e['date']<LAUNCH]; eds=[e for e in eds_all if e['date']>=LAUNCH]
    # Pass 1: keep every beta pick/ticker page online (history is never deleted); main pages below overwrite shared paths.
    nfl_weeks(eds_all); stock_stats(eds_all); sports_stats(eds_all); league_hubs(eds_all)
    brows=[dict(id=p['id'],date=e['date'],kind=p['kind'],horizon=p['horizon'] if p['kind']=='Finance' else 'Sports',action=p['action'],pick=p['label'] if p['kind']=='Finance' else f"{p['label']} · {p['market']}",short=p['label'][:7],entry=p['entry'],cur=p['cur'],final=p['final'],note=p['note'],ret=p['ret'],src=p['source']['url'],pts=p['pts']) for e in BETA for p in e['finance']+e['sports']]
    beta_extra=seo_pages(eds_all,brows,'') if BETA else []
    ALLEDS[:]=eds
    nfl_weeks(eds); stock_stats(eds); sports_stats(eds); lgh=league_hubs(eds)
    beta_page(BETA,brows)
    items=[]
    for i,ed in enumerate(eds_all):
        prev=eds_all[i+1] if i+1<len(eds_all) else None
        if ed['date']==LAUNCH: prev=None  # Day 1: no 'yesterday' recap from the beta
        d=ed['date']; dd=datetime.date.fromisoformat(d); nice=dd.strftime('%A, %B %-d, %Y')
        picks=", ".join(f"{p['action']} {p['label']}" for p in ed['finance'][:4])
        title=f"{ed['headline']} | Daily Five, {dd.strftime('%b %-d')}"
        desc=ed_desc(ed,nice,picks)
        sch={"@context":"https://schema.org","@type":"NewsArticle","headline":ed['headline'][:110],"datePublished":d,"dateModified":d,"description":desc,"publisher":{"@type":"Organization","name":BRAND,"url":SITE,"logo":{"@type":"ImageObject","url":SITE+"/favicon.svg"}},"author":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/{d}/"}
        og=ogimage(ed,nice); sch['image']=SITE+og
        if i==0: OGIMG['v']=og
        hr=hero(ed,nice); w(f'{d}/index.html',shell(title,desc,f'/{d}/',body(ed,prev),sch,hr,og)); items.append((d,nice,title,desc,ed,hr))
    if items:
        d,nice,title,desc,ed,hr=items[0]
        w('index.html',shell(f"The Daily Five: Today's Best Stock Picks, AI News & Sports Market Plays",f"{TAG} Today: {desc}",'/',body(ed,eds[1] if len(eds)>1 else None,home=True),{"@context":"https://schema.org","@type":"WebSite","name":BRAND,"url":SITE+"/","description":TAG},hr))
    items=[x for x in items]  # archive lists every edition, beta included
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
    tiles=tile('All picks',rows)+''.join(tile(h,[r for r in rows if r['horizon']==h]) for h in ['3 Month','1 Day','1 Month','1 Year','Sports'] if any(r['horizon']==h for r in rows))
    fmt=lambda r,v: (f"{v*100:.1f}¢" if r['kind']=='Sports' else f"${v:,.2f}") if v is not None else 'pending'
    tr=''.join(f'<tr><td class="mono">{r["date"][5:]}</td><td><span class="mini {r["action"].lower()}">{r["action"]}</span> <a href="{BASE}/picks/{r['id']}/"><b>{E(r["pick"])}</b></a></td><td>{E(r["horizon"])}</td><td class="mono">{fmt(r,r["entry"])}</td><td class="mono">{fmt(r,r["cur"])} <small>{E(r["note"])}</small></td><td>{spark(r["pts"],90,26)}</td><td>{chip(r["ret"],r["final"])}</td><td>{("Win" if r["ret"]>0 else "Loss" if r["ret"]<0 else "Flat") if r["ret"] is not None else "Pending"}{"" if r["final"] else " <small>open</small>"}</td><td><a href="{E(r["src"])}" rel="nofollow noopener" target="_blank" aria-label="source">↗</a></td></tr>' for r in rows)
    upd=datetime.datetime.now().strftime('%b %-d, %Y · %-I:%M %p ET')
    sbstrip=today_strip([p for e in eds for p in e['finance']+e['sports']],'sb',max(eds,key=lambda e:e['date'])['finance']+max(eds,key=lambda e:e['date'])['sports'])
    sb=f'''<section class="sbhero"><span class="kicker">📊 Scoreboard</span><h1 class="pt">If you traded it immediately</h1><p class="sub">Every pick at its published entry price, marked to real market data from Yahoo Finance (stocks) and Polymarket (markets). SELL returns are short-side. Picks close at the end of their horizon or when the market resolves. Updated {upd}.</p>{sbstrip}</section>
<div class="tiles">{tiles}</div>{bar_chart(rows)}<div class="tbl"><table><thead><tr><th>Date</th><th>Pick</th><th>Horizon</th><th>Entry</th><th>Now / exit</th><th>Trend</th><th>P/L</th><th>Result</th><th></th></tr></thead><tbody>{tr}</tbody></table></div>{leans_section(eds)}'''
    w('scoreboard/index.html',shell(f"Scoreboard: Track Record of Every Pick | {BRAND}","If you traded every Daily Five pick immediately: entry, current price, % return, win rate and average return by horizon.",'/scoreboard/',sb,{"@context":"https://schema.org","@type":"Dataset","name":f"{BRAND} Scoreboard","description":"Track record of featured picks","url":SITE+"/scoreboard/"}))
    hub=best_stocks_hub(eds); pmh=polymarket_hub(eds); nfr=nfl_results(eds)+stock_results(eds)+sports_results(eds); nfh=nfl_hub(eds); mxh=max_edge_hub(eds_all); erh=earnings_hub(); tmh=three_month_hub(eds); league_hub_pages(eds); extra=seo_pages(eds,rows,tiles); render_pick_ogs(); write_live(eds); w('live.js',open(os.path.join(ROOT,'live.js')).read())
    faq_ents=[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in FAQS]
    how_sch={'@context':'https://schema.org','@graph':[
        {'@type':'Article','headline':'How we rank: the Daily Five Score','author':{'@type':'Organization','name':BRAND},'publisher':{'@type':'Organization','name':BRAND},'mainEntityOfPage':SITE+'/how-we-rank/','description':'How the 0-100 Daily Five Score ranks every stock and sports-market pick.'},
        {'@type':'FAQPage','mainEntity':faq_ents,'url':SITE+'/how-we-rank/'},
    ]}
    w('how-we-rank/index.html',shell(f'How We Rank Picks: The Daily Five Score Methodology | {BRAND}','How the 0-100 Daily Five Score ranks every stock and sports-market pick: source credibility, consensus, edge vs analyst targets and sportsbook odds, and risk/reward.','/how-we-rank/',HOWTO,how_sch))
    # lastmod: hubs today; an edition page changes until all its picks settle; pick/ticker pages from lastmod()
    edlm=lambda e: max([lastmod(p,e) for p in e['finance']+e['sports']]+[e['date']])
    urls=[(u,TODAY.isoformat()) for u in ['/','/scoreboard/','/track-record/','/how-we-rank/',hub,pmh,nfh]+([mxh] if mxh else [])+([erh] if erh else [])+([tmh] if tmh else [])+lgh+['/archive/','/beta-archive/']]+[(f"/{e['date']}/",edlm(e)) for e in eds_all]+[(f'/max-edge/{os.path.basename(f)[4:14]}/',os.path.basename(f)[4:14]) for f in sorted(glob.glob(os.path.join(ROOT,'clips','max-*.mp4')))]+nfr+extra
    seen={u for u,_ in urls}; urls+=[x for x in beta_extra if x[0] not in seen]
    w('sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{SITE}{u}</loc><lastmod>{lm}</lastmod></url>" for u,lm in urls)+'</urlset>')
    w('googlef258d1e6972b7938.html','google-site-verification: googlef258d1e6972b7938.html')
    w(INDEXNOW_KEY+'.txt',INDEXNOW_KEY)  # IndexNow key file (Bing, Yandex, Seznam, Naver); indexnow.py pings after deploy
    # video sitemap: one <url> per Max Edge clip, landing on that day's edition page (Google video results)
    vids=''
    for f in sorted(glob.glob(os.path.join(ROOT,'clips','max-*.mp4'))):
        d=os.path.basename(f)[4:14]; dur=mp4_secs(f); vt,vdsc,vp=clip_meta(d)
        vids+=(f"<url><loc>{SITE}{vp}</loc><video:video><video:thumbnail_loc>{SITE}/video/max-{d}.jpg</video:thumbnail_loc>"
               f"<video:title>{E(vt[:100])}</video:title>"
               f"<video:description>{E(vdsc)}</video:description>"
               f"<video:content_loc>{SITE}/video/max-{d}.mp4</video:content_loc>"+(f"<video:duration>{round(dur)}</video:duration>" if dur else '')+
               f"<video:publication_date>{d}T07:00:00-04:00</video:publication_date><video:family_friendly>yes</video:family_friendly></video:video></url>")
    w('video-sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">'+vids+'</urlset>')
    w('robots.txt',f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\nSitemap: {SITE}/video-sitemap.xml\n")
    os.makedirs(os.path.join(OUT,'email'),exist_ok=True)
    for f in glob.glob(os.path.join(ROOT,'email','*.html')): shutil.copy(f,os.path.join(OUT,'email'))
    rfc=lambda d: datetime.datetime.fromisoformat(d+'T09:00:00-04:00').strftime('%a, %d %b %Y %H:%M:%S %z')
    w('feed.xml','<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'+f"<title>{BRAND}</title><link>{SITE}/</link><description>{E(TAG)}</description>"+''.join(f"<item><title>{E(t)}</title><link>{SITE}/{d}/</link><guid>{SITE}/{d}/</guid><pubDate>{rfc(d)}</pubDate><description>{E(ds)}</description></item>" for d,_,t,ds,_,_ in items)+'</channel></rss>')
    w('404.html',shell(f"Not found | {BRAND}","Page not found",'/404.html',f'<h1 class="pt">Not found</h1><p><a href="{BASE}/">Go to today\'s edition →</a></p>'))
    try:
        import email_build; print('email ->',email_build.write(eds[0],eds[1] if len(eds)>1 else None,safe_rec(),open3(eds[0]['date'])))
    except Exception as ex: print('email build skipped:',ex)
    print(f"built {len(items)} editions, {len(rows)} scoreboard rows -> {OUT}")
if __name__=='__main__': main()
