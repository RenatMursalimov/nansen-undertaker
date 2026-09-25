# Sentinel: spec and roadmap

Live alerts on Variational Omni plus Smart Ignition on Nansen. What is built, on which
measurements, where the limits are, and what comes next.

Date: 2026-09-25. Package: `sentinel/`. Tests: `python3 tests/test_sentinel.py` (154 checks, no
network needed) plus `t_live_watcher_has_its_own_cache_door` in `tests/test_nansen_contest.py`.
Live proof: `python3 nansen/proofs/sentinel_live_proof.py MSTR 4.5`.

---

## 1. The problem in plain words

The owner trades manually on omni.variational.io. The phone should buzz the moment something
material happens to an instrument, and a brief should follow immediately: where smart money is
going on the same asset and what X is saying about it. The human decides whether to enter. The
bot does not trade and does not advise.

Three requirements follow, and they shaped the whole design:

1. **Event-driven, not scheduled.** The alert fires on the event, not on the next digest tick.
2. **Number first, words second.** Price cannot wait for a model.
3. **An honest refusal instead of emptiness.** Every line either carries a number with a named
   source, or names its failure class.

---

## 2. What was measured on the venue (2026-09-25)

| Measurement | Value |
|---|---|
| `GET /metadata/stats` | HTTP 200, 283 KB, **553 instruments in one request**, 53-138 ms |
| Rate limit | 10 requests / 10 s per IP; 1000/min global (documented) |
| Quote age | median 55 s, range 37-93 s (552 of 553 instruments) |
| Venue totals | 24 h volume $3.22B, open interest $1.91B, TVL $242M |
| Per-instrument fields | `ticker, name, mark_price, volume_24h, open_interest{long,short}, funding_rate, funding_interval_s, base_spread_bps, quotes{updated_at, base, size_1k, size_100k, size_1m}` |
| `size_1m` quotes | present on **18** of 553 |
| Missing `quotes`/`base_spread_bps` | 1 instrument (TWIS) |
| Asset class from the provider's own `name` | 72 equities, 20 funds/ETFs, 461 undecidable |

**The 403 was not a Cloudflare fingerprint check, it was an empty User-Agent.** Bare `urllib`
got 403; the same `urllib` with an ordinary UA got 200 in 0.05 s. No proxy and no `curl_cffi`
are needed. This is written into the code, because without that line the next investigation
would head for the fingerprint theory again.

**There is no verified deep link to a single instrument.** `/trade/BTC` and `/markets/BTC`
answer 403; `?market=BTC` answers 200 exactly as the bare root does, so 200 proves nothing (any
query parameter on a single-page app returns 200). Until it is measured, the link does not
exist, and the card points at the root.

**The unit of `funding_rate` is not stated and the provider's own help contradicts the
measurement.** The help page says RWA/TradFi funding is fixed at 0.005 % per 8-hour interval
([source](https://help.variational.io/en/articles/16038203-funding-rates-for-rwa-tradfi-markets)),
while the live response shows MRNA = 0.442690, MSTR = 0.455416, US500 = 0. No hypothesis matches
the measurement. **Consequence in code:** the number is printed under the provider's field name
together with the interval, no annualisation is performed, and funding events are detected by the
instrument's percentile against itself - a criterion that does not depend on the unit at all.
Verification debt #1 (see section 10).

**A negative funding rate on an equity can be a dividend rather than positioning** - the
provider says so directly
([source](https://help.variational.io/en/articles/16038446-dividends-as-funding-payments)).
The card says this itself on equities and deducts 30 confidence points.

---

## 3. What is built

```
sentinel/
  variational_feed.py   one public endpoint -> Listing objects; a failure class, never emptiness
  detector.py           PURE arithmetic: rings -> events. No database, no network, no model
  ignition.py           Smart Ignition on Nansen plus on-chain confirmation
  store.py              12 tables: ring, events, subscriptions, deliveries, outcomes, lease, spend
  cards.py              event -> text. Deterministic, no model and no network
  outbox.py             queue in the database, one Telegram door, "delivered" only on confirmation
  enrichment.py         second message: Nansen + X + summary (delivered events only)
  engine.py             ticks: ingest / ignition / deliver / brief / outcome / prune
  ui.py                 direct-message commands; parsing is separated from action
  main.py               separate process: same domain, own loop, own lease
  config.py             every threshold, read from the environment on every tick
```

### Five event kinds

| Kind | What it catches | Default threshold |
|---|---|---|
| `move_up` / `move_down` | price moved **and moved unusually for itself** | 3 % in 15 min **and** >=2.5 sigma; or 6 % in 60 min |
| `oi_surge` | open interest jumped (money entering even if price is flat) | +/-20 % in an hour |
| `funding_extreme` | rate in its own tail (>=98th percentile over the ring) | >=50 samples in the ring |
| `spread_shock` | quote widened - a **warning**, not a signal | x3 its own median |
| `ignition` | **several DISTINCT** smart-money addresses bought one token | >=3 addresses, >=$150k, >=5 bps of market cap, 180 min window |

**A percentage without sigma is spam; sigma without a percentage is noise.** 3 % on MSTR and
3 % on an illiquid alt are events of different rarity, so one shared percentage would either
bury the human in alts or miss the equity. Sigma is computed from our own snapshots of the same
instrument, so no per-instrument threshold table exists.

**Distinct addresses are counted, not trades.** Ten trades from one address are one person
slicing an entry. The test `IGN: three trades from ONE address is not ignition` holds the rule.

### Two rings, and this is the key decision

The naive "write every poll to the database" does not work arithmetically: 15 s x 7 days x 553
instruments = **22 million rows**. Therefore:

* **hot ring** - in memory, one point per 60 s, 90 minutes deep -> 15- and 60-minute returns;
* **cold ring** - in the database, one point per 15 minutes, 7 days (~371k rows) -> sigma,
  funding percentile, spread median, outcome measurement.

The detector knows this by construction: it takes `rows` (hot - to measure the move) and `ring`
(cold - to measure how unusual it is) as two arguments. A single ring for both questions would
give either a wrong sigma or an unaffordable database. The price of the in-memory hot ring is
stated out loud: after a restart it is empty, and moves are not published until it refills.

### Confidence: from one hundred downwards, with named reasons

Not "low confidence" but "67, because the quote is older than two minutes and $100k depth is
thin". Penalties travel into the card in full: the human decides whether that particular reason
matters. Adding points "for good things" is forbidden - such a score cannot be argued with,
because it never says what is missing from it.

Penalties: quote older than 120 s (-20), quote age not stated (-15), no $100k quote (-10),
$100k entry costs more than 50 bps (-15), fields missing from the provider (-10), sigma on a
small sample (-25), sigma measured as zero (-25), move inside the usual spread (-20), 24 h
turnover below $500k (-10), market cap unknown (-25), token younger than 2 days (-20), addresses
carry no labels (-10), last trade older than 30 min (-15), negative funding on an equity (-30).

### Two deliveries per event

1. **The card** - deterministic, sent immediately. Magnitude in the first two lines, then
   market, quote and depth, confidence with reasons, a "what this alert did NOT check" list,
   and the source.
2. **The brief** - a separate message: the same asset's on-chain contract (resolved **by price**
   through `oc_passport.canonical_contract`, not by ticker similarity), who bought and sold over
   24 h, what X wrote in the last 90 minutes, a model summary labelled "a retelling of the data
   above", and a cost line.

The brief is not appended by editing the first message: an edit is invisible, the phone does not
buzz twice. Waiting for the brief inside the first message is also wrong: those are exactly the
seconds the human wanted to save.

---

## 4. A live card (2026-09-25 run, MSTR, +4.5 % shift)

```
Move up - MSTR (Strategy Inc)
+4.50% in 15m
That is 28.7 sigma of its own 15-minute volatility (sigma=0.16%, 59 points)

Mark price: 169.9467
24h volume: $1.84M
Open interest: 1.074e+06 contracts, 27% long
Funding (provider field funding_rate): 0.47438, interval 8h
Base spread: 6.0 bps
$100k entry: 11.1 bps from mid
Quote updated: 40s ago

Confidence: 100/100 (no penalties)

What this alert did NOT check:
- the fundamental reason for the move - the sentinel does not read news
- where the underlying went on spot - check whether this is a move or a quote
- your own risk: size, leverage, distance to liquidation

Source: Variational Omni, public /metadata/stats endpoint - https://omni.variational.io/
```

The whole path took 0.06 s and burned 0 Nansen credits. (The card ships in Russian; this is a
translation of the same run - the bot speaks the owner's language.)

---

## 5. Commands and menu

**Buttons are the main path.** The sentinel screen opens from **two** menus, which is the owner's
request verbatim ("through Nansen, and in parallel through On-chain"): *On-chain -> Alerts ->
Sentinel* and *Nansen -> What smart money is doing -> Sentinel*. Both lead to ONE screen
(`sen:*` in `sentinel/ui.py`); there is no second copy, because two copies diverge on the first
edit. The screen carries toggles for alerts, briefs and whole-venue watching, plus minus/plus
controls for the **personal** move threshold, cooldown and daily cap, a quiet-hours ladder, the
hit-rate report and help. Toggle captions state the CURRENT STATE ("Alerts: on"), not the
action - "Turn alerts off" does not answer the question "how is it now".

**Only personal settings are on buttons.** The shared thresholds (3 % / 2.5 sigma / ignition) are
the same for every subscriber, so a "+1 %" button under one person would silently change everyone
else's behaviour. They are shown on the screen as a line (so you can see what the sentinel runs
on) and edited in `.env`.

**Words are the fast path,** and English forms work through the `en_triggers` registry (English is
data in this project, not a second branch of logic): `sentinel BTC`, `watch all`,
`sentinel remove ETH`, `sentinel threshold 5`, `sentinel quiet 22 8`, `sentinel off` /
`sentinel on`, `sentinel briefs off`, `sentinel report`. The `sentinel off` rule sits BEFORE the
general `sentinel <ticker>` on purpose: without it the most likely phrasing subscribed the person
to a non-existent instrument called "OFF" - they asked for silence and got a complaint about a
ticker.

Words and buttons share ONE parser: had they diverged, half the commands would have quietly
stopped working. Matching is exact and anchored at the head of the message, so the word inside a
sentence routes onwards as usual.

---

## 6. Money and noise

| Limiter | Value | Why |
|---|---|---|
| Venue polling | 15 s | limit is 10/10 s; three polls 3 s apart returned identical numbers, so below ~10 s there is no new data |
| Ignition (Nansen) | 3 min | it costs credits; the feed is trailing and does not refresh instantly |
| Sentinel daily cap | **off** (0) | the owner's decision: Nansen is free for the hackathon. The mechanism stays - put a number in `.env` and it limits again. Spend is always measured and shown on the screen |
| Cooldown per (instrument, kind, step) | 60 min | the step is in the event key: "the move doubled" is separate news |
| Daily cap per person | 25 alerts | hitting it is printed as a quantity: "cap 24/25" |
| Quiet hours | optional | window across midnight |
| Own cache for live feeds | 20 s under a SEPARATE key | the shared 30-minute cache would turn "now" into "every half hour", and shortening it for everyone would make the digest pay for someone else's freshness |

Sentinel spend is a separate line in the daily telemetry: scenes `sentinel_watch` and
`sentinel_ignition`, surface `sentinel` (separate from `cron` - a scheduled job spends
predictably, the sentinel spends three times more on a volatile day).

---

## 7. Outcome measurement: how we learn whether it works

An alerting system without outcome measurement is an opinion generator: it cannot tell "works"
from "noisy", and the first person to notice would be the one who lost money.

Once an hour the sentinel takes events older than each horizon (60 min and 24 h), reads the
price at that moment from the cold ring, and writes a row into `sentinel_outcome`. The report
command computes, from those rows, the share of moves that continued and the median follow-on
move. **Fewer than 20 measurements in a bucket prints "sample too small" and no percentage.**
"80 % hit rate" on five events is four out of five, that is, nothing at all - and yet decisions
get made on such a number.

---

## 8. Deployment

**Sandbox first, production after** (the owner's rule). Today the sentinel runs as bot jobs
(`sentinel_tick` 15 s, `sentinel_ignition` 3 min, `sentinel_brief` 1 min, `sentinel_outcome`
hourly at :13). That is a deliberate first step: the module and the control panel must work
before the move, otherwise the "separate process" would have to be debugged together with new
logic.

Acceptance on the sandbox: pull, run `tests/test_sentinel.py` (expect 154 PASS / 0 FAIL), run
the live proof, restart the test service, check it is `active`, then grep `[sentinel]` in
`bot.log` and use the commands in the test bot's direct messages. Production repeats the same
steps only after the sandbox run is green.

A systemd unit for the separate process is included in the Russian twin of this document. Before
enabling it, the two polling jobs are disabled in the bot; if both happen to be alive,
`store.lease` hands polling to exactly one and the other prints who holds the lease. The domain
does not change on the move: both paths call `engine.*`.

---

## 9. Round two: what live production found (2026-09-25)

The sentinel went to production and produced three defects that no green test could see. Each is
a separate class, so all three are written down in full.

**1. `SELECT DISTINCT … ORDER BY d.delivered_at` - briefs did not work at all.** PostgreSQL
answers "for SELECT DISTINCT, ORDER BY expressions must appear in select list", and the brief job
failed EVERY MINUTE - dozens of identical lines in the log. On sqlite (sandbox, tests) the same
query passes, so 104 green checks guaranteed nothing. Fixed with `GROUP BY d.event_key` and
`MAX(d.delivered_at)`. Guarded by a test that parses the module's queries through `ast` (Python
folds implicit string concatenation itself, so each query is exactly one literal) and fails on any
`DISTINCT` ordered by a column outside the select list. The project's rule held: a PG-specific
failure cannot be dismissed as "test only" - the test is precisely the thing that is green.

**2. `database is locked` - 14 test failures on the server.** Not an environment issue:
`conn.execute('SELECT …').fetchone()` reads one row and abandons the cursor UNFINISHED, and an
unfinished cursor holds a read transaction. In sqlite that blocks writes; in PostgreSQL it leaves
the connection "idle in transaction" - worse on production, not better. Nine functions did this,
each leaving its own lock. Fixed with two shared read doors, `_one` and `_all`, which close the
cursor in `finally`. A cleanup you must remember twenty-two times will be forgotten the
twenty-third, so the fix goes in the bottleneck rather than at every call site. Guarded by a test
that performs six reads and then REQUIRES the next write to succeed.

**3. A zero cap meant "no money" instead of "no ceiling".** The owner: "everything Nansen-related
is free for the hackathon; switch the cap on later." The default became zero - and at zero
`budget_left()` returned zero remaining, so a disabled limiter looked like a triggered one: the
sentinel would quietly stop calling Nansen while the log claimed "budget exhausted" at zero
spend. Fixed: `store.budget_block()` answers with a REASON rather than yes/no, zero blocks
nothing, `budget_left()` returns `None` when the cap is off (a full answer: "no ceiling"), and
spend is always measured and printed as "N credits spent, cap off" - not "N of 0", because the
second reads as exactly the opposite.

One more: the test now STOPS if the database path is not inside a temporary directory. It gets run
on the server next to the live service, and a test that could write to the production database is
more dangerous than no test at all.

## 10. Limits, debts and refuted hypotheses

**The boundary with the trading contour is hard.** No file in `sentinel/` imports
`nansen_signer` or calls quote/prepare/execute. The `ISOLATION` test holds it (import graph plus
a call search). Entering a position happens by hand on the venue.

**Verification debts:**

1. **The unit of `funding_rate`** - not stated by the provider, and the help page contradicts
   the measurement. Until measured, there is no absolute funding threshold (percentile only).
2. **A deep link to a single instrument** - not measured (403 on paths, and 200 on a query
   parameter proves nothing).
3. **Asset class for 461 of 553 instruments** - not derivable from the name. Metals, oil and
   indices sit in `unknown`.
4. **The hot ring does not survive a restart** - for 90 minutes after a deploy, moves on the
   15-minute window are not published.

**Refuted hypotheses, written down so they do not come back:**

* "The 403 from Variational is Cloudflare cutting the TLS fingerprint; we need curl_cffi or a
  proxy." **Wrong:** a non-empty User-Agent is enough (measured: 200 in 0.05 s).
* "A distribution tail can be detected as the share of values <= x." **Wrong:** on a constant
  series that equals 1.0, so "rate in the upper tail" would print on every tick for an
  instrument whose rate never changed. A test caught it; strict comparisons fixed it.
* "Sigma measured as zero means infinite unusualness." **Wrong and dangerous:** zero sigma more
  often means the provider repeated the same number. The first draft went silent because of it -
  a 4 % move in 15 minutes was not published at all.

---

## 11. Roadmap, ordered by value over cost

**Step 1 - finish the sentinel (1-2 days).** Sandbox acceptance, then production. The separate
`sentinel.main` unit plus lease (code is ready; only the unit file and the owner's decision are
missing). Flush the hot ring on shutdown, closing debt #4. Buttons under the card ("Nansen on
this asset", "Chart", "Mute for an hour") that reuse screens the bot already has and add no new
provider calls.

**Step 2 - signals whose data we already hold (2-4 days).**
1. **Spot versus perp divergence.** The venue's mark price against the same asset's spot price
   (already read elsewhere in the bot). A gap of N bps at live turnover is either an opportunity
   or a warning about quote quality.
2. **Crowded squeeze.** `oi_skew` >= 0.9 with an extreme funding rate and a widening spread - the
   shape people get carried out of. Computed from a single venue response.
3. **Absorption.** Price flat, open interest rising, spread not widening - somebody is
   accumulating against the flow. Stronger than a "move", because it is visible *before* it.
4. **Cross-asset relay.** BTC moves N % -> check MSTR, COIN, HOOD on the venue (all three are
   listed) and say which has not reacted yet. Measured links only, no "similar" assets.

**Step 3 - where a new source or a new check is needed (4-8 days).**
5. **Holder quality as a regime.** `smart-money/historical-holdings` (beta, daily snapshots,
   ~4-year window) is not in our 59-route inventory. It answers "the holder base changed", not
   "the price moved". Needs a live schema probe, its own telemetry scene and its own cap.
6. **Coordinated wallet clusters.** `profiler/related-wallets` plus `counterparties` around an
   ignition: three addresses that bought the same thing may be one person. This is a
   **confidence penalty**, not a new event - which makes it more valuable than a new event.
7. **Informed move on Polymarket.** Our reputation screens already measure who was right before.
   The event: the market moved and it was those wallets. Crossing it with the sentinel by asset
   gives a prediction-market-to-perp link.
8. **Backtest lab on historical holdings.** Validate ignition thresholds against the past rather
   than against taste. Needs a careful cap: years of daily snapshots cost credits.

**Step 4 - owner decisions, not agent decisions.** Tokenised equities (the `robinhood` chain is
in Nansen's supported list) must map ticker to token only through a verified mapping; deriving it
from ticker equality would repeat the mistake that already cost three screens. The ninth refusal
class and the repository About text are the owner's calls: the number eight is written into the
README, the About text and the tests, and the About text itself returns 403 for the agent's
token.

---

## 12. Reconciliation with the scouting report

Nine requested items. Fully delivered here: the alert engine stages 0-2 (dedupe by
`transaction_hash`, a Nansen daily cap, per-token cooldown, one outcome row per alert), the
venue poller and move detector with a 7-day ring, quote-age checks and thresholds in config, the
brief builder where every line is a number with a source or a named failure class, the weekly
hit-rate report with a 20-alert minimum, and trading-contour isolation with an import-graph
test. Deliberately changed: polling is 15 s rather than 60 s, because the venue's limit is
10/10 s, one request returns the whole market, and 60 s is late for a squeeze.

Not in this round and carried into the roadmap: the four scenario ideas (step 2 above), the
mini-app README section, and the scenario and thread document edits before submission. One item
turned out to be stale against our HEAD: the counter claim. Our catalog is generated from code
and reports 34 scenarios and 59 routes, `tools/nansen_catalog.py --check` passes, and the public
README contains no Cyrillic at all. What remains is the repository About text, which only the
owner can edit.
