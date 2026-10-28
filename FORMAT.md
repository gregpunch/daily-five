# The Daily Five: edition format (for the daily routine)

One file per day: `editions/YYYY-MM-DD.json`. Then run:
```
SITE_URL=https://readdailyfive.com python3 build.py
git add -A && git commit -m "Edition YYYY-MM-DD" && git push   # auth: credential helper reads $GITHUB_TOKEN
```
`build.py` renders the site, re-prices every past pick for the Scoreboard (Yahoo Finance chart API for stocks, Polymarket Gamma API for markets), writes `scoreboard.csv`, and freezes final exits in `data/exits.json`. Run it daily even with no new edition so the Scoreboard stays current.

## Rules
- Never invent facts, numbers, prices, or odds. Every item needs a real, resolving source URL.
- Entry prices must come from a real quote at publish time (Yahoo `https://query1.finance.yahoo.com/v8/finance/chart/{SYM}?interval=1m&range=1d` → `meta.regularMarketPrice`; Polymarket `https://gamma-api.polymarket.com/markets?slug={slug}` → `outcomePrices[outcome]`).
- If an action is our own inference rather than the source's call, the `why` must say "Our read:".
- No third-party or personal strategy branding. No lottery/sweepstakes content.
- `symbol` must be a valid Yahoo ticker; `slug` + `outcome` must be a live Polymarket market (outcome = index into its `outcomes`).

- **Sports value rule (pick quality).** For every candidate game, read the DraftKings moneyline (ESPN scoreboard JSON above, or another real published line) and compute the edge: no-vig sportsbook chance minus the Polymarket price, in points. Prefer plays where Polymarket is **≥ 2 pts under** the no-vig line (verdict 💰 Value); fill the 5 with those first. A play within 2 pts either way is a **coin flip at a fair price** (🪙): use one only when there aren't 5 value plays, and its `why` must say so plainly, e.g. "Coin flip at a fair price: Polymarket 41¢ vs 41.5% no-vig at DraftKings; we like it because …". Never pick a side that is ≥ 2 pts **over** the line (⚠️ Pricey). Always fill `book` with the line you used. Why: through Oct 20, 14 settled picks bought within 2 pts of the books went 8-6 but averaged −5.5% per $1; a winning record at fair prices still loses money.


## Relaunch rules (from Oct 25, 2026: Max Edge Day 1) — these override older rules below
Data behind them (beta, Oct 15–24, 42 settled sports picks, 16 settled 1-day stock calls):
- Sports under 40¢ went **2-13, avg −64% per $1**, even with a +2–3 pt "value" edge (13 picks at +2–3 pts went 3-10, −46%). A 2-pt edge on a longshot is inside the noise of the line.
- Coin flips (within 2 pts of the no-vig line) went 11-11, **−14%**.
- 40–60¢ picks went 8-6, **+10%**; that's the only bucket that made money.
- 1-day stock calls went 8-8, −0.3%: noise.

**Sports (pick quality gate). A pick qualifies only if ALL hold:**
1. Real DraftKings/ESPN (or other published) moneyline in `book`; no line, no pick.
2. Edge = no-vig book chance − Polymarket price **≥ +2.5 pts**.
3. Polymarket price **between 40¢ and 70¢** (no longshots, no heavy favorites).
4. No futures.
Publish **0–5** sports picks: only the ones that qualify. Fewer than 5 is fine; zero is fine ("No bets today: nothing cleared our bar" is a valid section). Never pad with coin flips.
**Bold Bet of the Day:** set `"bold": true` on exactly one qualifying sports pick, the one with the highest edge (tie → closer to 50¢). Max Edge's daily video leads with it. If nothing qualifies, no Bold Bet that day (Max says so).

**Stocks: single 3-month horizon.** `horizon` must be `"3 Month"`. No 1 Day / 1 Month / 1 Year calls.
- Make **1–2 new calls per week** (not daily). On other days `finance` is `[]`; the site and email automatically show the open 3-month calls with live performance.
- Each call: `action` BUY, `entry` (real quote), `target_price` (number, e.g. Yahoo `financialData.targetMeanPrice` or a named analyst target; say which in `target_note`), `spy_entry` (SPY price at the same moment as `entry`), and a one-line `why`.
- Selection: favor an upcoming catalyst (earnings within the window), recent analyst target raises, reasonable valuation (forward P/E vs history/peers) and positive momentum (above 50-day average). Ignore daily noise and single-day moves.
- Catalyst field (optional, on a 3-month call): `"catalyst": {"event","date":"YYYY-MM-DD","when":"after the close|before the open","right":[...],"wrong":[...],"max":"..."}`. After the report, add `"result": {"verdict":"beat|miss|mixed","short":"<=44 chars for the share card","line":"headline numbers vs estimates","source":{"name","url"}}` using only numbers from a cited source (never invent). That turns on the "📊 The print" line, the /earnings/ verdict box and the post-earnings verdict card (/og/verdict.png, also the /earnings/ og:image) for 5 days after the report. Morning-after editions, Kit and X posts should lead with it.
- Grading: exits at the first close on/after entry + 91 days. **Win = beat SPY** over the same window. build.py sets `ret` = stock return − SPY return and shows both.
- The sports and stock records shown on the site/email count only picks dated ≥ 2026-10-25 (`LAUNCH` in build.py). Earlier picks live on `/beta-archive/`.

## Schema
```json
{
  "date": "YYYY-MM-DD",
  "headline": "One-line hook for the day (page title/SEO)",
  "top_call": "Big punchy hero headline about the day's top call (optional; falls back to headline)",
  "backdrop": "1–2 sentence market context with real numbers",
  "backdrop_source": {"name": "AP", "url": "https://..."},
  "finance": [            // 6 items: 2 each for "1 Day", "1 Month", "1 Year"
    {"horizon": "1 Day|1 Month|1 Year", "action": "BUY|SELL", "label": "NVDA", "symbol": "NVDA",
     "entry": 214.39, "entry_note": "Yahoo Finance, <date time ET>",
     "why": "One line, ≤ 120 chars.", "risk": "One line.",
     "source": {"name": "Outlet", "url": "https://..."}}
  ],
  "ai": [                 // 5 items
    {"category": "Money|Policy|Safety|Regulation|Agents|Models|Chips|...", "headline": "...", "why": "One-line why it matters.", "source": {"name": "...", "url": "https://..."}}
  ],
  "sports": [             // 5 Polymarket/Kalshi plays
    {"action": "BUY", "label": "Brewers YES", "market": "Brewers win NLCS",
     "slug": "polymarket-market-slug", "outcome": 0, "entry": 0.9035,
     "event_date": "YYYY-MM-DD or null for futures",
     "why": "Biggest move / volume / mispricing vs sportsbook or news.", "source": {"name": "Polymarket", "url": "https://polymarket.com/event/..."}}
  ]
}
```
Horizons close at entry date + 1 / 30 / 365 days (exit = first daily close on/after that date). A horizon ending on a weekend exits at the next session's close. A pick whose exit session is today freezes at today's close on the first build after 4:15 PM ET (not the next morning); today's still-forming daily bar is never frozen before 4:15 PM ET (until then the pick reads "live (exits at today's close)" or "live (exits at next close)"), and only when the daily bar matches Yahoo's `regularMarketPrice` (servers briefly disagree right after the close). Sports picks close when the Polymarket market resolves; on a real game (NFL/MLB/NBA/NHL slugs) a BUY settles provisionally at 100¢/0¢ as soon as Polymarket's events API reports the game ended with a decisive final score (note "final score, awaiting resolution", not frozen into exits.json, so the official resolution still wins). live.js does the same in the browser the moment a card's game-day line flips to FINAL. SELL finance returns are short-side; sports picks are always BUY of an outcome (use the NO outcome to fade).

Signup forms POST natively to Kit form 10050182 (field `email_address`).

## Live prices (automatic)
GitHub Actions (`.github/workflows/pages.yml`) rebuilds and redeploys every 15 min on weekday market hours (13–21 UTC, at :07/:22/:37/:52) and every 30 min otherwise (:12/:42). GitHub cron is best-effort and can lag or skip; `live.js` shows a "stale, refreshing soon" note when `live.json` is >25 min old in market hours (>50 min otherwise). Kick a manual rebuild with `gh workflow run pages.yml --repo gregpunch/daily-five`. Each build writes `site/data/live.json` (cur, day open, since-open %, since-pick %, final, label, updated_et, `ts` epoch). The homepage and Scoreboard show a "Today so far" strip (open picks up/down, avg since pick, avg today, best/worst) that live.js recomputes every minute. `live.js` reloads it every 60 s and also polls Polymarket's Gamma API directly (CORS-enabled) for sports cards. Stocks are labeled delayed (Yahoo may lag up to ~15 min). After 4 PM ET on weekdays the strip flips to "🔔 Closing bell" (amber; "stocks closed for the day · sports still live"), shows "Pre-market" before 9:30 AM ET and "Weekend" on Sat/Sun, lists picks from the latest edition that have settled (final P/L), and counts down to the next 7 AM ET edition (also in the recap box). Resolved Polymarket markets drop out of Gamma's default query, so `build.py` retries with `&closed=true`; a closed market only counts as final (and is frozen into `data/exits.json`) once its price is ≥0.99 or ≤0.01. `site/` is no longer committed: CI builds it. Only `data/exits.json` is committed back by CI (with `[skip ci]`).

## SEO pages (automatic)
`/picks/<id>/` per pick, `/ticker/<SYMBOL or polymarket-slug>/` per ticker/market, `/track-record/`, `/how-we-rank/`, and a per-edition OG image `/og/<date>.png` (SVG rendered to PNG with headless Chrome when available, otherwise the SVG). All go in `sitemap.xml`, with an honest `lastmod`: hubs, home and anything still marked to live prices get today; a settled pick page gets the day it settled (`closed YYYY-MM-DD` note, last market tick, or kickoff), a ticker page its latest pick, and an edition the latest of its picks. `/picks/` lists every pick by day with that day's settled record. Pick and ticker pages carry a visible breadcrumb (Home › Stock picks / NFL picks / Polymarket picks › ticker or game › pick) plus BreadcrumbList JSON-LD in the page's `@graph`. Each pick page ends with up to 4 related-pick links: other picks within 45 min of the same kickoff ("More Sun 1 PM ET kickoff picks"), else picks from the same edition, same hub first. The recap block shows the previous edition's picks with P/L, plus "Come back tomorrow at 7 AM ET".

## Sports `why`
Every sports item must state a sourced reason, or start with "Our read:" if it's our inference. It renders as "Why BUY: …".

## Daily Five Score (computed by build.py)
Four components, each 0–25 (neutral 12.5 when they can't be computed, and the card says so):
1. **Credibility**: hit rate of `source.name` across closed picks in our Scoreboard (needs ≥5 closed picks; otherwise "new source").
2. **Consensus**: from the `consensus` field, which you fill with REAL sources found by search: `"consensus": {"agree": [{"name","url"}], "dissent": [{"name","url"}]}` (count the primary source in `agree`).
3. **Edge**: stocks = % gap to Yahoo `financialData.targetMeanPrice` (signed by BUY/SELL). Sports = no-vig sportsbook probability minus Polymarket price, in points, from `"book": {"name","url","odds":[american_for_our_outcome, american_other]}` (real published lines only).
   Sportsbook lines (automatic, `attach_books`): for NFL/NBA/MLB/NHL/WNBA game picks, build.py reads the moneyline from ESPN's free public scoreboard JSON (`site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates=YYYYMMDD`, DraftKings, no account or key), matched on start time (±4h) and team name, and stores it in `data/books.json` (key `date/sN`, with read time). Before the game starts, Edge = live ESPN no-vig line vs live Polymarket price (refreshed every build). Once the game starts or settles, Edge = the edition's `book` (line at publish) vs our entry, else the last pre-game ESPN line stored in `data/books.json` vs our entry (labeled "Pre-game line" with its read time). Futures keep the edition `book` vs the live price. Keep filling `book` in editions (it's the publish-time line and covers futures). Sports cards show a "📒" sportsbook-check line (odds, no-vig %, Polymarket price, edge in points, source + time); pick pages show the full math and any other line we have. Every sports card, pick page and the email also show a plain **value verdict** from that edge (`vkey`/`verdict` in build.py, `VAL_PTS`=2): 💰 Value (≥ +2 pts), 🪙 Coin flip at a fair price (within 2 pts), ⚠️ Pricey (≤ −2 pts), ❔ Unchecked (no real line); started/settled picks keep the verdict at our entry, past tense, plus our settled record for that verdict. The home/edition sports header has a "Value check vs the sportsbooks" summary of the open plays. `/sports-results/` has a "Results by value verdict" section (`#value`) with each verdict's settled record and avg, and tags every settled row with its verdict; `/how-we-rank/#value` explains it. `data/books.json` is committed by local builds (edition pushes, check-ins), not by CI, so CI never races the edition push; CI reads the live line in memory each build.
4. **Risk/reward**: stocks = horizon-scaled target gap ÷ (60-day daily vol × √trading days); sports = EV at the fair probability.
Cards show the score badge, four component bars, and a one-line breakdown. Finance and sports are ranked by score (#1 = highest); the hero "Top call" is the top-scored finance pick (so `top_call` text should match it, or omit `top_call`).

Evergreen SEO hubs (rebuilt every build, real picks only): `/best-stocks-to-buy-today/` (finance BUYs) and `/polymarket-picks-today/` (sports prediction-market plays: today ranked by Daily Five Score, settled win rate/avg return, every pick graded, FAQ + CollectionPage schema). `/nfl-picks-this-week/` (open NFL Polymarket plays, latest call per game, grouped by kickoff from Gamma `gameStartTime`, NFL record, every NFL pick graded, FAQ + CollectionPage + SportsEvent ItemList schema). All are in the sitemap and footer. A sports pick may set `"pid"` to pin its URL id when its `market` text is corrected later.

Weekly NFL results (automatic): `/nfl-results/week-N/` recaps every NFL pick whose game kicks off in that NFL week (Tue to Mon, so TNF, London, Sunday, SNF and MNF), with entry, final score (Polymarket events API), result, return, W-L, average return, $100-a-pick P/L, a Week N+1 signup ask, Article + BreadcrumbList JSON-LD, and any still-open game (e.g. MNF) shown live. The week number comes from the `Week N` in the pick's `market` text (keep writing it). A week's page appears once one of its games settles; `/nfl-results/` lists all weeks. Linked from the NFL hub (banner + pills), `/picks/`, `/track-record/`, the footer and the sitemap.

League hubs (automatic): `/mlb-picks-today/` and `/nba-picks-today/` are built once we have published a pick in that league (MLB = `mlb-` game slugs plus World Series / ALCS / NLCS / league-championship futures by slug text; NBA = `nba-` slugs). Each lists open plays by day and start time (latest call per market, then futures), a game-day live score board, the league's settled record (games and futures, both sides shown if we flipped), every pick graded with final scores, a Kit signup ask, FAQ + CollectionPage + BreadcrumbList + SportsEvent ItemList schema. The MLB hub is titled "MLB playoff picks" while our recent MLB picks are postseason markets. Pick and ticker pages in those leagues breadcrumb to their league hub. Linked from the homepage sports header, `/polymarket-picks-today/`, `/picks/`, `/track-record/`, the footer and the sitemap.

Stock results (automatic): `/stock-results/` grades every settled stock pick at its real exit close, grouped by edition (record + avg per edition), with settled record, avg return, $100-a-pick P/L, best call, per-horizon tiles (1 Day / 1 Month / 1 Year: settled record + open avg mark), BUY vs SELL split, a Kit signup ask, every still-open call marked live, FAQ, and Article + BreadcrumbList + FAQPage JSON-LD. Appears once a stock pick settles. Linked from `/best-stocks-to-buy-today/`, `/picks/`, `/track-record/`, the footer and the sitemap.

Sports results (automatic): `/sports-results/` grades every settled Polymarket sports pick (all leagues, games and series futures) with its real final score (Polymarket events API) and real entry/exit price: settled record, avg return per $1 at entry, $100-a-pick P/L, best call (ties named), a W/L strip in settle order, per-league records (NFL, MLB, ...), favorites (60¢+) vs under-60¢ and single games vs futures splits, a game-day live board for open games, every settled pick by league (newest game first), every open pick marked live, a Kit signup ask, FAQ, and Article + BreadcrumbList + FAQPage JSON-LD (SportsEvent mentions). Appears once a sports pick settles. Linked from `/polymarket-picks-today/`, `/nfl-picks-this-week/`, `/nfl-results/`, the MLB/NBA hubs, `/stock-results/`, `/picks/`, `/track-record/`, the footer and the sitemap.

Closing bell recap (automatic): from 4:15 PM ET on the newest edition's day (and overnight until the next 7 AM edition), the home page and that edition's page open with a "🔔 Closing bell · How today's picks finished" section (`#closing-bell`, `closing_bell()` in build.py): picks that settled that day (stock exits frozen at that close from any edition, plus sports games that kicked off that day and went final) with W/L, entry → exit and avg; today's stock calls marked at the real daily close bar (same Yahoo read and `regularMarketPrice` agreement check that freezes exits); games still playing tonight; all-time stock and sports records linking the results pages; and a "Tomorrow's five drop at 7 AM ET" countdown + Kit signup. Real data only; it renders nothing before 4:15 PM ET.

Email preview text (automatic): the hidden preheader in each email (`preheader()` in email_build.py) leads with yesterday's biggest settled win at +25% or better ("Yesterday: BUY Flyers settled +182%"), else the running sports record, then the headline, padded so the inbox preview doesn't pull in body text.
