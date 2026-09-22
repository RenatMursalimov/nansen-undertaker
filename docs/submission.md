# Nansen Undertaker — Meridian submission draft

**Status: ELIGIBILITY CONFIRMED (5,484 CALLS ON SEP 20); PRIMARY + BACKUP LIVE HERO PASSED;
WAITING FOR CROPPED USAGE SCREENSHOT FILE, VIDEO/X URL AND ENTRY-FORM CONFIRMATION.**
Three external artifacts remain before submission:

1. save a cropped copy of the supplied Usage Analytics screenshot (the dashboard shows 5,484
   calls on Sep 20; remove browser chrome/bookmarks/wallet area before publishing);
2. a 30–60 second live screen recording;
3. the X post URL and official entry-form confirmation.

Do not remove this status until all three exist. A green local test is not eligibility.

## One-sentence pitch

> A Polymarket market says 78% YES. Nansen Undertaker tells you **whose 78% it is** — how much
> money behind each side belongs to wallets that were right before, while counting missing wallet
> histories on neither side.

## Why Nansen data drives the logic

The hero workflow is not a dashboard field. It composes two Nansen datasets:

1. `prediction-market/top-holders`: side, shares, entry price and current price;
2. `prediction-market/address-summary`: lifetime win rate, PnL and markets traded.

The build computes position value as `shares × current price`, separates Yes/No money, and measures
how much known money belongs to wallets below a visible 40% historical win-rate threshold. If a
wallet history is unavailable, its money is counted on **neither** side. If the API failed, the
screen says the history was not delivered — it does not call that “no history.”

Nansen data therefore changes the conclusion: identical 78% market prices become different
analytical objects depending on the quality and coverage of the money behind them.

## Two supporting workflows

- **Liquidation map:** `tgm/perp-positions` becomes capital clustered by liquidation price — for
  example, `$22.5M between $61.5K and $62.4K`. Missing liquidation prices are stated; an empty chart
  is never drawn; the caption says this is where other people stop out, not a forecast.
- **Smart-money trade as % of market cap:** the same `$48K` buy is 2.3% of a $2.1M token but noise
  in a $50B asset. Market cap and token age arrive in the same Nansen response, so this context
  costs no additional request.

## Trust layer

Eight states have eight user-facing meanings: no key, no credits, rate limit, timeout, malformed
request, unsupported asset, provider error and genuinely empty data. “No label” never reads as
“safe wallet.” Every output names Nansen and freshness; every network call writes one telemetry
record; cache hits count as activity but zero spend.

## Architecture

```text
Telegram command / inline button
        │
        ▼
  one shared screen function
        │
        ▼
  nansen_api.py — 53 network routes, cache, schema repair, eight outcomes
        │
        ├── structured Nansen endpoints
        ├── agent/fast + agent/expert
        └── trade routes (client capability, not the contest hero)
        │
        ▼
  nansen_log.py — one row per call, per-workflow scenes, contribution ledger
        │
        ▼
  tools/nansen_daily.py — one authoritative reader for k=v daily telemetry
```

The numbered Polymarket buttons carry the **market identity**, not its rank. A button sent before
the ranking changes cannot silently open a different market. The five wallet summaries in the hero
screen run in parallel with a 10-second timeout and preserve each failure class.

## Factual inventory

- **53 unique Nansen API routes** in the client.
- **25 documented workflows** in generated `docs/CATALOG.md`:
  - 23 user-facing workflows that call Nansen;
  - 1 background digest workflow;
  - 1 local contribution-tally workflow that reads the integration's own ledger.
- **29 unique API routes** drive those documented workflows; remaining routes are explicitly
  listed as client-only/owner-only rather than presented as shipped user scenarios.
- **28 telemetry scenes**, including separate evidence for market list, chart, orderbook, holder
  reputation, wallet profile, market leaders, liquidation map, fresh endpoint sweeps and isolated
  human-gated trade diagnostics.

Counts are generated from code. Do not copy old counts from commit messages.

## Reproducibility

Offline proof (no key/network; the wire is substituted, parsing/calculation/telemetry are real):

```bash
pip install httpx
python3 tests/test_public.py
python3 scrub.py
```

Live hero proof (read-only, up to five calls; explicit human flag):

```bash
NANSEN_API_KEY=... python3 tools/nansen_live_smoke.py --run
```

Expected final lines:

```text
LIVE PROOF: PASS
Requests: 4 · known histories: 1+ · provider failures: 0
```

## Live evidence collected on Sep 20

- Hero live smoke: **three PASS runs**. Final primary `1130012`: 4 requests, 3 known wallet histories, 0 provider failures, $500.4K / 58% of examined money below 40% historical win rate. Backup `4323345`: 4 requests, 3 known histories, 0 failures, $0 / 0% below 40%.
- Meaningful Smart Money corpus: **1,050 client invocations / 1,050 network calls / 0 cache hits**,
  exactly at the hard cap; 155 tokens discovered, 1,048 latest unique cells across 75 tokens,
  414 top-100 partial cells, 2 transient failures.
- Sanitized evidence: `docs/proofs/LIVE_HERO_2026-09-20.md`,
  `docs/proofs/LIVE_MARKET_SELECTION_2026-09-20.md` and
  `docs/proofs/MERIDIAN_CORPUS_2026-09-20.md` in the public repo.

The first hero run also found two presentation defects now fixed: unexamined holders are no longer
called “no measurable history”, and factual live freshness now reaches the source footer.

## Eligibility: 1,000+ calls

Official rules require 1,000+ calls during the contest window. The Sep 20 corpus produced 1,050
network calls locally, and Nansen Usage Analytics independently showed **5,484 calls on Sep 20**
plus 13,850 total in 30D. Eligibility is confirmed; save a cropped copy of the supplied screenshot
before submission.

Pre-corpus local snapshot (kept to show the instrument's partial-window boundary):

| metric | preliminary value |
|---|---:|
| days with local telemetry | 6 of 13 |
| calls recorded locally | 31 |
| network calls recorded locally | 30 |
| measured credits | 3,044 |
| unpriced calls | 2 |
| people in contribution ledger | 5 |
| calls with no workflow scene | 4 |

The corpus has now run at the 1,050-call hard cap. Do not run it again for eligibility unless Usage
Analytics contradicts the local evidence; two transient cells remain retryable but are irrelevant to
the threshold.

## Final telemetry block

Generate only after the recording and eligibility run:

```bash
./venv/bin/python3 tools/nansen_daily.py --submission 2026-09-14 2026-09-27
./venv/bin/python3 tools/nansen_daily.py --range 2026-09-14 2026-09-27 --csv
```

The short `--submission START END` form and explicit `--range` form are tested to cover the same
full range. Unpriced calls are shown separately; they are not silently added to measured credits.

## Demo and X

- Silent 52-second storyboard: `DEMO_SCRIPT.md`.
- Ready six-post thread: `X_THREAD.md`.
- Full build/eligibility roadmap: `../WINNER_PLAN.md`.
- Generated workflow catalog and tweet hooks: `../CATALOG.md`.

## Final links

Fill only with existing public artifacts:

- Public repo: https://github.com/RenatMursalimov/nansen-undertaker
- Live demo post: `<ADD AFTER POSTING>`
- Official submission confirmation: `<ADD AFTER SUBMITTING>`

## Final gate

- [x] Nansen Usage Analytics threshold: 5,484 calls on Sep 20 (inside Sep 14–27).
- [ ] Cropped Usage Analytics screenshot file saved.
- [ ] Public repo opens in incognito; CI green.
- [ ] Live smoke passes on primary and backup market.
- [ ] Video is 30–60 seconds, understandable silently, no private data.
- [ ] First X post tags `@nansen_ai` and links the public repo.
- [ ] Entry form contains email, X post URL and GitHub URL.
- [ ] No `<ADD ...>` markers remain.

Rules and judging criteria were rephrased from the [official campaign page](https://nansen.ai/campaigns/meridian-buildathon)
and [official FAQ](https://nansen.featurebase.app/help/articles/3540155-nansen-meridian-buildathon-sep-14-27).
Content was rephrased for compliance with licensing restrictions.
