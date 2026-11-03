"""AI earnings explainer pages: /earnings/<ticker>-<quarter>/ from data/earnings/*.json.
Every number lives in the JSON with its sources; this file only renders. See prototypes/earnings-explainer-runbook.md."""
import json, glob, os, datetime, time, urllib.request

def load(root):
    out=[json.load(open(f)) for f in sorted(glob.glob(os.path.join(root,'data','earnings','*.json')))]
    return sorted(out,key=lambda r:(r['date'],r['ticker']),reverse=True)

def live_reaction(r):
    """Latest price incl. pre/post-market from Yahoo vs the stored pre-report close. Falls back to the stored snapshot."""
    try:
        u=f"https://query1.finance.yahoo.com/v8/finance/chart/{r['ticker']}?range=5d&interval=5m&includePrePost=true"
        j=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=8))['chart']['result'][0]
        pts=[(t,c) for t,c in zip(j['timestamp'],j['indicators']['quote'][0]['close']) if c]
        rep=datetime.date.fromisoformat(r['date'])
        if pts and datetime.date.fromtimestamp(pts[-1][0])>=rep:
            t,c=pts[-1]; lt=time.localtime(t); hm=lt.tm_hour*60+lt.tm_min
            kind='premarket' if hm<570 else 'after hours' if hm>=960 else 'intraday'
            if kind=='after hours' and r.get('when','').startswith('before'): kind='close+after hours'
            return {'kind':kind,'price':round(c,2),'asof':time.strftime('%Y-%m-%d %-I:%M %p ET',lt)}
    except Exception: pass
    return r.get('reaction') or {}

def render(B, reports):
    """B: dict of build.py helpers (shell,w,sform,crumbs,E,BASE,SITE,BRAND,TODAY). Returns sitemap (url,lastmod) pairs."""
    E=B['E']; BASE=B['BASE']; SITE=B['SITE']; BRAND=B['BRAND']; urls=[]
    for r in reports:
        P=f"/earnings/{r['slug']}/"; nm=r['company']; tk=r['ticker']; q=r['quarter']
        rx=live_reaction(r) if B.get('live',True) else (r.get('reaction') or {})
        pc=r.get('prev_close'); move=None
        if rx.get('price') and pc: move=(rx['price']/pc-1)*100
        d=datetime.date.fromisoformat(r['date']).strftime('%B %-d, %Y')
        def cls(x): return 'up' if x.startswith(('Beat','Raised','Above')) else 'dn' if x.startswith('Miss') else ''
        rows=''.join('<tr><td>%s</td><td><b>%s</b></td><td>%s</td><td>%s</td></tr>'%(E(h['metric']),E(h['actual']),E(h['consensus']),('<span class="%s">%s</span>'%(cls(h['result']),E(h['result'])) if h['result'] else '')) for h in r['headline'])
        tks=''.join(f'<li>{E(t)}</li>' for t in r['takeaways'])
        rxh=(f"<p class=\"sub\"><b class=\"{'up' if move>=0 else 'dn'}\">{tk} {move:+.1f}%</b> {E(rx['kind'])} at ${rx['price']:,.2f} vs the ${pc:,.2f} close before the report (as of {E(rx['asof'])}). Live moves change fast; this updates every time the site rebuilds.</p>" if move is not None else '<p class="sub">Reaction pending: the first trade after the report will show here.</p>')
        srcs=''.join(f'<li><a href="{E(s["url"])}" rel="nofollow noopener" target="_blank">{E(s["title"])}</a></li>' for s in r['sources'])
        bw=[h for h in r['headline'] if h['result']]
        ans_beat=f"{nm} reported {q} results on {d} ({r['when']}). "+'; '.join(f"{h['metric']}: {h['actual']} vs {h['consensus']} expected ({h['result'].lower()})" for h in bw if h['consensus']!='n/a')+'.'
        gd=[h for h in r['headline'] if 'guid' in h['metric'].lower()]
        faqs=[(f"Did {nm} beat earnings in {q}?",ans_beat)]
        if gd: faqs.append((f"What is {nm}'s guidance after {q}?",' '.join(f"{h['metric']}: {h['actual']} (consensus {h['consensus']})." for h in gd)))
        if move is not None: faqs.append((f"How did {tk} stock react to earnings?",f"{tk} was {move:+.1f}% {rx['kind']} at ${rx['price']:,.2f} versus the ${pc:,.2f} close before the report, as of {rx['asof']}."))
        faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(a)}</summary><p>{E(b)}</p></details>' for a,b in faqs)+'</div>'
        cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),(f'{tk} {q}',P)])
        h1=f"{nm} ({tk}) {q} Earnings Explained"
        body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">🧾 Earnings explained · {E(d)} · {E(r["when"])}</span><h1 class="pt">{E(h1)}</h1>'
              f'<p class="sub wksum"><b>Bottom line: {E(r["verdict_word"])}.</b> The numbers vs Wall Street, what actually mattered, and how the stock took it, in plain English.</p></section>'
              f'<section class="card"><h2 class="h2s">The headline numbers</h2><div class="tbl"><table><thead><tr><th>Metric</th><th>Reported</th><th>Consensus</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
              f'<section class="card"><h2 class="h2s">📈 Stock reaction</h2>{rxh}</section>'
              f'<section class="card"><h2 class="h2s">What actually mattered</h2><ol class="why">{tks}</ol></section>'
              f'<section class="card"><h2 class="h2s">🤖 Max\'s verdict</h2><p class="why">{E(r["verdict"])}</p><p class="disc">Max Edge is an AI host. This is commentary, not financial advice.</p></section>'
              f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get every big earnings report explained in your inbox, free.</h2><p>Beat or miss, guidance, the stock reaction and what it means, in plain English. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
              f'<section class="card"><h2 class="h2s">Sources</h2><ul class="why">{srcs}</ul><p class="disc">Numbers come from the company\'s release and the coverage above. Where no consensus was published we leave it out rather than guess.</p></section>'
              f'{faqh}<p class="sub"><a href="{BASE}/earnings/">All earnings explained →</a></p><p class="disc-bar">⚠️ <b>Not financial advice.</b> AI-written summary of public filings and news. Check the sources before you trade.</p>')
        title=f"{nm} {q} earnings explained: beat or miss, guidance, stock reaction"
        desc=f"{nm} ({tk}) {q} earnings: {r['verdict_word']}. "+'; '.join(f"{h['metric']} {h['actual']}" for h in r['headline'][:2])+'. Guidance, key takeaways and stock reaction.'
        sch={"@context":"https://schema.org","@graph":[{"@type":"Article","headline":h1,"description":desc[:300],"datePublished":r['date'],"dateModified":B['TODAY'].isoformat(),"author":{"@type":"Organization","name":BRAND},"publisher":{"@type":"Organization","name":BRAND},"mainEntityOfPage":SITE+P,"about":{"@type":"Corporation","name":nm,"tickerSymbol":tk},"citation":[s['url'] for s in r['sources']]},csch,
             {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
        B['w'](f"earnings/{r['slug']}/index.html",B['shell'](title,desc[:155],P,body,sch))
        r['_move']=move; urls.append((P,B['TODAY'].isoformat()))
    return urls

def index_section(B, reports):
    E=B['E']; BASE=B['BASE']
    if not reports: return ''
    li=''.join(f'<li><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(r["company"])} ({r["ticker"]}) {E(r["quarter"])}</b></a>: {E(r["verdict_word"])}'+(f' · stock {r["_move"]:+.1f}%' if r.get('_move') is not None else '')+f' · {datetime.date.fromisoformat(r["date"]).strftime("%b %-d")}</li>' for r in reports)
    return f'<section class="card"><h2 class="h2s">🧾 Earnings explained: beat or miss, in plain English</h2><ul class="why">{li}</ul></section>'

def home_strip(B, reports, days=3):
    """Home-page box: the newest earnings explainers (reports from the last `days` days), so the front page
    links straight into the explainer pages. No prices here: the home renders before the live reaction fetch, so the move lives on each explainer page."""
    E=B['E']; BASE=B['BASE']; today=B['TODAY']
    rec=[r for r in reports if 0<=(today-datetime.date.fromisoformat(r['date'])).days<=days]
    if not rec: return ''
    def mv(r):
        rx=r.get('_move')
        if rx is None and (r.get('reaction') or {}).get('price') and r.get('prev_close'): rx=(r['reaction']['price']/r['prev_close']-1)*100
        return f' <span class="{"up" if rx>=0 else "dn"}">{r["ticker"]} {rx:+.1f}%</span>' if rx is not None else ''
    li=''.join(f'<li><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(r["company"])} ({r["ticker"]})</b></a>: {E(r["verdict_word"])}</li>' for r in rec[:8])
    return (f'<section class="card ernhome"><h2 class="h2s">🧾 Earnings explained: who beat, who missed</h2>'
            f'<p class="sub">This week\'s big reports in plain English: the numbers vs Wall Street, guidance, and how the stock took it.</p>'
            f'<ul class="why">{li}</ul><p class="sub"><a href="{BASE}/earnings/">All earnings explained →</a></p></section>')
