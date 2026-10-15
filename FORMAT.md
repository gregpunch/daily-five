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
Horizons close at entry date + 1 / 30 / 365 days (exit = first daily close on/after that date). Sports picks close when the Polymarket market resolves. SELL finance returns are short-side; sports picks are always BUY of an outcome (use the NO outcome to fade).

The hero's "Top call" card shows finance item #3 (first 1-Month pick); order items accordingly. Signup forms POST natively to Kit form 10050182 (field `email_address`).
