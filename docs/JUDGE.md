# For judges: from clone to the first screen in under a minute

Three commands. No API key, no Telegram account, no build step.

```bash
git clone https://github.com/RenatMursalimov/nansen-undertaker && cd nansen-undertaker
python3 -m http.server 8080
# open http://127.0.0.1:8080/webapp/index.html?rehearsal=1
```

Measured on a clean machine: the page and all fixtures are served in **18 ms**; the whole
sequence is dominated by `git clone`. What you should see, top to bottom:

1. a yellow **REHEARSAL** banner naming the recording timestamp — the data is recorded, not live;
2. the hero screen: *“Of $1.94M examined, $1.30M (67%) sits with wallets whose win rate is below
   40%.”*, one bar per holder (area is money, colour is the win-rate bucket), and **two grey bars**
   whose money is counted on neither side;
3. tab **🎯 Sharp money** — the same four heated markets side by side: how much money sits with
   wallets that were right before (win rate at or above 60%) against the money of those that were
   not (below 40%), ordered by sharp **dollars**, because 90% of $300 is not a signal. A tap on a
   row opens that market in the hero — there is exactly one market breakdown on the page;
4. on that hero, the button **🧾 who is in it, with PnL** — the same market's holders with what is
   happening to them *here*: entry price, and how far up or down they are in this market. The market
   id is never typed: it travels from the card you tapped;
5. tab **🗺 Map** → **⚔️ compare top four** — the four most traded perps ordered by how *close* the
   price is to the densest liquidation cluster, not by how big it is. A token whose price did not
   load goes last and says so: last place is not "safer". Two sliders change the price window and
   the number of levels, and **↔ / ↕** redraws the same numbers in either orientation without a
   single new request; **💾 save image** writes the chart to a file;
6. tab **➕ More** — the two signals that answer something the other screens cannot: who is buying on
   a *schedule* (the only forward-looking signal in the set) and which chains hold and move the
   money;
7. under every screen: source, freshness, cost in requests, the caveats, and the **exact sentence
   the bot would say in chat**.

`?rehearsal=1` reads `fixtures/*.json`. Those files carry `"provenance": "synthetic"`: the shape is
real (it comes from the production formatters), the numbers are invented. That is stated in the file
and printed on the banner, because “recorded” and “invented” are different claims.

## What the offline suite proves (still no key)

```bash
python3 tests/test_public.py     # network boundary substituted, everything else is production code
python3 scrub.py                 # no server paths, wallets, keys or runtime state
```

## The live mode needs a key, and it is honest about it

```bash
cp .env.example .env             # put NANSEN_API_KEY here
python3 tools/nansen_live_smoke.py --run --market-id 1130012
```

Without a key every screen answers **`nokey` — “the request never went out”**, not “no data”. That
distinction is the point of the whole failure layer: eight states, eight different sentences, and
none of them reads like “all clear”.

## The one claim worth checking in the code

The mini-app **does not compute anything**. Every screen renders the same dictionary the bot uses
to build its chat message:

- `nansen_scene.py` — builds the dictionary (thresholds, “unknown history counts on neither side”,
  cost, caveats);
- `nansen_gate.py` — limits, telemetry surface, strips wallet addresses before the browser sees
  them;
- `webapp/index.html` — draws it. Hand-rolled SVG, zero dependencies.

A law test in the private repository injects one number into the dictionary and requires **both**
the bot text and the mini-app JSON to change. If only one changes, a second source of truth has
appeared and the build goes red. That is why the number on the chart cannot drift away from the
number in the sentence below it.

## Cost is named in requests, not invented in credits

Nansen does not publish prices for `prediction-market/top-holders`, `prediction-market/address-summary`,
`tgm/perp-positions` or `smart-money/dex-trades`. So the screens say “6 requests”, not a made-up
credit number. Guessing there would be a lie in the most checkable place.
