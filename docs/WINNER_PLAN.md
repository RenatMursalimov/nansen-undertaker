# Nansen Meridian: a plan to win, not to ship one more endpoint

Revision date: 2026-09-20. Deadline: **September 27, 23:59 UTC**.

## Verdict of the independent review

The integration is technically broad: 58 API routes in the client, 32 documented workflows,
eight failure classes, telemetry, images, Telegram commands and buttons. But breadth by itself
does not win the contest. It even gets in the way if, in 60 seconds, a judge is trying to figure
out what exactly to remember.

**There is one winning product:**

> A Polymarket market says 78% YES. The Undertaker answers: **whose 78% is it** — how much money
> behind the side belongs to wallets that guessed right before, and how much history is unknown
> to us.

This is not a dashboard and not "five more fields". Nansen data changes the analytical
conclusion: the same 78% becomes a different object depending on the quality of the money behind
the probability.

**Two proofs of depth, but not two competing pitches:**

1. the liquidation map — where by price other people's leverage sits;
2. a smart-money buy as a percentage of market cap — $48K into a $2.1M token is 2.3% of the
   entire cap, the same $48K into a $50B token is noise.

The semantics of honest refusals, the cost of each screen and reproducible telemetry are the
**trust moat**, but not the headline. In the clip they get one line, in the README — the
technical depth.

---

## What the rules require — four equal quarters

Per the [official campaign page](https://nansen.ai/campaigns/meridian-buildathon) four equal
parts are judged: Data Integration, Functionality, Creativity & Originality, Documentation &
Submission. Per the [official FAQ](https://nansen.featurebase.app/help/articles/3540155-nansen-meridian-buildathon-sep-14-27)
also mandatory:

- **1,000+ API calls** specifically between September 14 and 27;
- a public GitHub;
- an X post tagging `@nansen_ai` with a link to the GitHub;
- a 30–60 second screen recording with **live** Nansen data, understandable without sound;
- submitting the entry form before September 27, 23:59 UTC.

### Our matrix

| Criterion | What we present | Risk right now |
|---|---|---|
| Data Integration 25% | top holders + lifetime wallet history **themselves determine** the hero-screen conclusion; plus liquidation levels and smart-money % of mcap | the live hero has to be run after hardening |
| Functionality 25% | a working Telegram flow + live smoke + public offline tests | no video yet; needs a stable market_id |
| Creativity 25% | "whose 78%?" — nothing like it in public examples | must not dilute 25 workflows into one pitch |
| Documentation 25% | public repo, generated catalog, exact demo script, reproducible live smoke | the README must stay hero-first, without conflicting counters |

---

## P0: 1,050 network calls done; eligibility awaits the Usage Analytics screenshot

On September 20 the meaningful corpus finished exactly at the hard cap: **1,050 client
invocations, 1,050 network calls, 0 cache hits**. This happened inside the contest window.
Sanitized proof: `nansen/proofs/MERIDIAN_CORPUS_2026-09-20.md`.

An authoritative external artifact was obtained: the Usage Analytics screenshot shows **5,484
calls on September 20** and 13,850 total in 30D. Sep 20 alone already exceeds the mandatory
1,000 inside the window. Before publishing, the screenshot must be cropped to the Nansen panel:
in the original there is browser chrome, bookmarks and a wallet-balance area.

Do NOT run the corpus again for eligibility if the dashboard already shows ≥1,000. It built a
real 7-day research corpus for low-cap discovery:

```bash
# Already done on September 20. The commands are kept for reproducibility, DO NOT repeat for the threshold.
./venv/bin/python3 tools/nansen_meridian_corpus.py --max-calls 1050
./venv/bin/python3 tools/nansen_meridian_corpus.py --run --max-calls 1050
```

Result: 155 tokens found, 1,048 latest unique cells over 75 tokens, 414 top-100 partial cells
and 2 transient failures. The checkpoint stores only aggregated counts/volumes, **without buyer
addresses**. The ranking is explicitly exploratory because of the partial cells.

After the run, still check Nansen Usage Analytics anyway: cache hits are not network calls, and
local telemetry does not know about calls made before it was installed.

---

## Competitors and what is worth learning from them

### smartmoney.sh

[Public example](https://x.com/zacxbt/status/2098107107094733016): a terminal for buys, sells and
PnL of smart wallets across several chains. [A user's feedback](https://x.com/0xsammy/status/2098400411417727302)
shows the real value: finding low-cap tokens with meaningful flow.

**Strength:** one clear daily task. **Our difference:** Telegram is already where the person
sits; plus % of market cap, Polymarket and leverage.

### id8.markets

[Public example](https://x.com/BawsaXBT/status/2098224639436808575): a user formulates a thesis,
the tool interrogates it, forces them to lock in a numeric invalidation condition and then
watches it. It does not send a trade.

**Main lesson:** what wins is not showing data but a workflow with a position. And a good tool
does not just help — it **constrains** the person, not letting them take size without a
thesis-death condition. This is the next product after the contest; do not start it next to the
submission before the 27th.

### Zatto

[Public repo](https://github.com/sneg55/zatto): measures how many new buyers arrived after a
smart-money buy, and what happened to the price a day later; separates "crowded" from "quiet",
has a live demo, CI and a live proof script.

**Strength:** a narrow claim, a measured method, a live URL. **Our difference:** the quality of
the money behind a Polymarket probability, not crowding behind a token. **What to borrow:** a
live proof as a separate command and one narrow claim in the first line of the README.

### General takeaway

Do not win by the number of endpoints. Win by a new question that Nansen lets you answer:
**who is behind this probability?**

---

## The 52-second clip without sound

Before recording:

1. English interface/chat, no personal addresses and no service chats.
2. One pre-checked active market + one backup.
3. Sufficient credits remaining.
4. Live proof:
   ```bash
   ./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id <ID>
   ```
   Up to 4 read-only calls at `top=3`; needs at least one `known history` and `provider
   failures: 0`.
5. Record **live** Telegram, not fixtures.

### Frames

| Time | Frame | On-screen text |
|---:|---|---|
| 0–3 | black title card | `A market says 78% YES. But whose conviction is it?` |
| 3–9 | Telegram → `polymarket markets` | live list, probability/volume, `Source: Nansen` |
| 9–12 | tap `🎭 1` | `Checking holders — up to 6 live Nansen requests` |
| 12–26 | hero result | highlight: `Of $X examined, $Y (Z%) sits with wallets below 40% win rate` |
| 26–35 | two holder rows | Yes/No, entry→current, win rate, PnL |
| 35–41 | honesty row | `N holders have no measurable history — counted on NEITHER side` |
| 41–47 | footer | `Source: Nansen · just now · requests: N` |
| 47–52 | final card | `Nansen data changes the conclusion — not just the UI` + repo URL |

**Do not show in the main clip:** tests, forced failure, Agent, trading, telemetry dashboard,
24 scenarios. They prove depth in the README but eat the story.

**Backup clip**, if holder histories are unstable: `smart trades` → highlight `% of mcap` →
`liquidation map BTC`. More reliable, but less original.

---

## Roadmap to September 27

### September 20–21 — reliability and eligibility

- [x] merge winner-hardening: exact market identity, partial-failure semantics, parallel
      summaries, separate telemetry scenes;
- [x] run live smoke on primary `1130012` and backup `4323345`;
- [x] meaningful corpus finished: 1,050 network calls, 0 cache hits, hard cap respected;
- [x] Usage Analytics: 5,484 calls Sep 20, 13,850 total 30D; threshold confirmed;
- [ ] save the cropped Usage Analytics screenshot without browser chrome/wallet area.

### September 22–23 — content, not new features

- [x] pick the primary `1130012` and backup `4323345` markets;
- [ ] record 2–3 silent takes, pick one without a glitch;
- [ ] frame-by-frame check: no participant addresses, keys, service DMs;
- [ ] make the hero screenshot and the liquidation-map screenshot.

### September 24–25 — X and submission

- [ ] publish the thread from `nansen/submission/X_THREAD.md`, first post with the video;
- [ ] tag `@nansen_ai` and the public repo in the first post;
- [ ] collect the numbers with `tools/nansen_daily.py --submission START END`;
- [ ] reconcile local calls with Nansen Usage Analytics (the dashboard leads for eligibility);
- [ ] fill in the entry form, do not wait for the last hour.

### September 26 — submit a day early

- [ ] submit before the 27th, ideally on the 26th;
- [ ] save the confirmation URL/form screenshot;
- [ ] no more changing hero logic without a critical bug.

### September 27 — control only

- [ ] public repo accessible without authorization, CI green;
- [ ] the X video opens without sound and the link leads to the repo;
- [ ] no `<TBD>` in the submission draft.

---

## What NOT to do before the deadline

- do not add more endpoints for the sake of the number;
- do not build thesis-invalidation/watch-conviction before closing eligibility/video/form;
- do not make a live trade the main demo — it leads away from the unique Polymarket insight and
  adds security/reliability risk;
- do not demo 24 workflows in a row;
- do not claim "1,000 calls" from the local log: only from Usage Analytics.

---

Internet sources are paraphrased, not copied verbatim. Content was rephrased for compliance with
licensing restrictions.
