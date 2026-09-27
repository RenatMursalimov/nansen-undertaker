Published on X on 27.09.2026; current numbers are in docs/CATALOG.md

Nansen  & The Undertaker - the full guide to an AI agent that reads the chain for you
Nansen knows whose wallets these are. To see it you usually need a tab, a subscription and a habit of reading dashboards. 
I put it inside my Telegram agent by @harecrypta_ai based on @nansen_ai so the answer lands where I already sit all day.

https://nsn.ai/harecrypta
What is Nansen inside: 
34 scenarios in chat, a Telegram mini-app with its own screens, a live alerter over three perp venues, a free-form door to the Nansen agent and a morning digest. 
Below, section by section: which question each screen answers, where to tap, what to type, and how to read the reply. At the end: how the screens chain into each other, how to read a refusal, what the bot will not do, the price list, and a coverage table against the catalog.
Bookmark it. It is long on purpose.
Before you start
The button. 
Right now the bottom menu of the bot has 
🧠 Nansen.    
Every path below starts at 🧠 Nansen, and the typed commands work either way.

https://telegram.me/harecrypta_digest_bot 
The button. Right now the bottom menu of the bot has  🧠 Nansen.
Three doors, and it matters which one you use.
💬 In DM: every scenario. Typed commands, inline menus and the mini-app button all live here. No mode needs to be switched on.
👥🔘 In a group, by a button: the bot posts a card by itself (a bare contract address, chart $BTC), and the Nansen buttons on that card answer into the group. Same structured screens, same numbers as in DM. 
https://telegram.me/hara_chat
chart $W
👥🤖 In a group, by asking the agent in words: address the bot by username, by nickname ("гроб", "гробовщик", "undertaker") or by replying to it. 
The group has to be approved, and there is a daily cap per person, because the agent is the expensive path.

An AI character The Undertaker that lives in dm and  in two Telegram community chats 24/7
https://telegram.me/harecrypta_digest_bot
https://telegram.me/hara_chat (EN)
https://telegram.me/harecrypta_chat  (RU)
Typed commands do not work in a group. The group handler never calls the DM router, so smart flows typed in a group reaches the agent at best: 
a different, more expensive path with a different answer.
How it is wired.
✅ every screen is built from one dictionary. 
The chat message and the mini-app picture render the same dict, so the number on a chart cannot drift from the number in the sentence under it. A law test injects one number and requires both outputs to change 
✅ every line either carries a number with a named source or names the reason there is none 
✅ every network call is logged
endpoint, outcome, milliseconds, credits, cache or wire, and which surface asked 
✅ the Nansen key never leaves the server
Wallet addresses are stripped before the browser sees anything 
✅ where Nansen publishes a price, the screen shows credits. 
Where it does not, the screen shows the number of requests
https://nsn.ai/harecrypta
1. Smart money: where the money goes
1.1 Smart money inflow by window
Question: what is smart money buying right now, and does it hold.
Path: 🧠 Nansen → 🧠 Smart money → 💹 Smart flows (1h/24h/7d/30d) 
or Type: smart flows
How to read: tickers with net inflow over the window, in dollars. Switch the window: an inflow that holds on 24h and on 7d is not a one-off buy. Tapping a ticker opens the token card.
https://telegram.me/harecrypta_digest_bot
🧠 Nansen → 🧠 Smart money → 💹 Smart flows (1h/24h/7d/30d)
1.2 Smart money inside the Trends screen
Question: what is trending, seen through smart money.
Path: 🧠 Nansen → 🧠 Smart money → 🔥 Screener: 24h inflow
How to read: tokens with positive netflow in the same format as the shared Trends screen. A tap opens the token card, and from there holders, flows and trades are one tap away. Nansen is not a separate mode here, it is part of the daily route: trend → card → who is behind it.
https://telegram.me/harecrypta_digest_bot
🧠 Nansen → 🧠 Smart money → 🔥 Screener: 24h inflow
1.3 What smart money holds
Question: not what they bought today, what they already hold.
Path: 🧠 Nansen → 🧠 Smart money → 💼 What they hold 
Type: smart holdings
How to read: top positions by dollars with the 24h change. Flow says "what they are buying now", holdings say "what they already hold". Newcomers confuse these two more than anything else, and the two screens side by side settle it.
🧠 Nansen → 🧠 Smart money → 💼 What they hold
1.4 Smart money trades over 24h, as a share of market cap
Question: who entered what, and did it matter for that token.
Path: 🧠 Nansen → 🧠 Smart money → 🧠 Trades now 
Type: smart trades 
In the mini-app: ➕ More, see section 9
How to read: who entered what and for how much, plus the token's market cap and the trade's share of it. "$48K went into a token" says nothing until it says into what: into a $2.1M token that is 2.3% of the whole market cap and a signal, into a $50B token it is noise. Cap and token age arrive in the same response, so the share costs no extra request.
🧠 Nansen → 🧠 Smart money → 🧠 Trades now
🧠 Nansen → Nansen screens (mini-app). In the mini-app: ➕ More, see section 9


1.5 Who buys on a schedule (smart money DCA)
Question: is anyone committed to buying later, not just yesterday.
Path: 🧠 Nansen → 🧠 Smart money → 🧊 Buying on a schedule 
Type: dca 
In the mini-app: ➕ More
How to read: active DCA programs: who, from which token into which, the size of the program and the share already spent. The only signal in the set about future buying: a single $2M trade and a $2M DCA program are different statements of intent. When every program in the response is already executed, the screen says so in words.
🧠 Nansen → Nansen screens (mini-app). In the mini-app Nansen screen: ➕ More
1.6 Jupiter DCA by token (Solana only)
Question: who is buying this Solana token on a schedule.
Path: 🧠 Nansen → 🧠 Smart money → 🧊 Jupiter DCA by token 
Type: jup dca <mint> (<pair info>)
How to read: DCA programs for one token: who, from which token into which, the deposit and the share already spent. On Solana scheduled buying runs through Jupiter, so this is the same question about future purchases, on a different venue.
🧠 Nansen → 🧠 Smart money → 🧊 Jupiter DCA by token
2. One token, fully
2.1 Token breakdown
Question: who is in this token, four ways at once.
Path: token or meme card → 🧠 
Type: passport 0x… deep 
In a group: the 🧠 button on a card the bot posted
How to read: net flows by holder segment, the Nansen Score (risk and potential), the labels of the top holders, the top traders of the token by PnL. 4 requests, about 12 credits, named before you tap.


token or meme card → 🧠

2.2 Who net-bought and who sold
Question: the net flow is a total. Who made it?
Path: token card → 🧠 → 🔄 Who bought and sold 
Type: who bought 0x… 7, who bought sold 0x… 
In a group: the button on a card the bot posted
How to read: a label or an address and the dollar volume for each side over the period. The chain is resolved by fact, not by the look of the address: the same 0x… exists on ten chains.
2.3 Holder-segment flows as a chart
Question: who against whom.
Path: token card → 🧠 → 📊 Flows chart 
Type: flows chart 0x… 
In a group: the button on a card the bot posted
How to read: bars by segment: smart money, whales, top PnL, public figures, exchanges, fresh wallets. Colour is the sign of the flow, the source is baked into the image. Text answers "how much", the chart answers "who against whom": smart money accumulating while whales dump is a half-second read. If there is no data there is no picture, because six zero bars look like a measurement.
2.4 Token info sheet
Question: the basic numbers, from the same source as everything else.
Path: 🧠 Nansen → 🔎 Wallet and token → 🪪 Token information 
Type: token info 0x…
How to read: market cap, volume, liquidity, holder count. No second vendor.
2.5 Backtest on onchain candles
Question: a meme has no exchange chart. How would an idea have done on its own history?
Path: meme card → 🧪 Backtest
How to read: a simple strategy run over the token's historical daily candles, taken onchain. 89 daily candles for 5 credits.


3. Perps: leverage and liquidations
3.1 Leveraged positions and the liquidation price
Question: who is in with leverage, and where each of them gets liquidated.
Path: token card (BTC, for example) → 💥 Liq. 
Type: perp positions BTC, liquidations BTC 
In a group: the button on a card the bot posted
How to read: for each account: position size, leverage, unrealized PnL and the liquidation price. Before this endpoint the bot had no liquidation price at all, it was guessed from the entry.


3.2 Liquidation map
Question: at which level does the market move fast.
Path: token card → 💥 Liq. → 🗺 Liquidation map 
Type: liquidation map BTC, liq map BTC 
In a group: the button on a card the bot posted 
In the mini-app: 🗺 Map, see section 9
How to read: an image of position sizes by liquidation price. 
Red is longs, green is shorts, blue is money on wallets Nansen has a name for, the dashed line is the current price. 
The caption names the biggest cluster. Any ticker the venue has. The position list answers "who is in", the map answers "where the market runs", and that is a distribution, not a line. 
Positions without a liquidation price are counted out loud, not dropped. This is a map of other people's stops, not a forecast. 5 credits, the same request as the list.
🧠 Nansen → Nansen screens (mini-app). In the mini-app: 🗺 Map, see section 9
In a group or in dm: the button on a card the bot posted


3.3 Who is positioned on a token
Question: who against whom on leverage: whales, smart traders, public figures.
Path: 🧠 Nansen → ⚔️ Leverage → ⚖️ Who is positioned, or 🔍 Nansen on a token → ⚖️ Who is positioned 
Type: positioning ETH, who is positioned <ticker> 
In a group: the button on a card the bot posted
How to read: leverage split by segment, longs against shorts and the net skew for each. The neighbouring screen answers row by row, this one answers who against whom: "whales long twelve million while smart traders are short nine" is a statement a list of positions cannot make.
🧠 Nansen → ⚔️ Leverage → ⚖️ Who is positioned, or 🔍 Nansen on a token → ⚖️ Who is positioned
3.4 Risk board
Question: whose leverage is closest to the edge right now.
Path: 🧠 Nansen → ⚔️ Leverage → ⚔️ Perp risk board, or under the map: ⚔️ Compare all four 
Type: risk board 
In a group: the button on a card the bot posted 
In the mini-app: 🗺 Map → ⚔️ compare top four
How to read: BTC, ETH, SOL and HYPE ordered by how close the price is to the densest liquidation cluster, not by how big it is: distance in percent, the side of that cluster, longs against shorts, and how much of it sits on named wallets. 3% away and 40% away are different situations. A token whose price did not load goes last and says so.
🧠 Nansen → Nansen screens (mini-app). In the mini-app: 🗺 Map → ⚔️ compare top four
3.5 A wallet's perp account and room to liquidation
Question: not what a leveraged whale holds, how much room is left.
Path: 🧠 Nansen → ⚔️ Leverage → 🩺 Wallet perp account 
Type: nansen perp 0x…
How to read: capital, how much is collateralized, unrealized PnL, account health and every position with its liquidation price.
3.6 Top perp traders
Question: who is making money on leverage right now.
Path: 🧠 Nansen → ⚔️ Leverage → 🏆 Top perp traders 
Type: top perps
How to read: profitable perp accounts. Tapping a trader opens the account. 5 credits.
🧠 Nansen → ⚔️ Leverage → 🏆 Top perp traders
4. Prediction markets
4.1 Trending markets
Question: which markets are hot, and how do I open one.
Path: 🧠 Nansen → 🎲 Polymarket → 🎲 Trending markets 
Type: polymarket markets
How to read: markets by volume, probability, 24h volume. Each market is a button carrying its own question, and a tap opens its card. The id is printed on the card, not under every row of the list.
🧠 Nansen → 🎲 Polymarket → 🎲 Trending markets
4.2 The card of one market
Question: one market, everything about it in one place.
Path: 🎲 Trending markets → the button carrying the question, or 
in the mini-app: 🎭 Whose % → 📲 open in the bot 
Type: polymarket market 654412
How to read: the question, the price, 24h volume, the id to copy, and four breakdowns of that market as buttons: 📈 Probability, 📖 Orderbook, 🎭 Who holds it, 🧾 Who is in it now. The card is where the list, the mini-app and the command all arrive. 0 requests when the list is warm.
Nansen - Nansen screens -in the mini-app: 🎭 Whose % → 📲 open in the bot
4.3 Probability over time
Question: 45% after what?
Path: market card → 📈 Probability 
Type: polymarket chart 654412
How to read: an image of how the probability moved, with the 50% line between "more likely yes" and "more likely no". 45% after 20% and 45% after 70% are opposite stories, and one number cannot tell them apart.
4.4 Order book
Question: how much does it cost to test this price with money.
Path: market card → 📖 Orderbook Type: polymarket orderbook 654412
How to read: order levels by side and a depth line in money. 45% with an empty book and 45% with a dense one are different things: the price says what people believe, the book says what it costs to test that.
4.5 Who holds the market and how they guessed before
Question: "78% Yes" is a consensus of whom?
Path: market card → 🎭 Who holds it 
Type: market reputation 654412, who holds market 654412 
In the mini-app: 🎭 Whose %, see section 9
How to read: how much of the examined money sits with wallets whose win rate is below 40%, a breakdown by side, and holders with win rate, PnL and number of markets. Holders with no history are counted on neither side, and the screen says so. One number looks the same when the money was staked by wallets with a 70% win rate and by wallets with 35%: the first is a signal, the second an invitation to stand against. 6 requests: the holders plus the lifetime history of each of the five.
4.6 Who is in the market now, and their PnL
Question: how is the same holder doing right here.
Path: market card → 🧾 Who is in it now, or 🧠 Nansen → 🎲 Polymarket → 🧾 Who is in the market and their PnL Type: market positions 654412 In the mini-app: 🎭 Whose % → 🧾 who is in it, with PnL
How to read: every holder with their PnL in this market: entry, current price, realized and open. Reputation says how a holder did over a lifetime, this says how they are doing here, and together they separate skill from luck.
4.7 Top traders of one market
Question: who wins and who loses on this market.
Path: 🧠 Nansen → 🎲 Polymarket → 🏆 Market leaders 
Type: market leaders 654412
How to read: who made and lost the most on this market, with the side. The fastest way to see who trades it.
4.8 Polymarket trader profile
Question: before copying someone's bet, how did the previous ones end.
Path: 🧠 Nansen → 🎲 Polymarket → 🎰 Trader profile 
Type: polymarket profile 0x…
How to read: lifetime PnL, win rate, wallet age and top markets by PnL. Win rate and PnL are different things: you can win more often and still lose money. 2 requests.
4.9 Where the money is sharp
Question: out of ten heated markets, where is the other side not random people.
Path: 🧠 Nansen → 🎲 Polymarket → 🎯 Where money is sharp 
Type: sharp money 
In the mini-app: 🎯 Sharp, see section 9
How to read: four heated markets side by side: money of wallets with a win rate at or above 60% against money of wallets below 40%, plus the biggest sharp holder, ordered by sharp dollars. 90% of $300 is not a signal. A single-market breakdown does not answer the question of choice, only a comparison does. 1 + N + N×H requests, 13 by default.
5. Wallet
5.1 Wallet profile
Question: who is this, an address from the chat.
Path: drop a bare address into the bot's DM → 🕵 Dossier 
Type: profile 0x…, profile 0x… deep
How to read: labels, PnL and win rate, related wallets. "No labels" does not mean "clean address", and the screen says so directly. 3 requests; deep adds premium labels for 150 credits.
5.2 Wallet portfolio
Question: what does this wallet hold.
Path: 🧠 Nansen → 🔎 Wallet and token → 💼 Wallet portfolio 
Type: nansen balance 0x…
How to read: composition by dollars, without spam tokens. The nansen prefix is required: a plain balance command is already taken by another source.
5.3 The DeFi part: assets minus debts
Question: is this $2M wallet really $2M.
Path: 🧠 Nansen → 🔎 Wallet and token → 💠 DeFi part 
Type: defi 0x…
How to read: the net figure, assets minus debts, unclaimed rewards and protocols by size. A wallet holding $2M with no debt and one holding $2M against $1.7M of debt look identical in a token list.
5.4 Counterparties
Question: who does this wallet trade with most.
Path: 🧠 Nansen → 🔎 Wallet and token → 🤝 Counterparties 
Type: counterparties 0x…
How to read: counterparties over 30 days and volumes. An address's connections say more about it than its balance.
6. Chains and your own tally
6.1 Chain ranking
Question: where to look today, before picking a token.
Path: 🧠 Nansen → 🌐 Chains and tally → 🌐 Chain ranking 
Type: chain rank In the mini-app: ➕ More
How to read: chains by TVL with the daily change, DEX volume and active addresses. When the response returns a zero change for every chain, the screen says "not measured in this window" instead of printing calm zeroes.
6.2 My contest tally
Question: how much of Nansen did I use.
Path: 🧠 Nansen → 🌐 Chains and tally → 🧮 My contest tally 
Type: nansen stats
How to read: your calls, credits and rank; a leaderboard without names and IDs. Free, it reads the bot's own log. Contribution is counted, privacy is not spent.
7. A free-form question to the Nansen agent
Question: anything that has no structural screen.
Three doors:
💬 In DM: ask in words.
👥🔘 In a group, by button: exchange card → 🔍 Nansen, on a card the bot posted.
👥🤖 In a group, by words: address the bot (a mention by username, the nickname "гроб" or "undertaker", or a reply to it) and ask.
How to read: the agent's answer in words, with a source attribution. 200 credits for fast, 750 for expert, the most expensive path in the bot. That is why the group door needs an approved group and has a daily cap per person, and why every other screen in this guide exists: a question with a structural answer should not cost 200 credits.
https://x.com/Rencrypta/status/2103016647061656017
8. Morning digest
Question: what did smart money do overnight, without asking.
Path: none, it arrives on a schedule in DM.
How to read: the smart money section of the morning digest. Background calls are counted apart from people: a job has no person and does not go into anyone's tally, otherwise the spend could not be explained.
9. The mini-app
The same answers, on a phone, as screens you can tap.
How to open: 🧠 Nansen → Nansen screens (mini-app). 
DM only: Telegram rejects a message carrying a mini-app button in a group, and the bot does not post the link there.
The mini-app computes nothing. Every screen renders the same dictionary the bot uses for its chat message, and under every chart sits the exact sentence the bot would say in chat, with the source, freshness, cost in requests and caveats. The picture and the words cannot drift apart.
Every list leads somewhere. Three crossings land on cards that already exist in the bot: token → token card, market → market card, wallet → account card. 
The page asks the bot to post the card in your chat, and prints what the bot answered next to the button you tapped. 
No full wallet address ever reaches the page: it sends the row number and the start of the label, the bot finds the address in the same response the screen was drawn from, and if the list moved in between, the bot refuses instead of opening the neighbouring wallet.
9.1 🎭 Whose %
Question: whose conviction is behind a market price.
How to read: pick a market, and the headline says how much of the examined money sits with wallets below a 40% win rate. One bar per holder: area is money, colour is the win-rate bucket (below 40, 40 to 60, above 60). Grey bars are holders whose history was not examined, counted on neither side. A resolved market is flagged: the numbers are final, not open risk.
Under it:
🧾 who is in it, with PnL: the same market's holders with entry price and how far up or down they are here. The market id is never typed, it travels from the card you tapped.
📲 open in the bot: the same market's card in chat.
9.2 🎯 Sharp
Question: which heated market has smart money on the other side.
How to read: four markets side by side, sharp money (win rate at or above 60%) against money of wallets that were wrong more often, ordered by sharp dollars. The biggest sharp holder is named for each. Tap a row and it opens in 🎭 Whose %: there is exactly one market breakdown on the page.
9.3 🗺 Map
Question: where other people's leverage hangs, for any perp.
How to read: the liquidation map. The ticker buttons are the most traded perps by measured 24h Hyperliquid volume, not a list kept by hand, and any other ticker can be typed → show map.
scale slider: the price window around the current price. Money outside the window is counted and named, not dropped.
detail slider: how many equal slices the window is cut into.
↔ / ↕: the same numbers in either orientation, redrawn without a single new request.
💾 save image: writes the chart to a file.
📩 send to chat: the bot posts the map as a picture in your chat, from where Telegram can save and forward it.
⚔️ compare top four: the risk board, four perps ordered by distance from price to the densest cluster. Tap a row for its map.
9.4 ➕ More
Question: what the other tabs cannot answer.
How to read: three signals.
Smart money trades as a share of market cap: the same $50K means opposite things in a $2M token and a $50B one.
Scheduled buying (DCA): the only forward-looking signal in the set, with the share of each program already spent. When every program is executed, the screen says so.
Chain ranking: where the money is at all, before an object is picked. Zero change on every chain reads "not measured in this window".
9.5 📡 Live
Question: is this data live.
How to read: one row per network call: endpoint, outcome class, milliseconds, credits, cache or wire, and which surface asked. It costs nothing extra, the telemetry was already writing those rows. People are not identifiable: the log stores a daily hash and never leaves the server.
9.6 When a screen refuses
It names the outcome class and the HTTP status. 402, 429 and 502 call for three different actions, and nobody reading a phone should have to open a server log to tell them apart.
9.7 Run it without a key
git clone https://github.com/RenatMursalimov/nansen-undertaker
cd nansen-undertaker
python3 -m http.server 8080
then open http://127.0.0.1:8080/webapp/index.html?rehearsal=1
A yellow REHEARSAL banner names the recording time. The fixtures are marked synthetic: the shape is real, from the production formatters, the numbers are invented, and the banner says so. The 📡 Live tab is off in rehearsal, because recorded rows would be the opposite of a liveness proof. The page and all fixtures are served in 18 ms.
10. Sentinel: live perp alerts
Question: what unusual is happening right now on the instruments I trade.
Path: 🔔 Onchain → Alerts → 👁 Sentinel, or 🧠 Nansen → 🧠 What smart money is doing → 👁 Sentinel 
Type: sentinel BTC (or watch BTC), sentinel all (the whole venue), sentinel (the state screen)

🧠 Nansen → 🧠 What smart money is doing → 👁 Sentinel
This is a subscription, not a question. 
Every 30 seconds the bot polls three public venues with no key: 
553 instruments on Variational, 234 perps on Hyperliquid, 210 live markets on Lighter. 
The hot ring keeps a point per poll for 90 minutes and gives the 15 and 60 minute moves. The cold ring keeps a point every 15 minutes for 7 days and gives sigma and percentiles. 
The detector is pure arithmetic: no network, no model, no database.
It rings only when a move is unusual for that instrument itself: 1.2% in 15 minutes or 2.5% in an hour, and at least 2.5 sigma over 20+ points of its own history. No sigma, no event. Instruments under $50,000 of daily turnover are not watched.
What it can send (tick them on the screen under 🔔 WHAT TO SEND):
Moves: price up or down, unusual for the instrument.
Open interest: money entering even while the price stands. An in-and-out spike within 3 hours is logged but does not ring. When interest grows and price does not move, the card says someone is absorbing against the flow.
Volume: turnover jumps against its own usual hour. Money shows up in volume before it shows up in price.
Venue gap: one ticker priced differently across venues, with the cost of entering on both sides next to it. If entry costs more than the gap, the card says so.
Crowded: 92% or more of open interest on one side, and paying for it at the top of its funding range. The card describes the construction, not the direction.
Ignition 🔥: 3+ smart money addresses bought one token, $100k+ within 180 minutes, at least 5 bps of market cap. Addresses, not trades: ten trades from one address is one person. Linked wallets are counted as one participant: "3 independent participants (addresses 4)".
Smart perp 🐋: 2+ smart money addresses opened the same side, $250k+ within 30 minutes.
Funding and Spread: off by default. Useful as the cost of entry on a card, noisy as a reason to ring.
How to read the card: 
the first line is the ticker and the size, the ticker links to the instrument card. Below it the venue, the cost of entry, the confidence out of 100 with every penalty named ("quote older than two minutes", "thin at $100k"). 

Then the same card is edited in place with Nansen: large addresses over 3h (who bought and sold), whose leverage sits in the token, the two nearest liquidation clusters from $100k, and a verdict computed by code. 

For crypto with a Polymarket price market, the card adds that market and who holds it. After the first card only "strengthened" or "pulled back" arrive as replies to it, at most two per kind.
Presets: a tap first shows, in numbers, what will change.
Beginner (set on the first subscription): moves, ignition, smart perp · moves from 3% · fuse 2 per 10 min · 12 a day · 120 min pause · digest every 30 min
Trader: adds open interest, volume, crowded · moves from 2% · fuse 3 per 10 min · 25 a day · 60 min pause · digest every 10 min
Quiet: moves, ignition, smart perp · moves from 5% · 6 a day · 180 min pause · digest every 60 min
Settings in words:
sentinel threshold 5: stay silent below 5%
sentinel quiet 22 8: quiet hours in UTC, sentinel quiet off clears them
sentinel off / sentinel on: pause without losing the list. Turning off also cancels what is already queued and says how many
sentinel briefs off: numbers only, no Nansen and no X
sentinel remove BTC: stop watching
sentinel report (📊 Hit rate): did the move continue an hour and a day later. Fewer than 20 samples in a bucket prints "sample too small", no percentage
On the screen:
📈 Market now: what moved most, where turnover grows, how many instruments moved at all, and the strongest move against the threshold. "Moved 0 of 192, strongest 0.00% against 1.20%" means the market is quiet, not the Sentinel. No request, no credit.
the 24h line: events, delivered, in digests, Nansen credits.
if your settings mean silence (no subscriptions, every kind unticked, every venue off), the screen lists why.
❓ How it works.
The fuse counts people, not tickers. A hard ceiling per window per person, 12 at most. Whatever does not pass goes into one digest message, sorted by strength, with the reason it did not ring and the rest named as a number: "and 34 weaker".
Before V2 the bot sent me 586 messages in one day, 101 and 100 in two neighbouring hours, with 2969 events in the detector. After V2: [число] messages a day.
No key needed to see it: python3 cli.py sentinel-card BTC hyperliquid (a live card), sentinel-demo (every alert kind), sentinel-presets (what each preset changes).
[FRAME S1: a live card with the Nansen block] [FRAME S2: the Sentinel screen with presets] [FRAME S3: 📈 Market now]
11. Through routes
Every screen leads to the next one. Three chains that show how.
From a trend to the people behind it. 🔥 Screener: 24h inflow → tap a ticker → token card → 🧠 breakdown → 🔄 Who bought and sold → tap a buyer → 🕵 Dossier. From "what is trending" to "who exactly is buying it" without copying a single address.
From a price to the quality of the money. 🎲 Trending markets → the market button → market card → 🎭 Who holds it → 🧾 Who is in it now → 🎰 Trader profile of the biggest holder. From "78% Yes" to "and this is how the wallet holding most of it did before".
From an alert to the leverage. 👁 Sentinel card → tap the ticker → instrument card → 💥 Liq. → 🗺 Liquidation map → ⚔️ Compare all four. From "BTC moved" to "here is where the next stops sit, and which of the four is closest to its edge".
The mini-app runs the same chains: every token, market and wallet on its screens opens the matching card in chat.
12. When it does not work: how to read a refusal
A screen never says "no data" when it means something else. Eight states, eight sentences:
✅ nokey: the request never went out 
✅ nocredits: the credit balance is exhausted 
✅ ratelimit: Nansen throttled the request, wait and repeat 
✅ timeout: no answer arrived in time 
✅ badreq: our request body was rejected, that is our bug, not the market 
✅ unsupported: the endpoint explicitly does not cover this asset
✅ http: provider or network error 
✅ empty: the request succeeded and there genuinely is no data
Only the last one means "nothing happened". 
The mini-app adds the HTTP status to the refusal. 
Charts are not drawn out of zeros, and a wallet without labels is "no labels", never "clean".
13. Boundaries
✅ The bot does not trade and does not advise. Not one "buy", not one "entry". It shows what happened and how unusual it was. 
✅ No hit rate on fewer than 20 samples. 
✅ A line that would not change a trader's decision is not printed. 
✅ Typed commands and the mini-app work in DM only. In a group: buttons on a card, or ask the agent in words. 
✅ The agent is the most expensive door: 200 or 750 credits, a daily cap per person, approved groups only.
 ✅ The Sentinel does not read the reason for a move: the card says so and leaves the news to you. Equities and funds outside their exchange session arrive only in the digest. 
✅ The Nansen key never leaves the server, wallet addresses never reach the browser, and the trading contour is not part of anything in this guide. 
✅ Where Nansen publishes no price, the screen names requests, not invented credits.
14. What it costs
✅ Smart flows: not in the official list, counted on a separate line 
✅ Screener 24h inflow: 1 credit 
✅ Smart holdings: 3 credits 
✅ Smart trades: 1 to 5 credits 
✅ DCA, Jupiter DCA: 1 request each
✅ Token breakdown 🧠: 4 requests, about 12 credits 
✅ Who bought and sold: 1 credit per side 
✅ Flows chart: 1 credit 
✅ Token information: 1 credit
✅ Backtest: 5 credits for 89 daily candles 
✅ Leveraged positions and the liquidation map: 5 credits, one and the same request 
✅ Who is positioned: 1 request 
✅ Risk board: one request per token, 4 
✅ Wallet perp account: not in the official list 
✅ Top perp traders: 5 credits 
✅ Trending markets, market card, probability, order book, market leaders: not in the official list; the card is 0 requests on a warm list 
✅ Who holds a market: 6 requests 
✅ Who is in a market: 1 request 
✅ Trader profile: 2 requests 
✅ Where money is sharp: 1 + N + N×H requests, 13 by default 
✅ Wallet profile: 3 requests; deep adds premium labels for 150 credits 
✅ Portfolio, counterparties: not in the official list 
✅ DeFi part: 1 request 
✅ Chain ranking: 1 request 
✅ My contest tally: free 
✅ Morning digest: counted apart from people 
✅ Sentinel: by number of requests, printed on its screen as "Nansen credits" ✅ The Nansen agent: 200 credits (fast) or 750 (expert)
15. Coverage: every scenario in the catalog, and where it is in this guide
All 34 scenarios of docs/CATALOG.md, generated from the bot's code.
💹 Smart money inflow by window → 1.1
🔥 Smart Money inside the shared Trends screen → 1.2
💼 What smart money accumulates → 1.3
🧠 Smart money trades over 24h + share of market cap → 1.4, 9.4
🏆 Top perp traders → 3.6
💥 Leveraged positions and the liquidation price → 3.1
🗺 Liquidation map → 3.2, 9.3
🩺 A wallet's perp account and room to liquidation → 3.5
🧠 Token breakdown → 2.1
🔄 Who net-bought and who sold → 2.2
🪪 Token info sheet → 2.4
📊 Holder-segment flows as a chart → 2.3
🧪 Backtest on onchain candles → 2.5
👤 Wallet profile → 5.1
🤝 Who a wallet trades with most → 5.4
💼 Wallet portfolio → 5.2
🎲 Trending Polymarket markets → 4.1
🎲 The card of one Polymarket market → 4.2
📈 Market probability chart → 4.3
📖 Polymarket order book → 4.4
🎭 Who holds the market → 4.5, 9.1
🎰 Polymarket trader profile → 4.8
🏆 Top traders of a specific market → 4.7
🔍 Free-form question to the Nansen agent → 7
🧊 Who buys on a schedule (DCA) → 1.5, 9.4
🌐 Chain ranking → 6.1, 9.4
💠 The DeFi part of a wallet → 5.3
🧾 Who is in a Polymarket market, and their PnL → 4.6, 9.1
🧊 Jupiter DCA by token → 1.6
⚖️ Who is positioned on a token → 3.3
🎯 Where the money on Polymarket is sharp → 4.9, 9.2
⚔️ Risk board → 3.4, 9.3
🧮 My contest tally → 6.2
📰 Morning digest → 8
34 of 34. Not covered on purpose: the catalog's list of client routes with no ordinary user scenario.
The integration code is public 
github.com/RenatMursalimov/nansen-undertaker 