# Meridian final gate — go top to bottom

Deadline: **September 27, 2026, 23:59 UTC**. Better to submit on the 26th.

## 0. Eligibility — before everything else

- [x] Meaningful corpus completed locally: **1,050 network calls**, 0 cache hits, hard cap respected.
- [x] Nansen Usage Analytics: **5,484 calls on 20 Sep**, 13,850 total in 30D — threshold met.
- [ ] Saved a CROPPED screenshot of Usage Analytics: only the Nansen panel, no browser chrome/
      bookmarks/wallet balance.
- [x] Corpus run completed; **do not run again for eligibility** if Usage Analytics confirms
      ≥1,000. Two transient failures do not affect the threshold.
- [ ] After the corpus, Usage Analytics checked again. Local telemetry does not replace the
      dashboard.

## 1. Hero live proof

- [x] Primary live proof passed (`1130012`): 4 requests, 3 known histories, 0 provider failures; hero metric $500.4K / 58% below 40% win rate.
- [x] Backup live proof passed (`4323345`): 4 requests, 3 known histories, 0 provider failures; opposite metric $0 / 0% below 40%.
  ```bash
  ./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 1130012
  ./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 4323345
  ```
- [x] Primary live smoke: `LIVE PROOF: PASS`, known histories 3, provider failures 0.
- [x] Backup live smoke: `LIVE PROOF: PASS`, known histories 3, provider failures 0.
- [ ] The `🎭 N` button opens the same market_id that was in the list row.
- [ ] The screen fits in roughly 20 seconds on a cold cache (10s holders + 10s summaries;
      usually faster).

## 2. Verifiable numbers

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_daily.py --submission 2026-09-14 2026-09-27
./venv/bin/python3 tools/nansen_daily.py --range 2026-09-14 2026-09-27 --csv > /tmp/nansen_window.csv
./venv/bin/python3 tools/nansen_daily.py --contrib
```

- [ ] The short `--submission START END` and the explicit `--range START END` show the same window.
- [ ] "Days with data" is named honestly; gaps are not smoothed over with an average.
- [ ] The scene table reconciles with the total calls/credits — the line `reconciles with the total`.
- [ ] `calls with no scene = 0`. Not zero — fix it or explain before the entry.
- [ ] `pm_reputation`, `liq_map`, `pm_chart`, `pm_orderbook` are visible as separate scenes.
- [ ] Unpriced calls go on a separate line and are not mixed into measured credits.
- [ ] The CSV contains no `u` and no 0x addresses.
- [ ] Local network calls reconciled with Usage Analytics; for eligibility Usage Analytics leads.

## 3. Video — strictly 30–60 seconds

The script is next to this checklist: `DEMO_SCRIPT.md`.

- [ ] Target 52 seconds, understandable without sound.
- [ ] One storyline: `A market says 78% YES. But whose conviction is it?`
- [ ] `polymarket markets` → `🎭 N` → headline → holder rows → unknown coverage → footer.
- [ ] Live Nansen data visibly loads; not a fixture and not a pre-inserted image.
- [ ] No personal addresses, participants, admin screen, key, or service DMs in the frame.
- [ ] Do not show tests, forced failure, Agent, trading, telemetry and all 25 workflows.
- [ ] If the primary market does not pass — re-record with a pre-checked backup.

## 4. Public repo

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_catalog.py --write
./venv/bin/python3 tools/export_nansen_public.py --out ~/nansen-undertaker
cd ~/nansen-undertaker
python3 tests/test_public.py
python3 scrub.py
git status --short
```

- [ ] https://github.com/RenatMursalimov/nansen-undertaker opens in incognito.
- [ ] CI green.
- [ ] README starts with the hero question, not with no-key/tests/counts.
- [ ] `docs/CATALOG.md`, `docs/WINNER_PLAN.md`, `docs/DEMO_SCRIPT.md`, `docs/X_THREAD.md`,
      `docs/submission.md` exist.
- [ ] `.env`, `nansen_tele/`, cache/schema/credits/refs/corpus/db are absent.
- [ ] `tools/telemetry_rollup.py` is absent (a legacy reader of a different format is not exported).
- [ ] `MANIFEST.md` matches, stale managed files removed by the exporter.

## 5. X thread

The text is next to this checklist: `X_THREAD.md`.

- [ ] Video attached to post 1.
- [ ] `@nansen_ai` and the repo URL are in post 1, not only in the last reply.
- [ ] The call count is taken from Usage Analytics and is ≥1,000; no placeholder published.
- [ ] Hero screenshot — reputation; second screenshot — liquidation map.
- [ ] The thread does not sell "53 endpoints" as the hero. The hero is **who is behind this probability?**

## 6. Official entry form

- [ ] Email.
- [ ] X post URL.
- [ ] Public GitHub URL.
- [ ] Submitted on September 26, not in the last hour of the 27th.
- [ ] Saved the screenshot/confirmation URL.
- [ ] In the adjacent `README.md` (`docs/submission.md` in the public repo) the `<ADD ...>`
      placeholders are replaced and the status is changed only after confirmation.

## 7. Freeze

- [ ] After recording, do not add new features.
- [ ] Only critical fixes; after each — a new live smoke and a check of the video/repo links.
