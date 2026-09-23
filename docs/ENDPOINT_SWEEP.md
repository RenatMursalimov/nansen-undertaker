# Nansen: server sweep for every endpoint

This is the server-side counterpart to the Telegram workflows. It exercises the client inventory,
not only the 25 user scenarios.

## Coverage and safety boundary

The registry is checked against `nansen_api.py` on every start:

| Class | Routes | Scheduled behavior |
|---|---:|---|
| Structural reads | 47 | fresh POST through production telemetry; all in `complete` |
| Agent | 2 | only with explicit `--include-agents`; 200 + 750 credits |
| `trade/quote` | 1 | safe read, zero Nansen credits; included in routine/complete |
| `trade/bridge-status` | 1 | safe read only with an existing tx hash from env |
| `trade/prepare` | 1 | never scheduled; human-only signable-intent probe |
| `trade/execute` | 1 | never available in the generic probe; broadcasts real money |
| **Total** | **53** | every client route is covered or explicitly blocked |

Every structural call bypasses the 30-minute response cache but still passes through the normal
Nansen telemetry throat. The final line reconciles logical attempts against fresh network rows;
cache hits or a mismatch return a non-zero exit code.

The tool persists only a daily aggregate (`runs`, wire count, planning budget and outcome counts).
It never saves response bodies, wallet results, quotes, transactions or keys.

## Inspect without spending anything

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_endpoint_sweep.py --list
./venv/bin/python3 tools/nansen_endpoint_sweep.py --profile complete
./venv/bin/python3 tools/nansen_endpoint_sweep.py --profile agents
./venv/bin/python3 tools/nansen_trade_probe.py quote --wallet "$NANSEN_SWEEP_TRADE_WALLET"
```

All four commands above are plans: zero network calls.

## One fresh run

Routine: 47 calls, about 212 planning credits. It omits three expensive structural routes and both
Agent routes, but includes a zero-credit trading quote:

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --profile routine \
  --max-wire 50 --daily-wire-cap 700 --daily-credit-cap 6000 --reserve-credits 15000
```

Complete structural run: 49 structural reads + trading quote = 50 fresh calls, conservative planning
budget about 412 credits:

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --profile complete \
  --max-wire 55 --daily-wire-cap 700 --daily-credit-cap 6000 --reserve-credits 15000
```

Agent pair: exactly two fresh Agent calls, 950 credits total. `use_cache=False` is enforced. Keep it
once daily rather than every two hours:

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --profile agents --include-agents \
  --max-wire 2 --daily-wire-cap 700 --daily-credit-cap 6000 --reserve-credits 15000
```

One exact endpoint:

```bash
./venv/bin/python3 tools/nansen_endpoint_sweep.py --run \
  --only prediction-market/orderbook --max-wire 1
```

## Twelve runs per day

A complete run every two hours produces up to **576 fresh structural/quote calls per day**. One Agent
pair adds 2 calls and 950 credits. The conservative total remains below the default 6,000-credit
daily planning cap. Before each paid route the sweep checks a recent remaining-balance snapshot;
after each response it requires a new valid credit header or stops non-zero.

Review the three lines first. `CRON_TZ=UTC` keeps twelve runs in the same accounting day as the
UTC state file, including across host timezone/DST changes:

```cron
CRON_TZ=UTC
7 */2 * * * cd <BOT_DIR> && ./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --profile complete --max-wire 55 --daily-wire-cap 700 --daily-credit-cap 6000 --reserve-credits 15000 >> <SWEEP_LOG> 2>&1
37 3 * * * cd <BOT_DIR> && ./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --profile agents --include-agents --max-wire 2 --daily-wire-cap 700 --daily-credit-cap 6000 --reserve-credits 15000 >> <SWEEP_LOG> 2>&1
```

Only a human installs scheduler state. To install after review:

```bash
crontab -e
```

Paste the two lines, save, then verify:

```bash
crontab -l
tail -100 <SWEEP_LOG>
```

The process also takes an exclusive lock, so a manual run and cron run cannot overlap. A 429, 402,
bad request, timeout, provider error, UTC rollover or truncated profile returns non-zero instead of
letting cron report success.

The wire cap and conservative planning cap are hard against the aggregate state. Endpoint prices
not published by Nansen remain estimates, so the 6,000 number is not claimed as exact billed spend.
The 15,000 reserve is a conservative guard, not a promise about exact billed spend: before every
paid route it requires a recent integer balance, and after every response it requires a newly dated
valid remaining-credit header. A missing/malformed/stale header stops non-zero. Because unpublished
route prices remain estimates and another process can spend concurrently, only Nansen Usage
Analytics is authoritative for exact remaining credits.

## Trading commands

Trading endpoints consume **zero** Nansen credits. They are useful integration checks, not credit
burn.

Read-only quote:

```bash
./venv/bin/python3 tools/nansen_trade_probe.py quote \
  --wallet "$NANSEN_SWEEP_TRADE_WALLET" --run
```

Read-only bridge reconciliation for an existing transaction:

```bash
NANSEN_SWEEP_BRIDGE_TX_HASH='<existing source tx>' \
./venv/bin/python3 tools/nansen_trade_probe.py bridge-status --run
```

Prepare + provider simulation creates an unsigned signable transaction. It requires all three human
steps: `--run`, `--yes-create-signable`, and typing `PREPARE SIGNABLE` in a live terminal. Cron,
pipes and non-interactive subprocesses are rejected. Amount is bounded by the configured trade cap
(default $300) and slippage by 1–500 bps:

```bash
./venv/bin/python3 tools/nansen_trade_probe.py prepare \
  --wallet "$NANSEN_SWEEP_TRADE_WALLET" --run --yes-create-signable
```

The tool prints only simulation status and field names. It does not print or save the quote or
unsigned transaction, does not sign and does not execute.

`trade/execute` is deliberately unavailable:

```bash
./venv/bin/python3 tools/nansen_trade_probe.py execute
```

It exits with `BLOCKED BY DESIGN`. Execute has no dry mode, changes onchain state, cannot be retried
blindly after timeout, and is not a legitimate way to increase Nansen usage.

## Interpreting the report

A healthy ending looks like:

```text
RESULT: logical=48 · telemetry network=48 · cache=0 · skipped=0
CREDITS: before=... · after=... · reserve=15000 · daily planned=.../6000
```

`empty` is a successful API response with no rows. `badreq` means our body was rejected and should
be fixed. `unsupported` is a provider coverage boundary. `rate_limited`, `no_credits`, timeout and
HTTP errors are not data verdicts.

Official Usage Analytics remains authoritative for total usage. Local planning estimates are
conservative guard rails, not invented endpoint prices.
