# Contest video: script, shot list and narration (110 seconds)

One idea per shot, one number per sentence. The narration is the **only** text that gets voiced;
everything else in this file is stage direction.

**Why 110 seconds and not three.** A judge decides in the first fifteen seconds whether this is
another dashboard. So the hook is a question, not a feature list, and the first real number arrives
before second 20. The script grew from 90 to 110 seconds for exactly two reasons — two screens that
answer a question the others cannot (what is still *going to be* bought, and what is happening to
the holders of one market) — and for nothing else. Every shot that only showed a feature was cut.

**The rule this video follows:** never say a number the screen is not showing at that moment. If a
take drifts and the words run ahead of the picture, the take is wrong — not the script.

---

## Before recording (checklist)

1. `?rehearsal=1` **off**. The yellow REHEARSAL banner in a frame means the take is unusable —
   that is exactly what the banner is for;
2. prepare a market with mixed holders (some sharp, some weak). A market where everything is
   `$0 (0%)` is technically correct and visually dead;
3. open `📡 Live` once before recording so the day's log is not empty;
4. phone in dark mode, notifications off, one Telegram chat open (`/start` screen clean);
5. have the chat command `карта ликвидаций BTC` ready to paste — the video shows the bot answering
   in chat too, not only the mini-app;
6. **check the two screens that depend on the response of the day**: `➕ More` leads with *"still to
   be bought"*, and if every DCA program in the answer is closed it says so in words. That is
   honest, but it is a weak frame — glance at it before the take and pick the moment when there is
   something still ahead. Same for the chain ranking: if the change came back zero for every chain,
   the screen says *"not measured in this window"*, and that sentence is worth having in frame only
   if you intend to talk about it.

---

## Shot list

| # | Time | On screen | Narration (voiced) |
|---|---|---|---|
| 1 | 0:00–0:11 | Telegram chat. Type `кто держит рынок`. The bot's answer appears. | "A prediction market says ninety percent yes. Everyone sees the price. Nobody sees whose money it is." |
| 2 | 0:11–0:23 | Tap the mini-app button. The hero screen loads: one bar per holder, two grey bars. | "Nansen knows. This screen asks it: of the money examined here, how much sits with wallets that were usually wrong." |
| 3 | 0:23–0:33 | Point at the grey bars, then at the caveats under the chart. | "Two holders have no measurable history. Their money is counted on neither side, and the screen says so instead of rounding it away." |
| 4 | 0:33–0:45 | Same hero. Tap `🧾 who is in it, with PnL`. Rows with entry price and profit or loss. | "The same market, one level deeper: who is in it, at what price they entered, and how far up or down they are right now. No identifier is typed anywhere — it travels from the card." |
| 5 | 0:45–0:56 | Tab `🎯 Sharp`. Four markets side by side, green and red bars. | "The same question across four heated markets at once. Sorted by sharp dollars, because ninety percent of three hundred dollars is not a signal." |
| 6 | 0:56–1:04 | Tap a row → it opens in `🎭 Whose %`. | "Tap a market and you are back in the breakdown. One market, one answer — there is no second version of this number anywhere in the product." |
| 7 | 1:04–1:20 | Tab `🗺 Map`. Switch BTC → HYPE. Drag the **scale** slider ±50% → ±10%, then the **detail** slider. The chart redraws; the sliders stay on screen. | "Perpetual leverage, grouped by liquidation price. Longs in red, shorts in green, and in blue the money on wallets Nansen has a name for. Two sliders: how wide a price window, and how finely to cut it." |
| 8 | 1:20–1:28 | Under the chart tap `↕ vertical`, then `↔ horizontal` back, then `💾 save image`. | "The same numbers, either orientation, and no new request for the redraw. Saved as a picture, the map is something you can send to someone." |
| 9 | 1:28–1:38 | Tap `⚔️ compare top four`. The board appears. | "Four tokens ranked by how close the price is to the densest cluster — not by how big it is. Three percent away and forty percent away are different situations." |
| 10 | 1:38–1:49 | Tab `➕ More`. The first line names how much is still to be bought; scroll to the chain ranking. | "Every other screen here reports the past. This one reports a commitment: money already placed on buying that has not happened yet. Below it, where the money sits across chains." |
| 11 | 1:49–1:58 | Tab `📡 Live`. Rows scroll in real time. | "Every row is one call to Nansen: endpoint, outcome, milliseconds, credits, cache or wire. This is live data, and here is the proof." |
| 12 | 1:58–2:06 | Back to the chat: the bot's picture of the same map, caption line by line. | "The app computes nothing. It draws the same dictionary the bot uses for its chat message, so the picture and the words cannot drift apart." |

**Closing card (no narration, 2 seconds):** `github.com/RenatMursalimov/nansen-undertaker` ·
"Fifty-eight Nansen routes. Thirty-two workflows. Eight ways to say I do not know."

> The three numbers on the closing card are asserted by the test suite against the code, so the card
> cannot quietly go stale: `58` routes and `52` structural reads come from `tools/nansen_endpoint_sweep.py`,
> `32` workflows from `tools/nansen_catalog.py`, and the eight refusal classes from `nansen_api`.

---

## Narration, as one block (for the voiceover tool)

> A prediction market says ninety percent yes. Everyone sees the price. Nobody sees whose money it is.
>
> Nansen knows. This screen asks it: of the money examined here, how much sits with wallets that were usually wrong.
>
> Two holders have no measurable history. Their money is counted on neither side, and the screen says so instead of rounding it away.
>
> The same market, one level deeper: who is in it, at what price they entered, and how far up or down they are right now. No identifier is typed anywhere — it travels from the card.
>
> The same question across four heated markets at once. Sorted by sharp dollars, because ninety percent of three hundred dollars is not a signal.
>
> Tap a market and you are back in the breakdown. One market, one answer — there is no second version of this number anywhere in the product.
>
> Perpetual leverage, grouped by liquidation price. Longs in red, shorts in green, and in blue the money on wallets Nansen has a name for. Two sliders: how wide a price window, and how finely to cut it.
>
> The same numbers, either orientation, and no new request for the redraw. Saved as a picture, the map is something you can send to someone.
>
> Four tokens ranked by how close the price is to the densest cluster — not by how big it is. Three percent away and forty percent away are different situations.
>
> Every other screen here reports the past. This one reports a commitment: money already placed on buying that has not happened yet. Below it, where the money sits across chains.
>
> Every row is one call to Nansen: endpoint, outcome, milliseconds, credits, cache or wire. This is live data, and here is the proof.
>
> The app computes nothing. It draws the same dictionary the bot uses for its chat message, so the picture and the words cannot drift apart.

---

## Voiceover in English: what the bot can already do

The bot has a working text-to-speech door (`tts.py`, Yandex SpeechKit) and the key is already on
the server. SpeechKit has an English voice — `john` (en-US, male). Emotions are Russian-only, so
the English path sends no emotion at all; sending one would be rejected.

```bash
# PLAN: prints every line, its shot number and the character count. Sends NOTHING.
cd <BOT_DIR> && ./venv/bin/python3 tools/nansen_voiceover.py

# RENDER: one ogg per shot + one joined track, into nansen/voiceover/
cd <BOT_DIR> && ./venv/bin/python3 tools/nansen_voiceover.py --run
```

The tool reads the lines **from this file**, not from its own code: a second copy of the script
inside a tool is a copy that drifts from the shot table on the first edit. Change a line here and
the voiceover changes with it.

## What is deliberately not in this video

* **the agent.** It works and it is the expensive path (200 or 750 credits). A judge who sees an
  LLM answer stops reading the numbers, and this submission is about numbers with a named source;
* **trading.** The bot can place an order on a prediction market, and none of that contour is
  reachable through the mini-app gateway — by absence, not by a check. A trading frame would move
  the conversation from data to risk;
* **the endpoints with no schema.** `tgm/position-intelligence` still answers 422 to every body
  shape we have tried. It is documented as unresolved in `nansen/ENDPOINT_SWEEP.md` rather than
  demonstrated as working.
