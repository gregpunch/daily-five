"""AI earnings explainer pages: /earnings/<ticker>-<quarter>/ from data/earnings/*.json.
Every number lives in the JSON with its sources; this file only renders. See prototypes/earnings-explainer-runbook.md."""
import json, glob, os, datetime, time, urllib.request

# Rough market cap in $B, used only to order explainers "biggest names first". A report JSON may override with "mcap_b".
MCAP={'NVDA':4500,'AAPL':3800,'MSFT':3700,'GOOGL':3000,'AMZN':2400,'META':1800,'AVGO':1600,'TSLA':1400,'BRK.B':1000,'LLY':800,'AMD':800,'JPM':800,
 'WMT':800,'V':650,'ORCL':600,'MA':500,'NFLX':500,'XOM':480,'COST':400,'PLTR':400,'JNJ':400,'HD':380,'ABBV':380,'PG':360,'BAC':340,'KO':300,
 'NVO':250,'CVX':250,'CSCO':250,'CRM':240,'MCD':220,'PEP':200,'SHOP':200,'IBM':200,'DIS':200,'UBER':190,'ANET':180,'AMGN':170,'BKNG':170,
 'QCOM':170,'PFE':145,'ETN':140,'CVS':90,'APO':80,'RACE':80,'MPC':50,'APP':110,'ARM':180,'CI':85,'COP':140,'CAH':55,'AMGN':170,'BKNG':170}
def size(r): return r.get('mcap_b') or MCAP.get(r['ticker'],0)
def fresh(r,today):
    """Last night's (after the close yesterday) or today's reports: these lead, ahead of yesterday morning's."""
    d=(today-datetime.date.fromisoformat(r['date'])).days
    return d==0 or (d==1 and r.get('when')=='after the close')
def lead(reports,today,days=2,n=8,pin=None):
    """Latest explainers for the home lead / email: reports from the last `days` days, last night's and today's first,
    then biggest names first. `pin` (the edition's optional "lead" explainer slug) goes first when it is in the window.
    Falls back to the newest `n` reports if nothing is that recent."""
    rec=[r for r in reports if 0<=(today-datetime.date.fromisoformat(r['date'])).days<=days] or reports[:n]
    return sorted(rec,key=lambda r:(r['slug']!=pin,not fresh(r,today),-size(r),r['ticker']))[:n]

def load(root):
    out=[json.load(open(f)) for f in sorted(glob.glob(os.path.join(root,'data','earnings','*.json')))]
    return sorted(out,key=lambda r:(r['date'],r['ticker']),reverse=True)

_rx_cache={}
def live_reaction(r):
    """Latest price incl. pre/post-market from Yahoo vs the stored pre-report close. Falls back to the stored snapshot.
    Memoized per (ticker, report date) for a single build.py run so home + explainer pages don't re-hit Yahoo."""
    key=(r.get('ticker'),r.get('date'))
    if key in _rx_cache: return _rx_cache[key]
    out=r.get('reaction') or {}
    try:
        u=f"https://query1.finance.yahoo.com/v8/finance/chart/{r.get('yahoo') or r['ticker']}?range=5d&interval=5m&includePrePost=true"
        j=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=8))['chart']['result'][0]
        pts=[(t,c) for t,c in zip(j['timestamp'],j['indicators']['quote'][0]['close']) if c]
        rep=datetime.date.fromisoformat(r['date'])
        if pts and datetime.date.fromtimestamp(pts[-1][0])>=rep:
            t,c=pts[-1]; lt=time.localtime(t); hm=lt.tm_hour*60+lt.tm_min
            kind='premarket' if hm<570 else 'after hours' if hm>=960 else 'intraday'
            if kind=='after hours' and r.get('when','').startswith('before'): kind='close+after hours'
            out={'kind':kind,'price':round(c,2),'asof':time.strftime('%Y-%m-%d %-I:%M %p ET',lt)}
    except Exception: pass
    _rx_cache[key]=out
    return out

def eps_result(r):
    """'Beat'/'Miss'/'In line' on the EPS line (not guidance), or None."""
    for h in r['headline']:
        m=h['metric'].lower()
        if ('eps' in m or 'per share' in m) and 'guid' not in m and h['result']: return h['result'].split(',')[0].strip()
    return None

def rev_result(r):
    """'Beat'/'Miss'/'In line' on the revenue/sales line (not guidance), or None."""
    for h in r['headline']:
        m=h['metric'].lower()
        if any(k in m for k in ('revenue','sales','net sales')) and 'guid' not in m and h.get('result'):
            return h['result'].split(',')[0].strip()
    return None

def surprise(r, move, thr=1.0):
    """Mismatch labels searchers ask about ("why did X stock fall after earnings"):
    'beat-fell' = EPS Beat but stock down; 'rev-beat-fell' = revenue Beat (EPS not Beat) but stock down;
    'miss-rose' = EPS Miss but stock up. Else None."""
    if move is None: return None
    e=eps_result(r); v=rev_result(r)
    if e=='Beat' and move<=-thr: return 'beat-fell'
    if e!='Beat' and v=='Beat' and move<=-thr: return 'rev-beat-fell'
    if e=='Miss' and move>=thr: return 'miss-rose'
    return None

def surprise_block(B, r, move, rx):
    """Explainer card + FAQ answer for a beat-but-fell / rev-beat-but-fell / miss-but-rose reaction."""
    E=B['E']; k=surprise(r,move)
    if not k: return '',None
    nm=r['company']; tk=r['ticker']; tw=r['takeaways'][:3]; kind=rx.get('kind','')
    if k=='beat-fell':
        q=f"Why did {tk} stock fall after beating earnings?"
        gen=("A beat on its own rarely moves a stock up, because the market prices in what it expects before the report. "
             "Stocks often fall after a beat when guidance, margins or a one-off announcement disappoint, or when the beat was smaller than the whisper number traders were hoping for.")
        lead=f"{nm} beat Wall Street's earnings-per-share estimate, yet {tk} was {move:+.1f}% {kind}."
    elif k=='rev-beat-fell':
        q=f"Why did {tk} stock fall after a revenue beat?"
        gen=("A top-line beat can still send a stock lower when earnings only matched (or missed), margins disappointed, guidance was soft, or traders had already priced in the growth. "
             "After hours especially, the tape often reacts to the weakest line in the release, not the strongest.")
        eps=eps_result(r) or 'no clean EPS print'
        lead=f"{nm} beat Wall Street's revenue estimate, but EPS was {eps.lower()}, and {tk} was {move:+.1f}% {kind}."
    else:
        q=f"Why did {tk} stock rise after missing earnings?"
        gen=("A miss doesn't always sink a stock. Shares can rise when guidance, a key growth metric or a one-off announcement beats what the market feared, "
             "or when expectations had already fallen so far that 'less bad' counts as good news.")
        lead=f"{nm} missed Wall Street's earnings-per-share estimate, yet {tk} was {move:+.1f}% {kind}."
    html=(f'<section class="card"><h2 class="h2s">🤔 {E(q)}</h2><p class="why"><b>{E(lead)}</b> {E(gen)}</p>'
          f'<p class="sub">The rest of the report, which is what the market is weighing, is in "What actually mattered" just below.</p></section>')
    ans=f"{lead} {gen} Key points from the report: "+' '.join(tw)
    return html,(q,ans)

def related(B, r, reports, n=6):
    """'More earnings this week' cross-links on each explainer: the other reports within 7 days, nearest first.
    Internal links between explainers help Google crawl new pages and give readers a next click."""
    E=B['E']; BASE=B['BASE']; d0=datetime.date.fromisoformat(r['date'])
    rel=[x for x in reports if x['slug']!=r['slug'] and abs((datetime.date.fromisoformat(x['date'])-d0).days)<=7]
    rel=sorted(rel,key=lambda x:(abs((datetime.date.fromisoformat(x['date'])-d0).days),x['ticker']))[:n]
    if not rel: return ''
    li=''.join(f'<li><a href="{BASE}/earnings/{x["slug"]}/"><b>{E(x["company"])} ({x["ticker"]}) {E(x["quarter"])}</b></a>: {E(x["verdict_word"])} · {datetime.date.fromisoformat(x["date"]).strftime("%b %-d")}</li>' for x in rel)
    return f'<section class="card"><h2 class="h2s">More earnings explained this week</h2><ul class="why">{li}</ul></section>'

def up_next(B, reports, n=8):
    """'Up next on the earnings calendar' card on every explainer and ticker hub: the next report day's names from
    data/calendar (before the open first), each linking its /earnings/<ticker>/ page or its explainer once out.
    Sends readers and crawlers from older, indexed explainers to the new earnings-date pages."""
    E=B['E']; BASE=B['BASE']; T=B.get('TODAY') or datetime.date.today()
    d,its=next_reports(T,reports)
    if not d or (d-T).days>6 or not its: return ''
    lab='today' if d==T else ('tomorrow' if (d-T).days==1 else d.strftime('%A'))
    def eps(v): return '' if v is None else ', EPS est. '+(f'-${abs(v):.2f}' if v<0 else f'${v:.2f}')
    li=''
    for x in its[:n]:
        r=x['_r']
        if r: li+=f'<li><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(x["company"])}</b> ({E(x["ticker"])})</a>, {E(x["when"])}: {E(eps_result(r) or "explained")}</li>'
        else: li+=f'<li><a href="{BASE}/earnings/{x["ticker"].lower()}/"><b>{E(x["company"])}</b> ({E(x["ticker"])})</a>, {E(x["when"])}{E(eps(x.get("eps_est")))}</li>'
    more=f' and {len(its)-n} more' if len(its)>n else ''
    return (f'<section class="card"><h2 class="h2s">🗓️ Up next: reporting {E(lab)}, {E(d.strftime("%b %-d"))}</h2><ul class="why">{li}</ul>'
            f'<p class="sub"><a href="{BASE}/earnings-calendar/#d-{d.isoformat()}">See the full day{E(more)} on the earnings calendar →</a> Dates and estimates from a public earnings calendar; companies can move dates.</p></section>')

_prerun_cache={}
def prerun(sym, rep_date, when=''):
    """Real 3-month move INTO a past report: last daily close before the report (same day if it reported after the close)
    vs the close ~63 trading days earlier, from Yahoo's chart API. Also the S&P 500 over the same window. None on failure."""
    key=(sym,rep_date,when)
    if key in _prerun_cache: return _prerun_cache[key]
    out=None
    try:
        rd=datetime.date.fromisoformat(rep_date); after=str(when).startswith('after')
        def closes(s):
            p1=int(time.mktime((rd-datetime.timedelta(days=130)).timetuple())); p2=int(time.mktime((rd+datetime.timedelta(days=1)).timetuple()))
            u=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(s)}?period1={p1}&period2={p2}&interval=1d"
            j=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=8))['chart']['result'][0]
            pts=[(datetime.date.fromtimestamp(t),c) for t,c in zip(j['timestamp'],j['indicators']['quote'][0]['close']) if c]
            pts=[(d,c) for d,c in pts if (d<=rd if after else d<rd)]
            if len(pts)<64: return None
            return (pts[-64][0],pts[-1][0],round((pts[-1][1]/pts[-64][1]-1)*100,1))
        a=closes(sym); m=closes('^GSPC')
        if a: out={'start':a[0],'end':a[1],'m3':a[2],'spx':(m[2] if m else None)}
    except Exception: pass
    _prerun_cache[key]=out
    return out

def prerun_html(E, tk, pr, move):
    """One plain-English line pairing the run-up into the report with the reaction ("ran up 25% then fell 8%")."""
    if not pr: return '', None
    m3=pr['m3']; verb='ran up' if m3>=0 else 'fell'
    ctx=f' (S&amp;P 500 {pr["spx"]:+.1f}% over the same stretch)' if pr.get('spx') is not None else ''
    if move is None: tail='.'
    elif (m3>=0)==(move>=0): tail=f', and the report added to that: {move:+.1f}% so far.'
    else: tail=f', then the report reversed it: {move:+.1f}% so far.'
    note=(' A big run-up sets a high bar, which helps explain a sell-off on good numbers.' if m3>=10 and move is not None and move<0
          else ' A stock that was already beaten down can bounce on results that merely clear a low bar.' if m3<=-10 and move is not None and move>0 else '')
    txt=f'Going in, {tk} {verb} {abs(m3):.1f}% over the three months before the report{ctx}{tail}'
    h=(f'<p class="sub"><b>Into the report:</b> {txt}{note} Daily closes {pr["start"].strftime("%b %-d")} to {pr["end"].strftime("%b %-d, %Y")}, Yahoo Finance.</p>')
    return h, (txt.replace('&amp;','&')+note)

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
        pr=prerun(r.get('yahoo') or tk.replace('.','-'),r['date'],r.get('when','')) if B.get('live',True) else None
        prh,prtxt=prerun_html(E,tk,pr,move); rxh+=prh
        rx_h2=('📈 After-hours reaction' if 'after hours' in (rx.get('kind') or '') else '📈 Stock reaction')
        srcs=''.join(f'<li><a href="{E(s["url"])}" rel="nofollow noopener" target="_blank">{E(s["title"])}</a></li>' for s in r['sources'])
        bw=[h for h in r['headline'] if h['result']]
        ans_beat=f"{nm} reported {q} results on {d} ({r['when']}). "+'; '.join(f"{h['metric']}: {h['actual']} vs {h['consensus']} expected ({h['result'].lower()})" for h in bw if h['consensus']!='n/a')+'.'
        gd=[h for h in r['headline'] if 'guid' in h['metric'].lower()]
        faqs=[(f"Did {nm} beat earnings in {q}?",ans_beat)]
        if gd: faqs.append((f"What is {nm}'s guidance after {q}?",' '.join(f"{h['metric']}: {h['actual']} (consensus {h['consensus']})." for h in gd)))
        if move is not None: faqs.append((f"How did {tk} stock react to earnings?",f"{tk} was {move:+.1f}% {rx['kind']} at ${rx['price']:,.2f} versus the ${pc:,.2f} close before the report, as of {rx['asof']}."))
        if prtxt: faqs.append((f"How much did {tk} stock move before earnings?",prtxt))
        sbh,sfq=surprise_block(B,r,move,rx)
        if sfq: faqs.insert(0,sfq)
        r['_surprise']=surprise(r,move)
        faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(a)}</summary><p>{E(b)}</p></details>' for a,b in faqs)+'</div>'
        cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),(f'{tk} earnings',f'/earnings/{tk.lower()}/'),(f'{tk} {q}',P)])
        h1=f"{nm} ({tk}) {q} Earnings Explained"
        body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">🧾 Earnings explained · {E(d)} · {E(r["when"])}</span><h1 class="pt">{E(h1)}</h1>'
              f'<p class="sub wksum"><b>Bottom line: {E(r["verdict_word"])}.</b> The numbers vs Wall Street, what actually mattered, and how the stock took it, in plain English.</p></section>'
              f'<section class="card"><h2 class="h2s">The headline numbers</h2><div class="tbl"><table><thead><tr><th>Metric</th><th>Reported</th><th>Consensus</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
              f'<section class="card"><h2 class="h2s">{rx_h2}</h2>{rxh}</section>{sbh}'
              f'<section class="card"><h2 class="h2s">What actually mattered</h2><ol class="why">{tks}</ol></section>'
              f'<section class="card"><h2 class="h2s">🤖 Max\'s verdict</h2><p class="why">{E(r["verdict"])}</p><p class="disc">Max Edge is an AI host. This is commentary, not financial advice.</p></section>'
              f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get every big earnings report explained in your inbox, free.</h2><p>Beat or miss, guidance, the stock reaction and what it means, in plain English. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
              f'<section class="card"><h2 class="h2s">Sources</h2><ul class="why">{srcs}</ul><p class="disc">Numbers come from the company\'s release and the coverage above. Where no consensus was published we leave it out rather than guess.</p></section>'
              f'{related(B,r,reports)}{up_next(B,reports)}{faqh}<p class="sub"><a href="{BASE}/earnings/{tk.lower()}/">Every {E(nm)} earnings report →</a> · <a href="{BASE}/earnings/week-of-{_wk(r).isoformat()}/">This week\'s earnings recap →</a> · <a href="{BASE}/earnings/">All earnings explained →</a></p><p class="disc-bar">⚠️ <b>Not financial advice.</b> AI-written summary of public filings and news. Check the sources before you trade.</p>')
        title=f"{nm} {q} earnings explained: beat or miss, guidance, stock reaction"
        desc=f"{nm} ({tk}) {q} earnings: {r['verdict_word']}. "+'; '.join(f"{h['metric']} {h['actual']}" for h in r['headline'][:2])+'. Guidance, key takeaways and stock reaction.'
        # When the reaction contradicts the EPS result, match the question searchers type in the title and meta.
        if r['_surprise']=='beat-fell':
            title=f"Why {tk} stock fell after {nm} beat {q} earnings"
            desc=f"{nm} beat on EPS but {tk} was {move:+.1f}% {rx.get('kind','')}. What spooked the market, explained: "+'; '.join(f"{h['metric']} {h['actual']}" for h in r['headline'][:2])+'.'
        elif r['_surprise']=='rev-beat-fell':
            title=f"Why {tk} stock fell after {nm} beat on revenue in {q}"
            desc=f"{nm} beat on revenue but {tk} was {move:+.1f}% {rx.get('kind','')}. Why the tape sold off, explained: "+'; '.join(f"{h['metric']} {h['actual']}" for h in r['headline'][:2])+'.'
        elif r['_surprise']=='miss-rose':
            title=f"Why {tk} stock rose after {nm} missed {q} earnings"
            desc=f"{nm} missed on EPS but {tk} was {move:+.1f}% {rx.get('kind','')}. Why the market shrugged, explained: "+'; '.join(f"{h['metric']} {h['actual']}" for h in r['headline'][:2])+'.'
        sch={"@context":"https://schema.org","@graph":[{"@type":"Article","headline":h1,"description":desc[:300],"datePublished":r['date'],"dateModified":B['TODAY'].isoformat(),"author":{"@type":"Organization","name":BRAND},"publisher":{"@type":"Organization","name":BRAND},"mainEntityOfPage":SITE+P,"about":{"@type":"Corporation","name":nm,"tickerSymbol":tk},"citation":[s['url'] for s in r['sources']]},csch,
             {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
        B['w'](f"earnings/{r['slug']}/index.html",B['shell'](title,desc[:155],P,body,sch))
        r['_move']=move; urls.append((P,B['TODAY'].isoformat()))
    return urls+ticker_hubs(B,reports)+upcoming_hubs(B,reports)+week_recaps(B,reports)+calendar_page(B,reports)

def ticker_hubs(B, reports):
    """/earnings/<ticker>/: one evergreen page per company for searches like "AMD earnings" that name no quarter.
    Latest report's numbers up top, then every quarter we've explained, plus "More earnings explained this week"
    (other companies within 7 days of the latest report — same related() card as quarter explainers)."""
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
              f'{related(B,L,reports)}{up_next(B,reports)}'
              f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get the next {E(tk)} report explained in your inbox.</h2><p>Every big earnings report in plain English: beat or miss, guidance, and how the stock took it. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
              f'{faqh}<p class="sub"><a href="{BASE}/earnings/">All earnings explained →</a></p><p class="disc-bar">⚠️ <b>Not financial advice.</b> AI-written summary of public filings and news. Check the sources on each report page.</p>')
        title=f"{nm} ({tk}) earnings: latest results, guidance and stock reaction"
        desc=f"{nm} ({tk}) earnings in plain English. Latest: {L['quarter']}, {L['verdict_word']}. Beat or miss vs consensus, guidance and how the stock reacted."
        sch={"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":h1,"url":SITE+P,"about":{"@type":"Corporation","name":nm,"tickerSymbol":tk},"publisher":{"@type":"Organization","name":BRAND}},csch,
             {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
        B['w'](f"earnings/{tk.lower()}/index.html",B['shell'](title,desc[:155],P,body,sch)); urls.append((P,B['TODAY'].isoformat()))
    return urls

_runup_cache={}
def runup(sym):
    """Real 3-month daily closes from Yahoo's chart API: latest price and 1-week / 1-month / 3-month change, plus the 3-month
    range. Returns None on any failure so the page simply omits the section. Memoized per build."""
    if sym in _runup_cache: return _runup_cache[sym]
    out=None
    try:
        u=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range=3mo&interval=1d"
        j=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=8))['chart']['result'][0]
        pts=[(t,c) for t,c in zip(j['timestamp'],j['indicators']['quote'][0]['close']) if c]
        if len(pts)>=40:
            last=j['meta'].get('regularMarketPrice') or pts[-1][1]; lt=time.localtime(j['meta'].get('regularMarketTime') or pts[-1][0])
            def ch(n): return round((last/pts[-1-n][1]-1)*100,1) if len(pts)>n else None
            cl=[c for _,c in pts]
            out={'price':round(last,2),'asof':time.strftime('%b %-d, %Y %-I:%M %p ET',lt),'w1':ch(5),'m1':ch(21),'m3':round((last/pts[0][1]-1)*100,1),
                 'hi':round(max(cl+[last]),2),'lo':round(min(cl+[last]),2)}
    except Exception: pass
    _runup_cache[sym]=out
    return out

def runup_section(B, tk, sym):
    E=B['E']; r=runup(sym); m=runup('^GSPC')
    if not r: return ''
    def pc(v): return '—' if v is None else f'<span class="{"up" if v>0 else "dn" if v<0 else ""}">{v:+.1f}%</span>'
    rows=[('Latest price',f'<b>${r["price"]:,.2f}</b>'),('Past week',pc(r['w1'])),('Past month',pc(r['m1'])),('Past 3 months',pc(r['m3']))]
    if m: rows.append(('S&amp;P 500, past 3 months',pc(m['m3'])))
    rows.append(('3-month range',f'${r["lo"]:,.2f} to ${r["hi"]:,.2f}'))
    gap=''
    if m and r['m3'] is not None:
        d=round(r['m3']-m['m3'],1)
        gap=f' Over three months {E(tk)} is {"ahead of" if d>0 else "behind" if d<0 else "even with"} the S&amp;P 500'+(f' by {abs(d):.1f} points.' if d else '.')
    return (f'<section class="card"><h2 class="h2s">How {E(tk)} stock is trading into the report</h2><div class="tbl"><table><tbody>'
            +''.join(f'<tr><td>{a}</td><td>{b}</td></tr>' for a,b in rows)+'</tbody></table></div>'
            f'<p class="sub">'+('A big run-up raises the bar: the stock may need a clear beat to hold its gains. ' if r['m3']>=10 else 'The stock has already sold off, so the bar going in may be lower. ' if r['m3']<=-10 else '')+f'{gap.strip()} Prices from Yahoo Finance (latest trade vs. daily closes), as of {E(r["asof"])}; refreshed on every site build.</p></section>')

def upcoming_hubs(B, reports):
    """/earnings/<ticker>/ for calendar names we haven't explained yet ("CEG earnings date" searches): report date, before/after
    the bell, quarter and the Wall Street EPS estimate, all copied from data/calendar with its source. Nothing else is claimed.
    Same URL becomes the full ticker hub (ticker_hubs) once that company's explainer JSON lands, so the page keeps its ranking."""
    E=B['E']; BASE=B['BASE']; SITE=B['SITE']; BRAND=B['BRAND']; T=B['TODAY']; urls=[]
    done={r['ticker'].upper() for r in reports}; seen={}
    for m,cal in sorted(load_calendar().items()):
        for x in cal['items']:
            tk=x['ticker'].upper()
            if tk in done: continue
            seen[tk]=(x,cal)   # latest calendar week wins
    B['_uphubs']=set(seen)
    def eps(v): return 'not published' if v is None else (f'-${abs(v):.2f}' if v<0 else f'${v:.2f}')
    for tk,(x,cal) in seen.items():
        nm=x['company']; q=x['quarter']; dd=datetime.date.fromisoformat(x['date']); P=f"/earnings/{tk.lower()}/"
        ds=dd.strftime('%A, %B %-d, %Y'); sc=cal['source']; fetched=datetime.date.fromisoformat(cal['fetched']).strftime('%B %-d, %Y')
        past=dd<T; today=dd==T
        verb='reported' if past else 'reports'
        lead=(f"{nm} ({tk}) {verb} {q} earnings on {ds}, {x['when']}. Wall Street's consensus EPS estimate is {eps(x.get('eps_est'))}. "
              +("Our plain-English explainer of the results is on the way." if past else "Once the numbers are out, this page becomes our plain-English explainer: beat or miss, guidance and how the stock took it."))
        same=sorted([y for y in cal['items'] if y['date']==x['date'] and y['ticker'].upper()!=tk],key=lambda y:(y['when']!='before the open',y['ticker']))
        sameh=''.join(f'<li><a href="{BASE}/earnings/{y["ticker"].lower()}/"><b>{E(y["company"])}</b> ({E(y["ticker"])})</a>, {E(y["when"])}, EPS est. {eps(y.get("eps_est"))}</li>' for y in same)
        faqs=[(f"When does {nm} ({tk}) report earnings?",f"{nm} {verb} {q} results on {ds}, {x['when']}, per the {sc['name']} as of {fetched}. Companies can move dates."),
              (f"What EPS is expected from {nm} in {q}?",f"The consensus estimate is {eps(x.get('eps_est'))} per share, per the {sc['name']} as of {fetched}.")]
        faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(a)}</summary><p>{E(b)}</p></details>' for a,b in faqs)+'</div>'
        cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),(f'{tk} earnings',P)])
        h1=f"{nm} ({tk}) Earnings Date: {q} on {dd.strftime('%b %-d')}, What Wall Street Expects"
        wk=dd-datetime.timedelta(days=dd.weekday())
        body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">🗓️ Earnings preview · {E(tk)}'+(' · today' if today else '')+f'</span><h1 class="pt">{E(h1)}</h1><p class="sub wksum">{E(lead)}</p></section>'
              f'<section class="card"><h2 class="h2s">{E(q)} at a glance</h2><div class="tbl"><table><tbody>'
              f'<tr><td>Report date</td><td><b>{E(ds)}</b></td></tr><tr><td>Timing</td><td><b>{E(x["when"])}</b></td></tr>'
              f'<tr><td>Quarter</td><td><b>{E(q)}</b></td></tr><tr><td>Consensus EPS estimate</td><td><b>{E(eps(x.get("eps_est")))}</b></td></tr></tbody></table></div>'
              f'<p class="sub">Source: <a href="{E(sc["url"])}" rel="nofollow noopener">{E(sc["name"])}</a> as of {E(fetched)}. Dates and estimates can change before the report.</p></section>'
              f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get the {E(tk)} report explained in your inbox.</h2><p>Beat or miss, guidance and the stock reaction in plain English, every weekday morning. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
              +(runup_section(B,tk,x.get('yahoo') or tk.replace('.','-')) if not past else '')
              +(f'<section class="card"><h2 class="h2s">Also reporting {E(dd.strftime("%A, %b %-d"))}</h2><ul class="why">{sameh}</ul></section>' if sameh else '')
              +f'{faqh}<p class="sub"><a href="{BASE}/earnings/week-of-{wk.isoformat()}/">Everyone reporting the week of {E(week_label(wk))} →</a> · <a href="{BASE}/earnings/">All earnings explained →</a></p>'
              f'<p class="disc-bar">⚠️ <b>Not financial advice.</b> Calendar data from a public earnings calendar; dates can change.</p>')
        title=f"{nm} ({tk}) earnings date: {q} on {dd.strftime('%b %-d, %Y')}, EPS estimate"
        desc=f"{nm} ({tk}) {verb} {q} earnings {dd.strftime('%a %b %-d')}, {x['when']}. Consensus EPS {eps(x.get('eps_est'))}. Results explained here in plain English."
        sch={"@context":"https://schema.org","@graph":[{"@type":"WebPage","name":h1,"url":SITE+P,"description":desc[:300],"about":{"@type":"Corporation","name":nm,"tickerSymbol":tk},"publisher":{"@type":"Organization","name":BRAND}},csch,
             {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
        B['w'](f"earnings/{tk.lower()}/index.html",B['shell'](title,desc[:155],P,body,sch)); urls.append((P,T.isoformat()))
    return urls

def cal_week(today, CAL):
    """Which week /earnings-calendar/ shows: the current Mon–Fri week, or the coming week from Saturday on."""
    m=today-datetime.timedelta(days=today.weekday())
    if today.weekday()>=5: m+=datetime.timedelta(days=7)
    if m in CAL: return m
    up=[w for w in CAL if w>=m]
    return min(up) if up else (max(CAL) if CAL else None)

def calendar_page(B, reports):
    """/earnings-calendar/: one evergreen URL ("earnings calendar this week") that always shows the current week day by day,
    before the open / after the close, with the Wall Street EPS estimate from data/calendar and, once we've explained a report,
    the beat/miss and stock move from the explainer. Nothing beyond those two sources is shown."""
    E=B['E']; BASE=B['BASE']; SITE=B['SITE']; BRAND=B['BRAND']; T=B['TODAY']; CAL=load_calendar()
    m=cal_week(T,CAL)
    if not m: return []
    cal=CAL[m]; P='/earnings-calendar/'
    wk=[r for r in reports if _wk(r)==m]; done={r['ticker'].upper():r for r in wk}
    items=[dict(x) for x in cal['items']]
    have={x['ticker'].upper() for x in items}
    for r in wk:
        if r['ticker'].upper() not in have: items.append(dict(date=r['date'],ticker=r['ticker'],company=r['company'],quarter=r['quarter'],when=r.get('when',''),eps_est=None))
    def eps(v): return '—' if v is None else (f'-${abs(v):.2f}' if v<0 else f'${v:.2f}')
    def row(x):
        tk=x['ticker'].upper(); r=done.get(tk)
        if r:
            er=eps_result(r); mv=r.get('_move')
            res=(f'<span class="{"up" if er=="Beat" else "dn" if er=="Miss" else ""}">{E(er)}</span>' if er else 'Explained')+(f' · <b class="{"up" if mv>=0 else "dn"}">{mv:+.1f}%</b>' if mv is not None else '')
            return f'<tr><td><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(x["company"])}</b> ({E(tk)})</a><br><small>{E(x["quarter"])}</small></td><td>{eps(x.get("eps_est"))}</td><td>—</td><td>{res}</td></tr>'
        ru=runup(x.get('yahoo') or tk.replace('.','-')); m1=ru and ru.get('m1')
        mvh='—' if m1 is None else f'<span class="{"up" if m1>0 else "dn" if m1<0 else ""}">{m1:+.1f}%</span>'
        return f'<tr><td><a href="{BASE}/earnings/{tk.lower()}/"><b>{E(x["company"])}</b> ({E(tk)})</a><br><small>{E(x["quarter"])}</small></td><td>{eps(x.get("eps_est"))}</td><td>{mvh}</td><td>Coming up</td></tr>'
    order={'before the open':0,'after the close':2}
    days=sorted({x['date'] for x in items}); sec=''; faqd=[]
    for d in days:
        dd=datetime.date.fromisoformat(d); its=sorted([x for x in items if x['date']==d],key=lambda x:(order.get(x['when'],1),-MCAP.get(x['ticker'],0),x['ticker']))
        lab=dd.strftime('%A, %b %-d')+(' · today' if dd==T else '')
        groups=''
        for w in sorted({x['when'] for x in its},key=lambda w:order.get(w,1)):
            g=[x for x in its if x['when']==w]
            groups+=(f'<h3 class="h3s">{E(w.capitalize() if w else "Time not set")}</h3>' if w or len(its)>1 else '')+f'<div class="tbl"><table><thead><tr><th>Company</th><th>EPS est.</th><th>Past month</th><th>Result</th></tr></thead><tbody>{"".join(row(x) for x in g)}</tbody></table></div>'
        sec+=f'<section class="card" id="d-{d}"><h2 class="h2s">🗓️ {E(lab)}</h2>{groups}</section>'
        faqd.append(f"{dd.strftime('%A')}: "+', '.join(f"{x['company']} ({x['ticker']})" for x in its))
    jump=' · '.join(f'<a href="#d-{d}">{datetime.date.fromisoformat(d).strftime("%a %-d")}</a>' for d in days)
    lab=week_label(m); n=len(items); ex=len(done)
    F=cal.get('featured') or []; tm={x['ticker']:x for x in items}
    names=([tm[t]['company'] for t in F if t in tm] or [x['company'] for x in sorted(items,key=lambda x:-MCAP.get(x['ticker'],0))])[:4]
    summ=(f"{n} big earnings reports the week of {lab}, including {', '.join(names).rstrip('.')}. Day by day, before the open or after the close, with Wall Street's EPS estimate"
          +(f"; {ex} already explained with beat or miss and the stock move." if ex else "; each turns into a plain-English explainer once it reports."))
    sc=cal['source']; fetched=datetime.date.fromisoformat(cal['fetched']).strftime('%B %-d, %Y')
    prev=m-datetime.timedelta(days=7); prevh=''
    if any(_wk(r)==prev for r in reports): prevh=f'<a href="{BASE}/earnings/week-of-{prev.isoformat()}/">Last week\'s recap: who beat, who missed →</a> · '
    faqs=[(f"Which companies report earnings this week ({lab})?",'; '.join(faqd)+'.'),
          ("Where do these dates and estimates come from?",f"The {sc['name']}, as of {fetched}. Companies can move report dates, so check the company's investor relations page before you trade.")]
    faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(a)}</summary><p>{E(b)}</p></details>' for a,b in faqs)+'</div>'
    cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),('Earnings calendar',P)])
    h1=f"Earnings Calendar This Week ({lab})"
    body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">🗓️ Earnings calendar · updated {E(T.strftime("%b %-d"))}</span><h1 class="pt">{E(h1)}</h1><p class="sub wksum">{E(summ)}</p><p class="sub">Jump to: {jump}</p></section>{sec}'
          f'<p class="sub">Dates and estimates: <a href="{E(sc["url"])}" rel="nofollow noopener">{E(sc["name"])}</a> as of {E(fetched)}. Past month is the stock\'s change over roughly 21 trading days into the report, from Yahoo Finance at build time. Results and moves come from our explainers and refresh with every site rebuild.</p>'
          f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get this week\'s big reports explained in your inbox.</h2><p>Beat or miss, guidance and the stock reaction in plain English, every weekday morning. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
          f'{faqh}<p class="sub">{prevh}<a href="{BASE}/earnings/week-of-{m.isoformat()}/">This week\'s recap page →</a> · <a href="{BASE}/earnings/">All earnings explained →</a></p>'
          f'<p class="disc-bar">⚠️ <b>Not financial advice.</b> Calendar data from a public earnings calendar; dates can change.</p>')
    title=f"Earnings calendar this week ({lab}): who reports, when, EPS estimates"
    sch={"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":h1,"url":SITE+P,"description":summ[:300],"dateModified":T.isoformat(),"publisher":{"@type":"Organization","name":BRAND}},csch,
         {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
    B['w']("earnings-calendar/index.html",B['shell'](title,summ[:155],P,body,sch))
    return [(P,T.isoformat())]

def _wk(r):
    d=datetime.date.fromisoformat(r['date']); return d-datetime.timedelta(days=d.weekday())
def week_label(m, rs=()):
    f=max([m+datetime.timedelta(days=4)]+[datetime.date.fromisoformat(r['date']) for r in rs])
    return f"{m.strftime('%b %-d')}–{f.strftime('%-d') if f.month==m.month else f.strftime('%b %-d')}, {f.year}"
def load_calendar(root=None):
    """data/calendar/week-of-<monday>.json: upcoming reports (date, ticker, company, quarter, when, eps_est) copied from a public
    earnings calendar, with its source. Gives a week its recap URL before any explainer exists (preview flips to results in place)."""
    root=root or os.path.dirname(os.path.abspath(__file__)); out={}
    for f in sorted(glob.glob(os.path.join(root,'data','calendar','week-of-*.json'))):
        c=json.load(open(f)); out[datetime.date.fromisoformat(c['week'])]=c
    return out
def cal_section(B, cal, rs):
    """'On the calendar' table: calendar names with no explainer yet that week (matched by ticker)."""
    E=B['E']; done={r['ticker'].upper() for r in rs}; it=[x for x in cal['items'] if x['ticker'].upper() not in done]
    if not it: return ''
    it=sorted(it,key=lambda x:(x['date'],x['when']!='before the open',x['ticker']))
    def eps(v): return '—' if v is None else (f'-${abs(v):.2f}' if v<0 else f'${v:.2f}')
    rows=''.join(f'<tr><td><a href="{B["BASE"]}/earnings/{x["ticker"].lower()}/"><b>{E(x["company"])}</b> ({E(x["ticker"])})</a><br><small>{E(x["quarter"])}</small></td><td>{datetime.date.fromisoformat(x["date"]).strftime("%a %b %-d")}<br><small>{E(x["when"])}</small></td><td>{eps(x.get("eps_est"))}</td></tr>'
                 if x['ticker'].upper() in B.get('_hubs',set()) else
                 f'<tr><td><b>{E(x["company"])}</b> ({E(x["ticker"])})<br><small>{E(x["quarter"])}</small></td><td>{datetime.date.fromisoformat(x["date"]).strftime("%a %b %-d")}<br><small>{E(x["when"])}</small></td><td>{eps(x.get("eps_est"))}</td></tr>' for x in it)
    sc=cal['source']
    return (f'<section class="card" id="calendar"><h2 class="h2s">🗓️ On the calendar'+(' this week' if rs else '')+f'</h2><p class="sub">Big reports still to come and the Wall Street EPS estimate. Each one gets a plain-English explainer here once it reports.</p>'
            f'<div class="tbl"><table><thead><tr><th>Company</th><th>When</th><th>EPS est.</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p class="sub">Dates and estimates: <a href="{E(sc["url"])}" rel="nofollow noopener">{E(sc["name"])}</a> as of {datetime.date.fromisoformat(cal["fetched"]).strftime("%b %-d")}; companies can move dates.</p></section>')
def week_recaps(B, reports):
    """/earnings/week-of-<monday>/: one recap per week ("earnings this week: who beat, who missed"), built only from
    the explainer JSON results and the live moves render() just computed. Weekend reports (e.g. Berkshire on Saturday) roll into that week."""
    E=B['E']; BASE=B['BASE']; SITE=B['SITE']; BRAND=B['BRAND']; urls=[]; by={}
    for r in reports: by.setdefault(_wk(r),[]).append(r)
    CAL=load_calendar(); B['_hubs']={r['ticker'].upper() for r in reports}|B.get('_uphubs',set())
    for m in CAL: by.setdefault(m,[])
    weeks=sorted(by,reverse=True)
    for i,m in enumerate(weeks):
        rs=sorted(by[m],key=lambda r:(r['date'],-size(r))); P=f"/earnings/week-of-{m.isoformat()}/"; lab=week_label(m,by[m]); cal=CAL.get(m)
        calh=cal_section(B,cal,rs) if cal else ''
        if rs and i>0 and not by[weeks[i-1]]:
            calh+=f'<section class="card"><h2 class="h2s">🗓️ Coming up next week</h2><p class="sub"><a href="{BASE}/earnings/week-of-{weeks[i-1].isoformat()}/"><b>Earnings next week ({E(week_label(weeks[i-1]))}) →</b></a> who reports, when, and what Wall Street expects.</p></section>'
        if not rs:
            if not cal: continue
            ci=sorted(cal['items'],key=lambda x:-(MCAP.get(x['ticker'],0)))
            F=cal.get('featured') or []; tm={x['ticker']:x for x in cal['items']}
            names=([tm[t]['company'] for t in F if t in tm] or [x['company'] for x in sorted(cal['items'],key=lambda x:(x['date'],x['ticker']))])[:6]
            summ=f"{len(cal['items'])} big reports on the calendar the week of {lab}, including {', '.join(names[:-1])} and {names[-1]}. Dates, times and Wall Street's EPS estimates below; each gets a plain-English explainer once it reports."
            faqs=[(f"Which companies report earnings the week of {lab}?",'; '.join(f"{datetime.date.fromisoformat(d).strftime('%A')}: "+', '.join(f"{x['company']} ({x['ticker']})" for x in cal['items'] if x['date']==d) for d in sorted({x['date'] for x in cal['items']}))+'.')]
            nav=[]
            if i+1<len(weeks): nav.append(f'<a href="{BASE}/earnings/week-of-{weeks[i+1].isoformat()}/">← Week of {E(week_label(weeks[i+1],by[weeks[i+1]]))}</a>')
            if i>0: nav.append(f'<a href="{BASE}/earnings/week-of-{weeks[i-1].isoformat()}/">Week of {E(week_label(weeks[i-1],by[weeks[i-1]]))} →</a>')
            faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(a)}</summary><p>{E(b)}</p></details>' for a,b in faqs)+'</div>'
            cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),(f'Week of {lab}',P)])
            h1=f"Earnings Next Week ({lab}): Who Reports and What Wall Street Expects" if m>B['TODAY'] else f"Earnings This Week ({lab}): Who Reports and What Wall Street Expects"
            body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">🗓️ Earnings preview · {E(lab)}</span><h1 class="pt">{E(h1)}</h1><p class="sub wksum">{E(summ)}</p></section>{calh}'
                  f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get these reports explained in your inbox.</h2><p>Beat or miss, guidance and the stock reaction in plain English, every weekday morning. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
                  f'{faqh}<p class="sub">{" · ".join(nav+[f"<a href=\"{BASE}/earnings/\">All earnings explained →</a>"])}</p><p class="disc-bar">⚠️ <b>Not financial advice.</b> Calendar data from a public earnings calendar; dates can change.</p>')
            title=h1.replace('Earnings Next Week','Earnings next week').replace('Earnings This Week','Earnings this week').replace('Who Reports and What Wall Street Expects','who reports and what Wall Street expects')
            sch={"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":h1,"url":SITE+P,"description":summ[:300],"publisher":{"@type":"Organization","name":BRAND}},csch,
                 {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
            B['w'](f"earnings/week-of-{m.isoformat()}/index.html",B['shell'](title,summ[:155],P,body,sch)); urls.append((P,B['TODAY'].isoformat()))
            continue
        ep=[eps_result(r) for r in rs]; rv=[rev_result(r) for r in rs]
        en=sum(1 for x in ep if x); eb=sum(x=='Beat' for x in ep); rn=sum(1 for x in rv if x); rb=sum(x=='Beat' for x in rv)
        mv=sorted([r for r in rs if r.get('_move') is not None],key=lambda r:r['_move'])
        bf=[r for r in mv if surprise(r,r['_move']) in ('beat-fell','rev-beat-fell')]
        def cl(x): return 'up' if x=='Beat' else 'dn' if x=='Miss' else ''
        def cell(x): return f'<span class="{cl(x)}">{E(x)}</span>' if x else '—'
        rows=''.join(f'<tr><td><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(r["company"])}</b> ({E(r["ticker"])})</a><br><small>{E(r["quarter"])} · {datetime.date.fromisoformat(r["date"]).strftime("%a %b %-d")}</small></td>'
                     f'<td>{cell(eps_result(r))}</td><td>{cell(rev_result(r))}</td><td>'+(f'<b class="{"up" if r["_move"]>=0 else "dn"}">{r["_move"]:+.1f}%</b>' if r.get('_move') is not None else 'pending')+'</td></tr>' for r in rs)
        def tile(big,l): return f'<div class="sct"><b>{big}</b><span>{l}</span></div>'
        tiles=''
        if en: tiles+=tile(f'{eb} of {en}','beat on EPS')
        if rn: tiles+=tile(f'{rb} of {rn}','beat on revenue')
        lnk=lambda r: f'<a href="{BASE}/earnings/{r["slug"]}/">{E(r["company"])}</a>'
        if mv and mv[-1]['_move']>0: tiles+=tile(f'<span class="up">{mv[-1]["ticker"]} {mv[-1]["_move"]:+.1f}%</span>',f'biggest pop: {lnk(mv[-1])}')
        if mv and mv[0]['_move']<0: tiles+=tile(f'<span class="dn">{mv[0]["ticker"]} {mv[0]["_move"]:+.1f}%</span>',f'biggest drop: {lnk(mv[0])}')
        if bf: tiles+=tile(str(len(bf)),'beat and still fell')
        beats=[r['company'] for r,x in zip(rs,ep) if x=='Beat']; miss=[r['company'] for r,x in zip(rs,ep) if x=='Miss']
        summ=(f"{len(rs)} big reports explained the week of {lab}. "+(f"{eb} of {en} beat Wall Street on earnings per share" if en else '')
              +(f"; the biggest pop was {mv[-1]['company']} ({mv[-1]['ticker']} {mv[-1]['_move']:+.1f}%)" if mv and mv[-1]['_move']>0 else '')
              +(f" and the biggest drop {mv[0]['company']} ({mv[0]['ticker']} {mv[0]['_move']:+.1f}%)" if mv and mv[0]['_move']<0 else '')+'.')
        faqs=[(f"Which companies beat earnings the week of {lab}?",(f"On EPS: {', '.join(beats)} beat consensus." if beats else 'No EPS beats among the reports we explained.')+(f" Missed: {', '.join(miss)}." if miss else ''))]
        if mv: faqs.append((f"Which stock moved the most after earnings the week of {lab}?",f"Among the reports we explained, {mv[-1]['company']} ({mv[-1]['ticker']}) moved {mv[-1]['_move']:+.1f}% and {mv[0]['company']} ({mv[0]['ticker']}) moved {mv[0]['_move']:+.1f}% versus the close before each report, as of the latest site rebuild."))
        if bf: faqs.append((f"Which stocks fell after beating earnings the week of {lab}?",'; '.join(f"{r['company']} ({r['ticker']} {r['_move']:+.1f}%)" for r in bf)+'. Each explainer covers why.'))
        faqh='<h2 class="h2s">FAQ</h2><div class="faq">'+''.join(f'<details class="fq"><summary>{E(a)}</summary><p>{E(b)}</p></details>' for a,b in faqs)+'</div>'
        nav=[]
        if i+1<len(weeks): nav.append(f'<a href="{BASE}/earnings/week-of-{weeks[i+1].isoformat()}/">← Week of {E(week_label(weeks[i+1],by[weeks[i+1]]))}</a>')
        if i>0: nav.append(f'<a href="{BASE}/earnings/week-of-{weeks[i-1].isoformat()}/">Week of {E(week_label(weeks[i-1],by[weeks[i-1]]))} →</a>')
        cnav,csch=B['crumbs']([('Home','/'),('Earnings explained','/earnings/'),(f'Week of {lab}',P)])
        h1=f"Earnings This Week ({lab}): Who Beat, Who Missed, Biggest Stock Moves"
        body=(f'{cnav}<section class="sbhero hubhero"><span class="kicker">📊 Weekly earnings recap · {E(lab)}</span><h1 class="pt">{E(h1)}</h1><p class="sub wksum">{E(summ)}</p></section>'
              f'<section class="card scard"><h2 class="h2s">📊 The week in one glance</h2><div class="scgrid">{tiles}</div><p class="sub">Beat or miss is vs the consensus on each explainer; stock moves are vs the close before the report and refresh with every site rebuild.</p></section>'
              f'<section class="card"><h2 class="h2s">Every report this week</h2><div class="tbl"><table><thead><tr><th>Company</th><th>EPS</th><th>Revenue</th><th>Stock</th></tr></thead><tbody>{rows}</tbody></table></div></section>{calh}'
              f'<section class="signup wksign"><div><span class="kicker">📬 Free</span><h2>Get next week\'s big reports explained in your inbox.</h2><p>Beat or miss, guidance and the stock reaction in plain English, every weekday morning. No spam, unsubscribe anytime.</p></div>{B["sform"]("ern")}</section>'
              f'{faqh}<p class="sub">{" · ".join(nav+[f"<a href=\"{BASE}/earnings/\">All earnings explained →</a>"])}</p><p class="disc-bar">⚠️ <b>Not financial advice.</b> AI-written summary of public filings and news. Check the sources on each report page.</p>')
        title=f"Earnings this week ({lab}): who beat, who missed, biggest stock moves"
        desc=summ
        sch={"@context":"https://schema.org","@graph":[{"@type":"CollectionPage","name":h1,"url":SITE+P,"description":desc[:300],"publisher":{"@type":"Organization","name":BRAND},
              "hasPart":[{"@type":"Article","headline":f"{r['company']} {r['quarter']} earnings explained","url":f"{SITE}/earnings/{r['slug']}/"} for r in rs]},csch,
             {"@type":"FAQPage","url":SITE+P,"mainEntity":[{"@type":"Question","name":a,"acceptedAnswer":{"@type":"Answer","text":b}} for a,b in faqs]}]}
        B['w'](f"earnings/week-of-{m.isoformat()}/index.html",B['shell'](title,desc[:155],P,body,sch)); urls.append((P,B['TODAY'].isoformat()))
    return urls

def weeks_section(B, reports):
    E=B['E']; BASE=B['BASE']; by={}
    for r in reports: by.setdefault(_wk(r),[]).append(r)
    CAL=load_calendar()
    for m in CAL: by.setdefault(m,[])
    if not by: return ''
    li=''.join(f'<li><a href="{BASE}/earnings/week-of-{m.isoformat()}/"><b>Week of {E(week_label(m,by[m]))}</b></a>: '+(f'{len(by[m])} reports, who beat, who missed, biggest moves' if by[m] else f'preview: {len(CAL[m]["items"])} big reports on the calendar and what Wall Street expects')+'</li>' for m in sorted(by,reverse=True))
    return f'<section class="card" id="weekly"><h2 class="h2s">📅 Weekly earnings recaps</h2><p class="sub"><a href="{BASE}/earnings-calendar/"><b>🗓️ Earnings calendar this week →</b></a> day by day, before the open or after the close.</p><ul class="why">{li}</ul></section>'

def week_picks(reports, today=None):
    """Cards for this week's recap, last week's recap, and next week's preview.
    Labels follow the Mon–Sun week of `today`: Saturday still says 'this week';
    Monday promotes last week's recap and the new preview."""
    today = today or datetime.date.today()
    cur = today - datetime.timedelta(days=today.weekday())
    last = cur - datetime.timedelta(days=7)
    nxt = cur + datetime.timedelta(days=7)
    by = {}
    for r in reports:
        by.setdefault(_wk(r), []).append(r)
    CAL = load_calendar()

    def blurb(m):
        rs = by.get(m) or []
        cal = CAL.get(m)
        lab = week_label(m, rs)
        if rs:
            ep = [eps_result(r) for r in rs]
            en = sum(1 for x in ep if x)
            eb = sum(x == 'Beat' for x in ep)
            extra = f'{eb} of {en} beat on EPS' if en else f'{len(rs)} reports explained'
            return lab, f'{len(rs)} reports · {extra}', True
        if not cal:
            return None, None, False
        n = len(cal['items'])
        F = cal.get('featured') or []
        tm = {x['ticker']: x for x in cal['items']}
        names = ([tm[t]['company'] for t in F if t in tm] or
                 [x['company'] for x in sorted(cal['items'], key=lambda x: (x['date'], x['ticker']))])[:3]
        who = (f", including {', '.join(names)}" if names else '')
        return lab, f'{n} big reports on the calendar{who}', False

    out = []
    lab, text, has = blurb(last)
    if lab and has:
        out.append({'kind': 'last', 'monday': last, 'url': f'/earnings/week-of-{last.isoformat()}/',
                    'kicker': '📊 Last week', 'title': f'Earnings recap ({lab})',
                    'blurb': text, 'cta': 'See who beat, who missed →'})
    lab, text, has = blurb(cur)
    if lab:
        out.append({'kind': 'this', 'monday': cur, 'url': f'/earnings/week-of-{cur.isoformat()}/',
                    'kicker': '📊 This week' if has else '🗓️ This week',
                    'title': f'Earnings recap ({lab})' if has else f'Who reports ({lab})',
                    'blurb': text, 'cta': 'See who beat, who missed →' if has else 'Dates, times and EPS estimates →'})
    lab, text, has = blurb(nxt)
    if lab:
        out.append({'kind': 'next', 'monday': nxt, 'url': f'/earnings/week-of-{nxt.isoformat()}/',
                    'kicker': '🗓️ Next week',
                    'title': f'Who reports ({lab})' if not has else f'Earnings recap ({lab})',
                    'blurb': text, 'cta': 'Dates, times and EPS estimates →' if not has else 'See who beat, who missed →'})
    return out

def next_reports(today, reports=(), cal=None):
    """Calendar names reporting on the next report day: today if it's a weekday with names on the calendar (and some
    still to come), else the first later calendar date. Returns (date, items) with each item's explainer (if any) as '_r'."""
    cal=cal if cal is not None else load_calendar(); today=today or datetime.date.today()
    items=[x for c in cal.values() for x in c['items']]
    done={}
    for r in reports: done.setdefault(r['ticker'].upper(),[]).append(r)
    def ex(x):
        rs=[r for r in done.get(x['ticker'].upper(),[]) if 0<=(datetime.date.fromisoformat(r['date'])-datetime.date.fromisoformat(x['date'])).days<=3]
        return rs[0] if rs else None
    days=sorted({x['date'] for x in items if datetime.date.fromisoformat(x['date'])>=today})
    for d in days:
        its=[dict(x,_r=ex(x)) for x in items if x['date']==d]
        if datetime.date.fromisoformat(d)==today and all(x['_r'] for x in its): continue
        order={'before the open':0,'after the close':2}
        return datetime.date.fromisoformat(d), sorted(its,key=lambda x:(order.get(x['when'],1),-MCAP.get(x['ticker'],0),x['ticker']))
    return None, []
def home_next(B, reports):
    """'Reporting today' / 'Reporting Monday' strip on the homepage from data/calendar: who reports, when, EPS estimate;
    names already explained show beat/miss and link the explainer."""
    E=B['E']; BASE=B['BASE']; T=B.get('TODAY') or datetime.date.today()
    d,its=next_reports(T,reports)
    if not d or (d-T).days>4: return ''
    lab='today' if d==T else ('tomorrow' if (d-T).days==1 else d.strftime('%A'))
    def eps(v): return '' if v is None else ' · EPS est. '+(f'-${abs(v):.2f}' if v<0 else f'${v:.2f}')
    chips=''
    for x in its[:10]:
        r=x['_r']
        if r:
            er=eps_result(r) or 'Explained'
            chips+=f'<a class="rnx" href="{BASE}/earnings/{r["slug"]}/"><b>{E(x["company"])}</b> <span>{E(x["ticker"])} · {E(x["when"])} · <em class="{"up" if er=="Beat" else "dn" if er=="Miss" else ""}">{E(er)}</em></span></a>'
        else:
            chips+=f'<a class="rnx" href="{BASE}/earnings/{x["ticker"].lower()}/"><b>{E(x["company"])}</b> <span>{E(x["ticker"])} · {E(x["when"])}{E(eps(x.get("eps_est")))}</span></a>'
    more=f' (+{len(its)-10} more)' if len(its)>10 else ''
    return (f'<div class="rnext"><h3 class="h3s">🗓️ Reporting {E(lab)}, {E(d.strftime("%b %-d"))}{E(more)}</h3><div class="rnxg">{chips}</div>'
            f'<p class="sub"><a href="{BASE}/earnings-calendar/#d-{d.isoformat()}">Full day on the earnings calendar →</a> Dates and estimates from a public earnings calendar; companies can move dates.</p></div>')
def home_weeks(B, reports):
    """Homepage cards linking the current week's recap and the next week's preview (same pages as /earnings/#weekly)."""
    E = B['E']; BASE = B['BASE']
    picks = week_picks(reports, B.get('TODAY'))
    nx = home_next(B, reports)
    if not picks:
        return nx
    cards = ''.join(
        f'<a class="ercard" href="{BASE}{p["url"]}"><span class="erk">{E(p["kicker"])}</span>'
        f'<h3>{E(p["title"])}</h3><p>{E(p["blurb"])}</p><span class="erg">{E(p["cta"])}</span></a>'
        for p in picks)
    return nx + f'<div class="ergrid wkhome">{cards}</div><p class="sub"><a href="{BASE}/earnings-calendar/"><b>🗓️ Earnings calendar this week →</b></a> who reports each day and what Wall Street expects.</p>'

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
    bf=[r for r in rec if r.get('_move') is not None and surprise(r,r['_move']) in ('beat-fell','rev-beat-fell')]
    if bf: tiles+=tile(f'{len(bf)}','beat and still fell · <a href="#beat-but-fell">see all →</a>')
    return (f'<section class="card scard"><h2 class="h2s">📊 Earnings season scorecard: last {days} days</h2>'
            f'<p class="sub">{len(rec)} big reports explained. Beat or miss is vs the consensus on each page; stock moves are vs the close before the report and refresh with every site rebuild.</p>'
            f'<div class="scgrid">{tiles}</div></section>')

def beat_fell_section(B, reports, days=7):
    """Dedicated 'This week\'s beat-but-fell' list on /earnings/: every explainer where the stock dropped ≥1% after an EPS or revenue beat.
    Matches the search phrasing ('why did X stock fall after beating earnings') and deep-links each page's surprise FAQ."""
    E=B['E']; BASE=B['BASE']; today=B.get('TODAY') or datetime.date.today()
    rec=[r for r in reports if 0<=(today-datetime.date.fromisoformat(r['date'])).days<=days]
    bf=[r for r in rec if r.get('_move') is not None and surprise(r,r['_move']) in ('beat-fell','rev-beat-fell')]
    if not bf: return ''
    bf=sorted(bf,key=lambda r:r['_move'])
    def row(r):
        k=surprise(r,r['_move'])
        why=('fell after a revenue beat' if k=='rev-beat-fell' else 'fell after beating earnings')
        return (f'<li><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(r["company"])} ({r["ticker"]})</b></a> '
                f'<span class="dn">{r["_move"]:+.1f}%</span> · {E(why)} · {datetime.date.fromisoformat(r["date"]).strftime("%b %-d")}</li>')
    li=''.join(row(r) for r in bf)
    return (f'<section class="card" id="beat-but-fell"><h2 class="h2s">📉 This week\'s beat-but-fell: why the stock dropped anyway</h2>'
            f'<p class="sub">{len(bf)} report{"s" if len(bf)!=1 else ""} where the company beat Wall Street on EPS or revenue, yet the stock still fell 1%+. '
            f'Each page answers the question searchers type — "Why did X stock fall after beating earnings?" — with the real numbers and Max\'s take.</p>'
            f'<ul class="why">{li}</ul></section>')

def index_section(B, reports):
    E=B['E']; BASE=B['BASE']
    if not reports: return ''
    li=''.join(f'<li><a href="{BASE}/earnings/{r["slug"]}/"><b>{E(r["company"])} ({r["ticker"]}) {E(r["quarter"])}</b></a>: {E(r["verdict_word"])}'+(f' · stock {r["_move"]:+.1f}%' if r.get('_move') is not None else '')+f' · {datetime.date.fromisoformat(r["date"]).strftime("%b %-d")}</li>' for r in reports)
    return scorecard(B,reports)+beat_fell_section(B,reports)+weeks_section(B,reports)+f'<section class="card"><h2 class="h2s">🧾 Earnings explained: beat or miss, in plain English</h2><ul class="why">{li}</ul></section>'

def home_lead(B, reports):
    """Home-page lead: 'Earnings, explained' cards for the latest reports, biggest names first.
    Each card shows the live stock reaction vs the pre-report close (fetched here so the front page
    answers 'and what did the stock do?' without an extra click)."""
    E=B['E']; BASE=B['BASE']; rec=lead(reports,B['TODAY'],days=2,n=8,pin=B.get('PIN'))
    if not rec: return ''
    def mv_badge(r):
        rx=live_reaction(r); pc=r.get('prev_close'); move=None
        if rx.get('price') and pc: move=(rx['price']/pc-1)*100
        r['_move']=move; r['_rx']=rx
        if move is None: return ''
        cls='up' if move>=0 else 'dn'
        kind=E(rx.get('kind',''))
        return f'<span class="ermv {cls}">{E(r["ticker"])} {move:+.1f}% <em>{kind}</em></span>'
    def card(r):
        v=str(r.get('verdict','')); v=v.split('. ')[0].rstrip('.')+'.' if v else ''
        hl=' · '.join(f'{E(h["metric"])}: <b>{E(h["result"])}</b>' for h in r['headline'] if h.get('result'))[:400]
        return (f'<a class="ercard" href="{BASE}/earnings/{r["slug"]}/"><span class="erk">{E(r["ticker"])} · {E(r["quarter"])} · {E(r.get("when",""))}</span>'
                f'<h3>{E(r["company"])}: {E(r["verdict_word"])}</h3>{mv_badge(r)}<p>{E(v)}</p><span class="erm">{hl}</span><span class="erg">Read the plain-English breakdown →</span></a>')
    cards=''.join(card(r) for r in rec)
    sline=home_scoreline(B,reports,rec)
    return (f'<section class="sec ernlead" id="earnings"><div class="sh"><span class="si">🧾</span><div><h2>Earnings, explained</h2>{sline}'
            f'<p class="sub">Last night\'s and this morning\'s big reports in plain English: the numbers vs Wall Street, guidance, and how the stock took it. Biggest names first. Live stock moves refresh with every rebuild.</p></div></div>'
            f'<div class="ergrid">{cards}</div>{home_weeks(B,reports)}<p class="sub"><a href="{BASE}/earnings/">All earnings explained →</a></p></section>')

def home_scoreline(B, reports, rec, days=7):
    """One-line earnings season scorecard under the home 'Earnings, explained' heading:
    EPS beat tally over the last `days` days plus the biggest pop/drop among the lead cards (live moves)."""
    E=B['E']; BASE=B['BASE']; today=B.get('TODAY') or datetime.date.today()
    wk=[r for r in reports if 0<=(today-datetime.date.fromisoformat(r['date'])).days<=days]
    if len(wk)<3: return ''
    res=[]
    for r in wk:
        for h in r['headline']:
            m=h['metric'].lower()
            if ('eps' in m or 'per share' in m) and 'guid' not in m and h.get('result'):
                res.append(h['result'].split(',')[0].strip()); break
    parts=[]
    if res: parts.append(f'<b>{sum(x=="Beat" for x in res)} of {len(res)}</b> beat on EPS this week')
    mv=sorted([r for r in rec if r.get('_move') is not None],key=lambda r:r['_move'])
    if mv and mv[-1]['_move']>0: parts.append(f'biggest pop <span class="up">{E(mv[-1]["ticker"])} {mv[-1]["_move"]:+.1f}%</span>')
    if mv and mv[0]['_move']<0: parts.append(f'biggest drop <span class="dn">{E(mv[0]["ticker"])} {mv[0]["_move"]:+.1f}%</span>')
    if not parts: return ''
    return f'<p class="ersl">📊 {" · ".join(parts)} · <a href="{BASE}/earnings/">full scorecard →</a></p>'

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

def week_stats(reports, monday):
    """Numbers for a weekend 'weekly recap leads' edition (ed['lead_week']=<monday>): same math as week_recaps()
    (EPS/revenue beat counts, biggest pop/drop and beat-but-fell from live moves vs the pre-report close)."""
    if isinstance(monday, str): monday = datetime.date.fromisoformat(monday)
    rs = [r for r in reports if _wk(r) == monday]
    if not rs: return None
    for r in rs:
        if r.get('_move') is None:
            rx = live_reaction(r); pc = r.get('prev_close')
            r['_move'] = (rx['price']/pc-1)*100 if rx.get('price') and pc else None
    ep = [eps_result(r) for r in rs]; rv = [rev_result(r) for r in rs]
    mv = sorted([r for r in rs if r.get('_move') is not None], key=lambda r: r['_move'])
    return dict(monday=monday, label=week_label(monday, rs), url=f'/earnings/week-of-{monday.isoformat()}/', rs=rs,
                n=len(rs), en=sum(1 for x in ep if x), eb=sum(x == 'Beat' for x in ep),
                rn=sum(1 for x in rv if x), rb=sum(x == 'Beat' for x in rv),
                pop=mv[-1] if mv and mv[-1]['_move'] > 0 else None, drop=mv[0] if mv and mv[0]['_move'] < 0 else None,
                bf=[r for r in mv if surprise(r, r['_move']) in ('beat-fell', 'rev-beat-fell')],
                top=sorted(rs, key=lambda r: (-size(r), r['ticker'])))

def home_week_lead(B, reports, ed):
    """Home lead block for weekend editions with ed['lead_week']: the weekly recap headline numbers, the biggest
    names (with live moves) and a link to every explainer of that week, above the regular 'Earnings, explained' cards."""
    E = B['E']; BASE = B['BASE']; s = week_stats(reports, ed['lead_week'])
    if not s: return ''
    def mv(r):
        if r.get('_move') is None: return ''
        return f'<span class="ermv {"up" if r["_move"] >= 0 else "dn"}">{E(r["ticker"])} {r["_move"]:+.1f}%</span>'
    tiles = ''.join(f'<div class="sct"><b>{b}</b><span>{l}</span></div>' for b, l in [
        (f'{s["eb"]} of {s["en"]}', 'beat on EPS'), (f'{s["rb"]} of {s["rn"]}', 'beat on revenue')]
        + ([(f'<span class="up">{E(s["pop"]["ticker"])} {s["pop"]["_move"]:+.1f}%</span>', f'biggest pop: {E(s["pop"]["company"])}')] if s['pop'] else [])
        + ([(f'<span class="dn">{E(s["drop"]["ticker"])} {s["drop"]["_move"]:+.1f}%</span>', f'biggest drop: {E(s["drop"]["company"])}')] if s['drop'] else [])
        + ([(str(len(s['bf'])), 'beat and still fell')] if s['bf'] else []))
    cards = ''.join(f'<a class="ercard" href="{BASE}/earnings/{r["slug"]}/"><span class="erk">{E(r["ticker"])} · {E(r["quarter"])}</span>'
                    f'<h3>{E(r["company"])}: {E(r["verdict_word"])}</h3>{mv(r)}<span class="erg">Read the breakdown →</span></a>' for r in s['top'][:8])
    allx = ' · '.join(f'<a href="{BASE}/earnings/{r["slug"]}/">{E(r["company"])}</a>' for r in s['top'])
    return (f'<section class="sec ernlead" id="week-lead"><div class="sh"><span class="si">📊</span><div><h2>{E(ed.get("lead_title") or "This week in earnings")}</h2>'
            f'<p class="sub">{s["n"]} big reports explained the week of {E(s["label"])}. Biggest names first; moves are vs the close before each report and refresh with every rebuild. '
            f'<a href="{BASE}{s["url"]}"><b>Full weekly recap →</b></a></p></div></div>'
            f'<div class="scgrid">{tiles}</div><div class="ergrid">{cards}</div>'
            f'<p class="sub"><b>Every explainer this week:</b> {allx}</p></section>')
