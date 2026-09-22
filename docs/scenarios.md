# Nansen scenarios for the community — spec A4

**Input for spec B.** Eight scenarios, selected against these conditions: (1) they already
work, (2) the answer comes back in a single request, (3) a newcomer understands them,
(4) they cost a reasonable amount of credits.

**About the sample outputs.** A live sandbox key is not available, so the examples below are
**reconstructed from the formatter code** (file and line cited for each), not captured from a
live run. The shape, emoji, field order and labels are exact — they come from the code. The
numbers and tickers are made up, to show the shape. Before publishing any of these in the chat,
each scenario must be run live once and its example replaced with a real one: that is exactly
the material for the B5 video demo.

**Credit prices** come from the official page docs.nansen.ai/api/overview (captured
2026-09-14), registry `nansen_log.py:101-109`. They were not measured with a live run
(audit §A2). Where it says "not measured", the price is neither in the overview nor in the
client docstring, and the zero is there on purpose instead of a guess.

---

## 1. Smart money flows: where the smart money goes

- **RU:** Смарт-потоки за 24 часа
- **EN:** Smart money net flows (24h)
- **Ask:** button 🔗 Onchain → 🧠 Nansen → "Smart flows", or type `смарт потоки`
- **Price:** cheap, **not measured**. Endpoint `smart-money/netflow`
- **Code:** `oc_menu.py:537` (button handler), `oc_dm.py:1380` (text), formatter
  `nansen_api.py:1423`
- **Has a window switch:** 1h / 24h / 7d / 30d, buttons `ocm:sm:*` (`oc_menu.py:440-441`)

Sample output shape (`nansen_api.py:1434-1450`):

```
🧠 Приток smart money за 24ч (Nansen netflow):
1. WIF [solana] · +$4.10M
2. PENDLE [ethereum] · +$1.82M
3. AERO [base] · -$960.4K
...
ТФ ниже переключает окно · тапни тикер — открою карточку.
```

**Why someone in the chat cares.** One screen answers the question asked every single day in
the chat: "what are people even buying?" The tickers are clickable — you jump into the token
card without copy-pasting an address. The window switch shows whether an inflow is a one-off or
holds for a week.

---

## 2. What Smart Money accumulates

- **RU:** Что копит Smart Money
- **EN:** What smart money holds
- **Ask:** button `ocm:run:nsn_holdings` (`oc_menu.py:418`), or `смарт холдинги`
- **Price:** ~1-5 credits. Endpoint `smart-money/holdings` (`nansen_api.py:857`)
- **Code:** `oc_dm.py:1338`, scene `oc_dm.py:1346`, text assembly `oc_dm.py:1355-1371`

```
🧠 Что копит Smart Money (топ по $):
1. ETH [ethereum] — $412.30M (+3% 24ч)
2. SOL [solana] — $88.10M (-1% 24ч)
3. PENDLE [ethereum] — $21.40M (+12% 24ч)
...
Тапни тикер — открою карточку токена.
```

**Why.** Flows (scenario 1) are about the last 24 hours of movement; holdings are about the
position. The difference between "they bought in today" and "they've held for a while" is what
a newcomer confuses most often, and the two scenarios side by side show that difference
clearly.

---

## 3. Wallet dossier by labels

- **RU:** Досье кошелька
- **EN:** Wallet dossier
- **Ask:** `профиль 0x…` (or `досье 0x…`, `кошелёк 0x…`), or the 🕵 button under a bare
  address dropped into the chat
- **Price:** cheap, **not measured**. Three endpoints: `profiler/address/labels`,
  `profiler/address/pnl-summary`, `profiler/address/related-wallets`
- **Code:** one door with two entrances — `oc_dm.py:780`, regex `oc_dm.py:1306`,
  button `oc_callbacks.py:875`. Formatter `nansen_api.py:1069`
- **Careful:** the suffix `глубже` (deeper) switches to premium labels at **150 credits**
  (`oc_dm.py:1311`, `nansen_api.py:875`). Advertise it in the community **without** the suffix

```
👤 Профиль кошелька 0x1234…abcd [ethereum]
🏷 Smart Money · DEX Trader · Fund
📈 реализ. PnL +$1.24M · ROI +38% · winrate 61% · сделок 412
💼 топ-токены: ETH, PENDLE, AERO, WIF, LINK
🔗 связанных кошельков: 5+ (funded_by, interacted)
```

**Why.** Exactly the scenario from the spec — "profile an address from the chat feed with one
command." Addresses get thrown into the chat constantly; today people answer with guesses. Here
Nansen labels answer in seconds, and — crucially — when there are no labels the bot says exactly
that, rather than "the address is clean" (`oc_dm.py:752`).

---

## 4. 🧠 Token breakdown

- **RU:** Разбор токена по Nansen
- **EN:** Token breakdown
- **Ask:** the 🧠 button in the first row of any token card (`hub_scanner.py:217`)
- **Price:** **16 credits** — the most expensive of the selected set. Four endpoints:
  `tgm/flow-intelligence` (1) + `tgm/indicators` (5) + `tgm/holders` (5) +
  `tgm/pnl-leaderboard` (5)
- **Code:** `oc_callbacks.py:352-388`, assembly `nansen_api.py:1348`

```
🧠 Nansen · разбор токена

🧠 Nansen потоки 24ч: 🧠SM +$1.20M · 🐳киты +$840.0K · 🏦биржи -$310.5K
📊 Nansen Score: риск 🟡 средний · потенциал 🟢 бычий (4/6)
🏷 В топ-20 холдерах: 6 🧠 smart money, 3 🏛 фонды, 2 🏦 биржи
🏆 Топ-трейдеры по PnL (реализ.):
1. Smart HL Perps Trader: +$412.0K · ROI +180%
2. 0xab12…9f04: +$210.5K · ROI +96%
```

**Why.** The only scenario that answers "is this token worth a look" in a single tap: flows,
risk, who is in the holders, who made money. The 16-credit price against 5 for the others means
one 🧠 equals three other scenarios, not eight, as the docstrings had implied. For a community
kit that is no longer an expensive scenario.

---

## 5. Top perp traders

- **RU:** Топ перп-трейдеры за неделю
- **EN:** Top perp traders (7d)
- **Ask:** button `ocm:run:nsn_perps` (`oc_menu.py:419`), or `топ перпы`
- **Price:** ~5 credits. Endpoint `perp-leaderboard` (`nansen_api.py:927`)
- **Code:** `oc_dm.py:1315`, formatter `nansen_api.py:1125`

```
🏆 Топ перп-трейдеры (Hyperliquid, 7д):
1. Smart HL Perps Trader: +$2.10M · ROI +240%
2. 0xcd34…7a11: +$1.05M · ROI +88%
...
Тапни трейдера — открою его счёт.
```

**Why.** A ready-made list of who is worth following, with a tap-through to the account. Cheap
and self-explanatory.

---

## 6. Trending prediction markets

- **RU:** Трендовые рынки предсказаний
- **EN:** Trending prediction markets
- **Ask:** button `ocm:run:pm_markets` (`oc_menu.py:431`), or `pm рынки`
- **Price:** **not measured**. Endpoint `prediction-market/market-screener`
- **Code:** `oc_dm.py:1409`, formatter `nansen_api.py:1505`

```
🎲 Трендовые рынки Polymarket (объём 24ч):
1. Will the Fed cut rates in September? · 68% · vol24 $4.10M
2. Government shutdown before October? · 31% · vol24 $1.882M
...
Разбор трейдера: «полимаркет профиль 0x…».
```

**Why.** A separate category of Nansen data that almost nobody in the chat knows. Price-as-
probability is the most vivid way to explain what a prediction market is.

---

## 7. Prediction market trader profile

- **RU:** Профиль трейдера на рынках предсказаний
- **EN:** Prediction market trader profile
- **Ask:** `pm профиль 0x…` (`oc_dm.py:1427`)
- **Price:** **not measured**. Two endpoints: `address-summary` + `pnl-by-address`
- **Code:** `oc_dm.py:1427`, formatter `nansen_api.py:1525`
- **No button** — text command only. A task for B1

```
🎰 Polymarket · профиль 0x1234…abcd
📈 PnL +$210.4K · реализ. +$180.2K · нереализ. +$30.2K
🎯 winrate 58% · выиграно 44/76 · возраст 412д
💼 топ-рынки по PnL:
• Will the Fed cut rates in September? [Yes] · +$41.2K
• Government shutdown before October? [No] · -$8.10K
```

**Why.** Shows that win rate and PnL are different things: you can win more often and still lose
money. A good teaching scenario, and it is effectively free for the person.

---

## 8. Top traders of a specific market

- **RU:** Кто заработал на этом рынке
- **EN:** Market PnL leaders
- **Ask:** `топ рынка <market_id>` (`oc_dm.py:1447`)
- **Price:** **not measured**. Endpoint `prediction-market/pnl-by-market`
- **Code:** `oc_dm.py:1447`, formatter `nansen_api.py:1578`
- **No button**, and worse — it needs a `market_id` the person sees nowhere: scenario 6 prints
  the market question but not its id. **The chain is broken, a task for B1**

```
🏆 Топ-трейдеры рынка
Will the Fed cut rates in September?:
1. 0xab12…9f04 [Yes] · +$88.10K
2. 0xcd34…7a11 [No] · -$41.20K
```

**Why.** The natural continuation of scenario 6 in one tap. Unreachable in practice today,
because there is nowhere to get the id — and that is exactly what B1 must fix (a button under
each market from #6).

---

## What implementation must add (input for B1/B2)

1. **A source and freshness label in each of the eight answers.** Right now none of them has it
   (audit A3-4). Format: `per Nansen, captured 14 minutes ago` — or `captured just now` if the
   request went out to the network. The data for this exists: `_cache_get` knows the record's
   `ts`, `ask_agent` returns a `['cache']` marker. We only need to stop throwing it away.
2. **Buttons for scenarios 7 and 8**, and `market_id` in the output of scenario 6 — otherwise
   the eighth scenario exists only on paper.
3. **An honest refusal instead of "no data"** (A3-2, A3-3). Separately and mandatorily —
   "out of credits": during the contest that is the most likely refusal.
4. **Help.** By law 25, whatever is not in help does not exist for the user.
   Existing entries: `help_registry.py:170` (`nansen_smart`), `:484` (`nansen_polymarket`),
   `:141-152`. They must be brought in line with the eight.
5. **A limit on the `cx:nansen` button** — not part of the eight, but it is visible right there
   on the majors' cards, and one tap costs 200 credits, i.e. as much as forty of the cheap
   scenarios in the list and twelve times the cost of 🧠 (§A2). It has no daily counter.

## What is not in the integration

- **"Who bought and sold over the week"** — the endpoint `tgm/who-bought-sold` is written
  (`nansen_api.py:817`), but it is called from nowhere, and its default window is `days=1`.
  The cheapest (~1 credit) and most understandable scenario of all the spec candidates lies
  dead. I am not inventing that it exists: to make it appear, it needs wiring in B1.
- **"Contract safety check before buying" on Nansen data** — there is no separate scenario for
  it. The safety check is done by a third-party service (`help_registry.py:143`); from Nansen
  the only piece in this story is the Nansen Score inside scenario 4.
- `tgm_token_information` (~1 credit: mcap, holders, liquidity in one call) and
  `profiler_current_balance` (wallet portfolio) — also written and dead.


---
---



# PART II. NEW SCENARIOS (addendum 2026-09-15)

Same format as the first eight: **what to type to the bot**, what comes back, the price, why it
matters to the person. The first draft of this part was tables of client functions — i.e. a
document for a developer, from which no live run can be done. Ren said exactly that.

**All commands work from a DM and do not require turning on a mode** — they are registered in
the onchain-words registry. By button: `🎭 Modes` → `🔗 Onchain` → `🧠 Nansen`, where the hints
carry a copyable command.

---

## Scenario 9. Who bought in and who sold out

**What to type:** `кто входил 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 7`
(the number at the end is days, default 7; `кто выходил`, `кто набирал`, `кто сливал` work too)

**Comes back:** two groups — who net-bought and who sold, with Nansen labels and $ volumes.

**Price:** 2 credits (two requests, one per side) · **≈ $0.002**

**Why:** this is the answer to "who is even behind the move". The Smart Money label next to the
volume says more than the price itself.

**The chain is determined by fact**, not by the look of the address: the same `0x…` exists on
ten chains, and USDC with this address lives on Base. Earlier we queried on ethereum and got
nothing.

---

## Scenario 10. Leverage and liquidations by perp token

**What to type:** `перп позиции BTC` (or `ликвидации ETH`)

**Or by button:** `💥 Liquid.` on the exchange token card (`BTC`, `ETH`, `SOL` — the card opens
by ticker). The label is short on purpose: a full one added an eighth row to the card.

**Schema captured live 09-19:** the endpoint requires the field `token_symbol`, but we were
sending `token` — and got a 422 on every tap. The repair, driven by the provider's own words,
stopped honestly ("a required field `token_symbol` is needed, and we have nothing to build it
from") and thereby named the field.

**Comes back:**
```
⚡ Открытые позиции · BTC
1. Smart Money [LONG] · $10.70M · 20x · PnL -$120.2K · ликв. $71,234.50
```

**Price:** 5 credits · **≈ $0.004**

**Why:** before this endpoint **we had no liquidation price at all** — it was guessed from the
entry price. Now you can see the level at which the market will blow out someone else's
leverage, and that is exactly why people watch the whales.

---

## Scenario 10b. Liquidation map: where other people's leverage hangs

**What to type:** `карта ликвидаций BTC` (or `ликвид карта BTC`)

**Or by button:** `🗺 Liquidation map` under the leveraged-positions screen — i.e. the path is:
`BTC` card → `💥 Liquid.` → `🗺 Liquidation map`.

**Comes back:** an image — position sizes grouped by **liquidation price**. Red is longs, green
is shorts, the dashed line is the current price (from Hyperliquid). Plus a caption with the
magnitude:

```
BTC: карта ликвидаций. Самое плотное скопление: $22.5M между $61.5K и $62.4K.
Всего на карте $30.7M по 5 позициям. Лонги $22.5M против шортов $8.2M.
У 1 позиции цены ликвидации не было — их на карте НЕТ.
Это уровни чужих стопов, а не прогноз. Источник: Nansen.
```

**Price:** 5 credits (one request, the same one as the position list) · **≈ $0.004**

**Why:** the position list answers "who is in and with what leverage" — you have to read it and
add it up in your head. The question people watch leverage for is a different one: **at which
price level does the market move fast**, and the answer to that is not a line but a
distribution. "BTC has positions at 20x leverage" is a fact; "$22.5M hangs between $61.5K and
$62.4K" is a magnitude you make decisions on.

**Three honesties built into the screen:**
- positions **without** a liquidation price are not silently dropped, but named in the caption:
  a map over 5 of 6 and a map over 6 of 6 are different maps;
- emptiness is not drawn at all: an image made of zeros looks like a measurement;
- the caption says this is **not a forecast**. A map of other people's stops reads like a
  prediction unless you say otherwise in words.

**The current price is optional.** If it did not load — the map stays an honest map of levels,
just without a "you are here" marker. A made-up price would give a "3% left" marker that nobody
measured.

---

## Scenario 11. Wallet perp account health — THE SCREEN NO LONGER EXISTS

**What to type:** nothing. The command `нансен перпы 0x…` answers with an explanation, not a
screen.

**Why:** the endpoint `profiler/address/perp-positions` **does not exist on the provider** —
404 Not Found, captured with a live probe 09-19 (`tools/nansen_probe.py --run --only new`).
Along with it, the client, formatter and menu button were removed.

**Why we did not leave a "not working yet":** a client that always gets a 404 is a door into a
wall: it exists in the code, it exists in the menu, and the person behind it gets a refusal and
burns a call. Exactly the defect spec B fixed on four dead clients, only inverted: the wire is
there, and nothing on the other end.

**The door is left for exactly one thing** — to say this to whoever already used the command.
Removing it silently would have handed the person the generic "didn't understand", from which
they would conclude they made the mistake.

**What is left about leverage:** scenario 10 — `перп позиции BTC` and the "💥 Liquid." button on
the token card. There you get both leverage and liquidation price, only by token, not by wallet.

**If the path simply moved** — the probe has a `perp` group with candidates
(`--run --only perp`). If it turns up — we bring it back from git; if not — the 404 is confirmed
a second way. This is a decision by fact, not a hope in the code.

---

## Scenario 12. What smart money is buying right now

**What to type:** `смарт сделки`

**Or by button:** 🎭 Modes → 🔗 Onchain → 🧠 Nansen → `🧠 Smart money trades now`.

**Comes back:**
```
🧠 Сделки smart money за сутки
1. Smart Trader 1 AAA [base] · $48.3K · капа $2.1M · 2.3% капы · 3д
```

**Price:** 1–5 credits · **≈ $0.004**

**Why:** `смарт потоки` gives the **total** over a window ("they bought $231K"), and this gives
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

**What to type:** `потоки картинкой 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`

**Or by button:** `📊 Flows chart` under the 🧠 Nansen breakdown on a token or meme card (tap 🧠
on the card → Nansen answer → button beneath it). Next to it is `🔄 Who bought`.

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

**What to type:** `полимаркет график 654412`

**Or by button:** `📈 N` under the `полимаркет рынки` list, where N is the market's number in
the list.

**Where to get the market_id:** it is printed as a copyable line under each market in the
`полимаркет рынки` list. Earlier the hint promised "from the market screener", and the screener
did not print the id at all — the command existed only formally: there was nothing to call it
with.

**Comes back:** a photo — how the probability changed over 72 hours, the 50% line separating
"more likely yes" from "more likely no", the caption with the current value and the shift in
points.

**Price:** not measured · **Why:** we used to show the market price as a single number, but 45%
after 20% and 45% after 70% are opposite stories. One number on a prediction market means almost
nothing.

---

## Scenario 14b. Who holds the market and how they guessed before

**What to type:** `репутация рынка 654412` (or `кто держит рынок 654412`)

**Or by button:** `🎭 N` under the `полимаркет рынки` list.

**Comes back:**
```
🎭 Кто держит этот рынок
654412

💰 Из $2.00M разобранных денег $1.40M (70%) лежат у кошельков
   с винрейтом ниже 40%.
📊 По сторонам: Yes $1.60M · No $550.0K

Держатели (разобрано 5 из 6):
1. Whale A [Yes] · $800.0K · винрейт 33% · PnL -$120.0K · 84 рынков
2. 0xbbbb…bbbb [Yes] · $600.0K · винрейт 71% · PnL +$340.0K · 210 рынков
...
⚠️ По 2 держателям истории нет — их деньги НЕ посчитаны ни в одну сторону.
```

**Price: 6 requests** (holders + lifetime history of each of the five). Six times more expensive
than the neighbouring screens, and this is said both in the answer to the tap and in the screen
itself. The price is named **by the number of requests, not credits**: the prices of these
endpoints are not in the official list, and making one up would be a lie in the most verifiable
part.

**Why:** "78% Yes" is a consensus of **whom**? One number looks identical in two opposite cases:
the money was staked by wallets that guessed right in 70% of markets, or by wallets with a 35%
win rate. The first is a signal, the second an invitation to stand against it. The price does not
tell them apart at all.

This is the "magnitude instead of a flag" law applied to probability: "the market believes in
Yes" is a flag, "$1.4M of $2.1M sits with wallets below a 40% win rate" is a magnitude.

**Three honesties:**
- the money of holders **without** lifetime history is not counted on either side. Assigning a
  wallet a win rate we do not know would rig the conclusion — and that is exactly how convincing
  screens with no measurement behind them are born;
- the number of such holders is stated out loud. "Resolved 5 of 10" and "resolved 10 of 10" are
  different statements;
- the 40% threshold is printed **in the line itself**: you may disagree with it, but for that
  you have to see it.

**What the screen does not do:** it does not predict and does not advise. A past win rate does
not promise the future, and the caption says this in words — otherwise the screen reads as "bet
against the crowd".

**The schemas of two endpoints have not yet been captured with a live key** (`top-holders`,
`address-summary`). For them the probe has a `pm` group: `--run --only pm`. It takes a fresh
`market_id` from the screener itself — a hardcoded id would give a 404 in a week, and we would be
hunting a bug in a schema that has none.

---

## Scenario 15. Polymarket order book

**What to type:** `полимаркет стакан 654412`

**Or by button:** `📖 N` under the `полимаркет рынки` list.

**Comes back:** bids and asks by level plus a depth line: "buy $20.0K against sell $3.0K".

**Price:** not measured

**Why:** "45%" with an empty order book and "45%" with a dense one are different things. The
price says what people believe; the order book says how much it costs to test that with money.

---

## Scenario 16. Token info, counterparties, portfolio

Three commands from spec B, already described in Part I as connected:

| What to type | What comes back | Price |
|---|---|---|
| `инфо токен 0x…` | market cap, volume, liquidity, holders | 1 cr |
| `контрагенты 0x…` | who this wallet trades with over 30 days | not measured |
| `нансен баланс 0x…` | wallet portfolio per Nansen data | not measured |

The `нансен` head on the portfolio is mandatory: `баланс 0x…` is already taken by a balance from
a different source.

---

## Scenario 17. Own tally and stats (for the owner)

| What to type | For whom | What comes back |
|---|---|---|
| `нансен зачёт` | everyone | your calls, credits, rank; leaderboard **without names** |
| `нансен стата` | owner only | a breakdown by person **with names**, shares, scenarios, how much the cache answered |

Costs no credits: it reads our database, not the provider.

---

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
(messages, per-user DEK) and `gh_crypto` (GitHub tokens, its own master key). The decision on the
second was worded like this: "a separate encryption key, the compromise of one must not open the
other." The trading key is worth more than both: with a GitHub token you can **write** into
someone's code, and with this one you can **spend money**, irreversibly. Hence a third lock: its
own master-key file, its own storage.

**The main difference from both elder brothers: the key never leaves the module at all.**
`gh_crypto` offers `unseal()`, because the token has to go into an HTTP header — it has no other
use. The private key has no reason to leave: the only thing done with it is signing, and signing
can be done inside. Only the signature leaves, and the key cannot be recovered from it. There are
**no** `unseal`/`export`/`reveal` functions in the module, and this is not forgetfulness: as long
as they do not exist, no future edit in someone else's file can accidentally write the key to a
log or a bot reply.

**Verified by eight runs:** without the master key — a refusal with a reason, not a plaintext
write; the key is not in the safe file in the clear; the signature is assembled with the `0x`
prefix; the address recovered from the signature matches the safe's address; the wrong master
key — a refusal "not that key"; after `forget()` signing is impossible.

**The signature is verified locally before sending.** The provider has one error text for three
causes (wrong key, wrong address form, stale nonce), and telling them apart after sending is
expensive — this project has already walked that circle on another platform.

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

**Exactly one preview** — `prepare` with its `simulationPassed`. `execute` has no dry-run mode:
the documentation says plainly that every call that passes validation sends a transaction, and a
successful response means a trade with real money took place. Therefore it will only be called by
a path where the person has already pressed confirm on a card with numbers.

**Solana is not signed yet:** it needs `solders`, which is not in the venv. Base works via
`eth-account` (21 packages, no torch and no CUDA, does not downgrade the versions already
installed).

---

# Limits, accounting and activity

**The agent question limit is an admin knob** ("Limits and thresholds"), not a hardcode. Before
this the number "3" sat in three places and in **two different counter files**, so "3 per day" on
paper gave the person 6 in life.

There are two knobs, and they do not duplicate each other: **per person** — against one
over-eager user; **an overall daily credit cap** — against fifty at once (50 × 6 questions =
60,000 credits with 70,450 remaining). The cap knows the price of the upcoming question: letting
through a question worth 750 when there are 300 left to the cap would mean crossing it silently.

The limit is **only on the agent** (200 credits, expert 750). Structural scenarios at 1–5 credits
are not limited.

**Activity and spend are different magnitudes, and I glued them together at first.** The first
draft did not write cache hits into the tally: "the cache costs no credits, so it does not count".
True for spend, false for activity — and a live case showed it: a person tapped Nansen on an ETH
card in the chat, the answer came from a 30-minute cache, and they **vanished from the statistics
entirely**, as if they had not asked. Now all calls are written, with the cache's credits at
zero; in the owner's stats it shows "8 calls (3 from cache)". Gaming is still unprofitable: rank
is counted by credits, not by the number of rows.
