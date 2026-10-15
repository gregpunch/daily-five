#!/usr/bin/env python3
"""Newsletter HTML for an edition -> email/<date>.html (email-safe: tables + inline CSS, 600px).
Run: python3 email_build.py [YYYY-MM-DD]   (also called from build.py for the latest edition).
Named email_build.py (not email.py) so it doesn't shadow Python's stdlib `email` module."""
import sys, os, json, glob, html, datetime
ROOT=os.path.dirname(os.path.abspath(__file__)); E=lambda s: html.escape(str(s))
BG,CARD,LINE,TXT,MUT,UP,DN,VIO,AMB='#07080d','#11131e','#22263a','#f2f4fa','#9ba3ba','#16c784','#ff4d5e','#7c5cff','#ffb020'
F="font-family:Inter,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
M="font-family:'JetBrains Mono',SFMono-Regular,Menlo,Consolas,monospace;"
SITE='https://readdailyfive.com'
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
      f'<div style="{F}font-size:14px;line-height:20px;color:#e6e9f3;padding-top:8px;">{E(p["why"])}</div>'
      f'<div style="{F}font-size:12px;padding-top:6px;"><a href="{E(p["source"]["url"])}" style="color:#a5b4fc;text-decoration:none;font-weight:700;">{E(p["source"]["name"])} →</a></div>'
      f'</td>{score(p)}</tr></table>')
    return row(inner,tint)
def sp(p,i):
    inner=(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td valign="top">'
      f'<div style="{F}font-size:11px;font-weight:700;color:{MUT};letter-spacing:1px;text-transform:uppercase;padding-bottom:6px;">#{i} · {E(p["market"])}</div>'
      f'{act(p["action"])} <span style="{M}font-size:18px;font-weight:700;color:{TXT};vertical-align:middle;">&nbsp;{E(p["label"])}</span>'
      f'<span style="{M}font-size:14px;color:{MUT};vertical-align:middle;">&nbsp;@ {p["entry"]*100:.1f}¢</span>'
      f'<div style="{F}font-size:14px;line-height:20px;color:#e6e9f3;padding-top:8px;"><b style="color:{AMB};">Why {E(p["action"])}:</b> {E(p["why"])}</div>'
      f'<div style="{F}font-size:12px;padding-top:6px;"><a href="{E(p["source"]["url"])}" style="color:#a5b4fc;text-decoration:none;font-weight:700;">{E(p["source"]["name"])} →</a></div>'
      f'</td>{score(p)}</tr></table>')
    return row(inner,'#2a2110')
def ai(n,i):
    inner=(f'<div style="{F}font-size:11px;font-weight:800;color:#b9a8ff;letter-spacing:1px;text-transform:uppercase;padding-bottom:4px;">{i} · {E(n.get("category","AI"))}</div>'
      f'<a href="{E(n["source"]["url"])}" style="{F}font-size:17px;line-height:22px;font-weight:800;color:{TXT};text-decoration:none;">{E(n["headline"])}</a>'
      f'<div style="{F}font-size:14px;line-height:20px;color:#c3c8d8;padding-top:6px;">{E(n["why"])}</div>'
      f'<div style="{F}font-size:11px;font-weight:700;color:{MUT};text-transform:uppercase;letter-spacing:1px;padding-top:6px;">via {E(n["source"]["name"])}</div>')
    return row(inner,'#1a1533')
def render(ed):
    d=datetime.date.fromisoformat(ed['date']); nice=d.strftime('%A, %B ')+str(d.day)+d.strftime(', %Y')
    order={'1 Day':0,'1 Month':1,'1 Year':2}
    finl=sorted(ed['finance'],key=lambda p:(order.get(p['horizon'],9),-(p.get('score') or 0)))
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
      sec('💰','Money','Top ideas by horizon · BUY/SELL at publish price')]
    last=None
    for i,p in enumerate(finl,1):
        if p['horizon']!=last:
            rows.append(f'<tr><td style="padding:12px 24px 2px;{F}font-size:12px;font-weight:800;color:{AMB};letter-spacing:2px;text-transform:uppercase;">{E(p["horizon"])}</td></tr>'); last=p['horizon']
        rows.append(fin(p,i))
    rows.append(sec('🤖','AI','The 5 stories that matter today'))
    rows+= [ai(n,i) for i,n in enumerate(ed['ai'][:5],1)]
    rows.append(sec('🏆','Sports','Prediction markets · Polymarket & Kalshi'))
    rows+= [sp(p,i) for i,p in enumerate(sorted(ed['sports'],key=lambda p:-(p.get('score') or 0))[:5],1)]
    rows.append(f'<tr><td style="padding:30px 24px;" align="center"><div style="{F}font-size:15px;color:{MUT};padding-bottom:14px;">Prices move all day. Track every pick live and on the Scoreboard.</div>{btn}</td></tr>')
    rows.append(f'<tr><td style="padding:22px 24px 30px;border-top:1px solid {LINE};{F}font-size:12px;line-height:18px;color:{MUT};">'
      f'<b style="color:{TXT};font-size:14px;">The Daily Five</b> · <a href="https://x.com/ReadDailyFive" style="color:#a5b4fc;text-decoration:none;font-weight:700;">Follow @ReadDailyFive on X</a> · <a href="{SITE}/scoreboard/" style="color:#a5b4fc;text-decoration:none;">Scoreboard</a><br><br>'
      f'<b>Not financial advice.</b> Not financial, investment, or betting advice. The Daily Five aggregates public ideas and market prices for information and entertainment only. Past results don\'t guarantee future returns. You can lose money. D5 Score = 0–100 from source credibility, consensus, edge and risk/reward.</td></tr>')
    pre=E(ed['headline'])
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<meta name="color-scheme" content="dark light"><meta name="supported-color-schemes" content="dark light">'
      f'<title>The Daily Five · {E(nice)}</title><style>:root{{color-scheme:dark light;}}body{{margin:0;padding:0;}}@media (max-width:620px){{.wrap{{width:100%!important;}}}}</style></head>'
      f'<body style="margin:0;padding:0;background:{BG};" bgcolor="{BG}"><div style="display:none;max-height:0;overflow:hidden;">{pre}</div>'
      f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{BG}" style="background:{BG};"><tr><td align="center" style="padding:16px 0;">'
      f'<table role="presentation" class="wrap" width="600" cellpadding="0" cellspacing="0" bgcolor="{BG}" style="width:600px;max-width:600px;background:{BG};border:1px solid {LINE};border-radius:18px;overflow:hidden;">'
      + ''.join(rows) + '</table></td></tr></table></body></html>')
def write(ed):
    os.makedirs(os.path.join(ROOT,'email'),exist_ok=True); path=os.path.join(ROOT,'email',ed['date']+'.html')
    open(path,'w').write(render(ed)); return path
if __name__=='__main__':
    sys.path.insert(0,ROOT); import build
    f=os.path.join(ROOT,'editions',(sys.argv[1] if len(sys.argv)>1 else sorted(os.listdir(os.path.join(ROOT,'editions')))[-1].replace('.json',''))+'.json')
    ed=json.load(open(f)); build.enrich(ed); hits=build.source_hits([ed])
    for p in ed['finance']+ed['sports']: build.score_pick(p,hits)
    print(write(ed))
