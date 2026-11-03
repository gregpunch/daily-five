#!/usr/bin/env python3
"""Sportsbook line movement for a game, from ESPN's free public game summary JSON (DraftKings pickcenter; no account or key).
Used by build.py (book line move on Max's leans) and by the 7 AM routine as the lean line check (FORMAT.md):
  python3 lines.py <polymarket-slug> <espn-game-url-or-id> <label> [entry-price]
prints the open / current moneyline for our side and PASS or SKIP."""
import json, re, sys, urllib.request
LG={'nfl':'football/nfl','nba':'basketball/nba','mlb':'baseball/mlb','nhl':'hockey/nhl','wnba':'basketball/wnba','cfb':'football/college-football','ncaab':'basketball/mens-college-basketball'}
def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=15) as r: return json.load(r)
def _am(x):
    x=str(x or '').strip().upper().replace('\u2212','-')
    if x in ('EVEN','EV','PK'): return 100
    try: v=int(float(x)); return v if abs(v)>=100 else None
    except Exception: return None
def p_of(o): return 100/(o+100) if o>0 else -o/(-o+100)
def novig(a,b): pa,pb=p_of(a),p_of(b); return pa/(pa+pb)
def fmt(o): return f"{o:+d}" if o is not None else '—'
def move(slug,url,label):
    """{'open':[ours,theirs],'now':[ours,theirs],'state':'pre|in|post','book':name} or None.
    'now' is ESPN's latest line: the closing line once the game has started."""
    lg=LG.get((slug or '').split('-')[0]); gid=re.search(r'(\d{6,})',str(url or ''))
    if not lg or not gid: return None
    d=_get(f"https://site.api.espn.com/apis/site/v2/sports/{lg}/summary?event={gid.group(1)}")
    comp=d['header']['competitions'][0]; lab=label.lower()
    me=[c for c in comp['competitors'] if lab in (c['team'].get('displayName','')+' '+c['team'].get('name','')).lower() or lab==c['team'].get('abbreviation','').lower()]
    if len(me)!=1: return None
    ms=me[0]['homeAway']; os_='away' if ms=='home' else 'home'
    for pc in d.get('pickcenter') or []:
        ml=pc.get('moneyline') or {}
        op=[_am(((ml.get(s) or {}).get('open') or {}).get('odds')) for s in (ms,os_)]
        nw=[_am(((ml.get(s) or {}).get('close') or {}).get('odds')) for s in (ms,os_)]
        if None in op or None in nw: continue
        return {'open':op,'now':nw,'state':comp['status']['type']['state'],'book':(pc.get('provider') or {}).get('name','Sportsbook'),'team':me[0]['team'].get('abbreviation','')}
    return None
def check(mv):
    """Lean line check: post a lean only if the book's no-vig chance for our side has held or grown since open
    (the line moved toward us or stayed put). A line moving away from us means the money disagrees."""
    if not mv: return None
    d=(novig(*mv['now'])-novig(*mv['open']))*100
    return {'pass':d>=-0.5,'d':round(d,1)}
if __name__=='__main__':
    slug,url,label=sys.argv[1:4]; mv=move(slug,url,label)
    if not mv: print('NO LINE: ESPN has no open/current moneyline for this game -> no lean'); sys.exit(2)
    c=check(mv)
    print(f"{label}: opened {fmt(mv['open'][0])} ({novig(*mv['open'])*100:.1f}% no-vig), now {fmt(mv['now'][0])} ({novig(*mv['now'])*100:.1f}%), {c['d']:+.1f} pts since open")
    if len(sys.argv)>4: print(f"edge now vs Polymarket {float(sys.argv[4])*100:.1f}c: {novig(*mv['now'])*100-float(sys.argv[4])*100:+.1f} pts")
    print('PASS: line held or moved toward us, the lean can run' if c['pass'] else 'SKIP: the line moved away from us since open, no lean today')
    sys.exit(0 if c['pass'] else 1)
