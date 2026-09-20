# Silent demo script — 52 seconds

Goal: a judge understands the product with sound off.

## Preflight (not recorded)

Selected live markets from Sep 20:

- **Primary:** `1130012` — strongest hero result: $500.4K / 58% of examined money below 40% historical win rate.
- **Backup:** `4323345` — PASS with the opposite conclusion: $0 / 0% below 40%, three known histories.
- Do not use `4319462`: it has resolved to 0¢/100¢.

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 1130012
./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 4323345
```

Accept a market only when the tool ends with:

```text
LIVE PROOF: PASS
known histories: 1+
provider failures: 0
```

Also check:

- English chat/UI;
- live key and enough credits;
- public repo and CI open in an incognito window;
- no private wallet, participant username, admin screen or key in frame;
- one primary and one backup market written down before recording.

## Timeline

| Time | Action | What must be visible |
|---:|---|---|
| 0–3s | title card | **A market says 78% YES. But whose conviction is it?** |
| 3–9s | type `polymarket markets` | live list, probability, volume, `Source: Nansen` and freshness |
| 9–12s | tap `🎭 1` | acknowledgement: up to 6 live Nansen requests |
| 12–26s | result arrives | **Of $X examined, $Y (Z%) sits with wallets below 40% win rate** |
| 26–35s | short scroll | Yes/No split; two holder rows with entry→current, win rate and PnL |
| 35–41s | stop on coverage warning | unknown histories are counted on **NEITHER** side; partial API failures are named separately |
| 41–47s | stop on footer | `Source: Nansen · data just now · Requests: N` |
| 47–52s | end card | **Nansen data changes the conclusion — not just the UI.** + repo URL |

## Recording rules

- One take, 30–60 seconds. Target 52.
- No narration needed; cursor/highlight carries attention.
- Do not show tests, terminal, forced failure, Agent, trading, telemetry or all workflows.
- Do not cut away while live data loads: functionality must be visible.
- If the hero call fails, do not publish that take. Use the pretested backup market.
- The numbered button is bound to the exact market id; an old button never re-resolves against a
  changed ranking.

## Backup demo

If no active market has measurable wallet histories:

1. `smart trades` — highlight trade value as % of token market cap;
2. `liquidation map BTC` — highlight the largest liquidation cluster;
3. end card: **Raw Nansen rows become decision context: signal size and where leverage breaks.**

This is more reliable but less original; use only as backup.
