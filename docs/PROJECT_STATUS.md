# Nansen Undertaker — project status

**Updated:** 25 September 2026  
**Buildathon deadline:** 27 September 2026, 23:59 UTC  
**Status:** product and eligibility proven; recording, X post and official form remain.

## Executive status

| Area | Status | Evidence / next action |
|---|---|---|
| Core Nansen integration | ✅ Complete | 59 API routes in one client; 34 documented workflows; **no route left without a measured schema** |
| Server endpoint sweep | ✅ Ready | all 59 routes declared; 53 structural reads + safe trade reads, Agent tier, hard budgets |
| Hero: Polymarket holder reputation | ✅ Live PASS | primary `1130012`, backup `4323345`; 3 known histories, 0 failures each |
| Liquidation map | ✅ Complete | button + command + visualization + honest missing-data handling |
| Telegram mini-app | ✅ Complete | five tabs (`Whose %`, `Sharp`, `Map`, `More`, `Live`), nine scenes, rehearsal mode on recorded fixtures |
| Map controls | ✅ Complete | scale/detail sliders on a closed ladder, both orientations, save-as-picture; sliders stay put during a reload |
| No identifier typing left | ✅ Complete | market id travels from the card (`🧾 N` in chat, a button on the market card in the app); only tickers are typed, and a ticker is knowledge the user already has |
| Smart Money trade as % of market cap | ✅ Complete | no extra request; value, market cap and token age from one response |
| Honest outcomes | ✅ Complete | 8 distinct states; partial failures never become wallet properties |
| Sentinel: live alerts | ✅ Live on production | `sentinel/` (12 modules); eight event kinds across two venues (Variational Omni and Hyperliquid) plus Smart Ignition on Nansen; 248 offline checks in `tests/test_sentinel.py`; live proof in `proofs/sentinel_live_proof.py`; buttons in two menus; spec in [`SENTINEL_SPEC.md`](SENTINEL_SPEC.md), including the three defects live production found on day one |
| Telemetry | ✅ Complete | 28 workflow/operations scenes; one production reader; submission export |
| Public repository | ✅ Public, CI green | https://github.com/RenatMursalimov/nansen-undertaker |
| 1,000-call eligibility | ✅ Threshold exceeded | Nansen screenshot: **5,484 used on Sep 20**, 13,850 total in 30D |
| Meaningful corpus | ✅ Complete | 1,050 network calls, hard cap, 0 cache hits, 1,048 latest cells |
| Primary/backup preflight | ✅ Complete | both live smoke runs PASS |
| Recording | ✅ Published | 3-minute live walkthrough: https://x.com/Rencrypta/status/2103016647061656017 · running order + transcript in [`VIDEO.md`](VIDEO.md) · the 110-second scripted cut remains available for a tighter second take |
| X post | ✅ Published | same link; the thread draft in `submission/X_THREAD.md` can still be expanded around it |
| Official entry form | ⏳ Not submitted | submit by Sep 26 if possible |
| Social preview | ⏳ Image prepared, manual upload required | `assets/social-preview.png`, GitHub Settings upload |
| GitHub Wiki | ⏳ Source prepared, first page must be initialized | see Wiki section below |

## Eligibility proof

The screenshot supplied by the owner shows Nansen Usage Analytics in 30D mode:

- **Used Today: 5,484**
- **Total Usage: 13,850**
- graph tooltip: **20 Sep 2026 — Credit Usage 5,484**

Because 20 Sep is inside the Sep 14–27 contest window and that single day exceeds 1,000, the call
threshold is unambiguously met. The dashboard screenshot is the authoritative artifact; the local
corpus independently recorded 1,050 network calls at its hard cap.

The raw screenshot is intentionally not committed: it contains browser chrome/bookmarks and a
visible wallet-balance area. Crop it to the Nansen Usage Analytics panel before attaching it to a
submission or public post.

## Final product pitch

> A Polymarket market says 78% YES. Nansen Undertaker tells you **whose 78% it is** — how much
> money behind each side belongs to wallets that were right before, while excluding unmeasured
> histories from both sides.

Primary live market `1130012` produced the strongest result:

```text
$858.5K examined
$500.4K (58%) belongs to wallets below 40% historical win rate
3 known histories · 0 provider failures · live freshness
```

Backup `4323345` produced the opposite result (`$0 / 0%` below 40%), proving the screen is not
hard-coded to create an alarming conclusion.

## Technical inventory

- **59** unique Nansen API routes in the client — the last one without a schema (`tgm/position-intelligence`) was resolved on 24 Sep by the fourth probe round.
- **34** documented workflows:
  - 32 user-facing workflows that call Nansen;
  - 1 background digest workflow;
  - 1 local contribution-tally workflow.
- **30** unique API routes directly drive those documented workflows.
- **36** telemetry scenes, including separate `pm_reputation`, `pm_orderbook`, `pm_chart`,
  `liq_map`, `sharp_markets`, `perp_risk` and `perp_positioning` evidence.
- **9** mini-app scenes, each a new *surface* of an existing telemetry scene rather than a new
  scene: `pm_markets`, `pm_reputation`, `liq_map`, `smart_trades`, `sharp_markets`, `perp_risk`,
  `smart_dca`, `chain_rank`, `pm_positions`. Spend from chat and from the app therefore adds up on
  one row per scene.
- **9** recorded fixtures (one per scene), all marked `provenance: synthetic`, so the interface
  opens with no key and cannot pass itself off as a live run.
- **8** user-visible failure states.
- Private Nansen suite: **862 PASS / 0 FAIL** after all-route sweep and credit-safety checks.
- Public suite: **156 PASS / 0 FAIL**; scrub clean; latest published CI green.

## What is finished

1. Wallet profiles, Smart Money netflow/holdings/trades, token breakdowns, perps and Polymarket.
2. Button access from token, meme, exchange and prediction-market screens.
3. Live-probed schemas and dead-route removal/restoration by evidence.
4. Position shares converted to dollars only as `shares × current price`, explicitly labelled.
5. Prediction-market OHLCV filtered to one outcome and ordered in time.
6. Flat orderbook responses grouped into bids/asks and depth computed in money, not shares.
7. Market buttons bound to exact market identity, not a mutable rank.
8. Parallel holder-history lookup with bounded timeouts and partial-failure semantics.
9. Liquidation map and flow/probability visualizations.
10. Per-workflow cost/freshness/outcome telemetry, contribution ledger and reproducible export.
11. Generated public repository, generated workflow catalog, live smoke, corpus and submission kit.

## What deliberately remains after the contest

These are roadmap items, not missing submission requirements:

1. **Conviction watch:** alert when market price rises while holder quality deteriorates.
2. **Thesis invalidation:** user states a thesis and a measurable death condition before sizing;
   the bot watches Nansen data and returns when the thesis breaks.
3. **Low-cap discovery product:** operationalize the corpus ranking with liquidity and fresh-wallet
   filters rather than publishing an exploratory top-100-limited list.
4. **A/B comparison:** compare two tokens or markets by flow %, holder quality and wallet overlap.
5. **More direct UX doors:** the generated catalog lists client routes without an ordinary user
   workflow; add only when a real decision question exists, not to increase a route count.

## Freeze rule, and where it actually stood

The rule was written as *«add no new feature unless it fixes a demonstrated recording blocker»*, and
between 22 and 23 September it was **not** what happened: the owner watched live screens and asked
for the things that were missing, and those requests were built — sharp-money comparison, the perp
risk board, the measured ticker list, the map controls, two orientations, save-as-picture, the
`➕ More` tab, and the end of typing a market id. Recording that honestly matters more than looking
disciplined: every one of those came from a real defect or a real gap found on live data, and the
last of them removed a UX defect the owner had reported **twice**.

From here the freeze holds, and the remaining work is packaging:

1. crop/save Usage Analytics proof;
2. ~~record the demo~~ — **done**, published 23 Sep: see [`VIDEO.md`](VIDEO.md). A tighter
   110-second cut per [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md) is optional, not required;
3. upload social preview;
4. publish X thread;
5. submit official form and save confirmation.

Canonical detailed roadmap: [`WINNER_PLAN.md`](WINNER_PLAN.md).  
Final gate: [`submission/CHECKLIST.md`](submission/CHECKLIST.md).  
Recording runbook: [`submission/RECORDING_RUNBOOK.md`](submission/RECORDING_RUNBOOK.md).
