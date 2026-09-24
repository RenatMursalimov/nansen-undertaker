# The demo video: link, what is in it, transcript

**Watch it:** <https://x.com/Rencrypta/status/2103016647061656017>
(posted by the author — <https://x.com/Rencrypta> — during the Nansen Meridian Buildathon)

Recorded live on a phone, in Telegram, on live Nansen data — no staged screens, no rehearsal mode.
Length ≈ 3 minutes.

## Why this file is not `VIDEO_SCRIPT.md`

Two different things, and mixing them up would be the dishonest part:

* [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md) is the **plan**: a 12-shot, 110-second cut with a written
  narration line per shot, plus the rule *never say a number the screen is not showing*. It also
  drives the voiceover tool, which reads its lines from that file;
* **this** file is the **record of what was actually published**: the link, the running order of the
  take, and the transcript.

The published take follows the plan's *spirit* and not its shot list: it is a live walkthrough in one
pass, with the author speaking over the screen, and it covers the liquidation map first (the most
visual screen), then the market-conviction screen, then the token card and the free-form agent. The
scripted 110-second cut remains available for a second, tighter take.

## Running order of the published take

| Time | On screen | What it demonstrates |
|---|---|---|
| 0:00–0:20 | Telegram → menu → Trends → **Nansen** | the whole integration lives inside an existing bot, grouped by question rather than by API family |
| 0:20–0:30 | opening the Telegram **mini-app** | the same numbers on a canvas, no second source |
| 0:30–1:20 | **🗺 Map**: longs red, shorts green, named money blue; **scale** and **detail** sliders; 28 levels; another ticker (HYPE); vertical ↔ horizontal | leverage grouped by liquidation price; both controls redraw without a new request for orientation |
| 1:20–1:55 | **🎭 Whose %** on a live market (Houston vs Seattle, 47%) | price says what people believe, this says *whose* money it is |
| 1:55–2:25 | chat: `bitcoin` → token card → **Nansen** button | the Nansen block hangs off the card the user already has; no address typing |
| 2:25–3:02 | free-form question to the agent: *does Nansen show smart-money purchases of Ethereum?* → the answer names the window and says **no netflow data for native ETH over 24h** | the honest-refusal path on camera: the agent says what is missing instead of inventing a number |

That last frame is the one worth pausing on. The product's central claim is *eight ways to say I do
not know*, and the video ends on one of them being used for real, not described.

## Transcript

Auto-transcribed from the recording. **Only product names were corrected** — the speech-to-text
heard *Nansen* as “nothing”/“nonsense”, *longs* as “lones”, *Whose %* as “both percent”, *either
orientation* as “eyes orientation”, *Claude* as “Cloud” and *ChatGPT* as “charge GPT”. The rest is
left verbatim, including the rough spoken grammar: this is a live recording, and cleaning it up would
make the record a paraphrase.

```text
[00:00:00] Hi everyone, Nansen enthusiasts. I'm going to show you the integrating my AI agent with
Nansen. So go to my Telegram agent, The Undertaker. I'll show you a few scenarios below the menu.
First, let's get over to the Trends section. Tap Nansen. Nansen has a bunch of features grouped by
category. Let's jump into the Telegram mini app Nansen screens. I'll show

[00:00:30] you something really cool right away. Tap Map. Perpetual leverage grouped by liquidation
price. Longs in red, shorts in green, and in blue the money in wallets Nansen has a name for. Two
sliders, scale and detail. How wide the price window and how finely to cut it.

[00:00:53] more 28 levels you can choose another Hyperliquid more scale less scale the same numbers
either orientation you can choose a vertical or horizontal orientation and no new request for the
redraw. Okay guys, go to

[00:01:23] new features, go to Whose %. It's for the market, prediction market says, for example,
Houston with Seattle, 47 % after market. Everyone sees the price. Nobody sees whose money it is.
Nansen knows. We screen, ask it, all the money examined here, how much it is, who holds it, who was
usually wrong. Can show you next one.

[00:01:54] type bitcoin

[00:02:01] and we see card of bitcoin on any token tap Nansen and we get any information from Nansen
about bitcoin on any tokens ok good information, useful information and you see charts bitcoin and
Nansen information plus Don't forget, this is an AI agent, and you can select Claude or ChatGPT
[00:02:31] and it can process any text-based query type. Does Nansen show any smart money purchases
of Ethereum according to Nansen? or type okay and Nansen has no smart money net flow data for native
Ethereum over 24 hours all right thank you everyone I've only shared a brief overview but there are

[00:03:02] so many different use cases with Nansen friends bye
```

## What a judge can reproduce from the video without a key

Everything in the mini-app frames, in a browser, in under a minute — the same screens read recorded
fixtures in rehearsal mode:

```bash
git clone https://github.com/RenatMursalimov/nansen-undertaker && cd nansen-undertaker
python3 -m http.server 8080
# http://127.0.0.1:8080/webapp/index.html?rehearsal=1
```

The yellow REHEARSAL banner in that mode is deliberate and cannot be hidden from the page: the video
was recorded **without** it, which is what makes the video live data rather than a replay.
