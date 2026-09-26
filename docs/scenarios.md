# Nansen scenarios for the community — spec A4

**Input for spec B.** Eight scenarios, selected against these conditions: (1) they already
work, (2) the answer comes back in a single request, (3) a newcomer understands them,
(4) they cost a reasonable amount of credits.

**About the sample outputs.** These are reconstructed from the formatter code (file and line
cited for each). The shape, emoji, field order and labels are exact — they come from the code,
rendered in English mode (`/lang en`). The numbers and tickers are made up, to show the shape.
Before publishing any of these in the chat, each scenario should be run live once and its
example replaced with a real one: that is exactly the material for the B5 video demo.

**Language.** The bot is bilingual. Every command below has an English form the router
recognizes, every menu button has an English label, and every screen renders in English when the
user is in English mode. The Russian analog of this document is `scenarios_ru.md`.

**Credit prices** come from the official page docs.nansen.ai/api/overview (captured
2026-09-14), registry `nansen_log.py:101-109`. Where it says "not measured", the price is
neither in the overview nor in the client docstring, and the zero is there on purpose instead of
a guess.

---

## 1. Smart money flows: where the smart money goes

- **Ask:** button 🔗 Onchain → 🧠 Nansen → 💹 Smart flows, or type `smart flows`
- **Price:** cheap, **not measured**. Endpoint `smart-money/netflow`
- **Code:** `oc_menu.py:537` (button handler), `oc_dm.py:1380` (text), formatter
  `nansen_api.py:1423`
- **Has a window switch:** 1h / 24h / 7d / 30d, buttons `ocm:sm:*` (`oc_menu.py:440-441`)

Sample output shape (`nansen_api.py:sm_netflow_block`):

```
🧠 Smart money inflow, 24h (Nansen netflow):
1. WIF [solana] · +$4.10M
2. PENDLE [ethereum] · +$1.82M
3. AERO [base] · -$960.4K
...
The buttons below switch the window · tap a ticker to open the card.
```

**Why someone in the chat cares.** One screen answers the question asked every single day in
the chat: "what are people even buying?" The tickers are clickable — you jump into the token
card without copy-pasting an address. The window switch shows whether an inflow is a one-off or
holds for a week.

---

## 2. What Smart Money accumulates

- **Ask:** button `ocm:run:nsn_holdings` (`oc_menu.py:418`), or `smart holdings`
- **Price:** ~1-5 credits. Endpoint `smart-money/holdings` (`nansen_api.py:857`)
- **Code:** `oc_dm.py:1338`, scene `oc_dm.py:1346`, text assembly `oc_dm.py:1355-1371`

```
🧠 What Smart Money holds (top by $):
1. ETH [ethereum] — $412.30M (+3% 24h)
2. SOL [solana] — $88.10M (-1% 24h)
3. PENDLE [ethereum] — $21.40M (+12% 24h)
...
Tap a ticker to open the token card.
```

**Why.** Flows (scenario 1) are about the last 24 hours of movement; holdings are about the
position. The difference between "they bought in today" and "they've held for a while" is what
a newcomer confuses most often, and the two scenarios side by side show that difference
clearly.

---

## 3. Wallet dossier by labels

- **Ask:** `profile 0x…`, or the 🕵 Dossier button under a bare address dropped into the chat
- **Price:** cheap, **not measured**. Three endpoints: `profiler/address/labels`,
  `profiler/address/pnl-summary`, `profiler/address/related-wallets`
- **Code:** one door with two entrances — `oc_dm.py:780`, regex `oc_dm.py:1306`,
  button `oc_callbacks.py:875`. Formatter `nansen_api.py:1069`
- **Careful:** the suffix `deep` switches to premium labels at **150 credits**
  (`oc_dm.py:1311`, `nansen_api.py:875`). Advertise it in the community **without** the suffix

```
👤 Wallet profile 0x1234…abcd [ethereum]
🏷 Smart Money · DEX Trader · Fund
📈 realized PnL +$1.24M · ROI +38% · win rate 61% · trades 412
💼 top tokens: ETH, PENDLE, AERO, WIF, LINK
🔗 related wallets: 5+ (funded_by, interacted)
```

**Why.** Exactly the scenario from the spec — "profile an address from the chat feed with one
command." Addresses get thrown into the chat constantly; today people answer with guesses. Here
Nansen labels answer in seconds, and — crucially — when there are no labels the bot says exactly
that, rather than "the address is clean" (`oc_dm.py:752`).

---

## 4. 🧠 Token breakdown

- **Ask:** the 🧠 button in the first row of any token card (`hub_scanner.py:217`), or
  `passport 0x… deep`
- **Price:** **16 credits** — the most expensive of the selected set. Four endpoints:
  `tgm/flow-intelligence` (1) + `tgm/indicators` (5) + `tgm/holders` (5) +
  `tgm/pnl-leaderboard` (5)
- **Code:** `oc_callbacks.py:352-388`, assembly `nansen_api.py:1348`

```
🧠 Nansen · token breakdown

🧠 Nansen flows 24h: 🧠SM +$1.20M · 🐳whales +$840.0K · 🏦CEX -$310.5K
📊 Nansen Score: risk 🟡 medium · potential 🟢 bullish (4/6)
🏷 In top-20 holders: 6 🧠 smart money, 3 🏛 funds, 2 🏦 CEX
🏆 Top traders by PnL (realized):
1. Smart HL Perps Trader: +$412.0K · ROI +180%
2. 0xab12…9f04: +$210.5K · ROI +96%
```

**Why.** The only scenario that answers "is this token worth a look" in a single tap: flows,
risk, who is in the holders, who made money. The 16-credit price against 5 for the others means
one 🧠 equals three other scenarios, not eight, as the docstrings had implied. For a community
kit that is no longer an expensive scenario.

---

## 5. Top perp traders

- **Ask:** button `ocm:run:nsn_perps` (`oc_menu.py:419`), or `top perps`
- **Price:** ~5 credits. Endpoint `perp-leaderboard` (`nansen_api.py:927`)
- **Code:** `oc_dm.py:1315`, formatter `nansen_api.py:1125`

```
🏆 Top perp traders (Hyperliquid, 7d):
1. Smart HL Perps Trader: +$2.10M · ROI +240%
2. 0xcd34…7a11: +$1.05M · ROI +88%
...
Tap a trader to open their account (DeBank).
```

**Why.** A ready-made list of who is worth following, with a tap-through to the account. Cheap
and self-explanatory.

---

## 6. Trending prediction markets

- **Ask:** button `ocm:run:pm_markets` (`oc_menu.py:431`), or `polymarket markets`
- **Price:** **not measured**. Endpoint `prediction-market/market-screener`
- **Code:** `oc_dm.py:1409`, formatter `nansen_api.py:1505`

```
🎲 Trending Polymarket markets (24h volume):
1. Will the Fed cut rates in September? · 68% · vol24 $4.10M
2. Government shutdown before October? · 31% · vol24 $1.882M
...
Tap a market below — I will open its card: price, volume, the id the commands take, and four
breakdowns of that market.

[1. Will the Fed cut rates in September?]
[2. Government shutdown before October?]
```

**Why.** A separate category of Nansen data that almost nobody in the chat knows. Price-as-
probability is the most vivid way to explain what a prediction market is.

**What changed on 27 Sep, and why.** This list used to print the `market_id` under every row and
carry a grid of numbered buttons (`📈 3 / 📖 3 / 🎭 3 / 🧾 3`) — forty buttons under ten rows. Both
halves put service values on the reader: the id is needed by *commands*, not by a person reading
a list, and picking `3` required remembering that three was the third row of text above. Now
there is one button per market carrying the question itself, and it opens the card of that
market, where the id is printed to be copied and the four breakdowns are labelled with words.
The list is shorter (six markets) for a reason: every row shown now has a button, whereas rows
6–10 used to have none at all.

---

## 7. Prediction market trader profile

- **Ask:** `polymarket profile 0x…`
- **Price:** **not measured**. Two endpoints: `address-summary` + `pnl-by-address`
- **Code:** `oc_dm.py:1427`, formatter `nansen_api.py:1525`

```
🎰 Polymarket · trader profile 0x1234…abcd
📈 PnL +$210.4K · realized +$180.2K · unrealized +$30.2K
🎯 win rate 58% · won 44/76 · age 412d
💼 top markets by PnL:
• Will the Fed cut rates in September? [Yes] · +$41.2K
• Government shutdown before October? [No] · -$8.10K
```

**Why.** Shows that win rate and PnL are different things: you can win more often and still lose
money. A good teaching scenario, and it is effectively free for the person.

---

## 8. Top traders of a specific market

- **Ask:** `market leaders <market_id>`
- **Price:** **not measured**. Endpoint `prediction-market/pnl-by-market`
- **Code:** `oc_dm.py:1447`, formatter `nansen_api.py:1578`
- **The `market_id` now comes from the market card** (scenario 6 → tap the market), which prints
  it as a copyable line — the chain that used to be broken is closed.

```
🏆 Market top traders
Will the Fed cut rates in September?:
1. 0xab12…9f04 [Yes] · +$88.10K
2. 0xcd34…7a11 [No] · -$41.20K
```

**Why.** The natural continuation of scenario 6 in one tap.

---

## What implementation must add (input for B1/B2)

1. **A source and freshness label in each answer.** Format: `per Nansen, captured 14 minutes
   ago` — or `captured just now` if the request went out to the network. (Delivered: every
   screen now ends with a `Source: Nansen` line via `with_source`.)
2. **Buttons for scenarios 7 and 8**, and a reachable `market_id`. (Delivered: one button per
   market under the list, and on the market card the four breakdowns plus the id printed to be
   copied. The first delivery was a grid of numbered buttons with the id under every row; it was
   replaced on 27 Sep because both halves made the reader carry a service value.)
3. **An honest refusal instead of "no data"** (A3-2, A3-3). Separately and mandatorily —
   "out of credits": during the contest that is the most likely refusal.
4. **Help.** By law 25, whatever is not in help does not exist for the user.
   Existing entries: `help_registry.py:170` (`nansen_smart`), `:484` (`nansen_polymarket`),
   `:141-152`.
5. **A limit on the `cx:nansen` button** — not part of the eight, but it is visible right there
   on the majors' cards, and one tap costs 200 credits, i.e. as much as forty of the cheap
   scenarios in the list and twelve times the cost of 🧠 (§A2).


---
---



# PART II. NEW SCENARIOS (addendum 2026-09-15)

Same format as the first eight: **what to type to the bot**, what comes back, the price, why it
matters to the person.

**All commands work from a DM and do not require turning on a mode** — they are registered in
the onchain-words registry. By button: `🎭 Modes` → `🔗 Onchain` → `🧠 Nansen`, where the hints
carry a copyable command.

---

## Scenario 9. Who bought in and who sold out

**What to type:** `who bought 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 7`
(the number at the end is days, default 7; `who bought sold 0x…` covers both sides)

**Comes back:** two groups — who net-bought and who sold, with Nansen labels and $ volumes.

```
🔄 Who bought and sold · base · 7d

🟢 Bought:
1. Smart Money · $1.20M
2. 0xab12…9f04 · $640.0K

🔴 Sold:
1. Whale A · $980.0K
```

**Price:** 2 credits (two requests, one per side) · **≈ $0.002**

**Why:** this is the answer to "who is even behind the move". The Smart Money label next to the
volume says more than the price itself.

**The chain is determined by fact**, not by the look of the address: the same `0x…` exists on
ten chains, and USDC with this address lives on Base. Earlier we queried on ethereum and got
nothing.

---

## Scenario 10. Leverage and liquidations by perp token

**What to type:** `perp positions BTC` (or `liquidations ETH`)

**Or by button:** `💥 Liq.` on the exchange token card (`BTC`, `ETH`, `SOL` — the card opens by
ticker). The label is short on purpose: a full one added an eighth row to the card.

**Schema captured live 09-19:** the endpoint requires the field `token_symbol`, but we were
sending `token` — and got a 422 on every tap. The repair, driven by the provider's own words,
stopped honestly and thereby named the field.

**Comes back:**
```
⚡ Open positions · BTC
1. Smart Money [LONG] · $10.70M · 20x · PnL -$120.2K · liq $71,234.50
```

**Price:** 5 credits · **≈ $0.004**

**Why:** before this endpoint **we had no liquidation price at all** — it was guessed from the
entry price. Now you can see the level at which the market will blow out someone else's
leverage, and that is exactly why people watch the whales.

---

## Scenario 10b. Liquidation map: where other people's leverage hangs

**What to type:** `liq map BTC`

**Or by button:** `🗺 Liquidation map` under the leveraged-positions screen — i.e. the path is:
`BTC` card → `💥 Liq.` → `🗺 Liquidation map`.

**Comes back:** an image — position sizes grouped by **liquidation price**. Red is longs, green
is shorts, the dashed line is the current price (from Hyperliquid). Plus a caption with the
magnitude (`oc_nansen_viz.py:liq_caption`):

```
BTC liquidation map. Biggest cluster: $22.5M between $61.5K and $62.4K.
Total on the map: $30.7M across 5 position(s). Longs $22.5M vs shorts $8.2M.
1 position(s) had no liquidation price and are NOT on the map.
This is where other people stop out, not a forecast. Source: Nansen.
```

**Price:** 5 credits (one request, the same one as the position list) · **≈ $0.004**

**Why:** the position list answers "who is in and with what leverage" — you have to read it and
add it up in your head. The question people watch leverage for is a different one: **at which
price level does the market move fast**, and the answer to that is not a line but a
distribution.

**Three honesties built into the screen:**
- positions **without** a liquidation price are not silently dropped, but named in the caption:
  a map over 5 of 6 and a map over 6 of 6 are different maps;
- emptiness is not drawn at all: an image made of zeros looks like a measurement;
- the caption says this is **not a forecast**.

**The current price is optional.** If it did not load — the map stays an honest map of levels,
just without a "you are here" marker.

---

## Scenario 11. Wallet perp account and room to liquidation

**What to type:** `nansen perp 0x…`

**Or by button:** 🧠 Nansen → 🩺 Wallet perp account.

**Comes back** (`nansen_api.py:wallet_perp_block`):
```
🩺 Perp account 0x1234…abcd
📈 equity $2.40M · margin $310.0K · unrealized +$180.2K
🩺 account health: 0.72
• BTC LONG 20x · liq $71,234.50
• ETH SHORT 10x · liq $4,120.00
```

**Price:** **not measured**. Endpoint `profiler/address/perp-positions`

**Why:** the main question about a leveraged whale is not "what does he hold" but "how much room
is left". This endpoint was briefly buried as a 404 on 09-19; a live path probe on 09-20 found
it alive at `profiler/perp-positions`, and the screen came back from git — a decision by fact,
not a hope in the code.

**What differs from scenario 10:** scenario 10 shows leverage and liquidation price **by token**
(everyone in it); this one shows a **single wallet's** whole perp account and its cushion.

---

## Scenario 12. What smart money is buying right now

**What to type:** `smart trades`

**Or by button:** 🎭 Modes → 🔗 Onchain → 🧠 Nansen → `🧠 Smart money trades now`.

**Comes back:**
```
🧠 Smart money trades, 24h
1. Smart Trader 1 AAA [base] · $48.3K · mcap $2.1M · 2.3% of mcap · 3d
...
Tap a ticker for the card.
```

**Price:** 1–5 credits · **≈ $0.004**

**Why:** `smart flows` gives the **total** over a window ("they bought $231K"), and this gives
the trades themselves. The total does not say who entered what; for a decision you need the
second one.

**About "2.3% of mcap" — that is the key number of the row.** "$48K went into a token" says
nothing until it says into WHAT exactly: the same $48K into a $2.1M token is 2.3% of the entire
market cap and a real signal, while into a $50B token it is noise. Market cap and age arrive in
the SAME answer (captured by the probe 09-19), so extra requests and credits — zero.

**Schema captured live 09-19:** the trade amount lives in the field `trade_value_usd`. Earlier
there were three names here, guessed from neighbouring endpoints, none matched — and the person
saw a dash in all twelve rows with readable tickers and addresses.

---

## Scenario 13. Flows as a chart

**What to type:** `flows chart 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`

**Or by button:** `📊 Flows chart` under the 🧠 Nansen breakdown on a token or meme card (tap 🧠
on the card → Nansen answer → button beneath it). Next to it is `🔄 Who bought and sold`.

**Comes back:** a photo — bars by segment (Smart Money, whales, top-PnL, public figures,
exchanges, fresh wallets). Green is accumulating, red is dumping. The source is baked into the
canvas itself.

**Price:** 1 credit · **≈ $0.001**

**Why:** a line of text answers "how much", a chart answers "who against whom". Smart money
accumulating while whales dump is visible on the bars in half a second; in text you have to
compare in your head.

**If there is no data — there will be no image, a text with the reason comes instead.** Six zero
bars look like a measurement and lie harder than the absence of an image.

---

## Scenario 14. Polymarket market chart

**What to type:** `polymarket chart 654412`

**Or by button:** `📈 Probability` on the market card (`polymarket markets` → tap the market).

**Where to get the market_id:** it is printed as a copyable line on the market card. Earlier the
hint promised "from the market screener", and the screener did not print the id at all — the
command existed only formally. Then the screener printed it under every row, which made the list
technical to read; now it lives one tap deeper, where it is needed.

**Comes back:** a photo — how the probability changed over 72 hours, the 50% line separating
"more likely yes" from "more likely no", the caption with the current value and the shift in
points.

**Price:** not measured · **Why:** we used to show the market price as a single number, but 45%
after 20% and 45% after 70% are opposite stories. One number on a prediction market means almost
nothing.

---

## Scenario 14b. Who holds the market and how they guessed before

**What to type:** `market reputation 654412` (or `who holds market 654412`)

**Or by button:** `🎭 Who holds it` on the market card.

**Comes back** (`nansen_api.py:pm_reputation_block`):
```
🎭 Who holds this market
654412

💰 Of $2.00M examined, $1.40M (70%) sits with wallets whose win rate is below 40%.
📊 Across all top holders: Yes $1.60M · No $550.0K

Holders (5 of 6 examined):
1. Whale A [Yes] · $800.0K · entry 12¢ → 45¢ · win rate 33% · PnL -$120.0K · 84 markets
2. 0xbbbb…bbbb [Yes] · $600.0K · entry 31¢ → 45¢ · win rate 71% · PnL +$340.0K · 210 markets
...
⚠️ 2 holder(s) have no measurable win rate — their money is counted on NEITHER side.
```

**Price: 6 requests** (holders + lifetime history of each of the five). Six times more expensive
than the neighbouring screens, and this is said both in the answer to the tap and in the screen
itself. The price is named **by the number of requests, not credits**: the prices of these
endpoints are not in the official list, and making one up would be a lie in the most verifiable
part.

**Why:** "78% Yes" is a consensus of **whom**? One number looks identical in two opposite cases:
the money was staked by wallets that guessed right in 70% of markets, or by wallets with a 35%
win rate. The first is a signal, the second an invitation to stand against it.

This is the "magnitude instead of a flag" law applied to probability: "the market believes in
Yes" is a flag, "$1.4M of $2.1M sits with wallets below a 40% win rate" is a magnitude.

**Three honesties:**
- the money of holders **without** lifetime history is not counted on either side;
- the number of such holders is stated out loud;
- the 40% threshold is printed **in the line itself**.

**What the screen does not do:** it does not predict and does not advise. A past win rate does
not promise the future, and the caption says this in words.

---

## Scenario 15. Polymarket order book

**What to type:** `polymarket orderbook 654412`

**Or by button:** `📖 N` under the markets list.

**Comes back:** bids and asks by level plus a depth line: "Depth in money: bids $20.0K vs asks
$3.0K".

**Price:** not measured

**Why:** "45%" with an empty order book and "45%" with a dense one are different things. The
price says what people believe; the order book says how much it costs to test that with money.

---

## Scenario 16. Token info, counterparties, portfolio

Three commands from spec B, already described in Part I as connected:

| What to type | What comes back | Price |
|---|---|---|
| `token info 0x…` | market cap, volume, liquidity, holders | 1 cr |
| `counterparties 0x…` | who this wallet trades with over 30 days | not measured |
| `nansen balance 0x…` | wallet portfolio per Nansen data | not measured |

The `nansen` prefix on the portfolio command is mandatory: a plain balance command is already
taken by a balance from a different source (DeBank).

---

## Scenario 17. Own tally and stats (for the owner)

| What to type | For whom | What comes back |
|---|---|---|
| `nansen stats` | everyone | your calls, credits, rank; leaderboard **without names** |
| `nansen admin` | owner only | a breakdown by person **with names**, shares, scenarios, cache hits |

Costs no credits: it reads our database, not the provider.

---

## Scenario 18. Sentinel: live perp alerts with Nansen in the card

A subscription, not a one-off question. `sentinel BTC` or `sentinel all` puts instruments under
watch (the first subscription sets the Beginner preset). The bot polls three public venues every
30 seconds and rings only when a move is unusual for that instrument (1.2% in 15 min or 2.5% in an
hour AND at least 2.5 sigma over 20+ points of its own history).

What arrives: one card per move (the ticker is a link to the instrument card, a class mark next to
it), then the **same card is edited** with Nansen context: smart-money net over 3 h and who
sold/bought (`tgm/who-bought-sold`), 24 h segments (`tgm/flow-intelligence`), leverage
(`perp-positioning`), the two nearest liquidation clusters from $100k (`perp-positions`) and a
verdict computed by code. Two events are born in Nansen itself: Smart Ignition (3+ smart
addresses bought one token for $100k+ within 180 min, `smart-money/dex-trades`) and Smart Perp
(2+ smart addresses opened one side for $250k+ within 30 min, `smart-money/perp-trades`).

Honest parts: no hit rate on fewer than 20 samples (`sentinel report`); equities outside their
exchange session arrive only in the digest; a line that does not change the trader's decision is
not printed. Terminal: `python3 cli.py sentinel-card BTC hyperliquid`, `sentinel-demo`,
`sentinel-presets`. Spec: `docs/SENTINEL_SPEC.md`.

# What exists in the client but has no door yet

**This is not "we forgot", it is a decision.** An endpoint with no command is the same thing the
four dead functions were before spec B: the code exists, for the person it does not. Below are
the ones connected at the client level and waiting for a scenario, because no question for them
has been voiced in the chat yet.

| Client function | What it gives when needed |
|---|---|
| `tgm_flows` | inflow and outflow **separately** (we currently show net) |
| `tgm_dex_trades`, `tgm_transfers` | all trades and large transfers by token |
| `tgm_price_ohlcv` | candles cheaper than beta (1 credit vs 5) |
| `perp_pnl_leaderboard` | PnL by a specific perp token |
| `sm_perp_trades` | what smart money trades on perps |
| `profiler_transactions`, `profiler_dex_trades`, `profiler_perp_trades` | operation history of an address |
| `profiler_historical_balances` | how the portfolio changed over time |
| `portfolio_positions` | DeFi positions; an alternative to paid DeBank on the same key |
| `pm_categories`, `pm_events`, `pm_market_trades`, `pm_wallet_trades`, `pm_top_holders`, `pm_holders_positions` | the rest of Polymarket: events, trades, largest holders |
| `hist_who_bought_sold` | **a smart-money signal for 5 credits instead of 450** — a backtest on buyer names |
| `hist_top_holders`, `hist_quant_scores`, `hist_token_screener` | what existed on a date: holders, scores, top |

Connecting any of them is a command, a help line and a formatter, roughly like scenarios 10–15.
Say which one, and it arrives the same way.

---

# Trading (Spot Trading)

## About the wallet — the short answer

**A "Nansen wallet" does not exist.** It is not a custodian and not an exchange: it compares
routes across aggregators, hands back an **unsigned** transaction and takes the signed one back
to send it to the network. The private key never leaves for it at any step, no deposit "to a
Nansen account" is needed, you can trade from **any** address of your own. The "Deposit Funds"
screen in their web app is Hyperliquid perps, where the money really does sit with them, and that
is a different model.

## How the key is stored (`nansen_signer.py`)

**A third safe, not a field in the existing ones.** We already have two: `crypto_store`
(messages, per-user DEK) and `gh_crypto` (GitHub tokens, its own master key). The trading key is
worth more than both: with a GitHub token you can **write** into someone's code, and with this
one you can **spend money**, irreversibly. Hence a third lock: its own master-key file, its own
storage.

**The main difference from both elder brothers: the key never leaves the module at all.** The
only thing done with it is signing, and signing can be done inside. Only the signature leaves,
and the key cannot be recovered from it. There are **no** `unseal`/`export`/`reveal` functions in
the module, and this is not forgetfulness: as long as they do not exist, no future edit in
someone else's file can accidentally write the key to a log or a bot reply.

**Verified by eight runs:** without the master key — a refusal with a reason, not a plaintext
write; the key is not in the safe file in the clear; the signature is assembled with the `0x`
prefix; the address recovered from the signature matches the safe's address; the wrong master
key — a refusal "not that key"; after `forget()` signing is impossible.

**The signature is verified locally before sending.** The provider has one error text for three
causes (wrong key, wrong address form, stale nonce), and telling them apart after sending is
expensive.

## What to do by hand (owner only, do not send the key to the chat)

```
mkdir -p <KEYS_DIR> && python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())" > <KEYS_DIR>/nansen_trade.key && chmod 600 <KEYS_DIR>/nansen_trade.key
cd <BOT_DIR> && ./venv/bin/python3 -c "import nansen_signer as s;s.seal_from_stdin()"
./venv/bin/python3 -c "import nansen_signer as s;print(s.status())"
```

The key is read from **hidden** input, not as a command argument: an argument would settle in
the shell history and the process list, i.e. it would leak by a route nobody thinks about.

## Platform boundaries and money

Only `solana` and `base`; one side of the swap must be USDC or the native token (meme-to-meme is
not routed — go into USDC first); cross-chain from ~$5; 403 by jurisdiction and sanction lists.
**Trading calls cost no credits at all** — the limit is monetary, the knob is "Nansen: cap of a
single trade, $", currently **300**.

**Exactly one preview** — `prepare` with its `simulationPassed`. There is **no dry-run mode** for
`execute`: the documentation says plainly that every call that passes validation sends a
transaction, and a successful response means a trade with real money took place. Therefore it
will only be called by a path where the person has already pressed confirm on a card with
numbers.

**Solana is not signed yet:** it needs `solders`, which is not in the venv. Base works via
`eth-account`.

---

# Limits, accounting and activity

**The agent question limit is an admin knob** ("Limits and thresholds"), not a hardcode. Before
this the number "3" sat in three places and in **two different counter files**, so "3 per day" on
paper gave the person 6 in life.

There are two knobs, and they do not duplicate each other: **per person** — against one
over-eager user; **an overall daily credit cap** — against fifty at once. The cap knows the price
of the upcoming question: letting through a question worth 750 when there are 300 left to the cap
would mean crossing it silently.

The limit is **only on the agent** (200 credits, expert 750). Structural scenarios at 1–5 credits
are not limited.

**Activity and spend are different magnitudes.** Cache hits are written to the tally with zero
credits; in the owner's stats it shows "8 calls (3 from cache)". Gaming is still unprofitable:
rank is counted by credits, not by the number of rows.
