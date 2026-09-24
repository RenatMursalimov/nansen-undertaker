# Nansen Undertaker

**▶️ Demo video (3 min, live data):** <https://x.com/Rencrypta/status/2103016647061656017> —
running order and full transcript: [`docs/VIDEO.md`](docs/VIDEO.md)

## A market says 78% YES. But whose conviction is it?

Nansen Undertaker is a live Telegram workflow that checks **who holds a Polymarket market and how
those wallets performed before**.

A price alone cannot distinguish two opposite situations:

- 78% backed by wallets with strong historical win rates;
- 78% backed mostly by wallets that were right less than 40% of the time.

The hero screen composes Nansen market holders with lifetime wallet history and leads with the
magnitude that changes the conclusion:

```text
Of $2.00M examined, $1.40M (70%) sits with wallets below a 40% win rate.
By side: Yes $1.60M · No $550K

1. Whale A [Yes] · $800K · entry 12¢ → 45¢ · win rate 33% · PnL -$120K
2. 0xbbbb…bbbb [Yes] · $600K · entry 31¢ → 45¢ · win rate 71% · PnL +$340K

2 holders have no measurable history — their money is counted on NEITHER side.
```

Nansen data drives the conclusion, not just the UI.

Built for the **Nansen Meridian Buildathon**.

## Mini-app: the same answer, on a phone

The screens above also run as a **Telegram mini-app** — the hero (plus the same market's holders
with their PnL *in that market*), the sharp-money market comparison, the liquidation map with a
four-token risk board and two sliders for window and detail, smart-money trades as a share of market
cap, scheduled buying, the chain ranking, and a live feed of the API calls themselves. See it in
under a minute, no key and no Telegram account:

```bash
python3 -m http.server 8080
# http://127.0.0.1:8080/webapp/index.html?rehearsal=1
```

Step-by-step, with what you should see: [`docs/JUDGE.md`](docs/JUDGE.md).

**The mini-app computes nothing.** Every screen renders the *same dictionary* the bot uses to build
its chat message — `nansen_scene.py` builds it, `nansen_gate.py` guards it, `webapp/index.html` draws
it with hand-rolled SVG and zero dependencies. Under each chart sits the exact sentence the bot would
say in chat, so the picture and the words cannot drift apart. A law test injects one number into the
dictionary and requires **both** outputs to change; if only one does, a second source of truth has
appeared and the build goes red.

The last screen is the liveness proof the contest asks for: one row per network call — endpoint,
outcome class, milliseconds, credits, cache or wire, and which surface asked. It costs nothing extra,
because the telemetry was already writing those rows.

Decisions, including the screen deliberately **not** shipped and two leaks the scrubber caught before
production: [`docs/MINIAPP_DECISIONS.md`](docs/MINIAPP_DECISIONS.md).

**59 Nansen API routes** · **33 documented workflows** · **36 named telemetry scenes** ·
**8 distinct failure states**

- [`docs/proofs/LIVE_HERO_2026-09-20.md`](docs/proofs/LIVE_HERO_2026-09-20.md) — sanitized live hero proof: 4 calls, 3 known histories, 0 failures.
- [`docs/proofs/MERIDIAN_CORPUS_2026-09-20.md`](docs/proofs/MERIDIAN_CORPUS_2026-09-20.md) — sanitized corpus proof: 1,050 network calls at the hard cap.
- [`docs/proofs/LIVE_MARKET_SELECTION_2026-09-20.md`](docs/proofs/LIVE_MARKET_SELECTION_2026-09-20.md) — primary/backup decision from two additional PASS runs.
- Current completion/eligibility status: [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- Exact sandbox deploy + recording runbook: [`docs/RECORDING_RUNBOOK.md`](docs/RECORDING_RUNBOOK.md)
- Social preview / demo title card: [`assets/social-preview.png`](assets/social-preview.png)
- Full generated workflow catalog: [`docs/CATALOG.md`](docs/CATALOG.md)
- All-53-route server sweep and 12×/day schedule: [`docs/ENDPOINT_SWEEP.md`](docs/ENDPOINT_SWEEP.md)
- Published demo video, running order and transcript: [`docs/VIDEO.md`](docs/VIDEO.md)
- Demo *plan* (110-second shot list with narration, drives the voiceover tool):
  [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md); the older silent plan:
  [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- Ready X thread: [`docs/X_THREAD.md`](docs/X_THREAD.md)
- Submission draft and eligibility gate: [`docs/submission.md`](docs/submission.md)
- Roadmap and competitor analysis: [`docs/WINNER_PLAN.md`](docs/WINNER_PLAN.md)

---

## Run it in under 10 minutes

```bash
git clone https://github.com/RenatMursalimov/nansen-undertaker
cd nansen-undertaker
pip install -r requirements.txt
cp .env.example .env                 # put NANSEN_API_KEY in this local ignored file
python3 tools/nansen_live_smoke.py    # PLAN: zero calls
python3 tools/nansen_live_smoke.py --run
python3 tools/nansen_endpoint_sweep.py --profile complete  # PLAN: all safe routes, zero calls
```

For sustained endpoint health and usage, the fresh sweep covers every client route or names why it
cannot be scheduled. See [`docs/ENDPOINT_SWEEP.md`](docs/ENDPOINT_SWEEP.md) for exact one-route,
complete, Agent, trading and 12-runs-per-day commands. It bypasses response cache, enforces daily
wire/credit caps and never schedules transaction preparation or execution.

The live smoke test is read-only and capped by design: one active market, its holders and up to
three wallet histories. Success ends with:

```text
LIVE PROOF: PASS
Requests: 4 · known histories: 1+ · provider failures: 0
```

No key yet? The offline suite substitutes exactly the network wire. Parsing, calculations,
failure classification, source attribution, telemetry and the contribution ledger remain the real
production code:

```bash
python3 tests/test_public.py
python3 scrub.py
NANSEN_LANG=en python3 cli.py --help
```

---

## Why this is not another dashboard

### 1. The probability is weighted by the quality of the money behind it

The workflow combines:

1. `prediction-market/top-holders` — side, shares, entry price and current price;
2. `prediction-market/address-summary` — lifetime win rate, PnL and markets traded.

Position value is computed as `shares × current price`; Nansen returns shares and price separately.
The screen then measures how much **known money** belongs to wallets below a visible 40% threshold.

Three guard rails keep that conclusion honest:

- a wallet with no measurable history is assigned to neither “strong” nor “weak” money;
- a provider failure is shown as **history not delivered**, never as “this wallet has no history”;
- the threshold, coverage and request count are printed in the screen, so the reader can disagree
  with the method rather than guess it.

Five wallet summaries run in parallel with a 10-second timeout; top-holder discovery has the same
bound. A numbered Telegram button is
bound to the exact `market_id`, not to the market's current rank; an old `🎭 2` can never silently
open a different market after the ranking changes.

Past win rate does not promise the future. This is composition of conviction, not a prediction or
financial advice.

### 2. A liquidation list becomes a liquidation map

`tgm/perp-positions` becomes capital clustered by liquidation price:

```text
Largest cluster: $22.5M between $61.5K and $62.4K.
Longs $22.5M vs shorts $8.2M.
```

The list answers **who is leveraged**. The map answers **at which price the market may move fast**.
Positions with no liquidation price are explicitly counted outside the map. An empty chart is never
drawn. The caption says these are other people's stop-out levels, not a forecast.

### 3. A Smart Money buy is measured against the token it moved into

“Smart Money bought $48K” says little by itself. The same response also contains token market cap
and age, so the workflow shows:

```text
$48.3K buy · $2.1M market cap · 2.3% of market cap · 3 days old
```

$48K into a $2.1M token can be signal. The same $48K into a $50B token is noise. No extra API call
is needed.

### 4. Missing data never becomes a silent verdict

Eight states have eight meanings:

| state | meaning |
|---|---|
| `nokey` | the request never went out |
| `nocredits` | the credit balance is exhausted |
| `ratelimit` | Nansen throttled the request |
| `timeout` | no answer arrived in time |
| `badreq` | our request body was rejected |
| `unsupported` | the endpoint explicitly does not cover this asset |
| `http` | provider/network error |
| `empty` | the request succeeded and genuinely returned no data |

This distinction matters most on wallet labels: **“no label” does not mean “safe wallet.”** Partial
multi-request screens name the pieces that were not delivered. Every result names Nansen and its
freshness.

### 5. Credit accounting is part of the product

Every network call writes exactly one telemetry row. Cache hits count as user activity but zero
spend. Calls are tagged by workflow (`pm_reputation`, `liq_map`, `smart_trades`, etc.), so the
submission can prove whether the new screens were actually used instead of showing one coarse
“Polymarket” bucket.

Published prices are used where Nansen names them. Unknown prices are zero in the total and counted
separately — a visible “184 unpriced calls” is better than a tidy total built from guesses.

---

## Factual inventory

The generated catalog distinguishes **client capability** from **shipped workflow**:

- 59 unique network routes exist in the client;
- 33 workflows are documented:
  - 31 user-facing workflows that call Nansen;
  - 1 background digest workflow;
  - 1 local contribution-tally workflow;
- 30 unique API routes drive those workflows;
- remaining client-only/owner-only routes are listed separately, not presented as working user
  screens.

Counts are generated from code. Commit-message counts are not used as a source of truth.

Main areas:

| area | examples |
|---|---|
| Agent | `agent/fast`, `agent/expert` |
| Smart Money | netflow, holdings, DEX trades, perp trades |
| Token God Mode | flows, holders, indicators, PnL, transfers, perp positions, history |
| Profiler | labels, balances, PnL, counterparties, transactions, perp positions |
| Prediction markets | screener, OHLCV, orderbook, holders, wallet/market PnL |
| Trading client capability | quote, prepare, execute, bridge status — not the contest hero |

See [`docs/CATALOG.md`](docs/CATALOG.md) for every human workflow, command, button, endpoint, cost,
output and one-line X hook.

---

## Repository map

| path | purpose |
|---|---|
| `nansen_api.py` | production client, calculations, cache, schema repair, 8 outcomes |
| `nansen_log.py` | one-row-per-call telemetry, workflow scenes, contribution ledger |
| `nansen_limits.py` | per-user daily limits and shared credit ceiling |
| `oc_nansen_viz.py` | segment-flow, probability and liquidation-map visualizations |
| `db.py` / `env_load.py` | standalone bridges for the production database/env contracts |
| `cli.py` | terminal access to the same production formatters |
| `tools/nansen_live_smoke.py` | smallest reproducible live proof; explicit `--run` |
| `tools/nansen_meridian_corpus.py` | resumable 7-day Smart Money corpus with a hard call cap |
| `tools/nansen_endpoint_sweep.py` | fresh all-route registry, budgets and safe 12×/day profiles |
| `tools/nansen_trade_probe.py` | human-gated quote/prepare/status; execute blocked by design |
| `tools/nansen_probe.py` | live schema probe; zero calls without `--run` |
| `tools/nansen_daily.py` | one authoritative telemetry reader and submission export |
| `tools/render_social_preview.py` | reproducibly renders the 1280×640 GitHub/demo card |
| `assets/social-preview.png` | generated GitHub social preview and 0–3s demo title card |
| `docs/PROJECT_STATUS.md` | current eligibility, evidence and remaining external steps |
| `docs/ENDPOINT_SWEEP.md` | all 59 routes, exact server commands, budgets and cron schedule |
| `docs/RECORDING_RUNBOOK.md` | exact sandbox deploy, live UX check and 52-second recording flow |
| `docs/wiki/` | version-controlled source for the short GitHub Wiki navigation layer |
| `tests/test_public.py` | offline proof with the network boundary substituted |
| `scrub.py` | blocks server paths, unknown wallet addresses, keys and runtime state |
| `MANIFEST.md` | source and SHA-256 for every exported file |

This public repository is **generated**, not maintained as a hand-written fork. Production modules
are copied byte-for-byte from the private bot repository. The exporter writes the manifest, removes
stale managed files, runs a privacy scrub and fails when the public extract drifts.

The Telegram handlers are deliberately not included: they contain private bot/user context. The
30–60 second live recording is the end-to-end proof for that layer; this repo exposes the complete
Nansen logic underneath it.

`nansen_signer.py` is also deliberately excluded. It keeps a trading key inside a no-export signing
module, but key-handling code is not needed to review the analytical build and creates unnecessary
copy-paste risk.

---

## Buildathon eligibility

The official rules require **1,000+ API calls made Sep 14–27**, a public repo, a 30–60 second live
screen recording, an X post tagging `@nansen_ai`, and the official entry form.

Eligibility is confirmed twice: the local corpus recorded **1,050 network calls**, and the supplied
Nansen Usage Analytics screenshot shows **5,484 calls on Sep 20** (inside the contest window) plus
13,850 total in 30D. Save a cropped copy of the dashboard panel before submission; do not publish
the raw screenshot with browser chrome/bookmarks/wallet area.

See [`docs/WINNER_PLAN.md`](docs/WINNER_PLAN.md) and [`docs/submission.md`](docs/submission.md).

---

## Language and safety

`NANSEN_LANG=en` selects English where production formatters support it. The judge-facing
documents are English-primary; a Russian analog of each sits next to it as `*_ru.md`
(`docs/CATALOG_ru.md`, `docs/scenarios_ru.md`, `docs/WINNER_PLAN_ru.md`,
`docs/submission-checklist_ru.md`), generated from the same source. In-code documentation comments
remain mostly Russian because they preserve the reasoning that led to each guard rail; replacing
that reasoning with a thinner translation would lose the useful part.

No trading action is part of the hero workflow. Tools that spend credits or change external state
print a plan by default and require a human to remove the explicit safety flag.

MIT licensed. Not financial advice.

Rules and judging criteria were rephrased from the [official campaign page](https://nansen.ai/campaigns/meridian-buildathon)
and [official FAQ](https://nansen.featurebase.app/help/articles/3540155-nansen-meridian-buildathon-sep-14-27).
Content was rephrased for compliance with licensing restrictions.
