# Earnings explainer runbook (add a report in ~30-60 min)

Pages: /earnings/<ticker>-<quarter>/ (e.g. /earnings/amd-q3-2026/), rendered by earnings_explainer.py from data/earnings/<slug>.json.
Index list sits at the top of /earnings/; sitemap entries are automatic.

## Steps
1. Wait for the release (AMD/AMGN/ANET/BKNG ~4:05-4:15 PM ET). Get: press release / IR / 8-K (sec.gov EDGAR), plus 1-2 reputable consensus sources (LSEG via CNBC, Investing.com, StreetInsider, Zacks/Yahoo, Reuters).
2. Copy data/earnings/pfe-q3-2026.json to data/earnings/amd-q3-2026.json and fill:
   - slug, ticker, company, quarter, date (report date), when ("after the close" / "before the open")
   - headline: list of {metric, actual, consensus, result}. result = Beat/Miss/In line/Raised.../"" . Put the consensus source in parentheses. No consensus published -> consensus "n/a", result "". NEVER estimate a number.
   - takeaways: 3-5 plain-English bullets from release + call coverage. Attribute non-release facts to the outlet.
   - verdict_word (short), verdict (Max: funny, honest, 2-3 sentences, no advice).
   - sources: [{title,url}] for every number used.
   - prev_close: the close BEFORE the report (after-close reporter = that day's 4 PM close; before-open = prior day close).
   - reaction: {"kind":"after hours","price":<last>,"asof":"YYYY-MM-DD h:mm PM ET"} as a fallback; the build refreshes it live from Yahoo (pre/post-market included) every rebuild.
3. Validate: `python3 -c "import json;json.load(open('data/earnings/amd-q3-2026.json'))"` and a quick render test:
   `python3 -c "import earnings_explainer as X;print([r['slug'] for r in X.load('.')])"`
4. `git add data/earnings earnings_explainer.py && git commit -m "Earnings explained: AMD Q3 2026" && git push` (don't run build.py locally; it hangs). GitHub Pages deploys in ~3-5 min. Check https://readdailyfive.com/earnings/amd-q3-2026/.
5. Next morning: the 30-min refresh rebuild updates the reaction line automatically; optionally add call takeaways.

## Rules
Real numbers only, cited. No posting outside the site without approval. Never feature Patient AI Trade.
