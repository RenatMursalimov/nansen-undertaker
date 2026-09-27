# Technical guide: the Nansen API in practice (from the Undertaker's code)

This is a guide for developers, not a pitch for a bot. The Undertaker is a Telegram bot for a
Russian-speaking crypto community; its Nansen layer lives in one client (`nansen_api.py`), a
telemetry module (`nansen_log.py`) and a live alerter on top of them (`sentinel/`). All of it is
published byte-for-byte in [nansen-undertaker](https://github.com/RenatMursalimov/nansen-undertaker),
so every path and every code block below can be opened next to this text.

What this guide covers: which endpoints we call, with which bodies, which response fields we
actually read, what each call costs by the official price list, and the traps we hit with live
probes and how we got around them. Every number has a source: a live probe of 27 September 2026
(two runs on the owner's key, 49 + 146 credits, recorded in
`docs/journal/2026-09-27-nansen-review.md`, section 9), the measurements in
`docs/journal/2026-09-26-sentinel-v2.md`, or the code itself. Where a price is not published,
this guide says so instead of guessing.

Russian version: [`ARTICLE_TECH_GUIDE_ru.md`](ARTICLE_TECH_GUIDE_ru.md). The user-facing guide
(screens and buttons) is [`ARTICLE_USER_GUIDE.md`](ARTICLE_USER_GUIDE.md); the machine-built
catalog of every screen is [`CATALOG.md`](CATALOG.md).

Wallet addresses in the response samples are replaced with `addr-N` labels. Token contracts are
public and left as they are.

---

## 1. Setup: one throat, one box, seven kinds of "no"

### Base URL and the key header

Everything is `POST` with a JSON body. The key travels in a header called `apikey`; there is no
`Authorization: Bearer`. From `nansen_api.py`:

```python
_BASE = "https://api.nansen.ai/api/v1"
_CACHE_TTL = 1800  # 30 мин кэш на одинаковые запросы

def _headers():
    return {"Content-Type": "application/json", "apikey": _key()}
```

The beta routes (`tgm/historical-*`, `token-screener/historical`) live under
`https://api.nansen.ai/api/v1beta1` and go through `_post_beta`; the shape of the body differs
from v1 (see `hist_token_screener` below).

### Every call goes through one throat

There is exactly one place where a network request is made, `_http_once`. It does the HTTP call,
reads the credit headers, classifies a failure, and writes one telemetry line. Everything else
(`_post`, `_post_fix`, `_post_beta`, `ask_agent`) is a wrapper around it. This is what makes
"where did the credits go" answerable:

```python
    try:
        r = httpx.post("%s/%s" % (base, path), headers=_headers(), json=body, timeout=timeout)
        http = r.status_code
        _note_credits(r.headers)
        if http != 200:
            _cls = _classify(http, r.text)
```

### Cache: 30 minutes by default, a shorter life for a live watcher

Identical requests are served from a JSON cache for 30 minutes (`_CACHE_TTL`). The alerter
needs fresher data, so `_post` takes a per-call `ttl`: the live feed reader uses 20 seconds and
its own cache key, so the digest and tweet jobs keep their 30-minute cache and their credit budget.
From `sm_dex_trades`:

```python
    return _rows(_post("smart-money/dex-trades",
                       {"chains": chains,
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "block_timestamp", "direction": "DESC"}]},
                       ckey=f"{_k}:{','.join(chains)}:{per_page}",
                       ttl=(ttl if ttl is not None else (20 if live else None))))
```

### Retries: exactly one, and only when the provider says so

On a non-200 the client retries once, and only for the error codes Nansen itself marks as
retryable, or for a 5xx without a body (that is how a 503 from their edge looks). It never
retries a 400/422 (the same body gives the same answer) and never a 402 (no money is no money).
If the provider asks to wait more than three seconds, the client does not wait: it tells the
person. From `nansen_api.py`:

```python
_ERR_RETRY = ('rate_limit_exceeded', 'query_timeout', 'upstream_unavailable', 'internal_error')
_HTTP_RETRY = (500, 502, 503, 504)
_RETRY_MAX_WAIT = 3.0
```

### Empty versus refused: the call box

An empty list from a 402 looks exactly like an empty list from "no trades today". The client
keeps them apart with a per-scene "box" in `nansen_log.py`: every call notes its outcome in the
box, and the worst outcome in the box is what the screen reports. The classes, from
`nansen_log._SEV`, ordered by severity:

```python
_SEV = {'ok': 0, 'empty': 1, 'unsupported': 2, 'http': 3, 'badreq': 4, 'timeout': 5,
        'ratelimit': 6, 'nocredits': 7, 'nokey': 8}
```

The HTTP status alone is not enough to classify. A 422 means two different things: "your body is
wrong" (our bug, repairable) and "this endpoint does not cover this asset" (a coverage boundary,
nothing to repair). Only the text tells them apart, and `_classify` reads the provider's own
error code first:

```python
_ERR_CLASS = {
    'insufficient_credits': 'nocredits',
    'rate_limit_exceeded': 'ratelimit',
    'query_timeout': 'timeout',
```

```python
    if status == 402:
        return 'nocredits'          # кредиты кончились
    if status == 429:
        return 'ratelimit'          # придержали по частоте
    if status in (400, 422) and any(m in str(text).lower() for m in _UNSUPPORTED_MARKS):
        return 'unsupported'        # площадка сказала: этого актива у эндпоинта нет вовсе
```

The rule that follows from this: **read the failure class inside the `with scene(...)` block.**
The box is reset on exit. We had a bug exactly here: `sentinel/ignition.py` read `fail_reason()`
after the block, got the default `empty`, and printed a 402 as "smart money is silent". The fix is
one box per side and the reason read inside it (`ignition.confirm`, fixed 27 September).

### Credits: the header, not a table

Every response carries `x-nansen-credits-cost`, `x-nansen-credits-remaining` and
`x-nansen-credits-used`, including 422 and 404 responses (probe of 27 September: a 422 on
`tgm/perp-pnl-leaderboard` cost 5, a 404 on `tgm/token-transfers` cost 1). The client reads the
cost header into the telemetry line as a measurement (`est=0`); a table of published prices is the
fallback, and a route with no published price is counted separately as "price unknown" rather than
given an invented number (`nansen_log._EP_EST`, `_EP_UNKNOWN`).

### Schema repair by the provider's own words

Some endpoints were never documented in a way we could trust, so `_post_fix` sends the body,
reads the 422 text ("Field 'x' is not recognized", "Required field 'body -> y' is missing"),
edits the body accordingly, retries up to `_FIX_ROUNDS = 3` times, and pins the learned body to
disk (`nansen_schema.json`) so the next restart does not repeat the rounds. It stops honestly when
the provider asks for a field it cannot build: that stop is exactly how we learned that
`tgm/perp-positions` wants `token_symbol` (see traps).

---

## 2. Endpoints by group

For each endpoint: the minimal body we send, the response fields we actually read, the price, and
one line on why a trader cares. Prices: **listed** means the official price list; **header** means
measured on 27 September from `x-nansen-credits-cost`; **openapi** means the `x-credit-cost` field
of `https://api.nansen.ai/openapi.json` as read on 27 September (probe №1); **not published** means
none of these, and the client counts the call as "price unknown". Client function names are from
`nansen_api.py`.

### Smart Money

| Endpoint | Body we send | Fields we read | Price | Why a trader cares |
|---|---|---|---|---|
| `token-screener` (`smart_money_netflow`) | `chains`, `timeframe` (`24h`), `filters.only_smart_money`, `order_by netflow`, `pagination` | `token_symbol`, `chain`, `netflow` fields per window | 1 (listed) | Where smart money moved net over the window |
| `smart-money/netflow` | `chains`, `filters.include_stablecoins: false`, `pagination` | `token_symbol`, `chain`, `net_flow_1h_usd`, `net_flow_24h_usd`, `net_flow_7d_usd`, `net_flow_30d_usd`, `trader_count`, `token_age_days`, `market_cap_usd` | 5 (header) | The same question with four windows and a trader count in one row |
| `smart-money/holdings` (`smart_money_holdings`) | `chains`, `filters.value_usd.min`, `filters.include_stablecoins`, `pagination`, `order_by value_usd` | `token_symbol`, `value_usd`, `holders_count`, `balance_24h_percent_change`, `share_of_holdings_percent` | 5 (header) | What they hold, not what they traded today |
| `smart-money/dex-trades` (`sm_dex_trades`) | `chains`, `pagination` (100 for the watcher), `order_by block_timestamp DESC` | `token_bought_symbol`, `token_bought_address`, `trade_value_usd`, `token_bought_market_cap`, `token_bought_age_days`, `trader_address`, `trader_address_label`, `block_timestamp`, `transaction_hash` | 5 (header) | Individual entries: who bought what, with market cap and token age in the same row |
| `smart-money/perp-trades` (`sm_perp_trades`) | `pagination`, `order_by block_timestamp DESC` | `token_symbol`, `side`, `action`, `value_usd`, `price_usd`, `token_amount`, `trader_address_label` | 5 (header) | Smart-money perp entries on Hyperliquid, one side per row |
| `smart-money/dcas` (`smart_money_dcas`) | `pagination` only (the route rejects `chains`) | rows as returned | 5 (openapi) | Who accumulates in equal slices |

Live sample, `smart-money/netflow`, 27 September, per_page 3 (first two rows):

```json
{"chain": "solana", "token_symbol": "🌱 E/ACC", "net_flow_24h_usd": 207520.29, "net_flow_7d_usd": 572729.81, "trader_count": 41}
{"chain": "solana", "token_symbol": "STONK", "net_flow_24h_usd": 138602.51, "net_flow_7d_usd": -3685700.51, "trader_count": 364}
```

### Token God Mode (`tgm/*`)

| Endpoint | Body we send | Fields we read | Price | Why a trader cares |
|---|---|---|---|---|
| `tgm/flow-intelligence` (`tgm_flow_intelligence`) | `chain`, `token_address`, `timeframe` (`1d`) | `smart_trader_net_flow_usd`, `whale_net_flow_usd`, `fresh_wallets_net_flow_usd`, `exchange_net_flow_usd`, `public_figure_*`, `top_pnl_*`, each with `_avg_flow_usd` and `_wallet_count` | 1 (listed) | Who is moving the token by holder segment |
| `tgm/who-bought-sold` (`tgm_who_bought_sold`) | `chain`, `token_address`, `buy_or_sell`, `date.from/to` (hours allowed), `pagination`, `order_by bought_volume_usd` or `sold_volume_usd` by side | `address`, `address_label`, `bought_volume_usd`, `sold_volume_usd`, `trade_volume_usd` | 1 (listed) | Who is net buying and who is net selling in a window |
| `tgm/holders` (`tgm_holders`) | `chain`, `token_address`, `label_type` (`all_holders`), `aggregate_by_entity: false`, `pagination`, `order_by value_usd` | `address`, `address_label`, `value_usd`, `ownership_percentage`, `balance_change_24h/7d/30d` | 5 (listed) | Who holds the token, with labels and share |
| `tgm/pnl-leaderboard` (`tgm_pnl_leaderboard`) | `chain`, `token_address`, `date`, `pagination` | `trader_address`, `trader_address_label`, `pnl_usd_realised`, `pnl_usd_total`, `roi_percent_total`, `nof_trades`, `still_holding_balance_ratio` | 5 (listed) | Who has actually made money on this token |
| `tgm/token-information` (`tgm_token_information`) | `chain`, `token_address`, `timeframe` | top level: `symbol`, `name`, `contract_address`; nested `token_details` and `spot_metrics` | 1 (listed) | One-call fact sheet (see traps: the numbers are nested) |
| `tgm/indicators` (`tgm_indicators`) | `chain`, `token_address` | `risk_indicators`, `reward_indicators` | 5 (listed) | Nansen Score decomposition |
| `tgm/perp-positions` (`perp_positions`) | `token_symbol` (required), `pagination`, `order_by position_value_usd` | `address`, `address_label`, `side`, `position_value_usd`, `entry_price`, `liquidation_price`, `leverage`, `mark_price`, `upnl_usd`, `funding_usd` | 5 (header) | Where other people's leverage and liquidation prices sit |
| `tgm/position-intelligence` (`perp_positioning`) | `token_address` only, and the value must be the perp ticker (`ETH`), not a contract | `smart_trader_longs_usd`, `smart_trader_shorts_usd`, `whale_longs_usd`, `whale_shorts_usd`, `public_figure_*`, `*_total_usd` | 1 (header) | Longs against shorts by segment: who is against whom |
| `tgm/perp-pnl-leaderboard` (`perp_pnl_leaderboard`) | `token_symbol`, `date`, `pagination`, `order_by pnl_usd_total` | as `pnl-leaderboard` | 5 (listed) | Who profits on this perp market |
| `tgm/transfers`, `tgm/token-ohlcv`, `tgm/flows`, `tgm/dex-trades`, `tgm/jup-dca` | bodies in `nansen_api.py` | registered, no user screen yet | 1 (openapi for `flows`, `dex-trades`, `jup-dca`; header for `transfers`, `token-ohlcv`) | Client-side groundwork, listed in `CATALOG.md` without a user door |

Live sample, `tgm/who-bought-sold`, WETH on Base, `BUY`, window `00:00` to `04:43` UTC on
27 September:

```json
{"address": "addr-1", "address_label": "Token Millionaire", "bought_volume_usd": 8209130.55, "sold_volume_usd": 5453679.78}
{"address": "addr-2", "address_label": "Token Millionaire", "bought_volume_usd": 3098666.86, "sold_volume_usd": 2191752.59}
```

Live sample, `tgm/perp-positions`, `token_symbol: BTC`, 27 September:

```json
{"address": "addr-7", "side": "Short", "position_value_usd": 238408587.02, "entry_price": 75949.4, "liquidation_price": 139297.91, "leverage": "5X"}
{"address": "addr-8", "side": "Short", "position_value_usd": 147645336.70, "entry_price": 74443.4, "liquidation_price": 149999.23, "leverage": "5X"}
```

### Perps (top level)

| Endpoint | Body we send | Fields we read | Price | Why a trader cares |
|---|---|---|---|---|
| `perp-screener` (`perp_screener`) | `date` (required), `pagination`, `order_by volume` | `token_symbol`, `volume`, `open_interest`, `funding`, `mark_price`, `buy_sell_pressure`, `trader_count` | 1 (header) | Which perp markets are busy and how they lean |
| `perp-leaderboard` (`perp_leaderboard`) | `date` (dates only), `pagination`, `filters.account_value` | `trader_address`, PnL and account fields | 5 (listed) | Who runs the biggest, best accounts |
| `profiler/perp-positions` (`profiler_perp_positions`) | `address` only (no `pagination`) | `data` is an object: `asset_positions[].position.{coin, szi, leverage.value, liquidation_px, position_value, unrealized_pnl}`, `margin_summary_account_value_usd`, `margin_summary_total_margin_used_usd`, `withdrawable_usd` | 1 (header) | A wallet's whole perp account and its distance to liquidation |

Live sample, `perp-screener`, 27 September:

```json
{"token_symbol": "BTC", "volume": 995803347.36, "open_interest": 3126957894.95, "funding": 1.25e-05}
{"token_symbol": "ZEC", "volume": 367999861.78, "open_interest": 845728495.85, "funding": 1.25e-05}
```

### Profiler (wallets)

| Endpoint | Body we send | Fields we read | Price | Why a trader cares |
|---|---|---|---|---|
| `profiler/address/labels` (`profiler_labels`) | `address`, `chain`, `pagination` | `label`, `category`, `kind` | **100 (header)** | Who this wallet is; note the price |
| `profiler/address/premium-labels` | same, premium | same plus smart-money labels | 500 (openapi) | Smart Money / Fund labels, at a real price |
| `profiler/address/pnl-summary` (`profiler_pnl_summary`) | `address`, `chain`, `date` (required) | `realized_pnl_usd`, `win_rate`, trade counts, top tokens | 1 (openapi) | Does this wallet actually win |
| `profiler/address/related-wallets` (`profiler_related_wallets`) | `address`, `chain`, `pagination` | `address`, `address_label`, relation | 1 (openapi) | The cluster behind an address |
| `profiler/address/counterparties` (`profiler_counterparties`) | `address`, `chain`, `date`, `pagination` | counterparty rows (27 September: empty for the probe address) | 5 (header) | Who this wallet trades with |
| `profiler/address/current-balance` (`profiler_current_balance`) | `address`, `chain`, `hide_spam_token: true`, `pagination` | token balances | 1 (openapi) | What is in the wallet now |
| `profiler/perp-trades`, `profiler/address/historical-balances`, `profiler/address/transactions`, `profiler/dex-trades` | bodies in `nansen_api.py` | registered, no user screen yet | 1 (openapi for `transactions`, `dex-trades`; header for `perp-trades`, `historical-balances`) | History of an address |

Live sample, `profiler/address/labels`, the public Ethereum block builder, 27 September. This one
call cost 100 credits:

```json
{"label": "biacc.eth*", "category": "social"}
{"label": "biacc.eth", "category": "social"}
```

### Prediction markets (Polymarket)

| Endpoint | Body we send | Fields we read | Price | Why a trader cares |
|---|---|---|---|---|
| `prediction-market/market-screener` (`pm_market_screener`) | `query`, `status` (`active`), `pagination`, `order_by volume_24hr` | `market_id`, `question`, `volume_24hr`, `liquidity`, outcome prices | 1 (openapi) | Which markets are live and liquid |
| `prediction-market/top-holders` (`pm_top_holders`) | `market_id`, `pagination`, `order_by position_size` | `address`, `address_label`, `outcome`, `position_size`, `avg_entry_price` | 5 (openapi) | Whose money sits on which side |
| `prediction-market/pnl-by-market` (`pm_pnl_by_market`) | `market_id`, `pagination`, `order_by` | PnL per trader on the market | 5 (openapi) | Who has been right on this market before |
| `prediction-market/pnl-by-address`, `address-summary`, `orderbook`, `ohlcv`, `position-detail`, `categories` | bodies in `nansen_api.py` | see `pm_*` functions | 1 to 5 (openapi) | Trader profile, book depth, price history |
| `prediction-market/event-screener`, `trades-by-market`, `trades-by-address` | registered after the 27 September probe (the old paths answered 404) | not read by a screen yet | 1 (header) for `event-screener` and `trades-by-market`; `trades-by-address` was not probed, price not measured | Events and trade tape |

The bot's reputation screen (`pm_reputation`) combines `top-holders` with `address-summary` per
holder to answer "whose conviction is this probability": the price is read next to how the money
behind each side has done before. That is the product story; the API story is that both calls cost
1 to 5 credits by the openapi list, and the per-address loop is the part that multiplies, so the
screen is capped at five addresses (`PM_REP_TOP = 5`) and fetches them in parallel.

### Agent

`agent/fast` (200 credits, listed) and `agent/expert` (750 credits, listed) take one required
field, `text`, and stream SSE events (`delta` with text, `finish` with a `conversation_id` you
can pass back to continue). `ask_agent` in `nansen_api.py` sends `{"text": question}`. These two
are the only calls the client never makes on its own: they are behind an explicit user action and
a confirmation, and the sweep tool refuses to run them without `--include-agents`.

---

## 3. Traps we caught with live probes

Each trap below is backed by a recorded probe. "27.09" is the two-run probe of 27 September
(`docs/journal/2026-09-27-nansen-review.md`, section 9); "sentinel-v2" is
`docs/journal/2026-09-26-sentinel-v2.md`. Where a trap is locked by a test, the test is named.

### 3.1 `price_usd` is the price of one token, not the size of the trade

In `smart-money/perp-trades` the row carries both `price_usd` and `value_usd`. The probe of
27.09 shows the ratio is exactly the token amount:

```text
{"token_symbol": "xyz:NCLD", "side": "Short", "price_usd": 25.166, "value_usd": 130.10822, "token_amount": 5.17}
value_usd / price_usd = 5.1700
{"token_symbol": "PURR", "side": "Short", "price_usd": 0.13061, "value_usd": 13.061, "token_amount": 100.0}
value_usd / price_usd = 100.0000
```

So the size is `value_usd`, and `price_usd` is the entry price. The DEX feed has no price at all;
its size is `trade_value_usd`. The generic money finder in the client refuses anything that looks
like a price, a fee or a balance:

```python
_NOT_MONEY = ('price', 'pnl', 'fee', 'gas', 'balance', 'market_cap', 'mcap', 'fdv',
              'liquidity', 'supply', 'net_worth', 'networth', 'roi', 'apy')
```

And the feed reader takes the size field by name, with the perp field as the fallback
(`sentinel/ignition.py`, `rows_from_feed`):

```python
            'usd': _f(t.get('trade_value_usd')) or _f(t.get('value_usd')),
```

Tests: `tests/test_nansen_contest.py::t_probe_19_09_schemas_are_pinned_and_dead_ends_buried`
("у перп-сделок сумма это value_usd").

### 3.2 `who-bought-sold`: the volume field depends on the direction

Every row carries both `bought_volume_usd` and `sold_volume_usd`. Which one is the answer depends
on `buy_or_sell`, and so does the sort field. Probe 27.09, WETH on Base:

```text
BUY  (order_by bought_volume_usd): addr-1 bought 8209130.55, sold 5453679.78
SELL (order_by sold_volume_usd):   addr-4 bought  982498.52, sold 2036729.13
```

Reading the wrong column gave us a card that listed a wallet under "sold" with its buy figure
(sentinel-v2, 26 September). The client sorts by side and reads by side:

```python
            "order_by": [{"field": "%s_volume_usd" % ("bought" if buy_or_sell == "BUY" else "sold"),
                          "direction": "DESC"}]}
```

```python
    want = 'sold_volume_usd' if str(side).upper() == 'SELL' else 'bought_volume_usd'
```

Note the labels in the sample: `Token Millionaire`. The body carries no smart-money label filter,
so these are large addresses, not smart money, and the bot's card says "large addresses over 3 h".
Test: `tests/test_sentinel.py::t_wallet_sizes_are_read_not_lost`.

### 3.3 `date.from/to` accepts hours; `days=1` was a 30-hour window into the future

The official CLI sends only `YYYY-MM-DD`, and our old `days=1` sent yesterday `00:00:00Z` to
today `23:59:59Z`: more than thirty hours, part of it in the future, under a caption that said
"24 h". The probe of 27.09 settled whether the endpoint honours the time part:

```text
window 00:00-02:00 UTC: 10 rows, bought $10,416,447
window 02:00-04:00 UTC: 10 rows, bought  $4,699,545
3 h window: 20 rows $12,812,346 | calendar "today": 20 rows $15,994,597
```

Two non-overlapping windows of the same day return different rows, so the hours are honoured. The
client builds the window from "now minus N hours" when `hours` is given (`_date_range`), and the
alerter's on-chain context is a 3-hour window (`sentinel/ignition.py`, `CONFIRM_HOURS = 3`).
Not every route accepts a time part: `smart-money/historical-holdings` answered 422 "Time
components (T, :, Z, +) are not supported for this endpoint" (`sentinel/lab.py`).

### 3.4 `position-intelligence` works by symbol; by contract it returns zeros

The field is called `token_address`, but the data behind it is Hyperliquid perp positioning, and
the key of a perp market is its ticker. Probe 27.09, three calls, one credit each:

```text
ETH                                          -> smart_trader_longs_usd 82104399.45, whale_longs_usd 1270977664.77
WETH                                         -> smart_trader_longs_usd 0.0, whale_longs_usd 0.0
0x4200000000000000000000000000000000000006   -> smart_trader_longs_usd 0.0, whale_longs_usd 0.0
```

A 200 with a row of zeros is not "no leverage"; it is the wrong key. Two things follow. The screen
asks by ticker, and when it starts from a contract it takes the symbol DexScreener gives that
contract. And wrappers are folded to the perp ticker, because DexScreener says `WETH` and the perp
market is `ETH` (`nansen_api.py`, `positioning_key`):

```python
_PERP_WRAPPERS = {
    'WETH': 'ETH', 'STETH': 'ETH', 'WSTETH': 'ETH', 'WEETH': 'ETH', 'RETH': 'ETH', 'CBETH': 'ETH',
    'WBTC': 'BTC', 'CBBTC': 'BTC', 'TBTC': 'BTC',
    'WSOL': 'SOL', 'WBNB': 'BNB', 'WMATIC': 'POL', 'WPOL': 'POL', 'WAVAX': 'AVAX',
}
```

Test: `tests/test_nansen_contest.py::t_positioning_key_folds_wrappers_to_the_perp_ticker_d8`.

### 3.5 `tgm/perp-positions` requires `token_symbol`

Probe 27.09, the same route with two bodies:

```text
POST tgm/perp-positions {"token_symbol": "BTC", ...} -> 200, 3 rows
POST tgm/perp-positions {"token_address": "BTC", ...} -> 422
{"error":"Missing field","message":"Required field 'body -> token_symbol' is missing","code":"missing_field","param":"token_symbol", ...}
```

Both calls cost 5 credits: a 422 is not free. The repair loop in `_post_fix` reads exactly this
message; it can rename a field the provider calls unknown, but it cannot invent a required one,
which is how the name was learned in the first place (19 September) and pinned in the client:

```python
    return _rows(_post_fix("tgm/perp-positions",
                       {"token_symbol": str(token).upper(),
```

The same trap sat next door: `tgm/perp-pnl-leaderboard` also wants `token_symbol`, and its sort
field is `pnl_usd_total`, not `total_pnl` (probe 27.09, №4: the 422 lists the valid options).
Test: `t_paths_and_bodies_match_the_live_probe_of_27_09`.

### 3.6 One page of `smart-money/dex-trades` covers about 40 minutes

The feed is a tape, and one page of 100 trades is shorter than any useful window. Measured twice:

```text
sentinel-v2, 26.09: 100 trades cover 44 minutes; 4 pages cover 128 minutes
probe 27.09:        100 trades cover 38 minutes (04:04:13 to 04:42:33 UTC)
```

The Smart Ignition event needs 180 minutes (`sentinel/config.py`, `ign_window_min`). So the
alerter stores every page in its own table and builds the window from the database, not from the
response (`sentinel/ignition.py`, `scan`):

```python
    rows = rows_from_feed(trades)
    store.sm_trades_put(rows, feed='dex', now=now)
    win_s = int(config.ign_window_min()) * 60
    stored = store.sm_trades_window(now - win_s, feed='dex')
    groups = group(stored or rows, now=now)
```

Test: `tests/test_sentinel.py::t_feed_is_stored_because_window_is_longer_than_page`.

### 3.7 The 🌱 mark inside symbols of new tokens

Nansen prefixes the symbol of a young token with a seedling. Probe 27.09: 11 of 100 trades in one
page carried it (`🌱 AAF`, `🌱 BAG`, `🌱 BOAR`), and a `⚠️ JIZZ` showed that other marks exist too.
The same symbol arrives in `smart-money/netflow` (`🌱 E/ACC`). If you key anything by symbol, strip
the mark or the same token lives under two names; if you show it to a person, keep it, because
"zero days old" is the most important thing about the token. From `sentinel/assets.py`:

```python
NEW_MARK = '\U0001F331'      # 🌱
```

```python
    s = str(sym or '').strip()
    new = NEW_MARK in s
    if new:
        s = s.replace(NEW_MARK, ' ')
    return ' '.join(s.split()).upper(), new
```

### 3.8 Wrapped natives on foreign chains

A native coin on an EVM chain lives as a wrapper, and the DEX flow of a wrapper answers "how much
was bridged", not "what is being done with the asset". For the alerter this is a decision, not a
measurement: assets without a DEX trace of their own are excluded from the on-chain block before
any credit is spent (`sentinel/assets.py`, `NATIVE_L1`, `onchain_refusal`). BTC is in that list
since 27 September (its "wrapper" WBTC is a bridge); ETH and SOL are not, because WETH and wSOL
live on their home chains. The live case that put HYPE on the list: price matching found a Solana
token with the same symbol and printed a $6 three-hour trace for the Hyperliquid native
(sentinel-v2, 26 September).

### 3.9 Seven paths that answered 404 and the paths from the openapi document

Probe 27.09, №6: seven registered paths were dead. For six of them the neighbouring path in the
openapi document answered 200 on the same probe, one credit each; the seventh,
`prediction-market/trades-by-address`, is taken from the openapi document and has not been probed
yet.

| 404 | path in the openapi document |
|---|---|
| `tgm/token-transfers` | `tgm/transfers` |
| `tgm/price-ohlcv` | `tgm/token-ohlcv` |
| `profiler/address/perp-trades` | `profiler/perp-trades` |
| `profiler/address/historical-token-balances` | `profiler/address/historical-balances` |
| `prediction-market/events` | `prediction-market/event-screener` |
| `prediction-market/trades` | `prediction-market/trades-by-market` |
| `prediction-market/wallet-trades` | `prediction-market/trades-by-address` (not probed) |

A 404 costs one credit and tells you nothing about whether the feature exists. The way to tell
"gone" from "moved" is `https://api.nansen.ai/openapi.json`: it lists every route with its
`x-credit-cost`, and the sweep tool compares the registry against it (probe 27.09, №1).

---

## 4. Architecture of an alerter on top of Nansen

The Sentinel watches three perp venues (Variational Omni, Hyperliquid, Lighter) with their public
endpoints and uses Nansen for two things: context on a move, and two events of its own. The model
takes no part in any decision; every threshold is a number from a measurement, named in
`sentinel/config.py`.

```text
 public venues (every 30 s)                    Nansen (every 180 s)
 Variational / Hyperliquid / Lighter           smart-money/dex-trades, per_page 100
        |                                              |
        v                                              v
 ring of snapshots per (venue, ticker)         sentinel_sm_trades table
 mark, volume, OI, funding, spread             (window 180 min built from the DB,
        |                                       one page covers ~40 min)
        v                                              |
 detector.detect(listing, rows, ring)                  v
   move_15m >= 1.2 % or move_60m >= 2.5 %      ignition.group(): 3+ distinct smart addresses,
   AND z >= 2.5 over >= 20 own points          $100k+, >= 5 bps of market cap -> Smart Ignition
   OI surge, volume surge, funding tail,       smart-money/perp-trades: 2+ addresses, one side,
   spread shock, crowd                         $250k+ in 30 min -> Smart Perp
        |                                              |
        +------------------ events --------------------+
                              |
                              v
                 outbox: one thread per instrument,
                 dedupe, cooldown, per-person fuse,
                 quiet hours, digest for the rest
                              |
                              v
                 card sent to Telegram (numbers from the venue)
                              |
                              v  (enrich_tick, budget: one per (venue, ticker) per hour)
                 ignition.confirm(): contract by price match (DexScreener),
                   tgm/who-bought-sold BUY + SELL, 3 h window, one box per side
                 _perp_lines(): tgm/position-intelligence by perp ticker,
                   tgm/perp-positions: two nearest $100k+ liquidation clusters
                 verdict_lines(): computed by code
                              |
                              v
                 edit_message_text on the SAME card (the phone does not buzz twice)
```

The parts that matter for anyone building on the API:

* **The ring is the sigma.** Every instrument gets its own history; a move is an event only when
  it is unusual for that instrument (`z >= 2.5` over at least 20 of its own points,
  `sigma_min_points`). No sigma, no event.
* **Threads, not floods.** One Telegram thread per instrument; later events on the same move are
  replies ("strengthened", "pulled back"), at most two per kind.
* **Enrichment is an edit.** Nansen context is added by editing the card that was already sent
  (`sentinel/outbox.py`, `edit_message_text`), so a person gets one notification, and the
  numbers from the venue never wait for Nansen.
* **A budget per instrument per hour.** `store.enrich_recent` refuses a second enrichment of the
  same (venue, ticker) within `ENRICH_EVERY_S = 3600`; on 26 September the owner had received 279
  enrichments in a day, one per event, most of them for the same instruments.
* **Refusal is printed as refusal.** A 402 or 429 on either side of `who-bought-sold` gives the
  verdict "on-chain not read: <reason>" and no net figure; only a genuine empty answer is "silent".
* **Credits are the header.** The alerter's daily spend is the sum of `x-nansen-credits-cost`
  headers, zero for cache hits, with the price table only as a fallback when the header is
  missing.

---

## 5. Run it yourself

Everything below is in the public repository
[nansen-undertaker](https://github.com/RenatMursalimov/nansen-undertaker).

### Without a key

```bash
git clone https://github.com/RenatMursalimov/nansen-undertaker
cd nansen-undertaker
pip install -r requirements.txt
python3 tests/test_public.py          # the offline suite: the network wire is the only thing replaced
python3 tests/test_sentinel.py        # the alerter: detector, delivery, cards, refusals
python3 scrub.py                      # no server paths, no wallets, no handles, no keys in the tree
python3 cli.py doctor                 # what is in the environment
python3 cli.py sentinel-card BTC hyperliquid   # live instrument card from the public venues
python3 cli.py sentinel-demo          # every alert kind, rendered by the real formatter
python3 cli.py sentinel-presets       # what each preset changes
python3 tools/nansen_endpoint_sweep.py --profile complete   # PLAN only: zero calls
```

The mini-app opens in a browser with recorded answers, no key:

```bash
python3 -m http.server 8080
# http://127.0.0.1:8080/webapp/index.html?rehearsal=1
```

### With a key

```bash
cp .env.example .env                  # put NANSEN_API_KEY in this local ignored file
NANSEN_LANG=en python3 cli.py flows 24h
NANSEN_LANG=en python3 cli.py who base 0x4200000000000000000000000000000000000006
NANSEN_LANG=en python3 cli.py info base 0x4200000000000000000000000000000000000006
NANSEN_LANG=en python3 cli.py perps BTC
NANSEN_LANG=en python3 cli.py wallet-perps <address>
NANSEN_LANG=en python3 cli.py pm
python3 tools/nansen_live_smoke.py --run       # read-only, capped: one market, its holders, <= 3 histories
python3 cli.py cost                            # today's spend by scene, from the telemetry lines
```

Every CLI command prints the same block the bot sends, built by the same formatter, and every call
lands in `nansen_tele/<day>.log` with its endpoint, outcome class and credits.

---

## 6. What else is in the API

The openapi document of 27 September listed 44 routes outside the client's registry
(`tools/nansen_endpoint_sweep.py`). Seven of them are the paths adopted in 3.9; the other 37 are
listed here so that nobody mistakes our coverage for the API's:

* **Account and search:** `account`, `search/general`, `search/entity-name`,
  `search/token-sectors`, `nansen-score/top-tokens`, `transaction-with-token-transfer-lookup`.
* **Smart alerts:** `smart-alert`, `smart-alert/list`, `smart-alert/toggle`,
  `smart-alert/{alert_id}`.
* **Smart Money, more:** `smart-money/historical-holdings`, `smart-money/pnl-leaderboard`,
  `v1beta1/smart-money/historical-token-balances`.
* **Token God Mode, more:** `tgm/perp-trades`, `v1beta1/tgm/historical-dex-trades`,
  `v1beta1/tgm/historical-pnl-leaderboard`.
* **Profiler, more:** `profiler/address/pnl`, `profiler/address/first-funder`,
  `profiler/address/counterparties/batch`, `profiler/perp-pnl-summary`,
  `v1beta1/profiler/address/historical-transactions`,
  `v1beta1/profiler/historical-transaction-lookup`.
* **Perp trading (execution):** `perp/account`, `perp/meta`, `perp/positions`, `perp/orders`,
  `perp/order`, `perp/cancel`, `perp/close`, `perp/leverage`, `perp/transfer`,
  `perp/execute`, `perp/builder-fee`, `perp/approve-builder-fee`, `perp/bridge/quote`,
  `perp/bridge/execute`, `perp/bridge/status`.

The perp execution family is deliberately outside this bot: it does not trade and does not advise.
`smart-alert` is the one we would look at first if the Sentinel ever moved server-side.

---

*Every number in this guide has a source: the probe log of 27 September 2026, the journal of
26 September, or the code. Where a price is not published, it says so.*
