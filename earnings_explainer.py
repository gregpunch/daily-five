"""AI earnings explainer pages: /earnings/<ticker>-<quarter>/ from data/earnings/*.json.
Every number lives in the JSON with its sources; this file only renders. See prototypes/earnings-explainer-runbook.md."""
import json, glob, os, datetime, time, urllib.request

# Rough market cap in $B, used only to order explainers "biggest names first". A report JSON may override with "mcap_b".
MCAP={'NVDA':4500,'AAPL':3800,'MSFT':3700,'GOOGL':3000,'AMZN':2400,'META':1800,'AVGO':1600,'TSLA':1400,'BRK.B':1000,'LLY':800,'AMD':800,'JPM':800,
 'WMT':800,'V':650,'ORCL':600,'MA':500,'NFLX':500,'XOM':480,'COST':400,'PLTR':400,'JNJ':400,'HD':380,'ABBV':380,'PG':360,'BAC':340,'KO':300,
 'NVO':250,'CVX':250,'CSCO':250,'CRM':240,'MCD':220,'PEP':200,'SHOP':200,'IBM':200,'DIS':200,'UBER':190,'ANET':180,'AMGN':170,'BKNG':170,
 'QCOM':170,'PFE':145,'ETN':140,'CVS':90,'APO':80,'RACE':80,'MPC':50}
def size(r): return r.get('mcap_b') or MCAP.get(r['ticker'],0)
def lead(reports,today,days=2,n=8):
    """Latest explainers for the home lead / email: reports from the last `days` days, biggest names first.
    Falls back to the newest `n` reports if nothing is that recent."""
    rec=[r for r in reports if 0<=(today-datetime.date.fromisoformat(r['date'])).days<=days] or reports[:n]
    return sorted(rec,key=lambda r:(-size(r),r['ticker']))[:n]

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

def related(B, r, reports, n=6):
    """'More earnings this week' cross-links on each explainer: the other reports within 7 days, nearest first.
    Internal links between explainers help Google crawl new pages and give readers a next click."""
    E=B['E']; BASE=B['BASE']; d0=datetime.date.fromisoformat(r['date'])
    rel=[x for x in reports if x['slug']!=r['slug'] and abs((datetime.date.fromisoformat(x['date'])-d0).days)<=7]
    rel=sorted(rel,key=lambda x:(abs((datetime.date.fromisoformat(x['date'])-d0).days),x['ticker']))[:n]
    if not rel: return ''
    li=''.join(f'<li><a href="{BASE}/earnings/{x["slug"]}/"><b>{E(x["company"])} ({x["ticker"]}) {E(x["quarter"])}</b></a>: {E(x["verdict_word"])} · {datetime.date.fromisoformat(x["date"]).strftime("%b %-d")}</li>' for x in rel)
    return f'<section class="card"><h2 class="h2s">More earnings explained this week</h2><ul class="why">{li}</ul></section>'

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
        cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),(f'{tk} earnings',f'/earnings/{tk.lower()}/'),(f'{tk} {q}',P)])
        h1=f"{nm} ({tk}) {q} Earnings Explained"
        body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">🧾 Earnings explained · {E(d)} · {E(r["when"])}</span><h1 class="pt">{E(h1)}</h1>'
              f'<p class="sub wksum"><b>Bottom line: {E(r["verdict_word"])}.</b> The numbers vs Wall Street, what actually mattered, and how the stock took it, in plain English.</p></section>'
              f'<section class="card"><h2 class="h2s">The headline numbers</h2><div class="tbl"><table><thead><tr><th>Metric</th><th>Reported</th><th>Consensus</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
              f'<section class="card"><h2 class="h2s">📈 Stock reaction</h2>{rxh}</section>'
              f'<section class="card"><h2 class="h2s">What actually mattered</h2><ol class="why">{tks}</ol></section>'
              f'<section class="card"><h2 class="h2s">🤖 Max\'s verdict</h2><p class="why">{E(r["verdict"])}</p><p class="disc">Max Edge is an AI host. This is commentary, not financial advice.</p></section>'
              f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get every big earnings report explained in your inbox, free.</h2><p>Beat or miss, guidance, the stock reaction and what it means, in plain English. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
              f'<section class="card"><h2 class="h2s">Sources</h2><ul class="why">{srcs}</ul><p class="disc">Numbers come from the company\'s release and the coverage above. Where no consensus was published we leave it out rather than guess.</p></section>'
              f'{related(B,r,reports)}{faqh}<p class="sub"><a href="{BASE}/earnings/{tk.lower()}/">Every {E(nm)} earnings report →</a> · <a href="{BASE}/earnings/">All earnings explained →</a></p><p class="disc-bar">⚠️ <b>Not financial advice.</b> AI-written summary of public filings and news. Check the sources before you trade.</p>')
        title=f"{nm} {q} earnings explained: beat or miss, guidance, stock reaction"
        desc=f"{nm} ({tk}) {q} earnings: {r['verdict_word']}. "+'; '.join(f"{h['metric']} {h['actual']}" for h in r['headline'][:2])+'. Guidance, key takeaways and stock reaction.'
        sch={"@context":"https://schema.org","@graph":[{"@type":"Article","headline":h1,"description":desc[:300],"datePublished":r['date'],"dateModified":B['TODAY'].isoformat(),"author":{"@type":"Organization","name":BRAND},"publisher":{"@type":"Organization","name":BRAND},"mainEntityOfPage":SITE+P,"about":{"@type":"Corporation","name":nm,"tickerSymbol":tk},"citation":[s['url'] for s in r['sources']]},csch,
             {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
        B['w'](f"earnings/{r['slug']}/index.html",B['shell'](title,desc[:155],P,body,sch))
        r['_move']=move; urls.append((P,B['TODAY'].isoformat()))
    return urls+ticker_hubs(B,reports)

def ticker_hubs(B, reports):
    """/earnings/<ticker>/: one evergreen page per company for searches like "AMD earnings" that name no quarter.
    Latest report's numbers up top, then every quarter we've explained. Renders only from the same JSON as the explainers."""
    E=B['E']; BASE=B['BASE']; SITE=B['SITE']; BRAND=B['BRAND']; urls=[]; by={}
    for r in reports: by.setdefault(r['ticker'],[]).append(r)
    for tk,rs in by.items():
        rs=sorted(rs,key=lambda r:r['date'],reverse=True); L=rs[0]; nm=L['company']; P=f"/earnings/{tk.lower()}/"
        d=lambda r: datetime.date.fromisoformat(r['date']).strftime('%B %-d, %Y')
        mv=L.get('_move')
        rows=''.join(f"<tr><td>{E(h['metric'])}</td><td><b>{E(h['actual'])}</b></td><td>{E(h['consensus'])}</td><td>{E(h['result'])}</td></tr>" for h in L['headline'])
        hist=''.join(f'<li><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(r["quarter"])}</b></a> ({E(d(r))}, {E(r["when"])}): {E(r["verdict_word"])}'+(f' · stock {r["_move"]:+.1f}% after' if r.get('_move') is not None else '')+'</li>' for r in rs)
        lead=(f"{nm}'s latest report was {L['quarter']} on {d(L)} ({L['when']}): <b>{E(L['verdict_word'])}</b>"
              +(f", and the stock moved {mv:+.1f}% on it" if mv is not None else '')+". Below: the numbers vs Wall Street, then every quarter we've explained in plain English.")
        faqs=[(f"Did {nm} ({tk}) beat earnings last quarter?",f"In {L['quarter']}, reported {d(L)}, {nm} came in {L['verdict_word']}. "+'; '.join(f"{h['metric']}: {h['actual']} vs {h['consensus']}" for h in L['headline'][:3] if h['consensus']!='n/a')+'.'),
              (f"When did {nm} last report earnings?",f"{nm} reported {L['quarter']} results on {d(L)}, {L['when']}.")]
        faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(a)}</summary><p>{E(b)}</p></details>' for a,b in faqs)+'</div>'
        cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),(f'{tk} earnings',P)])
        h1=f"{nm} ({tk}) Earnings: Results, Guidance and Stock Reaction"
        body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">🧾 Earnings explained · {E(tk)}</span><h1 class="pt">{E(h1)}</h1><p class="sub wksum">{lead}</p></section>'
              f'<section class="card"><h2 class="h2s">Latest: {E(L["quarter"])} vs consensus</h2><div class="tbl"><table><thead><tr><th>Metric</th><th>Reported</th><th>Consensus</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></div>'
              f'<p class="sub"><a href="{BASE}/earnings/{L["slug"]}/">Full {E(tk)} {E(L["quarter"])} explainer: what mattered, the reaction and Max\'s verdict →</a></p></section>'
              f'<section class="card"><h2 class="h2s">Every {E(nm)} report we\'ve explained</h2><ul class="why">{hist}</ul></section>'
              f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get the next {E(tk)} report explained in your inbox.</h2><p>Every big earnings report in plain English: beat or miss, guidance, and how the stock took it. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
              f'{faqh}<p class="sub"><a href="{BASE}/earnings/">All earnings explained →</a></p><p class="disc-bar">⚠️ <b>Not financial advice.</b> AI-written summary of public filings and news. Check the sources on each report page.</p>')
        title=f"{nm} ({tk}) earnings: latest results, guidance and stock reaction"
        desc=f"{nm} ({tk}) earnings in plain English. Latest: {L['quarter']}, {L['verdict_word']}. Beat or miss vs consensus, guidance and how the stock reacted."
        sch={"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":h1,"url":SITE+P,"about":{"@type":"Corporation","name":nm,"tickerSymbol":tk},"publisher":{"@type":"Organization","name":BRAND}},csch,
             {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
        B['w'](f"earnings/{tk.lower()}/index.html",B['shell'](title,desc[:155],P,body,sch)); urls.append((P,B['TODAY'].isoformat()))
    return urls

def scorecard(B, reports, days=7):
    """'Earnings season scorecard' on /earnings/: share of reports that beat on EPS and on revenue,
    and the biggest stock moves, over the last `days` days. Computed only from the JSON results and live moves."""
    E=B['E']; BASE=B['BASE']; today=B.get('TODAY') or datetime.date.today()
    rec=[r for r in reports if 0<=(today-datetime.date.fromisoformat(r['date'])).days<=days]
    if len(rec)<3: return ''
    def pick(r,keys):
        for h in r['headline']:
            m=h['metric'].lower()
            if any(k in m for k in keys) and 'guid' not in m and h['result']: return h['result'].split(',')[0].strip()
        return None
    def tally(keys):
        res=[x for x in (pick(r,keys) for r in rec) if x]
        return len(res),sum(x=='Beat' for x in res),sum(x=='Miss' for x in res)
    en,eb,em=tally(('eps','per share')); rn,rb,rm=tally(('revenue','sales'))
    mv=sorted([r for r in rec if r.get('_move') is not None],key=lambda r:r['_move'])
    def tile(big,lab): return f'<div class="sct"><b>{big}</b><span>{lab}</span></div>'
    tiles=''
    if en: tiles+=tile(f'{eb} of {en}',f'beat on earnings per share ({em} missed)')
    if rn: tiles+=tile(f'{rb} of {rn}',f'beat on revenue ({rm} missed)')
    lnk=lambda r: f'<a href="{BASE}/earnings/{r["slug"]}/">{E(r["company"])}</a>'
    if mv and mv[-1]['_move']>0: tiles+=tile(f'<span class="up">{mv[-1]["ticker"]} {mv[-1]["_move"]:+.1f}%</span>',f'biggest pop: {lnk(mv[-1])}')
    if mv and mv[0]['_move']<0: tiles+=tile(f'<span class="dn">{mv[0]["ticker"]} {mv[0]["_move"]:+.1f}%</span>',f'biggest drop: {lnk(mv[0])}')
    return (f'<section class="card scard"><h2 class="h2s">📊 Earnings season scorecard: last {days} days</h2>'
            f'<p class="sub">{len(rec)} big reports explained. Beat or miss is vs the consensus on each page; stock moves are vs the close before the report and refresh with every site rebuild.</p>'
            f'<div class="scgrid">{tiles}</div></section>')

def index_section(B, reports):
    E=B['E']; BASE=B['BASE']
    if not reports: return ''
    li=''.join(f'<li><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(r["company"])} ({r["ticker"]}) {E(r["quarter"])}</b></a>: {E(r["verdict_word"])}'+(f' · stock {r["_move"]:+.1f}%' if r.get('_move') is not None else '')+f' · {datetime.date.fromisoformat(r["date"]).strftime("%b %-d")}</li>' for r in reports)
    return scorecard(B,reports)+f'<section class="card"><h2 class="h2s">🧾 Earnings explained: beat or miss, in plain English</h2><ul class="why">{li}</ul></section>'

def home_lead(B, reports):
    """Home-page lead: 'Earnings, explained' cards for the latest reports, biggest names first."""
    E=B['E']; BASE=B['BASE']; rec=lead(reports,B['TODAY'],days=2,n=8)
    if not rec: return ''
    def card(r):
        v=str(r.get('verdict','')); v=v.split('. ')[0].rstrip('.')+'.' if v else ''
        hl=' · '.join(f'{E(h["metric"])}: <b>{E(h["result"])}</b>' for h in r['headline'] if h.get('result'))[:400]
        return (f'<a class="ercard" href="{BASE}/earnings/{r["slug"]}/"><span class="erk">{E(r["ticker"])} · {E(r["quarter"])} · {E(r.get("when",""))}</span>'
                f'<h3>{E(r["company"])}: {E(r["verdict_word"])}</h3><p>{E(v)}</p><span class="erm">{hl}</span><span class="erg">Read the plain-English breakdown →</span></a>')
    return (f'<section class="sec ernlead" id="earnings"><div class="sh"><span class="si">🧾</span><div><h2>Earnings, explained</h2>'
            f'<p class="sub">Last night\'s and this morning\'s big reports in plain English: the numbers vs Wall Street, guidance, and how the stock took it. Biggest names first.</p></div></div>'
            f'<div class="ergrid">{"".join(card(r) for r in rec)}</div><p class="sub"><a href="{BASE}/earnings/">All earnings explained →</a></p></section>')

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
