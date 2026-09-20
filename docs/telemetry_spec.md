# Nansen telemetry — the format that actually runs

This document describes the current writer and the **only authoritative reader**. The previous
JSONL design is retired; keeping two formats next to each other created two competing ways to
compute submission numbers.

## Source of truth

| concern | implementation |
|---|---|
| writer | `nansen_log.py` |
| files | `nansen_tele/YYYY-MM-DD.log` |
| line format | 16 space-separated `k=v` fields |
| workflow registry | `nansen_log.SCENES` |
| outcomes | `nansen_log.OUTCOMES` |
| reader / submission export | `tools/nansen_daily.py` |
| retention | 30 days |

`nansen/telemetry_rollup.py` is legacy: it reads an old JSONL file that production never writes.
It remains in the private repository only as history and is not exported to the public repo.

Telemetry is best effort: it must never break the answer shown to a user.

## One line per call

Example (illustrative, not a live user):

```text
ts=1789891200 scene=pm_reputation ep=prediction-market/address-summary ms=412 http=200 ok=1 empty=0 cache=0 out=ok rem=67605 used= d=1 est=0 cr=1 u=abc123 rep=1
```

Fields:

| field | meaning |
|---|---|
| `ts` | Unix timestamp |
| `scene` | human workflow, not endpoint; unknown is `?` |
| `ep` | Nansen route |
| `ms` | latency in milliseconds |
| `http` | status; `0` when no response exists |
| `ok` | request succeeded |
| `empty` | request succeeded but returned no usable rows |
| `cache` | no network call; cached response |
| `out` | normalized outcome |
| `rem` | remaining credits from response headers, if available |
| `used` | provider's used-credit header, if available |
| `d` | measured change in remaining credits when no other call overlapped |
| `est` | `0` measured, `1` estimated from official table, `2` price unknown |
| `cr` | measured/estimated credits; unknown is **0**, never a guessed default |
| `u` | daily rotating HMAC used only for unique-person counts |
| `rep` | repeat number for the same daily anonymous person |

## Outcomes

Closed registry:

```text
ok · empty · cache · http_error · bad_request · rate_limited · no_credits · timeout · nokey · quota_user · unsupported
```

`unsupported` is not `bad_request`: Nansen may return the same 422 for a malformed body and for a
coverage boundary such as an endpoint explicitly not supporting stablecoins. The response text
distinguishes them. They lead to opposite actions — fix our request vs accept a product boundary —
so telemetry must not merge them.

## Scenes

A scene is the question a human asked, not the API route used to answer it. Separate hero scenes
include:

```text
pm_markets · pm_chart · pm_orderbook · pm_reputation · pm_wallet · pm_leaders
perp_positions · liq_map · smart_trades
```

This separation makes the submission claim measurable: `pm_reputation` usage is visible instead
of hidden inside one coarse `polymarket` bucket.

The complete closed list lives only in `nansen_log.SCENES`; duplicating it in documentation would
create a second registry that drifts. An AST invariant checks both directions: every literal scene
used by code is registered, and every registered scene is used (or explicitly reserved).

## Credits

Three states, not two:

1. **measured** — change in `remaining` credits when exactly one request was in flight;
2. **estimated** — price exists in Nansen's official price table;
3. **unknown** — `cr=0`, `est=2`, counted separately.

Unknown never receives a generic 5-credit default. “184 unpriced calls” is reproducible; a clean
total built from guesses is not.

Cache hits always cost zero but still count as activity. This matters in a multi-user bot: a person
who taps a button and receives a cached answer did participate even though no credit was spent.

## Per-person contribution ledger

The daily file never contains a raw Telegram id. `u` is a daily rotating HMAC: it can distinguish
“twenty people once” from “one person twenty times” inside one day but cannot link the same person
across days.

A local database table (`nansen_contrib`) stores the contribution ledger for owner-only accounting
and deletion compliance. Public CSV/submission exports contain counters and ordinal places only.

Anti-farming does not block requests. The same person repeating the same request signature inside
10 minutes receives the answer but that contribution is marked not counted.

## Parallel calls

The reputation screen fetches up to five wallet summaries in parallel. The writer holds a lock
around each appended line so two threads cannot interleave one `k=v` record. Credit deltas are used
only when a single request was in flight; overlapping requests fall back to official estimates or
“unpriced.”

## Authoritative commands

```bash
# Human-readable daily/range report
./venv/bin/python3 tools/nansen_daily.py --range 2026-09-14 2026-09-27

# Submission block; both forms cover the full range
./venv/bin/python3 tools/nansen_daily.py --submission 2026-09-14 2026-09-27
./venv/bin/python3 tools/nansen_daily.py --submission --range 2026-09-14 2026-09-27

# Identifier-free CSV
./venv/bin/python3 tools/nansen_daily.py --range 2026-09-14 2026-09-27 --csv
```

If no daily file exists, the reader returns code 2 and says **NO VERDICT**. It never prints zeros:
“zero calls” and “telemetry did not run” require opposite decisions.

## Eligibility boundary

Local telemetry began after the contest window opened. It is evidence of behavior and spend, not
the authority for the official 1,000-call requirement. Nansen Usage Analytics is authoritative for
eligibility and must be checked separately.
