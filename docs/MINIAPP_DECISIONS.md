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


## The caption under the picture was a brick of plain text, and it said "Nansen" twice

Spotted by the owner in a group: *“why is it solid text with no formatting”* and *“why write this
below if Nansen is at the start”*. Both were true, and both were in the same three lines of code.

**Plain text.** `liq_caption` joined its sentences with a space, and `send_photo` was called without
`parse_mode`. So eight statements arrived as one paragraph. The cost is not only visual: the caption
carries *different* statements — the size of the densest cluster, the total on the map, whose money it
is, and **what is not on the map at all** — and glued into a paragraph the last of those is the one a
reader skips. One line per statement now, with the qualifiers marked, because a qualifier changes the
meaning of the number above it.

**The source twice.** The picture already carries a `Nansen` mark burnt into the canvas (bottom right,
`fig.text`), and that mark survives being forwarded as a file — which is exactly what the source line
is *for*. Repeating it in the caption of the same message is noise. The caption therefore takes
`on_image=True` from `liq_map_png` and omits the source; the **text-only** fallback (no picture, no
canvas, no mark) still names it, because there nothing else does. The rule: *one source claim per
object, on the part of the object that survives sharing.*

This is guarded by tests rather than by care: the caption must be multi-line, its markup must be
balanced, the text-only variant must name Nansen, the on-image variant must not, **and** the canvas
mark must exist in the drawing code — without that last check, removing the line would be removing
the claim.

Two consequences that are easy to miss:

* **markup means escaping.** Wallet labels come from Nansen, and one `&` or `<` in a label makes the
  markup invalid — Telegram then rejects the whole message and the person gets *nothing* instead of a
  map. Anything from the provider is escaped now (`_h`), and a test feeds a label containing both;
* **the caption is trimmed by Telegram's own measure** (`tg_html.fit`), not by `cap[:1024]`. A blind
  slice lands inside a tag and produces the same total rejection. The token card was fixed this way
  earlier; the map was still on the naive slice.

The single-line captions of the other pictures (flows, probability) still repeat the source, and that
is left as it is for now rather than swept silently — a one-line caption does not have the problem
that was reported, and a test currently *requires* the source in those captions.

## A collision the frame check could not see

With the horizontal layout the price marker `now $67.3K` is drawn at the right edge — and so are the
per-bar amounts. On the live render the marker landed on top of `$11.80M`: two different numbers read
as one string. Nothing was outside the canvas, so the "everything inside the frame" measurement was
green, and the defect was visible only in the picture.

**Resolution rule: the dashed price line wins.** The amount of the row the marker sits on is not
drawn — that number is still on the money axis and in the detail line under the chart, while the price
marker is unique and has nowhere else to go. Same "if it does not fit, do not draw it" rule, except
what crowds the label is another label rather than the frame.

The render harness now compares every pair of `<text>` rectangles for overlap, in both orientations,
in addition to comparing each one with the canvas. Currently zero overflows and zero collisions. This
is the second time in this project that a chart defect was found by measuring the rendered page rather
than by reading the code (the first was the invisible bars on the sharp-money screen), which is why
the check is in the harness and not in a reviewer's eye.


## One unit per axis, and labels that must differ

A live screenshot of the ETH map (28 levels) showed a price ladder ending like this:

```
$5.2K · $4.5K · $4.4K · … · $1.1K · $796.21
```

Every number is correct. The defect is that the **last one is in different units**, so a reader has
to convert it in their head — and an axis exists for exactly one purpose, comparison by eye. The
same thing happened inside a single sentence: *between $796.21 and $5.2K*.

The fix is not a fixed format but a **search**, because two rules collide here and one of them is
stronger:

1. one unit for the whole axis (comparability);
2. **different levels must get different labels** (meaning) — this is the rule that created the
   custom price formatter in the first place, back when the caption read *cluster between $62K and
   $62K*.

So the formatter walks a ladder — axis unit → the general price format → plain numbers with
increasing precision — and takes the first step at which **all** labels are distinct. Rule 2 can
never be silently broken by an improvement to rule 1, because the search steps down by itself.

This was caught on my own change, one minute after making it: the first version applied the axis
unit unconditionally and printed *between $1.2K and $1.2K* for a cluster spanning \$1,150–\$1,190 —
resurrecting the very bug the function was written to prevent. The guard that followed it (fall back
to the general format) was also not enough, because that format rounds to the same \$1.2K. Only the
full ladder is correct.

Both implementations — the bot's (for the chat picture) and the page's (for the canvas) — carry the
same ladder in the same order, are named as a deliberate pair in the comments, and are asserted by
tests on the same set of numbers.

## The same quantity printed twice: the third catch

The detail line under the map read:

```
$930.2K between $95.51 and $97.77 · mostly SHORT · $930.2K of it named
```

Two identical numbers in one line, and a reader looks for the difference between them. The map
caption had been fixed for this case, then the risk board, and this is the **third** place the same
value was printed twice. When everything in a bar is named, the line now says so in words.

Three catches of one defect in three renderers is itself the finding: the *rule* lives in the number
layer (named ≥ total means "all of it"), and each renderer re-implemented the sentence. The number
layer now carries the comparison, and each screen prints its verdict.

## A scene with no surface is work nobody can see

`smart_trades` — the flagship signal of the whole integration, a smart-money trade next to the
**share of the token's market cap** it represents — was registered in the scene list, had a recorded
fixture, had a price in the gateway, and appeared on **no tab at all**. Everything existed except the
surface.

It now leads the `➕ More` tab. The bar is the trade as a share of market cap, and the threshold below
which a share is not drawn comes from the dictionary, not from the page.

A test now walks the scene registry and requires each scene name to appear in the page, so a scene
can no longer be complete-but-invisible.

## Refusals name the status code on the screen

The sharp-money screen failed on a live provider error and said: *this is a provider failure, not a
verdict; the status code is in the bot log.* That sentence asks a person holding a phone to go read a
server log — and the difference between 402 (out of credits), 429 (rate limited) and 502 (their
outage) is three different actions.

The code was already in the call box (`note()` records it). It now travels in the envelope
(`http_status`) and is printed next to the outcome class. Not showing a number we already have, and
pointing at a log instead, looks like screen hygiene and costs the reader server access.

## What "Sharp money" explains about itself

The owner's words: *"Sharp Money пока непонятно как работает"* — and the screen deserved that. It
had a slogan (*price says what people believe, this says who believes it*) which explains the idea
and not the picture. Three things were missing, all now on the screen: what is being compared (four
of the most traded markets, side by side), what the two bars are (money held by wallets that were
right more often vs wrong more often, by **lifetime** record), and why the order is by sharp dollars
rather than by share (90% of \$300 is not a signal). Plus the honest price: this is the expensive
screen — one request per market and one per holder.


## A list with no way out is a dead end (27 Sep)

The owner tapped through the live build and wrote seven remarks. Six of them are one sentence:
*«должен же быть сквозной сценарий везде»* — every screen answered its own question and stopped.
You could see that smart money bought a token, that a market is priced at 65%, that a holder has a
67% win rate — and there was nothing you could do with any of it.

Three crossings were added, all of them landing on a card that already exists in the bot: token →
token card, market → market card, wallet → account card (full address to copy, labels, tracking).

### The deep link did not work, and the page could not tell

The first implementation built `t.me/<bot>?start=…` and called `openTelegramLink`. The owner's
verdict: *«Кнопочки Open in the bot, Open на Холсте не открывают в Гробовщике ничего»*. The link
points at the chat of the **same bot** whose mini app is open, and the shell does not perform that
navigation — for it, you are already there. Worse, the method returns nothing, so a refusal by the
shell is indistinguishable from success: the page could not even report the failure.

The crossings now use the mechanism that was already proven live in this project — **ask the bot**.
The bot posts the card into the chat, and the page prints what the bot answered. A status line is
attached to **each button**, not one per screen: the first version had a single note at the bottom
of the card, the owner tapped a button in the middle of a list, the answer appeared off-screen, and
the conclusion was «ничего не произошло». An answer that arrives somewhere else is not an answer.

### No address leaves the browser, and nothing is guessed

The wallet crossing had to work without ever sending a full address to the page (that rule is why
the holder rows show `0x676c…e139` and nothing more). So the page sends the **row number** plus the
first characters of the label it drew, and the bot finds the address in the same provider response
the canvas was drawn from. If the list moved between drawing and tapping, the prefix no longer
matches and the bot **refuses**: opening the neighbouring wallet would be a true answer about the
wrong wallet, and that kind of error is invisible to the person reading it.

The same rule applies to the token crossing: the ticker travels (the person sees it on screen), the
contract is resolved by the bot in the same cached list of trades, and a ticker that is no longer in
the fresh list gets an honest refusal rather than a similar-looking token.
