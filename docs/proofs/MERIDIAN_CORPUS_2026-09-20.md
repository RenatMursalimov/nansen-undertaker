# Meridian corpus proof — 20 Sep 2026

Command run by the owner after reviewing the dry-run plan and explicit upper bound:

```bash
./venv/bin/python3 tools/nansen_meridian_corpus.py --run --max-calls 1050
```

Result:

```text
Discovered tokens: 155
Pending token-day-side cells before run: 2,170
Client invocations: 1,050 (hard cap 1,050)
Network calls recorded by local telemetry: 1,050
Cache hits: 0
Latest unique corpus cells: 1,048
Tokens represented in completed/latest cells: 75
Top-100 partial cells: 414
Unresolved transient failures: 2
```

The corpus is not a repeated-call counter. It combines current Smart Money activity with seven
completed UTC days of historical BUY/SELL observations and stores aggregate counts/volumes only —
not buyer wallet addresses. A 100-row page is marked partial rather than presented as full coverage;
transient failures remain retryable and the report uses only the latest attempt per cell.

Exploratory examples from the resulting aggregate ranking:

| token | chain | BUY > SELL days | net aggregate |
|---|---|---:|---:|
| DRV | Base | 7/7 | $8.51M |
| JUPSOL | Solana | 7/7 | $6.75M |
| BIKETYSON | Solana | 7/7 | $3.28M |
| BP | Solana | 7/7 | $2.52M |
| LEVERCAT | Solana | 7/7 | $2.02M |

These rankings are explicitly exploratory because 414 cells reached the top-100 page limit.

## Eligibility boundary

Local telemetry proves that this tool made 1,050 network calls during the eligible date window.
The **authoritative contest eligibility evidence remains Nansen Usage Analytics**, which must show
at least 1,000 calls between Sep 14–27. Save a screenshot from the Nansen dashboard before submission.
