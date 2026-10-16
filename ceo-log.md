# CEO log: The Daily Five

## 2026-10-15 · ~1:10 PM ET check-in

**Shipped**
- "Today so far" strip on the homepage and Scoreboard: open picks up/down, avg since pick, avg today, best/worst. Updates every minute in the browser. At 1:10 PM ET: 5 up / 3 down of 11 open, avg since pick -0.42%, avg today +0.63%, best Brewers NO +1.90%, worst CRWV -7.08%.
- Stale-price warning in live.js when live.json is >25 min old in market hours (>50 min off-hours), so readers know when CI is behind.
- Refreshed prices (build at 1:10 PM ET) and pushed a manual rebuild.

**CI finding**
- `pages.yml` was valid and the workflow active, but zero `schedule` runs ever fired between when the crons were added (11:10 AM ET) and 1:10 PM ET. All 10 runs were `push`. Likely cause: GitHub's best-effort scheduler (new repo, plus dense `*/10` and `*/15` crons on round minutes, which GitHub routinely delays or drops at peak load).
- Fix: crons moved to off-round minutes, market hours every 15 min (:07/:22/:37/:52, 13-21 UTC weekdays), every 30 min otherwise (:12/:42). workflow_dispatch kept. If schedules still don't fire by tomorrow's open, fallback options (need user OK): a free external pinger that calls workflow_dispatch (needs an account), or a cron job on the box that runs `gh workflow run`.
- Still no `schedule` run at the 1:22 and 1:37 PM ET slots after the fix (new crons may take a while to register). Stopgap from 1:39 PM ET: `/workspace/bin/d5-dispatch.sh` on the box runs `gh workflow run pages.yml` every 15 min in market hours and every 30 min otherwise. It skips when a run is already active and exits on its own once GitHub fires any `schedule` run. Log: `/workspace/daily-top5-dispatch.log`. Stop it with `pkill -f d5-dispatch.sh`. It won't survive a box restart.

**Growth ideas (not yet done; nothing promoted externally)**
1. Google Search Console + Bing Webmaster: verify readdailyfive.com and submit sitemap.xml (free, but needs the user's Google account, so ask first). Ticker, pick, track-record and how-we-rank pages are already in the sitemap.
2. Fill `consensus` and `book` fields in each edition with more real sources, so Daily Five Scores move off neutral 12.5 and the ranking means more.
3. Kit welcome sequence (3 emails: how we rank, how to read the Scoreboard, yesterday's results), plus a 4:15 PM ET "closing bell" recap email that drives return visits. Ask the user before turning on any automation that sends.
4. @ReadDailyFive cadence: 7 AM edition card (OG image), a midday "Today so far" post, a 4:15 PM scorecard. Confirm cadence with the user before posting at volume.
5. Evergreen SEO pages: "/best-stocks-to-buy-today/" and per-horizon hubs (1 Day / 1 Month / 1 Year) that pull from the track record, plus FAQ schema on how-we-rank.

## 2026-10-15 · ~4:05 PM ET check-in

**Shipped**
- Closing-bell mode for the "Today so far" strip (homepage + Scoreboard). After 4 PM ET on weekdays it turns amber and reads "🔔 Closing bell · stocks closed for the day · sports still live". It shows "Pre-market" before 9:30 AM and "Weekend" on Sat/Sun. It also has a live countdown to the next 7 AM ET edition (in the strip and the recap box) and a "settled" chip for picks that closed today. Goal: give readers a reason to come back at 7 AM.
- Price refresh at 4:03 PM ET (Yahoo + Polymarket). Stocks: AMAT +0.96%, KLAC +1.29%, AVGO +0.99%, MRVL +2.51% since pick. SELL QQQ -0.74% and SELL CRWV -12.45% (CRWV +14.2% on the day). Sports: Guardians won ALCS G3 and settled at 100¢, **+86.92% final** (first closed pick). Brewers NO WS -0.36%. Dodgers, Seahawks and Brewers NLCS are flat ahead of tonight's games. Strip: 4 up / 4 down of 10 open, avg since pick -0.79%, avg today +1.74%.

**Fixed**
- Resolved sports picks showed as "pending". Polymarket's Gamma API leaves closed markets out of `?slug=` results, so after the Guardians game resolved its card had no price. `build.py` now retries with `&closed=true` and settles a pick only when the price is ≥0.99 or ≤0.01 (it's frozen in `data/exits.json`).
- Dispatch stopgap went quiet from 2:56 to 4:05 PM ET: no dispatches, nothing logged, process still alive (likely the box was paused mid-`sleep 900`). Rewrote `/workspace/bin/d5-dispatch.sh` (v2) to check the wall clock every 60 s, log failures, and time out gh calls after 60 s. Restarted at 4:06 PM ET.

**CI finding**
- Still zero GitHub `schedule` runs; every run since 1:39 PM ET was `workflow_dispatch` from the stopgap (all succeeded). The stopgap still won't survive a box restart. Proposal for the user: allow a free external cron pinger, or accept the box stopgap as the long-term trigger.

**Growth ideas still pending**
1. Google Search Console + Bing Webmaster: verify the domain and submit sitemap.xml (needs the user's Google account).
2. `book` lines for Seahawks (TNF) and Brewers WS, so their Edge scores leave neutral (only from real published sportsbook lines).
3. Kit welcome sequence + 4:15 PM ET closing-bell recap email (needs the user's OK before anything sends).
4. @ReadDailyFive cadence: 7 AM card, midday strip, and a 4:15 PM scorecard ("Guardians +86.9% final" makes a good first scorecard post).
5. Evergreen SEO: FAQ schema on /how-we-rank/ and per-horizon hub pages.

## 2026-10-15 · ~7:10 PM ET check-in

**Shipped**
- FAQ schema + visible FAQ on `/how-we-rank/`: Article + FAQPage via `@graph` (6 Q&As matching the methodology copy — score components, credibility, consensus, edge, price updates, not-advice disclaimer). Accordion FAQ section styled to match the bold card UI.
- Evening price refresh (build ~7:09 PM ET). Stocks after close unchanged vs 4 PM: AMAT +0.96%, KLAC +1.29%, AVGO +0.99%, MRVL +2.51%, SELL QQQ −0.74%, SELL CRWV −12.45%. Sports ahead of ~8 PM tips: Dodgers NLCS G4 58.5¢ flat, Seahawks TNF 56.5¢ flat, Brewers NO WS +0.71%, Brewers YES NLCS −0.06%. Guardians still **+86.92% final**. Strip: 5 up / 3 down of 10 open, avg since pick −0.68%, avg today +1.85%.

**CI / schedule**
- One GitHub `schedule` run fired at 4:25 PM ET (20:25 UTC); none since (no :12/:42 off-hours runs at 6:12 or 6:42 PM ET). Box stopgap `d5-dispatch` already exited after detecting that schedule (log: 5:58 PM ET). Did **not** restart the stopgap; kicked `workflow_dispatch` after this push so tonight's sports odds go live.

**Growth ideas still pending**
1. Google Search Console + Bing Webmaster: verify the domain and submit sitemap.xml (needs the user's Google account).
2. `book` lines for Seahawks (TNF) and Brewers WS, so their Edge scores leave neutral (only from real published sportsbook lines).
3. Kit welcome sequence + 4:15 PM ET closing-bell recap email (needs the user's OK before anything sends).
4. @ReadDailyFive cadence: 7 AM card, midday strip, and a 4:15 PM scorecard ("Guardians +86.9% final" makes a good first scorecard post).
5. Evergreen SEO hubs: `/best-stocks-to-buy-today/` and per-horizon pages (1 Day / 1 Month / 1 Year). FAQ schema on `/how-we-rank/` is done.

## 2026-10-16 · ~10:10 AM ET check-in

**Shipped**
- Evergreen SEO hub: `/best-stocks-to-buy-today/` — pulls real finance BUY picks from editions, ranks today's BUYs by Daily Five Score, shows live entry/P/L, horizon track-record lists (1 Day / 1 Month / 1 Year), FAQ + CollectionPage schema, sitemap + footer link. Bold card UI matching the site. Honest disclaimer; no invented prices.
- Price refresh (~10:05 AM ET local build / 10:03 AM ET live after workflow_dispatch). Strip: **5 up / 3 down of 11 open**, avg since pick **−0.05%**, avg today **−0.09%**, best **CROX +1.63%**, worst **LRCX −2.21%** (SMTC also −2.21%). Stocks: SMTC −2.21%, MBLY +0.47%, LRCX −2.21%, CROX +1.63%; SELL QQQ +0.92% (short), SELL META +1.33% (short). Sports: Guardians YES ALCS −1.80%, Brewers YES WS +1.32%, Chiefs/Packers/G4 flat. Prior settled (Oct 15): Guardians **+86.92% final**, Brewers YES NLCS **+10.68% final**, Dodgers/Seahawks **−100% final**. No new sports resolutions this morning (ALCS G4 is tonight).

**CI / schedule**
- Market-hours GitHub `schedule` slots (9:07 / 9:22 AM ET) still missing after overnight :12/:42 runs. Last schedule was 5:42 AM ET (09:42 UTC). Kicked `workflow_dispatch` for the morning price refresh (succeeded). Restarted box stopgap `/workspace/bin/d5-dispatch.sh` **v3**: only exits when a schedule succeeded in the last 40 minutes (overnight schedules no longer permanently kill it). Log: `/workspace/daily-top5-dispatch.log`.

**Growth ideas still pending**
1. Google Search Console + Bing Webmaster: verify readdailyfive.com and submit sitemap.xml (needs the user's Google account).
2. Kit welcome sequence + 4:15 PM ET closing-bell recap email (needs OK before any sends).
3. @ReadDailyFive cadence confirm before volume (7 AM card, midday strip, 4:15 PM scorecard).
4. Fill real `book` sportsbook lines into sports picks so Edge scores leave neutral (only published lines with name/url/odds).
5. Per-horizon SEO hubs: `/best-1-day-stock-picks/` · `/best-1-month-stock-picks/` · `/best-1-year-stock-picks/` (follow-on to today's evergreen hub).

## 2026-10-16 · ~1:10 PM ET check-in

**Shipped**
- New evergreen SEO hub `/polymarket-picks-today/` (live at https://readdailyfive.com/polymarket-picks-today/, push c50e08b, deploy succeeded 1:09 PM ET). Today's sports plays ranked by Daily Five Score with live Polymarket cards, tiles for settled win rate (2/4, 50%), avg settled return (−25.60%), open-markets avg, a graded list of every Polymarket pick (Won/Lost/Open), FAQ + CollectionPage schema, sitemap + footer link, and a "Every Polymarket pick, graded →" link from the homepage sports section. Aimed at "polymarket picks today" search intent and at the Polymarket crowd we're following on X. Checked desktop + mobile renders (`shots/pm-hub*.png`).
- Price refresh (1:08 PM ET live build). Today's edition: 3 up / 6 down / 2 flat. SELL META +3.11%, SELL QQQ +2.06%, Brewers YES WS +0.93%; MBLY −3.97%, SMTC −3.91%, LRCX −3.72%, Packers −1.90%, Guardians YES ALCS −1.80%, CROX −1.03%; Chiefs and Guardians G4 flat (G4 is tonight). Oct 15 holdovers: Brewers NO WS −16.98%, chips (AMAT/AVGO/KLAC/MRVL) −1.6% to −2.4%, SELL QQQ +1.33%, SELL CRWV +0.72% (1 Day picks exit at today's close per FORMAT.md).

**Fixed / CI**
- No broken pages found. GitHub `schedule` went quiet again after 10:46 AM ET (no runs for ~2h20m in market hours). Restarted box stopgap `/workspace/bin/d5-dispatch.sh` v3 at 1:10 PM ET.

**Growth ideas still pending**
1. Google Search Console + Bing Webmaster: verify readdailyfive.com and submit sitemap.xml (needs the user's Google account). Now 2 evergreen hubs that would benefit.
2. Kit welcome sequence + 4:15 PM ET closing-bell recap email (needs OK before any sends).
3. Use the new Polymarket hub as the link target in X replies to Polymarket posters (more relevant than the homepage).
4. Real `book` sportsbook lines on sports picks so Edge scores leave neutral.
5. Per-horizon stock hubs once there's ~1 week of picks (too thin today).
