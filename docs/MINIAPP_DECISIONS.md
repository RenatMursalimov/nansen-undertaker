# Mini-app: the decisions, including the one to not ship a screen

## Part C: the fourth screen is NOT added. Branch 3 — now by measurement.

**Two live probes on 2026-09-22 settled it, and the record is a fact rather than a shortage of
hours.**

Probe 1 — `422`, not `404`, with a machine-readable instruction:

```
Required field 'body -> date' is missing.
Expected format: {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
```

So the path exists and the body is parsed. Probe 2 sent the window and learned the decisive part:
the platform **does not know the fields `chain` and `token_address`**. Repair-by-the-provider's-words
removed both and the request returned `200 {"data": []}`.

**That 200 is the trap, and it is worth naming.** Repair strips fields the platform rejects — which
here meant stripping the very fields that carry the question *“which token?”*. What came back was a
syntactically valid query with no meaning, and its empty answer reads like *“there are no posts”*
when the truth is *“we never asked properly”*. This is the project's own ban on “emptiness passed off
as a measurement”, arriving from an unexpected direction: the repair mechanism itself.

General rule extracted: **repair is right when the platform says “a field is missing” (we can supply
it) and harmful when it says “I do not know your field” (it throws the question away).** For
discovering a field *name*, repair must be off — the raw refusal is the answer. The `ra` group was
therefore removed from `FIX_DEFAULT`.

### Probe 3 answered the name, and the answer closes the branch

Seven requests, one candidate field name each, repair off. The platform answered precisely:

| field sent | answer |
|---|---|
| `token_address` (control) | `422` — “Field 'token_address' is not recognized” |
| `token_addresses` | `422` — not recognized |
| `tokens` | `422` — not recognized |
| `token` | `422` — not recognized |
| `address` | `422` — not recognized |
| **`token_symbol`** | **`200`, 10 rows** |
| no token filter (baseline) | `200`, `data: []` |

So the schema is now known: `ra-agent/posts-by-token` takes **`token_symbol`** (a ticker, not an
address) plus the `date` window. The control case behaved as predicted, and the baseline explains what
“empty” means here — without a ticker the endpoint returns nothing, so the earlier empty answers were
our missing question, not missing coverage.

**And the response fields settle Part C: `likes, text, timestamp, tweet_id, username, views`.
There is no language field.**

Branch 1 was defined by that field: posts *with their language* next to the money flow, as a hybrid
with our Chinese slice. The language does not exist in the response, so branch 1 as specified cannot
be built. Nothing here was a guess and nothing was wasted: the endpoint is now documented, the schema
is known, and the cost of learning it was **12 credits of ~58,300**.

**Decision: still branch 3 — no fourth screen before the deadline.** Not because the endpoint is dead
(it is alive and cheap), but because the screen that was planned needs a field the platform does not
return, and inventing a substitute — guessing language from the text, or shipping a narrative feed
with no link to the Chinese slice — would be a different screen than the one reasoned about, designed
in the last hours before a recording. Three screens that hold up beat four with one improvised.

What is left behind is a fact, not a shrug: the schema is written down here, so connecting
`ra-agent/posts-by-token` later is a client function plus a formatter, not another round of probing.

## Why branch 3 was the right call even before the probe

The plan allowed three branches for one extra scene, to be chosen **by the result of a probe**:

1. `ra-agent/posts-by-token` answers and carries the post language → build “what they say vs what
   they do” (narrative next to money flow);
2. it does not → build “route price” on `trade/quote` (0 credits);
3. neither is assembled in time → **do not add the scene.**

**Chosen: branch 3, and the reason is a fact, not a shortage of hours.** The probe cannot be run
where this work was done: there is no live Nansen key in the build environment, and
`ra-agent/posts-by-token` is not in the client at all — its very existence is the open question.
Adding a screen on an unprobed endpoint would break the project's oldest rule: do not promise what
was not measured. A screen that renders an endpoint nobody called is exactly the “door into a wall”
defect the integration already paid for once (four dead clients, then `profiler/address/perp-positions`
buried on a single 404 and resurrected a day later).

The probe itself is shipped, so the decision can be revisited in thirty minutes with one command:

```bash
./venv/bin/python3 tools/nansen_probe.py --only ra          # plan, zero calls
./venv/bin/python3 tools/nansen_probe.py --run --only ra     # two read-only requests
```

Read three things off the raw answer: the status code (200 alive / 404 no such path / 422 path
exists but our body is wrong), whether a language field is present (`lang`/`language`/`locale`), and
whether Chinese posts appear at all. Without a language field the hybrid with our Chinese slice
cannot be built, and then the screen is not worth having.

Branch 2 was not taken either, and deliberately: `trade/quote` is read-only and free, but putting any
trading route into the mini-app gateway would put the trading contour on a public surface for the
sake of a screen nobody asked for. `trade/prepare` and `trade/execute` are unreachable through the
gateway **by absence** — they are not in the scene list, so a request for them returns the same
“unknown screen” as a typo, without confirming such a handle exists.

## The gateway is a mailbox, not a route, and that is not a shortcut

The plan asked for `GET /nansen/<scene>`. That shape is impossible here, and the reason is
architectural rather than stylistic: **the bot has no inbound port.** The mini-app stack is a
Cloudflare Worker (signature check + mailbox) plus a bot that *polls* that mailbox. The Nansen key,
the per-user limits and the telemetry all live in the bot.

A real `/nansen/<scene>` route on the Worker could only answer from the Worker's own storage — which
means a second source of numbers, and Law 0 dead on the first screen. So the gateway is a new signal
kind (`nsn`) in the existing mailbox: the browser asks, the bot computes, the answer comes back. The
browser never sees the key, and the numbers have exactly one origin.

## Two leaks the scrubber caught before production

Both were found by `tools/record_fixture.py` re-reading what it had just written, not by review:

1. `payload.rows[].addr` — a **token contract** address. Not personal data, but the screen does not
   draw it, so it is no longer sent. “Do not send what you do not show” is cheaper than loosening a
   scrubber rule.
2. `payload.first_row` — the **raw provider row**, kept for schema diagnostics and carrying every
   field Nansen returned, including fields that do not exist there yet.

Both are stripped in `nansen_gate._strip_private`, on the same path the live screen uses. A second
implementation of the stripping would have diverged silently.

## A limit bug caught on our own test

The first version of the gateway called the shared `nansen_limits.check(uid, …)`, which includes the
**agent** question counter (3/day). On the third run it refused a liquidation map with “your
questions for today are used up”. In the bot that limit applies to the agent only — structural
screens at 1–5 credits are not capped. Applying it in the mini-app would have introduced a rule the
bot does not have: free in chat, refused in the app. The gateway now checks the shared daily credit
cap only, knows the price of the pending screen before allowing it, and never touches the agent
counter. Spend is counted where it always was — one telemetry row per network call.

## Telemetry: a new surface, not a new scene

The mini-app writes `surface=miniapp` on the **same** scene names. Giving it its own scene names
would have split “market reputation” into two rows of the daily summary, and neither row would
answer “what did this screen cost in total”. The column is appended at the end of the log line, so
files written before this change still parse.


## An added quantity that erased the main one (caught on a live screenshot)

The liquidation map got a second quantity: how much of each cluster sits on wallets Nansen has a
name for (`address_label` from `tgm/perp-positions`). It was drawn as an inner bar across the **full
width** of the column.

On HYPE every one of the 45 positions carries a label. The inner bar therefore covered 100% of every
column, and the map went **single-coloured**: longs and shorts — the entire point of that chart —
disappeared from the screen while the legend kept promising red and green. The bug is not in the new
number; it is in letting an *additional* quantity occupy the same pixels as the *primary* one.

Fix: the named-money bar is now a narrow stripe down the centre of the column (42% of its width), so
the side colour stays visible at any share, including 100%. In the chat image the same rule was
already in force by accident — there the inner bar is half the height of the outer one.

The caption learned the 100% case too: instead of making a person compare `$1.01B` with `$1.01B`, it
says *“every position on this map sits on a wallet Nansen has a name for; the biggest: …”*.

Long labels were cut mid-word (`Uses "TRADEXYZ1" HL Refe`), which reads as corrupted data rather than
as an abbreviation. They are now cut at a word boundary with an ellipsis.

## Four tickers were four hardcoded tickers

The map offered BTC/ETH/SOL/HYPE — a list kept by hand in the page. Measured against Hyperliquid on
2026-09-24, the actual top by 24h volume was `BTC, ETH, HYPE, ZEC, NEAR, SOL, XRP, UNI, KPEPE, TAO`:
half of the buttons pointed away from where the leverage actually is, and the list would have rotted
further in silence.

Now the ticker list is **measured**: `oc_perps.hl_universe()` returns every perp coin in one request
(`metaAndAssetCtxs` — the same response the price marker already used), `hl_top_tokens()` orders it by
24h volume, and the list travels in the envelope as `known_tokens`. The page renders buttons from it
and keeps the hardcoded four only as a fallback for when the venue is silent — a screen with no
tickers at all would look broken.

The map is **not** limited to that list: the mini-app has a free ticker input, and the chat command
`карта ликвидаций <TICKER>` always accepted any ticker. An unknown ticker returns a state from the
gateway (“no positions came back”), not a guess from the page about what exists.

The risk board follows the same measured order (top four), instead of comparing whatever four were
frozen into the code.


## A slider that "worked with a delay" was a slider being deleted and rebuilt

The owner's words: *“when you move the slider it works with a delay, and it disappears together with
the detail; the sliders should stay and be easy to move with the mouse, and the maps should redraw.”*

The instinct is to blame the network, and it would have been wrong. The handler set `LIQ.env = null`
and the sliders were rendered **from the envelope** — so while the request was in flight the page
deleted its own controls and put them back a second later. The knob jumped and lost focus because the
`input` node was being recreated under the finger, not because the answer was slow. Tapping a bar did
the same thing: it rebuilt the entire screen, which is why the detail line “disappeared with the
sliders”.

Three separate operations now, instead of one rebuild for every event:

| what happens | what is rebuilt |
|---|---|
| first answer, ticker change, orientation change | controls + result |
| tap on a bar, board toggle, "updating…" | result only |
| answer for the same ticker | nothing — knob values and labels are *set*, not recreated |

The law that the active step is marked **from the answer** (not from the tap) survived; it is now
enforced by setting values on live nodes. One thing had to be corrected on the render harness: the
first version called that sync while the request was still in flight, which rewound the knob to the
*previous* answer the moment the finger let go — visually “the slider jumps by itself”, the very
complaint being fixed. During a request the controls are not touched at all.

Each request carries a sequence number. Two quick drags used to mean the first answer could repaint
the screen while the second was still in flight — showing a setting the person had already changed
their mind about.

## Two orientations, and the horizontal one is the default again

*“Why did you rebuild it vertical, it was horizontal.”* Correct twice over: the picture the bot sends
to chat is horizontal (`barh`), and horizontal labels need **no rotated text** — and rotated numbers
were exactly what escaped the card's frame. The vertical layout is kept as an option, because its
dashed price line reads like a candlestick chart. Neither is “right”, so the choice belongs to the
person: `↔ / ↕` redraws the same numbers with **zero** requests.

The row order matches the chat image: cheap levels at the bottom, expensive at the top. Drawn the
other way the map would be numerically correct and semantically upside down, and two different
pictures of one dataset read as an error.

**Numbers are clamped into the canvas, and a label that does not fit is not drawn at all.** An
amount cut in half looks like real data; a missing one sends the reader to the detail line under the
chart, where the number is in full. Verified by measurement rather than by eye: the render harness
compares every `<text>` rectangle with the `<svg>` rectangle in both orientations at 8/14/20/28
levels — currently zero escapes.

The slider says “14 levels” while the map may show five bars, and that needed one sentence rather
than a fix: detail is how many equal slices the window is **cut into**, and a slice with no money in
it is not drawn. Without that sentence the screen looks like it cannot count.

## Save as an image: the colours had to leave the CSS

`💾 save image` serialises the chart's SVG into a canvas and writes a PNG at ×3 scale (320 px is a
phone width; the labels would be unreadable in a file). Two details are load-bearing:

* the chart's fills used to be `var(--long)` / `var(--short)`. CSS custom properties **do not exist**
  inside an extracted SVG, so the saved file would have come out colourless. Hardcoding the hex
  values in the script would have created a second palette that silently drifts from the first, so
  the colours are read from the page itself (`getComputedStyle`) and written into the markup as
  numbers;
* Telegram's in-app browser does not always allow a page to write a file. The button therefore
  **does not promise success**: if the download does not land, the screen says so and names the path
  that always works — the bot sends the same map as a picture in chat.

## The “➕ More” tab, and why this is not the fourth screen that was refused

*“Didn't you add other tabs with features to the canvas?”* Two signals moved onto the canvas, chosen
by what the existing screens could **not** answer:

* **scheduled buying (DCA)** — the only forward-looking signal in the set. Every other screen reports
  the past: who already holds, where leverage already hangs. A DCA program is money committed to
  buying *later*, and the bar shows how much of it is already spent;
* **chain ranking** — the only screen that is about neither a wallet nor a market, but about where the
  money is at all. It answers “where to look today” before an object is picked.

This does not contradict Part C above. That refusal was about a screen whose central field
(`language`) the platform does not return. These two run on endpoints whose schemas were **measured**
by live probes on 2026-09-24, and both already worked in chat — the canvas gave them a surface, not a
second implementation: same dictionary, same telemetry scene name, so app and chat spend adds up on
one row.

## “Who is in this market” is attached to the market card, not to a tab of its own

The owner caught the same defect for the second time: *“I look and you are again making the user hunt
for the market identifier.”* The screen existed only as the command `позиции рынка <id>`, and there
is nowhere to get that id except someone else's website — the command required work **outside** the
bot.

A tab of its own would have reproduced the bug, because on entering a tab no market is selected yet,
so it would have to ask. The screen is therefore a button on the already-open market card in the app,
and the row **🧾 N** under the market list in chat — the id rides in the callback, next to 📈, 📖 and
🎭, which were fixed the same way earlier. The command stays as the fast path for whoever already has
an id, and the menu hint now points at the button instead of teaching a number by example.

## A number quietly damaged by a stray `.rstrip`

Found while splitting the chain ranking into numbers and words: the active-address count was formatted
and then passed through `.rstrip('0').rstrip('.')`, so **500 active addresses printed as “5”**. A
truncated figure is worse than a missing one, because it still looks like a measurement. The
formatting now prints what was measured, and the number goes through the same dictionary the mini-app
draws.
