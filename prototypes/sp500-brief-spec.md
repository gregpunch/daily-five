# S&P 500 Morning Brief — prototype spec (NOT live)
Lead section above the existing picks. Target read time is under 60 seconds, mobile-first, using the site's colors from style.css.

## Sections and sources (all free, no key)
1. **Overnight** — Yahoo chart API `v8/finance/chart/{sym}?interval=1d&range=10d`, comparing the last bar to the prior bar. Symbols: ES=F, NQ=F, ^TNX, ^VIX, CL=F, DX-Y.NYB, BTC-USD. ^TNX has no pre-market quote, so it shows the prior close and that day's change.
2. **Catalysts** — `api.nasdaq.com/api/calendar/economicevents?date=` (US rows; Fed speakers appear as "Fed X Speaks") and `api.nasdaq.com/api/calendar/earnings?date=`, top ~6 by market cap, split into pre-market and after-hours. Needs a browser User-Agent.
3. **Levels** — SPY daily 1y bars: prior close/high/low, 5-day high/low, and simple 50- and 200-day moving averages of closes.
4. **What it means** — 2–3 sentences in Max's voice, plus a not-financial-advice line. Never give a guarantee or a price target for the index.
5. **Slot** — the existing edition follows.

## Rules
Never invent numbers. Drop any line whose fetch fails. Run before about 7 AM ET.

## Gaps / open questions
- The economic calendar dates look one day late (ISM Manufacturing on Tue, JOLTS on Wed), and its `gmt` field appears to be ET. Cross-check against a second source before going live.
- Earnings timing is sometimes "time-not-supplied", for example TM.
- There are no consensus forecasts for the data releases yet.
- There are no Fed speaker topics.
