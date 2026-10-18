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

# 2026-10-18 ~10 AM ET CEO check-in
- Sports picks on real games now settle on the final score: once Polymarket's events API says the game ended with a decisive score, the pick shows 100¢/0¢, +P/L final, Won/Lost on the Scoreboard, track record and hubs (note "final score, awaiting resolution"), instead of waiting hours for UMA resolution. Provisional, not written to exits.json. live.js settles the card in the browser the moment its game line flips to FINAL.

# 2026-10-18 ~1 PM ET CEO check-in
- Pick pages get a "Since our pick" section: a full-width line-movement chart (real Polymarket CLOB / Yahoo history from the 7 AM publish time, dashed amber entry line, labeled now/final dot, time axis), a factual summary sentence (entry price and implied chance, current price, move in cents or %, range since the pick, won/lost on finals), the data source and update time, and two FAQ answers ("Who will win X vs. Y?", "What are the X vs. Y odds now?"; stocks: "Is <Company> (<SYM>) stock a buy?", "How has the <SYM> call done?"). The FAQs are also emitted as FAQPage JSON-LD alongside the Article schema (@graph), so each pick page has unique, matchup-specific copy for "X vs Y prediction / odds" searches.
