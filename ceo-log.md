# CEO log: The Daily Five

## 2026-10-15 · ~1:10 PM ET check-in

**Shipped**
- "Today so far" strip on the homepage and Scoreboard: open picks up/down, avg since pick, avg today, best/worst. Updates every minute in the browser. At 1:10 PM ET: 5 up / 3 down of 11 open, avg since pick -0.42%, avg today +0.63%, best Brewers NO +1.90%, worst CRWV -7.08%.
- Stale-price warning in live.js when live.json is >25 min old in market hours (>50 min off-hours), so readers know when CI is behind.
- Refreshed prices (build at 1:10 PM ET) and pushed a manual rebuild.

**CI finding**
- `pages.yml` was valid and the workflow active, but zero `schedule` runs ever fired between when the crons were added (11:10 AM ET) and 1:10 PM ET. All 10 runs were `push`. Likely cause: GitHub's best-effort scheduler (new repo, plus dense `*/10` and `*/15` crons on round minutes, which GitHub routinely delays or drops at peak load).
- Fix: crons moved to off-round minutes, market hours every 15 min (:07/:22/:37/:52, 13-21 UTC weekdays), every 30 min otherwise (:12/:42). workflow_dispatch kept. If schedules still don't fire by tomorrow's open, fallback options (need user OK): a free external pinger that calls workflow_dispatch (needs an account), or a cron job on the box that runs `gh workflow run`.

**Growth ideas (not yet done; nothing promoted externally)**
1. Google Search Console + Bing Webmaster: verify readdailyfive.com and submit sitemap.xml (free, but needs the user's Google account, so ask first). Ticker, pick, track-record and how-we-rank pages are already in the sitemap.
2. Fill `consensus` and `book` fields in each edition with more real sources, so Daily Five Scores move off neutral 12.5 and the ranking means more.
3. Kit welcome sequence (3 emails: how we rank, how to read the Scoreboard, yesterday's results), plus a 4:15 PM ET "closing bell" recap email that drives return visits. Ask the user before turning on any automation that sends.
4. @ReadDailyFive cadence: 7 AM edition card (OG image), a midday "Today so far" post, a 4:15 PM scorecard. Confirm cadence with the user before posting at volume.
5. Evergreen SEO pages: "/best-stocks-to-buy-today/" and per-horizon hubs (1 Day / 1 Month / 1 Year) that pull from the track record, plus FAQ schema on how-we-rank.
