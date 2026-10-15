# 2026-10-15 redesign
- Removed all Patient AI Trade content; editions are now JSON (see FORMAT.md).
- Finance: 6 action cards (2 each 1 Day / 1 Month / 1 Year) with green BUY / red SELL badges and entry prices from Yahoo Finance (~10:56 AM ET).
- Sports: 5 Polymarket action cards with entry odds from the Polymarket Gamma API.
- AI: numbered purple news cards (headline, why it matters, source).
- Scoreboard "If you traded it immediately": live mark-to-market from Yahoo/Polymarket, P/L, win/loss, per-horizon win rate + avg return; final exits frozen in data/exits.json.
- New mobile-first dark design: sticky nav, gradient hero, section color accents, signup block, disclaimer bar + footer.

# 2026-10-15 ~1 PM ET CEO check-in
- New "Today so far" running P/L strip on the homepage (under the live stamp) and the Scoreboard hero: open picks up/down, avg return since pick, avg move today, best and worst pick. live.js recomputes it every minute from live.json + Polymarket.
- live.js shows "⚠ stock prices from <time> · stale, refreshing soon" next to the timestamp when live.json is older than 25 min (market hours) / 50 min (off-hours).
- live.json now carries a timezone-aware `updated`, an epoch `ts`, and each pick's `label`.
- Actions schedule rewritten to off-round minutes (:07/:22/:37/:52 market hours, :12/:42 otherwise); scheduled runs had never fired.
