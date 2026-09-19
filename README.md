# Nansen Undertaker — an honesty layer on top of the Nansen API

Built for the **Nansen Meridian Buildathon**.

This is not another dashboard. It is the part of a live Telegram trading bot that answers one
uncomfortable question about market-data tooling:

> When the screen says nothing, is that because nothing happened — or because we failed to ask?

Most tools collapse those two into one blank panel. This layer refuses to. Every screen reports
**which of seven states** it is in, **what it cost in credits**, and **how fresh the data is** —
and it is built so that a silent failure becomes a loud one.

**50 Nansen endpoints** · **19 ready-made screens** · **20 named scenes with per-scene credit
accounting** · **runs without an API key** (honestly telling you so)

```bash
git clone https://github.com/RenatMursalimov/nansen-undertaker && cd nansen-undertaker
pip install httpx
export NANSEN_LANG=en            # refusals and 11 of 19 screens render in English
python3 tests/test_public.py     # green with no key and no network
python3 cli.py --help
```

---

## 1. Three minutes, no API key

The test suite substitutes exactly one thing — `httpx.post`, the process boundary. Response
parsing, failure classification, formatters, source attribution, telemetry and the contribution
ledger are all the real production code. Substituting `_post` or `record()` would mean the suite
tests itself.

```
$ python3 tests/test_public.py
· t_seven_refusals_are_seven_texts
· t_empty_is_not_error_and_error_is_not_empty
· t_one_call_one_row_and_cache_is_free
· t_scene_registry_is_closed
· t_422_is_repaired_by_the_providers_own_words
· t_money_field_is_found_or_named
· t_source_is_named
· t_ledger_counts_people_not_spam
· t_cli_without_key_says_why
· t_docs_are_here_and_name_prices
```

Then run any command without a key. It will not crash and it will not print an empty table:

```
$ NANSEN_LANG=en python3 cli.py perps BTC
🔌 Nansen: the API key is not set, so we never asked for leveraged positions on BTC.
   This is our configuration, not a verdict.

— this run: 0 call(s), ≈0 credits
```

Compare with what the same command says when the key works and the token genuinely has no open
positions:

```
🔍 Nansen answered, but has no leveraged positions on BTC. This does NOT mean "clean":
   a missing label is a missing label, not safety.
```

Those two sentences are the product. See §3.

## 2. With a key

```bash
export NANSEN_API_KEY=...            # https://app.nansen.ai -> API
python3 cli.py doctor                # what's configured, how many credits are left
python3 cli.py flows 24h             # smart money net inflow, 24h window
python3 cli.py perps BTC             # leveraged positions: size, leverage, LIQUIDATION price
python3 cli.py who base 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 7
python3 cli.py pm                    # trending Polymarket markets, with copyable market_id
python3 cli.py png-flows base 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
python3 cli.py cost                  # today's credit spend, broken down by scene
```

Every screen prints its own price:

```
— this run: 1 call, ≈5 credits · 70,431 left
```

The CLI contains **no formatters of its own**. Each command is three lines: call the client, hand
the rows to the existing block formatter, print. A prettier private rendering here would mean a
second version of the same data, diverging from the bot on the first edit.

## 3. What makes this different from a dashboard

### 3.1 Seven states, seven sentences

The original bug: the client returned `None` on any non-200, the row list came back empty, and
*out of credits*, *rate limited*, *timeout*, *our own malformed request* and *genuinely no data*
became indistinguishable. The user read one "nothing found" for all five.

On wallet labels that is actively dangerous: **"no labels" reads as "clean address."**

| state | what the user is told |
|---|---|
| `nokey` | the request never went out, this is our side |
| `nocredits` | credits ran out — waiting will not help |
| `ratelimit` | we were throttled, retry shortly |
| `timeout` | we asked and got no answer in time |
| `badreq` | **our** request was rejected (422) — provider is fine, we are not |
| `http` | the provider errored |
| `empty` | we asked correctly and there is genuinely nothing |

`badreq` is deliberately worded as our fault. A 422 is addressed *to us*, and calling it
"Nansen returned an error" points the reader away from the only place it can be fixed.

### 3.2 A closed registry of scenes, and credits counted per scene

Credits are spent per API call, but they are *earned* per human question. `tgm/indicators` tells
you nothing about why the month's budget went; "token breakdown" does. So every call site tags
itself with a **scene** from a closed list of 20, and the daily rollup is by scene.

Closed matters. A list you can silently append to stops being a list: three screens once shipped
without registering their names, and every one of their calls landed in the daily summary as
`? 5 credits` — spend visible, owner unknown. An AST scanner in the private repo now walks every
`scene(...)` call site and fails the build in **both** directions: no unregistered scene, and no
dead name in the registry either.

### 3.3 Unknown prices are zero, and counted separately

Where the official price list does not name a price, the estimate is **0** and the call goes into
a separate line: *"184 calls with unknown price."* That is more useful than a tidy total built
from guesses, and it converts into a real number the moment the provider publishes one — the same
log gets recomputed, nothing is re-collected.

Two prices in this layer were wrong for a year because they came from docstrings rather than the
price list: `agent/expert` is **750**, not 200 (3.75× off, on the most expensive path, reachable
by accident from a user's phrasing), and `tgm/indicators` is **5**, not 25.

### 3.4 A 422 is repaired using the provider's own words

Several request bodies here were written by analogy with neighbouring endpoints — never verified
against a live key. When one is wrong, Nansen says what is wrong, machine-readably:

```json
{"error":"Unknown field","message":"Field 'order_by' is not recognized"}
{"error":"Missing field","message":"Required field 'body -> date' is missing"}
{"error":"Invalid value","message":"Invalid value 'buy' for body -> buy_or_sell. Did you mean 'BUY'?"}
```

That is an instruction, not a complaint, so it gets executed: drop the unknown field, apply the
suggested value, supply the missing one — **but only from the small set we can honestly build**
(a date window, a page). What we cannot build we do not invent; the loop ends and the user is
told why.

Guard rails, so this never becomes a guessing machine: a hard cap on rounds; only endpoints with
unverified schemas use it; non-422 is never "repaired" (our request is not the problem there);
and the working body is printed to the log, because repair treats the symptom while a pinned
schema treats the cause. The learned *shape difference* (which fields to drop, which to add) is
remembered in `nansen_schema.json` — **not** the body, which carries arguments: remembering
`{"token": "BTC"}` would answer a question about ETH with BTC.

### 3.5 Presence is not usefulness

A recurring bug class, caught three times in this project: code reads a boolean "is available"
flag and shows it as if it were a result.

- leaders flagged `enabled` while the pool behind them was dead
- a systemd unit `active` while the engine traded nothing
- Polymarket positions flagged `redeemable` with a **$0** payout — 136 of them, read by a human
  as "money is sitting there", when the claimable total was zero

So the rule is: **lead with the magnitude, not the flag.** And when a magnitude is missing, say
so in words. When a rows-arrived-but-no-amount-field case appeared (twelve trades, every size
rendered as `?`), the fix was not a fourth guessed field name but a convention (`*_usd`) plus an
explicit line naming the fields the provider actually sent. `price_usd` is specifically excluded:
the price of one token shown as a trade size is not emptiness, it is a **wrong number** — and a
plausible wrong number is worse than a visible gap.

### 3.6 Attribution, with freshness

Every answer names Nansen as the source, and a cached answer says it is older. A number without
a timestamp is useless on trading data. In the bot this also reversed a prior rule that told the
model to hide which vendor the data came from — a rule that is exactly backwards when the data is
worth naming.

### 3.7 A contribution ledger

The bot is multi-user, so the layer records who asked what and at what cost — used to decide how
a shared prize is split. Two design points worth stealing:

- **a cache hit counts as activity but costs zero credits.** The first version skipped cache hits
  entirely ("free, so it does not count"), and a real person vanished from the statistics
  completely — he tapped a button and got a 30-minute cached answer.
- **anti-farming does not block, it declines to count.** The same question from the same person
  within 10 minutes is not counted, and that is announced up front. The public leaderboard
  carries no names and no IDs at all; names exist in exactly one owner-only screen.

## 4. What is in here

| file | what it is |
|---|---|
| `nansen_api.py` | the client: 50 endpoints, 19 screen formatters, failure classification, attribution, cache, schema repair |
| `nansen_log.py` | telemetry (one row per call), credit accounting per scene, the contribution ledger, daily rollup |
| `nansen_limits.py` | per-user daily question caps and a shared credit ceiling |
| `oc_nansen_viz.py` | two charts: holder-segment flows, market probability over time |
| `db.py` | **the only file that does not exist in the bot** — a ~70-line sqlite bridge for the ledger |
| `cli.py` | this terminal entry point |
| `tools/nansen_probe.py` | pull a live schema for endpoints whose body was never verified |
| `tools/nansen_daily.py` | daily/range spend export, CSV, contribution breakdown |
| `tools/telemetry_rollup.py` | aggregate the telemetry log |
| `tests/test_public.py` | the suite above |
| `scrub.py` | fails if a handle, a server path, an unknown wallet address or a key appears |
| `docs/scenarios.md` | **every screen: what to type, what comes back, what it costs, why you would want it** |
| `docs/telemetry_spec.md` | the telemetry format |

### API coverage

46 structured endpoints plus 4 trading calls:

| group | endpoints |
|---|---|
| `tgm/*` (Token God Mode) | 18 |
| `prediction-market/*` (Polymarket) | 12 |
| `profiler/*` | 9 |
| `smart-money/*` | 4 |
| `perp-leaderboard`, `portfolio/*`, `token-screener*` | 3 |
| `trade/*` (quote, prepare, execute, bridge status) | 4 |

The agent endpoints (`agent/fast`, `agent/expert`) are wired in the bot but are the expensive
path — 200 and 750 credits. The CLI here deliberately does not expose them: a demo that burns
750 credits per invocation is a bad demo, and every screen above is 1–5.

## 5. How this relates to the bot

This repository is **generated**, not maintained by hand. A builder in the private repo copies
the layer **byte for byte**, adds the handful of files that only make sense standalone, runs a
scrubber over the *output*, and writes `MANIFEST.md` with a sha256 of every file.

```bash
# in the private repo
python3 tools/export_nansen_public.py --out ../nansen-undertaker          # build
python3 tools/export_nansen_public.py --out ../nansen-undertaker --check  # verify, exit 1 on drift
```

A hand-made extract is a fork, and a fork diverges silently: the private repo fixes failure
classification, the public copy keeps the old one, and whoever followed the link is reading code
that no longer exists. `--check` is wired into a law test, so "the public repo fell behind"
becomes a red test rather than an unpleasant discovery a month later.

See `MANIFEST.md` for which files are byte-identical and which exist only here.

## 6. What is deliberately not here

- **The Telegram layer.** Handlers, keyboards, gates, user data. What is interesting about this
  build is the layer underneath, and the rest is someone else's private chat history.
- **`nansen_signer.py`**, the signing-key safe for the trading rail. The module has something to
  be proud of — the key never leaves it, there is no `unseal`/`export` function at all — but
  publishing key handling invites copy-paste by people who will not read the caveats. Named here
  rather than silently dropped: a quietly removed section is worse than a stated one.
- **Internal audits.** They are about the bot's kitchen, not about Nansen.
- **A dry-run mode for trading.** There is none, on purpose. Any tool that can send an order
  defaults to printing the plan, and the safety flag that enables real sending is removed by a
  human, never by the agent — a safety removed by the thing it constrains is a comment, not a
  safety.

## 7. Notes

**Language.** `NANSEN_LANG=en` switches the output to English where English exists: all seven
refusal texts, the whole command list, and 11 of the 19 screens (`who`, `info`, `balance`,
`counterparties`, `perps`, `wallet-perps`, `trades`, `pm`, `pm-book`, and both charts). The other
eight render in Russian, and that is left as is on purpose: writing an English translation *here*
would put text in the extract that **the bot does not have**, which would make the extract lie
about the product in the one place people read most carefully.

Code comments and `docs/` are in Russian — the bot's working language. The comments carry the
reasoning behind each decision rather than restating the code, so a thinner English paraphrase
would lose exactly the part worth reading. This README is the complete English entry point;
`NANSEN_LANG=en python3 cli.py --help` is the complete command list.

The same layer is guarded by 507 assertions in the private repo, including the bot-side
invariants that cannot run standalone (every button prefix is registered with a handler, every
callback fits in 64 bytes, the command and the button call the *same* function). The suite here
is the part that runs anywhere.

MIT licensed. Not financial advice — and the layer says so on every screen that shows a price.
