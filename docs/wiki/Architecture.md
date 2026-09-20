# Architecture

```text
Telegram command / inline button
        │
        ▼
shared screen function
        │
        ▼
nansen_api.py — 53 routes, cache, schema validation, 8 outcomes
        │
        ▼
nansen_log.py — one row per call, 26 workflow scenes, contribution ledger
        │
        ▼
tools/nansen_daily.py — authoritative submission export
```

## Hero composition

1. `prediction-market/top-holders`: side, shares, entry/current price.
2. `prediction-market/address-summary`: lifetime win rate, PnL, markets traded.
3. Position value = shares × current price; the response has no ready dollar total.
4. Unknown histories are assigned to neither strong nor weak money.
5. Parallel calls are bounded; market buttons carry exact identity, not mutable ranking.

Full architecture and reproducibility details: [README](https://github.com/RenatMursalimov/nansen-undertaker#readme).
