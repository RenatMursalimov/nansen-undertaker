# Contest video: script, shot list and narration (90 seconds)

One idea per shot, one number per sentence. The narration is the **only** text that gets voiced;
everything else in this file is stage direction.

**Why 90 seconds and not three minutes.** A judge decides in the first fifteen seconds whether
this is another dashboard. So the hook is a question, not a feature list, and the first real
number arrives before second 20.

**The rule this video follows:** never say a number the screen is not showing at that moment. If a
take drifts and the words run ahead of the picture, the take is wrong — not the script.

---

## Before recording (checklist)

1. `?rehearsal=1` **off**. The yellow REHEARSAL banner in a frame means the take is unusable —
   that is exactly what the banner is for;
2. prepare a market with mixed holders (some sharp, some weak). A market where everything is
   `$0 (0%)` is technically correct and visually dead;
3. open `📡 Live calls` once before recording so the day's log is not empty;
4. phone in dark mode, notifications off, one Telegram chat open (`/start` screen clean);
5. have the chat command `карта ликвидаций BTC` ready to paste — the video shows the bot answering
   in chat too, not only the mini-app.

---

## Shot list

| # | Time | On screen | Narration (voiced) |
|---|---|---|---|
| 1 | 0:00–0:11 | Telegram chat. Type `who holds this market`. The bot's answer appears. | "A prediction market says ninety percent yes. Everyone sees the price. Nobody sees whose money it is." |
| 2 | 0:11–0:24 | Tap the mini-app button. The hero screen loads: one bar per holder, two grey bars. | "Nansen knows. This screen asks it: of the money examined here, how much sits with wallets that were usually wrong." |
| 3 | 0:24–0:34 | Point at the grey bars, then at the caveats under the chart. | "Two holders have no measurable history. Their money is counted on neither side, and the screen says so instead of rounding it away." |
| 4 | 0:34–0:46 | Tab `🎯 Sharp money`. Four markets side by side, green and red bars. | "The same question across four heated markets at once. Sorted by sharp dollars, because ninety percent of three hundred dollars is not a signal." |
| 5 | 0:46–0:58 | Tap a row → it opens in `🎭 Whose %`. | "Tap a market and you are back in the breakdown. One market, one answer — there is no second version of this number anywhere in the product." |
| 6 | 0:58–1:12 | Tab `🗺 Liquidations`. Switch BTC → HYPE. Tap the scale buttons: ±50%, then ±10%. | "Perpetual leverage, grouped by liquidation price. Longs in red, shorts in green, and in blue the money on wallets Nansen has a name for. The scale is yours: fifty percent around the price, or ten." |
| 7 | 1:12–1:22 | Tap `⚔️ compare top four`. The board appears. | "Four tokens ranked by how close the price is to the densest cluster — not by how big it is. Three percent away and forty percent away are different situations." |
| 8 | 1:22–1:32 | Tab `📡 Live calls`. Rows scroll in real time. | "Every row is one call to Nansen: endpoint, outcome, milliseconds, credits, cache or wire. This is live data, and here is the proof." |
| 9 | 1:32–1:40 | Back to the chat: the bot's message with the same sentence under the chart. | "The app computes nothing. It draws the same dictionary the bot uses for its chat message, so the picture and the words cannot drift apart." |

**Closing card (no narration, 2 seconds):** `github.com/RenatMursalimov/nansen-undertaker` ·
"Fifty-five Nansen routes. Twenty-nine screens. Eight ways to say I do not know."

---

## Narration, as one block (for the voiceover tool)

> A prediction market says ninety percent yes. Everyone sees the price. Nobody sees whose money it is.
>
> Nansen knows. This screen asks it: of the money examined here, how much sits with wallets that were usually wrong.
>
> Two holders have no measurable history. Their money is counted on neither side, and the screen says so instead of rounding it away.
>
> The same question across four heated markets at once. Sorted by sharp dollars, because ninety percent of three hundred dollars is not a signal.
>
> Tap a market and you are back in the breakdown. One market, one answer — there is no second version of this number anywhere in the product.
>
> Perpetual leverage, grouped by liquidation price. Longs in red, shorts in green, and in blue the money on wallets Nansen has a name for. The scale is yours: fifty percent around the price, or ten.
>
> Four tokens ranked by how close the price is to the densest cluster — not by how big it is. Three percent away and forty percent away are different situations.
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

The tool prints the duration of every rendered file, so the shot list above can be trimmed to the
audio rather than the other way round. If a line runs long, shorten the **line**, not the pause.

**If a different voice is wanted** (ElevenLabs sounds better for narration and costs a few
dollars for this script): the tool takes the text from this file only, so switching the engine is
one function — say the word and the key, and it becomes another provider without touching the
script.
