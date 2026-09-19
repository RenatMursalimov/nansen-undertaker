# Nansen Meridian Buildathon — submission package (skeleton)

**Status: NOT READY TO SEND.** Every number in this package is collected by the telemetry that
shipped with this PR. Per the task spec, the package is assembled only **after telemetry has
been running for at least a week** — numbers taken earlier are false, because the credit
accounting was broken in three places until this PR (single instrumentation point out of ~20,
charged before the call and on cache hits, and the two most expensive paths never counted at
all).

Placeholders below are marked `<TBD:…>`. **Do not guess them.** A number without a mechanism
behind it is worse than no number (project law #22).

## What this is

A Telegram bot (~3000-person community, Russian-speaking crypto audience) that lets people ask
on-chain questions in plain language and get an answer with the source and its freshness stated
explicitly. Nansen is the on-chain data layer behind every such answer.

## Why it is not "another dashboard"

The interesting part is not the queries — it is what the bot does when Nansen does **not**
answer. Before this work, an empty result, a 402, a 429 and a timeout produced one and the same
sentence, and the wallet-profile screen said "no labels or the address is inactive" — which a
human reads as *"the address is clean"*. Absence of a label is absence of a label, not safety.
The integration now distinguishes four states in words and never lets an infrastructure failure
look like a verdict.

## Architecture (no keys, no addresses)

```
Telegram (DM · public chat · Hub)
        │
        ├── text commands / inline buttons        onchain/oc_dm.py, oc_menu.py, onchain/oc_callbacks.py
        ├── free-form question (LLM agent tool)   dm_module.py, pub_tools.py, bot.py
        │
        ▼
  nansen_api.py  ── the only Nansen client in the repo
        │  four network chokepoints: _post, _post_beta, ask_agent, smart_money_netflow
        │  each one: classifies the failure (402 / 429 / timeout / other), measures latency,
        │  reads the credits headers, writes exactly one telemetry line
        ▼
  nansen_log.py  ── telemetry, credit accounting, contribution ledger
        │  per-day file  nansen_tele/YYYY-MM-DD.log   (one line per call, stays on the server)
        │  persisted balance  nansen_credits.json     (survives a restart)
        │  ledger  table nansen_contrib               (per-person, local only)
        ▼
  tools/nansen_daily.py  ── daily summary + CSV export (numbers only, no identifiers)
```

### Nansen endpoints in use

| Area | Endpoints |
|---|---|
| Agent | `agent/fast`, `agent/expert` |
| Token God Mode | `tgm/flow-intelligence`, `tgm/indicators`, `tgm/holders`, `tgm/pnl-leaderboard`, `tgm/who-bought-sold`, `tgm/token-information` |
| Smart Money | `token-screener`, `smart-money/netflow`, `smart-money/holdings` |
| Profiler | `profiler/address/labels`, `.../premium-labels`, `.../pnl-summary`, `.../related-wallets`, `.../counterparties`, `.../current-balance` |
| Perps | `perp-leaderboard` |
| Prediction markets | `prediction-market/market-screener`, `.../address-summary`, `.../pnl-by-address`, `.../pnl-by-market` |
| Historical (v1beta1) | `tgm/historical-token-ohlcv`, `tgm/historical-token-flow-summary` |

Four of these (`tgm/who-bought-sold`, `tgm/token-information`,
`profiler/address/counterparties`, `profiler/address/current-balance`) had a written client and
**no reachable door** until this work: no command, no button, no background job. They now have
commands, help entries and honest refusals.

## Privacy

- No user identifier leaves the server. The per-day telemetry file carries a **daily HMAC** of
  the Telegram id (key derived from the bot token, salted with the date), used for exactly one
  thing: telling "twenty people once" from "one person twenty times". The hash changes every
  day, so a cross-day identifier does not exist by construction.
- The CSV export and every number in this package contain counters and ordinal places only. A
  test asserts the export has no `u` column and no raw id.
- The contribution ledger (`nansen_contrib`) is registered in the bot's GDPR/152-ФЗ erasure
  registry: `/delete_me` removes the person's rows.

## Numbers for the contest window

Fill from `tools/nansen_daily.py --range <start> <end> --csv` — **after** at least seven days of
telemetry.

| Metric | Value |
|---|---|
| Contest window | `<TBD: YYYY-MM-DD .. YYYY-MM-DD>` |
| Requests total / over the network | `<TBD>` / `<TBD>` |
| Share served from cache | `<TBD>` |
| Credits burned (measured vs estimated calls) | `<TBD>` |
| Unique people per day (median) | `<TBD>` |
| Honest refusals shown, by class (402 / 429 / timeout / empty) | `<TBD>` |
| Median latency per scenario | `<TBD>` |
| Calls with no scene tag (should be 0) | `<TBD>` |

## Links

- Published write-up of the integration ("The Eyes", part IV): `<TBD: URL>`
- 60–90 s demo video from the live chat: `<TBD: file>`
- Sanitised copy of the integration module, if the rules require a repository: `<TBD>` —
  ship `nansen_api.py` + `nansen_log.py` + `tools/nansen_daily.py`, **not** the whole bot.
