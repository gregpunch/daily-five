#!/usr/bin/env python3
"""Newsletter HTML for an edition -> email/<date>.html (email-safe: tables + inline CSS, 600px).
Run: python3 email_build.py [YYYY-MM-DD]   (also called from build.py for the latest edition).
Named email_build.py (not email.py) so it doesn't shadow Python's stdlib `email` module."""
import sys, os, json, glob, html, datetime, urllib.parse
ROOT=os.path.dirname(os.path.abspath(__file__)); E=lambda s: html.escape(str(s))
BG,CARD,LINE,TXT,MUT,UP,DN,VIO,AMB='#07080d','#11131e','#22263a','#f2f4fa','#9ba3ba','#16c784','#ff4d5e','#7c5cff','#ffb020'
F="font-family:Inter,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
M="font-family:'JetBrains Mono',SFMono-Regular,Menlo,Consolas,monospace;"
SITE='https://readdailyfive.com'
MIN_SCORE=50
import re as _re
def src(name):
    # Clean source names: 'Barclays (via Stocktwits)' -> 'Barclays', 'via CNBC' -> 'CNBC'
    n=_re.sub(r'\s*\(via [^)]*\)?','',str(name)).strip()
    n=_re.sub(r'^via\s+','',n,flags=_re.I).strip()
    return n or str(name)
def keep(p):
    s=p.get('score'); return s is None or s>=MIN_SCORE
def act(a):
    c=UP if a=='BUY' else DN; fg='#04130c' if a=='BUY' else '#ffffff'
    return f'<span style="display:inline-block;background:{c};color:{fg};{F}font-weight:900;font-size:12px;letter-spacing:1px;padding:5px 11px;border-radius:999px;">{a}</span>'
def score(p):
    s=p.get('score')
    if s is None: return ''
    c=UP if s>=70 else (AMB if s>=50 else DN)
    return f'<td align="right" valign="top" width="64" style="padding-left:10px;"><div style="border:2px solid {c};border-radius:12px;padding:6px 4px;text-align:center;{M}"><div style="font-size:20px;font-weight:700;color:{c};line-height:1;">{s}</div><div style="{F}font-size:9px;color:{MUT};letter-spacing:1px;padding-top:3px;">D5 SCORE</div></div></td>'
def sec(icon,title,sub):
    return f'<tr><td style="padding:30px 24px 10px;"><div style="{F}font-size:26px;font-weight:800;color:{TXT};letter-spacing:-0.5px;">{icon} {E(title)}</div><div style="{F}font-size:13px;color:{MUT};padding-top:2px;">{E(sub)}</div></td></tr>'
def row(inner,tint):
    return f'<tr><td style="padding:6px 24px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD};background-image:linear-gradient(180deg,{tint},{CARD} 60%);border:1px solid {LINE};border-radius:14px;"><tr><td style="padding:14px 16px;">{inner}</td></tr></table></td></tr>'
def fin(p,i):
    tint='#0f2a22' if p['action']=='BUY' else '#2d1218'
    inner=(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td valign="top">'
      f'<div style="{F}font-size:11px;font-weight:700;color:{MUT};letter-spacing:1px;text-transform:uppercase;padding-bottom:6px;">#{i} · {E(p["horizon"])}</div>'
      f'{act(p["action"])} <span style="{M}font-size:22px;font-weight:700;color:{TXT};vertical-align:middle;">&nbsp;{E(p["label"])}</span>'
      f'<span style="{M}font-size:14px;color:{MUT};vertical-align:middle;">&nbsp;@ ${p["entry"]:,.2f}</span>'
      +(f'<div style="{F}font-size:13px;font-weight:800;color:#ffb020;padding-top:8px;">Buy and hold 3 months · entry ${p["entry"]:,.2f} · target ${p["target_price"]:,.2f}</div>' if p.get("target_price") else '')+
      f'<div style="{F}font-size:14px;line-height:20px;color:#e6e9f3;padding-top:8px;">{E(p["why"])}</div>'
      f'<div style="{F}font-size:12px;padding-top:6px;"><a href="{E(p["source"]["url"])}" style="color:#a5b4fc;text-decoration:none;font-weight:700;">{E(src(p["source"]["name"]))} →</a></div>'
      f'</td>{score(p)}</tr></table>')
    return row(inner,tint)
def sp(p,i):
    inner=(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td valign="top">'
      f'<div style="{F}font-size:11px;font-weight:700;color:{MUT};letter-spacing:1px;text-transform:uppercase;padding-bottom:6px;">#{i} · {E(p["market"])}</div>'
      f'{act(p["action"])} <span style="{M}font-size:18px;font-weight:700;color:{TXT};vertical-align:middle;">&nbsp;{E(p["label"])}</span>'
      f'<span style="{M}font-size:14px;color:{MUT};vertical-align:middle;">&nbsp;@ {p["entry"]*100:.1f}¢</span>'
      f'<div style="{F}font-size:14px;line-height:20px;color:#e6e9f3;padding-top:8px;"><b style="color:{AMB};">Why {E(p["action"])}:</b> {E(p["why"])}</div>'
      f'{value(p)}'
      f'<div style="{F}font-size:12px;padding-top:6px;"><a href="{E(p["source"]["url"])}" style="color:#a5b4fc;text-decoration:none;font-weight:700;">{E(src(p["source"]["name"]))} →</a></div>'
      f'</td>{score(p)}</tr></table>')
    return row(inner,'#2a2110')
def value(p):
    """Plain value verdict vs the no-vig sportsbook line (same 2-pt rule as the site): value / coin flip / pricey."""
    pts=p.get('edge_pts')
    if pts is None: return ''
    if pts>=2: c,fg,lab,t=UP,'#04130c','💰 VALUE',f'Polymarket is {pts:.1f} pts cheaper than the books'
    elif pts<=-2: c,fg,lab,t=DN,'#ffffff','⚠️ PRICEY',f'Polymarket is {-pts:.1f} pts over the books'
    else: c,fg,lab,t='#e9ecf5','#0a0b12','🪙 COIN FLIP',f'fair price, within 2 pts of the books ({pts:+.1f})'
    return (f'<div style="{F}font-size:13px;line-height:18px;color:#dfe3ef;padding-top:8px;">'
            f'<span style="display:inline-block;background:{c};color:{fg};font-weight:900;font-size:11px;letter-spacing:1px;padding:3px 9px;border-radius:999px;">{lab}</span>&nbsp; {E(t)}</div>')
def ai(n,i):
    inner=(f'<div style="{F}font-size:11px;font-weight:800;color:#b9a8ff;letter-spacing:1px;text-transform:uppercase;padding-bottom:4px;">{i} · {E(n.get("category","AI"))}</div>'
      f'<a href="{E(n["source"]["url"])}" style="{F}font-size:17px;line-height:22px;font-weight:800;color:{TXT};text-decoration:none;">{E(n["headline"])}</a>'
      f'<div style="{F}font-size:14px;line-height:20px;color:#c3c8d8;padding-top:6px;">{E(n["why"])}</div>'
      f'<div style="{F}font-size:11px;font-weight:700;color:{MUT};text-transform:uppercase;letter-spacing:1px;padding-top:6px;">Source: {E(src(n["source"]["name"]))}</div>')
    return row(inner,'#1a1533')
def recap(prev):
    # Yesterday's picks with real results (same numbers as the site's recap block)
    if not prev: return ''
    ps=prev['finance']+prev['sports']; rs=[p['ret'] for p in ps if p.get('ret') is not None]
    ln=prev.get('lean') if not prev['sports'] else None
    if ln and ln.get('ret') is None: ln=None
    if not rs and not ln: return ''
    d=datetime.date.fromisoformat(prev['date'])
    summ=f"{sum(r>0 for r in rs)}/{len(rs)} winning · avg {sum(rs)/len(rs)*100:+.2f}%" if rs else "No picks yesterday: nothing cleared our bar"
    fin_=[p['ret'] for p in ps if p.get('final') and p.get('ret') is not None]; op_=len(rs)-len(fin_)
    if fin_ and op_: summ=f"Settled {sum(r>0 for r in fin_)}-{sum(r<=0 for r in fin_)} · avg {sum(fin_)/len(fin_)*100:+.1f}% · {op_} still open"
    def chip(p):
        r=p.get('ret')
        if r is None: return ''
        c=UP if r>0 else (DN if r<0 else MUT)
        return f'<span style="{M}font-size:12px;font-weight:700;color:{c};">{r*100:+.1f}%{" final" if p.get("final") else ""}</span>'
    order=sorted(ps,key=lambda p:(not p.get('final'),-(p.get('ret') or 0)))
    items=' &nbsp;·&nbsp; '.join(f'<span style="{F}font-size:13px;color:#e6e9f3;white-space:nowrap;"><b>{E(p["action"])} {E(p["label"])}</b> {chip(p)}</span>' for p in order if p.get('ret') is not None)
    if ln: items=(items+' &nbsp;·&nbsp; ' if items else '')+f'<span style="{F}font-size:13px;color:#c4b5fd;white-space:nowrap;"><b>🤏 Max\'s lean (not a pick): {E(ln["label"])}</b> {chip(ln)}</span>'
    inner=(f'<div style="{F}font-size:11px;font-weight:800;color:{AMB};letter-spacing:1px;text-transform:uppercase;padding-bottom:4px;">📬 Yesterday\'s results · {E(d.strftime("%a %b ")+str(d.day))}</div>'
      f'<div style="{F}font-size:17px;font-weight:800;color:{TXT};padding-bottom:6px;">{E(summ)}</div>'
      f'<div style="line-height:22px;">{items}</div>'
      f'{bigwin(prev,ps)}'
      f'<div style="{F}font-size:12px;padding-top:8px;"><a href="{SITE}/scoreboard/?utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign={prev["date"]}" style="color:#a5b4fc;text-decoration:none;font-weight:700;">Full Scoreboard →</a></div>')
    return row(inner,'#2a2110')
def topwin(prev):
    # Best settled win yesterday: sports-market picks need +25%, stock calls +5% (1 Day calls settle at the close); ranked by multiple of threshold
    if not prev: return None
    ws=[(p,0.25) for p in prev['sports'] if p.get('final') and (p.get('ret') or 0)>=0.25]+[(p,0.05) for p in prev['finance'] if p.get('final') and (p.get('ret') or 0)>=0.05]
    return max(ws,key=lambda x:x[0]['ret']/x[1])[0] if ws else None
def bigwin(prev,ps):
    # Spotlight yesterday's best settled win (sports +25%, stocks +5%) with a one-tap 'Share the win' X post (utm_source=win_share)
    p=topwin(prev)
    if not p or not p.get('id'): return ''
    sport=p in prev['sports']
    ent=f"{p['entry']*100:.1f}\u00a2" if sport else f"${p['entry']:,.2f}"
    d=datetime.date.fromisoformat(prev['date'])
    txt=f"Called it: {p['action']} {p['label']} at {ent} on {d.strftime('%b ')}{d.day}, settled {p['ret']*100:+.2f}%. Every Daily Five pick is graded in public, wins and losses."
    u=f"{SITE}/picks/{p['id']}/?utm_source=win_share&utm_medium=x&utm_campaign=email_{prev['date']}"
    href='https://x.com/intent/post?'+urllib.parse.urlencode({'text':txt,'url':u})
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;background:#0f2a22;border:1px solid {UP};border-radius:12px;"><tr><td style="padding:12px 14px;">'
      f'<div style="{F}font-size:11px;font-weight:800;color:{UP};letter-spacing:1px;text-transform:uppercase;">🔥 Biggest win</div>'
      f'<div style="{F}font-size:18px;font-weight:900;color:{TXT};padding-top:2px;"><a href="{SITE}/picks/{p["id"]}/?utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign={prev["date"]}" style="color:{TXT};text-decoration:none;">{E(p["action"])} {E(p["label"])} at {E(ent)}</a> <span style="{M}color:{UP};">{p["ret"]*100:+.1f}%</span></div>'
      f'<a href="{E(href)}" style="display:inline-block;margin-top:8px;padding:8px 14px;background:#ffffff;color:#07080d;{F}font-size:13px;font-weight:900;text-decoration:none;border-radius:999px;">\U0001D54F Share the win</a>'
      f'</td></tr></table>')
def record(rec,date):
    # Running track record (all-time + latest week), same numbers as /sports-results/ and /stock-results/
    if not rec: return ''
    nm={'sports':'🏆 Sports','stocks':'💰 Stocks'}
    cells=''
    for k in ('sports','stocks'):
        r=rec.get(k)
        if not r: continue
        c=UP if r['avg']>=0 else DN; wc=UP if r['wavg']>=0 else DN
        cells+=(f'<td valign="top" style="padding:0 8px 0 0;width:50%;"><a href="{SITE}{r["url"]}?utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign={date}#weekly" style="text-decoration:none;">'
          f'<div style="{F}font-size:12px;font-weight:800;color:{MUT};text-transform:uppercase;letter-spacing:1px;">{nm[k]}</div>'
          f'<div style="{F}font-size:24px;font-weight:900;color:{TXT};line-height:30px;">{r["w"]}-{r["l"]} <span style="{M}font-size:14px;color:{c};">{r["avg"]*100:+.1f}% avg</span></div>'
          f'<div style="{F}font-size:13px;color:#c3c8d8;">{E(r["wk"])}: <b>{r["ww"]}-{r["wl"]}</b> <span style="{M}color:{wc};font-weight:700;">{r["wavg"]*100:+.1f}%</span></div></a></td>')
    if not cells: return ''
    inner=(f'<div style="{F}font-size:11px;font-weight:800;color:#86efac;letter-spacing:1px;text-transform:uppercase;padding-bottom:8px;">🏁 Our track record · every settled pick</div>'
      f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'
      f'<div style="{F}font-size:12px;color:{MUT};padding-top:8px;">Avg return per $1 at our published entry price. Wins and losses both count.</div>')
    return row(inner,'#0f2018')
def refer(rec,date):
    # "Forward this to a friend who trades": share links (X / text / email) to the subscribe form, UTM-tagged per channel
    q=urllib.parse.quote
    hook='Max Edge\'s Bold Bet, the sports plays that clear our bar, and 3-month stock calls vs the S&P 500, graded in public'
    r=(rec or {}).get('sports')
    if r: hook+=f" (sports {r['w']}-{r['l']} so far)"
    txt=f'The Daily Five: {hook}. Free 7 AM email:'
    u=lambda m: f'{SITE}/?utm_source=newsletter_fwd&utm_medium={m}&utm_campaign=refer_{date}#subscribe'
    links=[('\U0001D54F Post it',f"https://x.com/intent/tweet?text={q(txt)}&url={q(u('x'))}",UP,'#04130c'),
           ('\u2709\ufe0f Email it',f"mailto:?subject={q('Free daily stock + sports picks, graded in public')}&body={q(txt+' '+u('email'))}",'#ffffff','#07080d')]
    btns=''.join(f'<a href="{E(h)}" style="display:inline-block;margin:6px 6px 0 0;padding:10px 16px;background:{bg};color:{fg};{F}font-size:14px;font-weight:900;text-decoration:none;border-radius:999px;">{E(t)}</a>' for t,h,bg,fg in links)
    inner=(f'<div style="{F}font-size:11px;font-weight:800;color:{AMB};letter-spacing:1px;text-transform:uppercase;padding-bottom:6px;">\U0001F91D Know someone who trades or bets?</div>'
      f'<div style="{F}font-size:20px;line-height:26px;font-weight:900;color:{TXT};">Forward this to a friend who trades.</div>'
      f'<div style="{F}font-size:14px;line-height:21px;color:#cdd2e1;padding:6px 0 4px;">Or send them the free signup in one tap. Every pick is graded in public, wins and losses.</div>'
      f'<div>{btns}</div>')
    return row(inner,'#1a1530')
def preheader(ed,prev,rec):
    # Inbox preview text: lead with yesterday's biggest settled win (+25%+) or the running sports record, then the headline
    bits=[]
    if prev:
        w=topwin(prev)
        if w: bits.append(f"Yesterday: {w['action']} {w['label']} settled {w['ret']*100:+.{0 if w['ret']>=0.25 else 1}f}%")
    r=(rec or {}).get('sports')
    if r and not bits: bits.append(f"Sports picks {r['w']}-{r['l']}, graded in public")
    bits.append(ed['headline'])
    t=' \u00b7 '.join(bits)
    return t+'\u00a0\u200c'*40
def render(ed,prev=None,rec=None,open3=None):
    d=datetime.date.fromisoformat(ed['date']); nice=d.strftime('%A, %B ')+str(d.day)+d.strftime(', %Y')
    order={'3 Month':0,'1 Day':1,'1 Month':2,'1 Year':3}
    finl=sorted([p for p in ed['finance'] if keep(p)],key=lambda p:(order.get(p['horizon'],9),-(p.get('score') or 0)))
    hl=ed.get('top_call') or ed['headline']
    btn=(f'<table role="presentation" cellpadding="0" cellspacing="0" align="center"><tr><td style="border-radius:999px;background:{UP};">'
         f'<a href="{SITE}/?utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign={ed["date"]}" style="display:inline-block;padding:14px 30px;{F}font-size:16px;font-weight:900;color:#04130c;text-decoration:none;border-radius:999px;">See live prices →</a></td></tr></table>')
    rows=[f'<tr><td style="padding:28px 24px 8px;background:{BG};background-image:radial-gradient(120% 100% at 0 0,#2a1f66,{BG} 60%);">'
      f'<div style="{F}font-size:13px;font-weight:600;color:{MUT};">The</div>'
      f'<div style="{F}font-size:38px;font-weight:900;color:{TXT};letter-spacing:-1px;line-height:1;">Daily <span style="color:{UP};">Five</span></div>'
      f'<div style="{F}font-size:12px;font-weight:800;color:{AMB};letter-spacing:2px;text-transform:uppercase;padding-top:12px;">{E(nice)}</div>'
      f'<div style="{F}font-size:22px;line-height:28px;font-weight:800;color:{TXT};padding-top:8px;">{E(hl)}</div>'
      f'<div style="{F}font-size:14px;line-height:21px;color:#cdd2e1;padding:12px 0 6px;">{E(ed["backdrop"])}</div>'
      f'<div style="padding:14px 0 10px;">{btn}</div></td></tr>',
      ]
    rc=recap(prev)
    if rc: rows.append('<tr><td style="padding:14px 0 0;"></td></tr>'); rows.append(rc)
    tr_=record(rec,ed['date'])
    if tr_: rows.append('<tr><td style="padding:10px 0 0;"></td></tr>'); rows.append(tr_)
    rows.append(sec('💰','Money','Buy-and-hold 3-month calls · graded vs the S&P 500'))
    last=None
    for i,p in enumerate(finl,1):
        if p['horizon']!=last:
            rows.append(f'<tr><td style="padding:12px 24px 2px;{F}font-size:12px;font-weight:800;color:{AMB};letter-spacing:2px;text-transform:uppercase;">{E(p["horizon"])}</td></tr>'); last=p['horizon']
        rows.append(fin(p,i))
    newids={id(p) for p in finl}; oc=[p for p in (open3 or []) if id(p) not in newids]
    if oc or not finl:
        li=''.join(f'<div style="padding:3px 0;">{E(p["action"])} <b>{E(p["label"])}</b> · entry ${p["entry"]:,.2f}'+(f' · target ${p["target_price"]:,.2f}' if p.get("target_price") else '')+(f' · {p["ret"]*100:+.1f}% vs S&amp;P' if p.get("ret") is not None else '')+'</div>' for p in oc)
        rows.append(f'<tr><td style="padding:8px 24px;{F}font-size:14px;line-height:20px;color:{TXT};">'+('<b>Open 3-month calls</b>'+li if oc else 'No new stock call today. We make 1–2 buy-and-hold 3-month calls a week.')+'</td></tr>')
    rows.append(sec('🤖','AI','The 5 stories that matter today'))
    rows+= [ai(n,i) for i,n in enumerate(ed['ai'][:5],1)]
    rows.append(sec('🏆','Sports','Prediction markets · Polymarket & Kalshi'))
    rows+= [sp(p,i) for i,p in enumerate(sorted([p for p in ed['sports'] if keep(p)],key=lambda p:-(p.get('score') or 0))[:5],1)]
    if not ed['sports']: rows.append(f'<tr><td style="padding:8px 24px;{F}font-size:14px;line-height:20px;color:{TXT};"><b>🚫 No bets today: nothing cleared our bar.</b> A pick needs a real sportsbook line, a 40¢–70¢ price and +2.5 points of edge. No Bold Bet of the Day. '+E(ed.get('no_bets_note') or '')+'</td></tr>')
    ln=ed.get('lean') if not ed['sports'] else None
    if ln:
        _b=sys.modules['__main__'] if hasattr(sys.modules.get('__main__'),'lean_rec_txt') else __import__('build')
        rows.append(f'<tr><td style="padding:6px 24px;"><div style="border:1px dashed {VIO};border-radius:14px;padding:14px 16px;background:#151233;{F}color:{TXT};">'
          f'<div style="font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#c4b5fd;">🤏 Max\'s lean · not a Bold Bet · not a pick</div>'
          f'<div style="font-size:20px;font-weight:800;padding-top:6px;">{E(ln["label"])} <span style="{M}font-size:14px;color:{MUT};font-weight:500;">at {ln["entry"]*100:.1f}¢'+(f' · {ln["edge"]:+.1f} pts vs the books' if ln.get('edge') is not None else '')+'</span></div>'
          f'<div style="font-size:13px;color:{MUT};padding-top:2px;">{E(ln["market"])}</div>'
          f'<div style="font-size:14px;line-height:20px;padding-top:8px;">🤖 <b>Max Edge (AI host):</b> {E(ln["why"])}</div>'
          f'<div style="font-size:12px;line-height:18px;color:{MUT};padding-top:8px;">Graded on a separate Leans record, never mixed into the sports or Bold Bet record. {E(_b.lean_rec_txt())} <a href="{SITE}/scoreboard/#leans" style="color:#a5b4fc;text-decoration:none;font-weight:700;">Leans record →</a></div></div></td></tr>')
    rows.append(f'<tr><td style="padding:30px 24px;" align="center"><div style="{F}font-size:15px;color:{MUT};padding-bottom:14px;">Prices move all day. Track every pick live and on the Scoreboard.</div>{btn}</td></tr>')
    rows.append('<tr><td style="padding:4px 0 0;"></td></tr>'); rows.append(refer(rec,ed['date'])); rows.append('<tr><td style="padding:14px 0 0;"></td></tr>')
    rows.append(f'<tr><td style="padding:22px 24px 30px;border-top:1px solid {LINE};{F}font-size:12px;line-height:18px;color:{MUT};">'
      f'<b style="color:{TXT};font-size:14px;">The Daily Five</b> · <a href="{SITE}/?utm_source=email&utm_medium=footer&utm_campaign=forward#subscribe" style="color:#a5b4fc;text-decoration:none;font-weight:700;">Got this forwarded? Get your own (free)</a> · <a href="{SITE}/scoreboard/" style="color:#a5b4fc;text-decoration:none;">Scoreboard</a><br><br>'
      f'<b>Not financial advice.</b> Not financial, investment, or betting advice. The Daily Five aggregates public ideas and market prices for information and entertainment only. Past results don\'t guarantee future returns. You can lose money. D5 Score = 0–100 from source credibility, consensus, edge and risk/reward.</td></tr>')
    pre=E(preheader(ed,prev,rec))
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<meta name="color-scheme" content="dark light"><meta name="supported-color-schemes" content="dark light">'
      f'<title>The Daily Five · {E(nice)}</title><style>:root{{color-scheme:dark light;}}body{{margin:0;padding:0;}}@media (max-width:620px){{.wrap{{width:100%!important;}}}}</style></head>'
      f'<body style="margin:0;padding:0;background:{BG};" bgcolor="{BG}"><div style="display:none;max-height:0;overflow:hidden;">{pre}</div>'
      f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{BG}" style="background:{BG};"><tr><td align="center" style="padding:16px 0;">'
      f'<table role="presentation" class="wrap" width="600" cellpadding="0" cellspacing="0" bgcolor="{BG}" style="width:600px;max-width:600px;background:{BG};border:1px solid {LINE};border-radius:18px;overflow:hidden;">'
      + ''.join(rows) + '</table></td></tr></table></body></html>')
def write(ed,prev=None,rec=None,open3=None):
    os.makedirs(os.path.join(ROOT,'email'),exist_ok=True); path=os.path.join(ROOT,'email',ed['date']+'.html')
    open(path,'w').write(render(ed,prev,rec,open3)); return path
if __name__=='__main__':
    sys.path.insert(0,ROOT); import build
    f=os.path.join(ROOT,'editions',(sys.argv[1] if len(sys.argv)>1 else sorted(os.listdir(os.path.join(ROOT,'editions')))[-1].replace('.json',''))+'.json')
    ed=json.load(open(f)); build.enrich(ed)
    eds=[json.load(open(x)) for x in sorted(glob.glob(os.path.join(ROOT,'editions','*.json')),reverse=True)]
    prev=next((e for e in eds if e['date']<ed['date'] and e['date']>=build.LAUNCH),None)
    if prev: build.enrich(prev)
    hits=build.source_hits([e for e in [ed,prev] if e])
    for p in ed['finance']+ed['sports']: build.score_pick(p,hits)
    print(write(ed,prev))
