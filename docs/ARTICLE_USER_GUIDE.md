# The complete guide: the Nansen API through the Undertaker bot

The Undertaker is a Telegram bot, and Nansen inside it is not a separate app but a menu section.
You tap a button and get an answer to a trader's question: where smart money is going, who sits in
a token, where other people's leverage is parked, who holds a prediction market. No Nansen key, no
account, no code.

This guide is for traders, not programmers. For every screen: which question it answers, how to
reach it by taps, which command asks the same thing in words, how to read the answer and what the
screen honestly cannot do. Prices are collected at the end.

Russian version: [`ARTICLE_USER_GUIDE_ru.md`](ARTICLE_USER_GUIDE_ru.md). Machine-built reference
with the price of every screen: [`CATALOG.md`](CATALOG.md). Public code:
[github.com/RenatMursalimov/nansen-undertaker](https://github.com/RenatMursalimov/nansen-undertaker).

Button labels are quoted as the bot shows them with the English interface. English commands work
regardless of the interface language.

---

## How to use it

**Where to open it.** For the hackathon the bot's bottom menu has a **🧠 Nansen** button. It is
also always available in two places: **🔥 Trends → 🧠 Nansen** and **🔗 Onchain → 🧠 Nansen (smart
money)**. All three open the same screen with five sections:

* 🧠 What smart money is doing
* 🎲 Polymarket: markets and whose money
* ⚔️ Other people's leverage
* 🔎 A wallet and a token
* 🌐 Chains and my tally

**Three kinds of buttons.** Worth knowing, so you do not decide a button "does nothing":

1. a section button opens the next menu;
2. a button that needs no address answers right away (for example "💼 What they hold");
3. a button that needs an address or a ticker sends a **ready command** with a short
   explanation. Tap the command to copy it, put your address in and send it to the bot.

**In words.** Every command in this guide can simply be typed to the bot in a private chat; no
mode needs to be switched on. In groups typed commands do not work: there you get the Nansen
buttons on cards the bot posted itself.

**Frames.** Every screen has a "FRAME" line: what to capture for a post or a video. Addresses for
frames: USDC on Base `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (the token scenarios were
checked on), WETH `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` (the example the bot itself uses).
Take a wallet address for frames from "🏆 Top perp traders", not someone's personal wallet.

---

## 1. Where smart money is going

### 💹 Smart flows

Answers: which tokens smart money put the most into over an hour, a day, a week, a month.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 💹 Smart flows (1h/24h/7d/30d) → window 1h,
24h, 7d or 30d.
**In words:** `smart flows` (24h window; other windows by button).
**On screen:** tickers with net inflow over the window. Plus means more came in than went out.
Tap a ticker to open the token card. Compare windows: an hour of inflow and a week of inflow are
different stories, a one-off entry versus steady accumulation.
**FRAME:** the flows screen with 24h selected, 3–5 rows and the window buttons visible.
**Limit:** net only. Inflow and outflow separately exist in the client (`tgm_flows`) but have no
screen yet.

### 🔥 Screener: 24h inflow

Answers: which tokens are trending today by smart money inflow specifically.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 🔥 Screener: 24h inflow.
**In words:** no command, button only.
**On screen:** tokens with positive inflow in the Trends screen format; a tap opens the token card.
**FRAME:** the screener, first rows with tickers.
**Limit:** a different source than "Smart flows" (the token screener, not netflow), so the numbers
on the two screens need not match.

### 💼 What smart money holds

Answers: what smart money already holds, not what it bought today.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 💼 What they hold.
**In words:** `smart holdings`.
**On screen:** top positions in dollars with the 24h change. Flows answer "what they take now",
holdings answer "what they already hold". A token can top the inflow list and still be a tiny
position.
**FRAME:** the holdings list with amounts and 24h change.
**Limit:** a snapshot of the position, not a history: how the portfolio changed over time is not
on this screen.

### 🧠 Smart money trades now

Answers: who exactly went into what over the last day.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 🧠 Smart money trades now.
**In words:** `smart trades`.
**On screen:** trader label, token, amount, the token's market cap and **the trade as a share of
that market cap**. The last number is the key one: $48K into a $2M token is 2.3% of its cap; into
a $50B token it is noise.
**FRAME:** 3–4 trade rows with the "% of cap" column visible.
**Limit:** perp trades are not on this screen; that feed is read only by Sentinel (the 🐋 Smart
Perp event, section 6).

### 🧊 Buying on a schedule (DCA)

Answers: who is building a position in parts, that is, intends to keep buying.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 🧊 Buying on a schedule.
**In words:** `dca`.
**On screen:** active DCA programs: who, from what into what, program size and how much is already
spent. A single $2M trade and a $2M program say different things about intent.
**FRAME:** 2–3 programs with the spent share visible.
**Limit:** only programs Nansen classes as smart money.

### 🧊 Jupiter DCA by token

Answers: who is buying a specific Solana token on a schedule.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 🧊 Jupiter DCA by token → the bot sends a
command with an example (the JUP mint); put your mint in and send it.
**In words:** `jup dca <mint>`.
**On screen:** DCA programs for the token: who, from what into what, deposit size and spent share.
**FRAME:** the answer to the command from the hint (JUP mint), as is.
**Limit:** Solana only. Jupiter is a Solana aggregator; an EVM address is cut off before the
request and the bot says why. Native SOL is not supported by this route.

### 🌐 Chain ranking

Answers: where to look today at the chain level, before the token level.

**Path:** 🧠 Nansen → 🌐 Chains and my tally → 🌐 Chain ranking.
**In words:** `chain rank`.
**On screen:** chains by TVL with the daily change, DEX volume and active addresses.
**FRAME:** the chain table with TVL and change.
**Limit:** the general picture of a chain; this screen says nothing about smart money.

---

## 2. Break down a token

### 🧠 Token breakdown by Nansen

Answers: is this token worth a look at all.

**Path:** 🧠 Nansen → 🔎 A wallet and a token → 🧠 Token breakdown → the bot sends a command, put
the contract address in. Shorter: tap 🧠 on any token card.
**In words:** `token breakdown 0x… deep`.
**On screen:** 24h flows by holder segment (smart money, whales, exchanges), Nansen Score (risk and
potential), labels of the top holders, top traders by PnL. Under the answer, three follow-up
buttons: 📊 Flows chart, 🔄 Who bought, ⚖️ Who is positioned.
**FRAME:** the full answer for USDC on Base, with the three buttons at the bottom.
**Limit:** this is not a contract safety check; there is no "check before buying" scenario on
Nansen data, only the Score comes from Nansen here.

### 🔄 Who bought and who sold

Answers: who is behind the move, is it inflow or a hand-off.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 🔄 Who bought and sold → the bot sends a
command, put the address in. Or under the 🧠 breakdown tap 🔄 Who bought, the address is already
filled in.
**In words:** `who bought 0x… 7` (the trailing number is days, 7 by default).
**On screen:** two groups, net buyers and net sellers, with Nansen labels and dollar volumes. A
Smart Money label next to a volume says more than the price does.
**FRAME:** the answer for USDC on Base over 7 days, both groups visible.
**Limit:** the chain is detected by fact, not by the look of the address: the same `0x…` exists on
several chains (USDC with this address lives on Base). The window is in days, not hours.

### 🪪 Token information

Answers: how big is this token.

**Path:** 🧠 Nansen → 🔎 A wallet and a token → 🪪 Token information → command, put the address in.
**In words:** `token info 0x…`.
**On screen:** market cap, volume, liquidity and holder count in one answer.
**FRAME:** the information for USDC on Base.
**Limit:** size numbers, no "good or bad" verdict.

### 📊 Flows chart

Answers: who is against whom in this token, at a glance.

**Path:** 🧠 Nansen → 🔎 A wallet and a token → 📊 Flows chart → command, put the address in. Or
under the 🧠 breakdown tap 📊 Flows chart.
**In words:** `flows chart 0x…`.
**On screen:** bars by segment: smart money, whales, top PnL, public figures, exchanges, fresh
wallets. Green accumulates, red dumps. Easy to drop into a chat instead of three paragraphs.
**FRAME:** the chart itself for USDC on Base.
**Limit:** with no data there is no picture, you get a text with the reason: six zero bars would
look like a measurement.

---

## 3. Perps: leverage and liquidations

### 🏆 Top perp traders

Answers: whom to watch on perps.

**Path:** 🧠 Nansen → ⚔️ Other people's leverage → 🏆 Top perp traders.
**In words:** `top perps`.
**On screen:** profitable Hyperliquid perp accounts; tap a trader to open their account.
**FRAME:** the list with PnL and ROI; this screen also gives the wallet address for the other
frames.
**Limit:** past PnL promises nothing; this is a list to watch, not to copy.

### 💥 Leveraged positions and the liquidation price

Answers: who holds the token with leverage and at what price they get wiped out.

**Path:** 🧠 Nansen → ⚔️ Other people's leverage → 💥 Leveraged positions → command with the
example `perp positions BTC`. Or on the exchange card (opened with `chart BTC`) tap 💥 Liq.
**In words:** `perp positions BTC` or `liquidations BTC`.
**On screen:** per account: position size, leverage, unrealized PnL and **liquidation price**.
Under the answer, a 🗺 Liquidation map button.
**FRAME:** BTC positions with the liquidation column visible.
**Limit:** Hyperliquid perps; positions on other venues are not here.

### 🗺 Liquidation map

Answers: at which price level the market will move fast.

**Path:** 🧠 Nansen → ⚔️ Other people's leverage → 🗺 Liquidation map → command
`liq map BTC`. Or under the leveraged positions screen tap 🗺 Liquidation map.
**In words:** `liq map BTC`.
**On screen:** a chart: position sizes grouped by liquidation price. Red is longs, green is
shorts, the dashed line is the current price. The caption names the densest cluster as a number,
for example "$22.5M between $61.5K and $62.4K".
**FRAME:** the BTC map with its caption. Under it, the ⚔️ Compare all four button (next frame).
**Limit:** these are other people's stops, **not a forecast**, and the caption says so in words.
Positions without a liquidation price are not dropped silently; their count is in the caption.

### ⚔️ Perp risk board

Answers: which of the large tokens has its price closest to other people's liquidations.

**Path:** 🧠 Nansen → ⚔️ Other people's leverage → ⚔️ Perp risk board. Or under the liquidation
map tap ⚔️ Compare all four.
**In words:** `risk board`.
**On screen:** BTC, ETH, SOL, HYPE ordered by how close the price is to the densest liquidation
cluster: distance in percent, the cluster's side, longs against shorts and how much sits on
wallets with a Nansen label.
**FRAME:** the whole board, four rows.
**Limit:** a fixed set of four tokens; for any other token use the liquidation map.

### ⚖️ Who is positioned on a token

Answers: who is against whom, whales or smart traders.

**Path:** tap 🧠 on any token card, then ⚖️ Who is positioned under the answer: no address to type.
From the menu: 🧠 Nansen → ⚔️ Other people's leverage → ⚖️ Who is positioned on a token → command
with an example (WETH).
**In words:** `positioning 0x…` (contract address).
**On screen:** leverage by holder segment: whales, smart traders and public figures separately,
longs against shorts and the net tilt with its sign.
**FRAME:** the answer for WETH from the hint.
**Limit:** a total per segment; for who exactly and where their liquidation is, use "Leveraged
positions".

### 🩺 Wallet perp account

Answers: how much room a leveraged whale has before liquidation.

**Path:** 🧠 Nansen → ⚔️ Other people's leverage → 🩺 Wallet perp account → command, put the
address in. Shorter: in "🏆 Top perp traders" tap a trader.
**In words:** `nansen perps 0x…`.
**On screen:** equity, margin used, unrealized PnL, account health and positions with liquidation
prices.
**FRAME:** the account of a trader from the top list.
**Limit:** one wallet; for who else sits in the same token, use "Leveraged positions".

---

## 4. Prediction markets (Polymarket)

### 🎲 Trending markets

Answers: where the money is on Polymarket right now.

**Path:** 🧠 Nansen → 🎲 Polymarket: markets and whose money → 🎲 Trending markets.
**In words:** `polymarket markets`.
**On screen:** markets by volume, probability and 24h volume. Under the list, one button per market
with the start of its question: a tap opens the market card.
**FRAME:** the list and the market buttons under it.
**Limit:** a market price is a probability of what people believe, not what will happen.

### 🎲 Market card

Answers: what is going on with this market and where to dig next.

**Path:** 🎲 Trending markets → the button with the market's question.
**In words:** `polymarket market <id>` (the id is printed on the card as a copyable line).
**On screen:** question, price, volume, market_id and four breakdowns as buttons: 📈 Probability,
📖 Orderbook, 🎭 Who holds it (6 req), 🧾 Who is in it now.
**FRAME:** the market card with the four buttons.
**Limit:** no market id to type, it is already inside the buttons; the command is for those who
already have the id.

### 📈 Probability chart

Answers: where the current market price came from.

**Path:** market card → 📈 Probability. From the menu: 🎲 Polymarket → 📈 Probability chart sends a
hint with this same path.
**In words:** `polymarket chart <id>`.
**On screen:** a chart of how the probability changed; the 50% line separates "more likely yes"
from "more likely no". 45% after 20% and 45% after 70% are opposite stories.
**FRAME:** the chart of a trending market.
**Limit:** a chart of the past, not a forecast.

### 📖 Market orderbook

Answers: what it costs to test this probability with money.

**Path:** market card → 📖 Orderbook. From the menu: 🎲 Polymarket → 📖 Market orderbook sends a
command with an example.
**In words:** `polymarket orderbook <id>`.
**On screen:** bids and asks by level and a depth line ("buy $20.0K against sell $3.0K"). 45% on
an empty book and 45% on a deep one are different things.
**FRAME:** the orderbook of a trending market.
**Limit:** a snapshot at request time, not a live feed.

### 🎭 Who holds the market and how they guessed before

Answers: "78% Yes" is whose consensus.

**Path:** market card → 🎭 Who holds it (6 req). From the menu: 🎲 Polymarket → 🎭 Who holds the
market sends a command.
**In words:** `market reputation <id>` or `who holds market <id>`.
**On screen:** how much money sits with wallets whose win rate is below 40% (the threshold is
printed in the line), the split by side, and holders with win rate, PnL and number of markets. A
value instead of a flag: "the market believes Yes" versus "$1.4M of $2M sits with wallets that
were wrong more often".
**FRAME:** the full screen, with the headline line about weak-wallet money visible.
**Limit:** holders with no history count on neither side, and their number is stated. A past win
rate promises nothing; the screen does not tell you to bet against the crowd.

### 🧾 Who is in the market and their PnL

Answers: which holders are doing well in this particular market.

**Path:** market card → 🧾 Who is in it now. From the menu: 🎲 Polymarket → 🧾 Who is in the market
and their PnL sends a hint with this same path.
**In words:** `market positions <id>`.
**On screen:** every holder of the market: entry, current price, realized and open PnL.
**FRAME:** the holder list of a trending market.
**Limit:** "Who holds" says how holders guessed in general; this screen says how it is going here.
Together they answer "who is good at this" versus "who is up for now".

### 🏆 Market leaders

Answers: who made and lost the most in this market.

**Path:** 🧠 Nansen → 🎲 Polymarket → 🏆 Market leaders → command with an example; put in the id
from the market card.
**In words:** `market leaders <id>`.
**On screen:** winners and losers of the market with their side.
**FRAME:** the leaders of a trending market.
**Limit:** this screen has no button on the market card; it needs the id from the card. ⚠️ The
menu hint says "market_id from the screener", but the market list no longer prints ids (see the end
of this guide).

### 🎰 Polymarket trader profile

Answers: how this wallet's previous bets ended.

**Path:** 🧠 Nansen → 🎲 Polymarket → 🎰 Trader profile → command, put the address in.
**In words:** `polymarket profile 0x…`.
**On screen:** lifetime PnL, win rate, wallet age and top markets by PnL. Win rate and PnL are
different things: you can win more often and still lose money.
**FRAME:** the profile of a holder taken from "Who holds".
**Limit:** Polymarket only; for the rest of the address onchain use "Wallet profile".

### 🎯 Where money is sharp

Answers: in which of the hot markets the people on the other side are not random.

**Path:** 🧠 Nansen → 🎲 Polymarket → 🎯 Where money is sharp.
**In words:** `sharp money`.
**On screen:** four hot markets side by side: money of wallets with a 60%+ win rate against money
of those below 40%, and the largest "sharp" holder.
**FRAME:** all four markets on one screen.
**Limit:** the heaviest screen of the section by request count: up to 17 per answer by default.

---

## 5. Wallet and account

### 👤 Wallet profile

Answers: whose address is this one from the chat feed.

**Path:** 🧠 Nansen → 🔎 A wallet and a token → 👤 Wallet profile → command, put the address in.
Shorter: send a bare address to the bot in a private chat and tap 🕵 Wallet dossier (Nansen).
**In words:** `profile 0x…`.
**On screen:** Nansen labels, PnL and win rate, related wallets. With no labels the bot says so,
rather than calling the address "clean".
**FRAME:** the profile of an address from "🏆 Top perp traders".
**Limit:** `profile 0x… deep` adds premium labels and costs 150 credits; for a normal question
the plain form is enough. The address's transaction history exists in the client but has no
screen yet.

### 💼 Wallet portfolio

Answers: what sits on this address.

**Path:** 🧠 Nansen → 🔎 A wallet and a token → 💼 Wallet portfolio → command, put the address in.
**In words:** `nansen balance 0x…` (the word "nansen" is required: a plain `balance 0x…` opens the
account screen from another source).
**On screen:** portfolio composition in dollars without spam tokens.
**FRAME:** the portfolio of an address from the top list.
**Limit:** debts are not subtracted here; that is the next screen.

### 💠 DeFi part of a wallet

Answers: how much the wallet really owns once debts are subtracted.

**Path:** 🧠 Nansen → 🔎 A wallet and a token → 💠 DeFi part of a wallet → command, put the address
in.
**In words:** `defi 0x…`.
**On screen:** the net value (assets minus debts), unclaimed rewards and protocols by size. A $2M
wallet with no debt and a $2M wallet with $1.7M of debt look the same as a token list.
**FRAME:** an address with DeFi positions, the "assets minus debts" line visible.
**Limit:** the DeFi part only; for tokens on the wallet use "Portfolio".

### 🤝 Wallet counterparties

Answers: whom this address deals with most.

**Path:** 🧠 Nansen → 🔎 A wallet and a token → 🤝 Wallet counterparties → command, put the address
in.
**In words:** `counterparties 0x…`.
**On screen:** counterparties over 30 days and volumes.
**FRAME:** the counterparties of an address from the top list.
**Limit:** a fixed 30-day window.

### 🧮 My contest tally

Answers: how much I have asked Nansen through the bot.

**Path:** 🧠 Nansen → 🌐 Chains and my tally → 🧮 My contest tally.
**In words:** `my contest tally`.
**On screen:** your calls, credits and rank; the leaderboard has no names and no IDs.
**FRAME:** your own tally.
**Limit:** the per-person breakdown with names (`нансен стата`) is visible to the bot owner only.

---

## 6. Sentinel: alerts

Answers: how to learn about an unusual perp move without sitting in a terminal.

This is a subscription, not a one-off question. Sentinel polls three public venues every 30
seconds (553 Variational instruments, 234 Hyperliquid perps, 210 live Lighter markets) and rings
only when a move is unusual **for that instrument**: 1.2% in 15 minutes or 2.5% in an hour and at
least 2.5 sigma over 20+ points of its own history. No sigma, no alert.

**Path:** 🧠 Nansen → 🧠 What smart money is doing → 👁 Sentinel (live alerts). Or 🔗 Onchain → 🔔
Alerts → 👁 Sentinel. On the screen pick a preset: ⚙️ Beginner, ⚙️ Trader or ⚙️ Quiet. The first tap
shows what will change, in numbers; the second ("✅ Apply") applies it.
**In words:** `sentinel` (the screen), `sentinel BTC` (watch an instrument), `sentinel all` (the
whole venue), `sentinel remove BTC`, `sentinel threshold 5`, `sentinel quiet 22 8`,
`sentinel report`.
**On screen:** one card per move: price, the 15 and 60 minute move, "unusualness N σ", turnover,
open interest. Soon after, the same card is edited with Nansen blocks: large addresses over 3
hours, net and who bought or sold, whose leverage sits in the market, the two nearest $100k+
liquidation clusters. After that, only "strengthened" or "pulled back" as a reply to the card.
Separately, events born in Nansen itself: 🔥 Smart Ignition (3+ smart wallets bought one token for
$100k+ within 3 hours) and 🐋 Smart Perp (2+ smart wallets opened the same side on Hyperliquid for
$250k+ within 30 minutes). The ticker in the card links to the instrument card.
**FRAME:** frames and the presets they need are listed in the Sentinel thread file
(`POST_SENTINEL_X`, frame list K1–K8, in Russian). With no live alert at hand: `sentinel` →
📈 Market now (a market snapshot from the ring), or the instrument card via
`/start sen_hyperliquid_BTC`.
**Limit:** no hit rate on fewer than 20 samples; you get "sample too small" instead
(`sentinel report`). Equities and funds outside their exchange session arrive only in the digest.
Sentinel does not trade and does not advise: it says what happened and how unusual it is.

---

## What it costs

Nansen credits are spent by the bot from its own key; for the hackathon the Nansen screens are
free for people (the owner's decision). The prices below show which screens are heavy. Rule: where
Nansen's official list names a price, it is in credits; where it does not, the **number of
requests** is given. All values come from [`CATALOG.md`](CATALOG.md).

| Screen | Price |
|---|---|
| 🔥 Screener: 24h inflow | 1 credit |
| 💼 What smart money holds | 3 credits |
| 🧠 Smart money trades | 1–5 credits |
| 🏆 Top perp traders | 5 credits |
| 💥 Leveraged positions | 5 credits |
| 🗺 Liquidation map | 5 credits (the same request as positions) |
| 🧠 Token breakdown | 4 requests, about 16 credits |
| 🔄 Who bought and sold | 1 credit per side |
| 🪪 Token information | 1 credit |
| 📊 Flows chart | 1 credit |
| 👤 Wallet profile | 3 requests; "deep" adds premium labels for 150 credits |
| 🎰 Polymarket trader profile | 2 requests |
| 🎭 Who holds the market | 6 requests |
| 🎯 Where money is sharp | 1 + N + N×H requests (17 by default) |
| ⚔️ Perp risk board | one request per token (4) |
| 🧊 DCA, 🧊 Jupiter DCA, 🌐 Chain ranking, 💠 DeFi part, ⚖️ Who is positioned, 🧾 Who is in the market | 1 request |
| 🎲 Market card | 0 requests when the market list is fresh (served from cache) |
| 💹 Smart flows, 🩺 Wallet perp account, 🤝 Counterparties, 💼 Portfolio, 🎲 Trending markets, 📈 Chart, 📖 Orderbook, 🏆 Market leaders | price not named in the official list, counted by requests |
| 🧮 My contest tally | free, reads the bot's own log |
| 👁 Sentinel | by number of requests; the spend shows on the Sentinel screen as "Nansen credits" |
| 🔍 Free-form question to the Nansen agent (button on the exchange card or a question in words) | 200 credits (fast) or 750 (expert), the most expensive path |

Before asking the agent, check whether a screen answers the same question: it is hundreds of times
cheaper and answers with numbers, not a retelling.

## What the bot does not do

* **It does not advise or forecast.** The liquidation map shows other people's stops, market
  reputation shows holders' past, Sentinel says how unusual a move is. The decision is yours.
* **It does not trade from the Nansen section.** Nansen's trading routes (`trade/quote`,
  `trade/prepare`, `trade/execute`) exist in the client but have no user button. Sentinel does not
  trade at all: its package has no signing code, and a test checks that.
* **It does not take typed commands in groups.** In groups you get the Nansen buttons on cards the
  bot posted itself, and a question to the agent when you address the bot. The mini-app opens only
  in a private chat.
* **It does not pass emptiness off as an answer.** With no data you get the reason in the venue's
  own words, not an empty chart or "nobody traded".
* **It does not invent prices.** Where Nansen does not name an endpoint's price, the bot and this
  guide count requests.
* **It does not check contract safety on Nansen data.** There is no such scenario; the only Nansen
  part of the token breakdown on that topic is the Nansen Score.

## ⚠️ Paths that need attention

No path in this guide lacks a handler: every PATH was traced to its callback or parsing line in
the bot, and every command in the guide was run through the parser (`oc_dm.is_onchain_command` and
the `oc_dm.handle_onchain` regexes; Sentinel commands through `sentinel/ui.parse` and
`en_triggers.py`). The bot's router is private; the public repository carries the Nansen client,
the formatters, Sentinel with its parser and `en_triggers.py`. Flagged separately: things that work
but can confuse.

1. **The "🏆 Market leaders" hint** (`ocm:hint:pm_leaders`) says "needs a market_id (from the
   screener)", but the market list no longer prints ids: they are on the market card. The command
   handler exists (the `market leaders` branch of the router); only the hint
   text is stale.
2. **The bottom-menu "🧠 Nansen" button is temporary**, for the hackathon
   (`dm_module.MENU_ROW2_TEMP`). Afterwards the paths in this guide start with "🔥 Trends → 🧠
   Nansen" or "🔗 Onchain → 🧠 Nansen (smart money)", and everything after that is the same.
3. **The Nansen mini-app** (the "📱 Nansen screens (mini-app)" button at the top of the section) is
   shown only if the page is published (`oc_menu._nansen_app_row`), so it is not part of the paths
   in this guide.
