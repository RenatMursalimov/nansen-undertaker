# Final live market selection — 20 Sep 2026

Two additional read-only live smoke runs were made after winner hardening. Both passed with fresh
Nansen data, three known wallet histories and zero provider failures. Holder wallet addresses are
omitted from this proof.

## Primary demo market — `1130012`

**Question:** Will United Russia (ER) gain the most seats in the next Russian parliamentary
election?

```text
LIVE PROOF: PASS
Requests: 4
Known histories: 3
Provider failures: 0
Source: Nansen, data just now
```

Hero result:

```text
Examined money: $858.5K
Money belonging to wallets below 40% historical win rate: $500.4K (58%)
All top-holder positions: Yes $1.53M · No $145.4K
```

Three examined holders:

| side | value | entry → current | historical win rate | lifetime PnL | markets |
|---|---:|---:|---:|---:|---:|
| Yes | $464.3K | 76¢ → 90¢ | 30% | +$7.2K | 54 |
| Yes | $358.2K | 76¢ → 90¢ | 56% | +$1.58M | 2,044 |
| No | $36.0K | 21¢ → 10¢ | 34% | -$120.9K | 1,108 |

Seven more top holders were **not examined** because the smoke test deliberately caps wallet
history lookups at three. The product does not claim those wallets lack history.

### Why this is primary

The headline is immediately legible without narration: **58% of examined money is controlled by
wallets below the visible 40% historical win-rate threshold.** It demonstrates that the Nansen
holder and wallet-history data changes the interpretation of a 90% market price rather than merely
adding fields to a dashboard.

The market topic is political. The recording and X text must stay strictly analytical and neutral:
this is composition of market conviction, not a political prediction or endorsement.

## Backup demo market — `4323345`

```text
LIVE PROOF: PASS
Requests: 4
Known histories: 3
Provider failures: 0
Source: Nansen, data just now
```

Hero result:

```text
Examined money: $270.0K
Money belonging to wallets below 40% historical win rate: $0 (0%)
All top-holder positions: No $575.5K · Yes $37.0K
```

Three examined holders:

| side | value | entry → current | historical win rate | lifetime PnL | markets |
|---|---:|---:|---:|---:|---:|
| No | $238.7K | 52¢ → 92¢ | 80% | +$197.4K | 10 |
| Yes | $17.0K | 48¢ → 8¢ | 44% | +$511.1K | 209 |
| Yes | $14.3K | 48¢ → 8¢ | 43% | -$7.75M | 22,470 |

### Why this is backup

It passes the same end-to-end path and demonstrates the opposite outcome: none of the examined
money falls below 40%. That is useful evidence that the tool is not hard-coded to produce an
alarming conclusion. It is less visually memorable than 58%, so it is the reliability backup, not
the main recording.

## Market no longer suitable — `4319462`

The first proof market (Manchester City FC on Sep 20) was useful for finding presentation defects,
but it has resolved: current prices were 0¢/100¢. Do not use it in the final video because a resolved
market weakens the “live conviction” story.

## Recording decision

1. Run primary `1130012` immediately before recording.
2. If it still returns `PASS`, known histories ≥1 and failures 0, record it.
3. If it fails or resolves, switch to `4323345`.
4. Do not discover a new market during the recorded take; discovery belongs to preflight.
