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
Horizons close at entry date + 1 / 30 / 365 days (exit = first daily close on/after that date). Sports picks close when the Polymarket market resolves; on a real game (NFL/MLB/NBA/NHL slugs) a BUY settles provisionally at 100¢/0¢ as soon as Polymarket's events API reports the game ended with a decisive final score (note "final score, awaiting resolution", not frozen into exits.json, so the official resolution still wins). live.js does the same in the browser the moment a card's game-day line flips to FINAL. SELL finance returns are short-side; sports picks are always BUY of an outcome (use the NO outcome to fade).

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
4. **Risk/reward**: stocks = horizon-scaled target gap ÷ (60-day daily vol × √trading days); sports = EV at the fair probability.
Cards show the score badge, four component bars, and a one-line breakdown. Finance and sports are ranked by score (#1 = highest); the hero "Top call" is the top-scored finance pick (so `top_call` text should match it, or omit `top_call`).

Evergreen SEO hubs (rebuilt every build, real picks only): `/best-stocks-to-buy-today/` (finance BUYs) and `/polymarket-picks-today/` (sports prediction-market plays: today ranked by Daily Five Score, settled win rate/avg return, every pick graded, FAQ + CollectionPage schema). `/nfl-picks-this-week/` (open NFL Polymarket plays, latest call per game, grouped by kickoff from Gamma `gameStartTime`, NFL record, every NFL pick graded, FAQ + CollectionPage + SportsEvent ItemList schema). All are in the sitemap and footer. A sports pick may set `"pid"` to pin its URL id when its `market` text is corrected later.
