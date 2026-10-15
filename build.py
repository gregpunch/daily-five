#!/usr/bin/env python3
"""Regenerate the static site from editions/*.md and scoreboard.csv.
Daily: drop editions/YYYY-MM-DD.md, append rows to scoreboard.csv, run `python3 build.py`.
Set SITE_URL env for absolute links (sitemap/RSS/canonical)."""
import csv, html, json, os, re, shutil, glob, datetime
import markdown
ROOT=os.path.dirname(os.path.abspath(__file__)); OUT=os.path.join(ROOT,'site')
BRAND="The Daily Five"; TAG="Five ideas a day, ranked by agents: markets, AI, and sports odds."
SITE=os.environ.get('SITE_URL','https://example.com').rstrip('/')
from urllib.parse import urlparse
BASE=urlparse(SITE).path.rstrip('/')
DISC="Not financial, investment, or betting advice. The Daily Five summarizes public sources and market prices for information only. Do your own research; you can lose money."
CSS="""*{box-sizing:border-box}body{margin:0;font:17px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0b0d12;color:#e6e8ee}
a{color:#7cc4ff}header,main,footer{max-width:820px;margin:auto;padding:0 20px}header{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;flex-wrap:wrap;gap:8px}
.logo{font-weight:800;font-size:22px;color:#fff;text-decoration:none}.logo span{color:#ffcc33}nav a{margin-left:16px;color:#c9cfdb;text-decoration:none}
.disc{background:#2a1f05;border:1px solid #ffcc33;color:#ffe08a;padding:10px 14px;border-radius:8px;font-size:14px;margin:12px 0}
h1{font-size:30px;line-height:1.2}h2{border-top:1px solid #222836;padding-top:18px;color:#ffcc33}h3{color:#9fb3d1}
table{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow-x:auto}td,th{border:1px solid #222836;padding:6px;text-align:left;vertical-align:top}th{background:#151a24}
.signup{background:#121826;border:1px solid #2b3550;padding:16px;border-radius:10px;margin:24px 0}.signup input{padding:10px;width:60%;border-radius:6px;border:1px solid #39435c;background:#0b0d12;color:#fff}.signup button{padding:10px 14px;border:0;border-radius:6px;background:#ffcc33;font-weight:700}
footer{color:#8a93a6;font-size:13px;padding:30px 20px}ul.arch li{margin:6px 0}"""
def page(title,desc,path,body,schema=None):
    url=SITE+path; s=f'<script type="application/ld+json">{json.dumps(schema)}</script>' if schema else ''
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><meta name="description" content="{html.escape(desc)}"><link rel="canonical" href="{url}">
<meta property="og:title" content="{html.escape(title)}"><meta property="og:description" content="{html.escape(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website">
<meta name="twitter:card" content="summary"><link rel="alternate" type="application/rss+xml" title="{BRAND}" href="{BASE}/feed.xml"><link rel="stylesheet" href="{BASE}/style.css">{s}</head><body>
<header><a class="logo" href="{BASE}/">The Daily <span>Five</span></a><nav><a href="{BASE}/">Today</a><a href="{BASE}/archive/">Archive</a><a href="{BASE}/scoreboard/">Scoreboard</a><a href="{BASE}/feed.xml">RSS</a></nav></header>
<main><div class="disc"><strong>Disclaimer:</strong> {DISC}</div>{body}
<form class="signup" onsubmit="event.preventDefault();this.innerHTML='<p>Thanks! Email delivery is launching soon.</p>'"><strong>Get the Daily Five in your inbox</strong> (coming soon)<br><br>
<input type="email" required placeholder="you@example.com" aria-label="Email"> <button>Notify me</button></form></main>
<footer>© {datetime.date.today().year} {BRAND}. {DISC}</footer></body></html>"""
def w(rel,txt):
    p=os.path.join(OUT,rel.lstrip('/')); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'w').write(txt)
def main():
    shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT); w('style.css',CSS)
    eds=sorted(glob.glob(os.path.join(ROOT,'editions','*.md')),reverse=True); items=[]
    for f in eds:
        d=os.path.basename(f)[:-3]; md=open(f).read()
        md=re.sub(r'^# .*\n','',md,count=1); md=re.sub(r'^\*Not financial.*\*\n','',md,flags=re.M)
        body=markdown.markdown(md,extensions=['tables'])
        nice=datetime.date.fromisoformat(d).strftime('%A, %B %-d, %Y')
        heads=[h for h in (re.sub('<[^>]+>','',x) for x in re.findall(r'<strong>(.*?)</strong>',body)) if len(h)>20 and 'backdrop' not in h.lower()][:3]
        title=f"Daily Five for {nice}: Top Trading Ideas, AI News & Sports Odds"
        desc=f"{nice}: "
        for h in heads:
            h=h.rstrip(':.')
            if len(desc)+len(h)+2>155: break
            desc+=("" if desc.endswith(": ") else "; ")+h
        desc=desc.rstrip(": ")+"."
        sch={"@context":"https://schema.org","@type":"NewsArticle","headline":title,"datePublished":d,"dateModified":d,"description":desc,"publisher":{"@type":"Organization","name":BRAND},"author":{"@type":"Organization","name":BRAND},"mainEntityOfPage":f"{SITE}/{d}/"}
        content=f"<h1>{BRAND}: {nice}</h1>{body}"
        w(f'{d}/index.html',page(title,desc,f'/{d}/',content,sch)); items.append((d,nice,title,desc))
    if items:
        d,nice,title,desc=items[0]; c=open(os.path.join(OUT,d,'index.html')).read()
        hs={"@context":"https://schema.org","@type":"WebSite","name":BRAND,"url":SITE+"/","description":TAG}
        body=re.search(r'<main>(.*)</main>',c,re.S).group(1); body=re.sub(r'^<div class="disc">.*?</div>','',body,flags=re.S); body=re.sub(r'<form class="signup".*</form>','',body,flags=re.S)
        w('index.html',page(f"{BRAND}: Daily Top Trading Ideas, AI News & Sports Prediction Markets",TAG+" Today: "+desc,'/',f'<p><em>{TAG}</em> <a href="{BASE}/{d}/">Permalink</a></p>'+body,hs))
    w('archive/index.html',page(f"Archive | {BRAND}","Every past edition of The Daily Five.",'/archive/',"<h1>Archive</h1><ul class='arch'>"+"".join(f'<li><a href="{BASE}/{d}/">{n}</a></li>' for d,n,_,_ in items)+"</ul>"))
    rows=list(csv.DictReader(open(os.path.join(ROOT,'scoreboard.csv'))))
    def cell(k,v):
        v=v or '—'; return f'<a href="{html.escape(v)}" rel="nofollow">source</a>' if k=='source' and v.startswith('http') else html.escape(v)
    cols=['date','section','idea','ticker_or_market','horizon','entry_price','thesis','source']
    tbl="<table><tr>"+"".join(f"<th>{c.replace('_',' ')}</th>" for c in cols)+"<th>result</th></tr>"+"".join("<tr>"+"".join(f"<td>{cell(c,r.get(c,''))}</td>" for c in cols)+f"<td>{html.escape(r.get('result','') or 'pending')}</td></tr>" for r in rows)+"</table>"
    w('scoreboard/index.html',page(f"Scoreboard: How Our Picks Performed | {BRAND}","A public track record of every idea The Daily Five has featured, with entry prices and results.",'/scoreboard/',f"<h1>Scoreboard</h1><p>We log every pick we feature, along with its entry price and odds from a real source, so you can see which ideas and sources hold up over time. Results update as the picks play out.</p>{tbl}",{"@context":"https://schema.org","@type":"Dataset","name":f"{BRAND} Scoreboard","description":"Track record of featured ideas"}))
    urls=['/','/archive/','/scoreboard/']+[f'/{d}/' for d,*_ in items]
    w('sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+"".join(f"<url><loc>{SITE}{u}</loc></url>" for u in urls)+'</urlset>')
    w('robots.txt',f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    def rfc(d): return datetime.datetime.fromisoformat(d+'T10:00:00-04:00').strftime('%a, %d %b %Y %H:%M:%S %z')
    w('feed.xml','<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'+f"<title>{BRAND}</title><link>{SITE}/</link><description>{html.escape(TAG)}</description>"+"".join(f"<item><title>{html.escape(t)}</title><link>{SITE}/{d}/</link><guid>{SITE}/{d}/</guid><pubDate>{rfc(d)}</pubDate><description>{html.escape(ds)}</description></item>" for d,_,t,ds in items)+"</channel></rss>")
    w('404.html',page(f"Not found | {BRAND}","Page not found",'/404.html','<h1>Not found</h1><p><a href="{BASE}/">Go to today\'s edition</a></p>'))
    print(f"built {len(items)} editions -> {OUT}")
if __name__=='__main__': main()
