# Технический гайд: Nansen API на практике (по коду Гробовщика)

Это гайд для разработчиков, а не реклама бота. Гробовщик - Telegram-бот русскоязычного
крипто-сообщества; его слой Nansen живёт в одном клиенте (`nansen_api.py`), модуле телеметрии
(`nansen_log.py`) и живом алертере поверх них (`sentinel/`). Всё это опубликовано байт в байт в
[nansen-undertaker](https://github.com/RenatMursalimov/nansen-undertaker), так что каждый путь и
каждый блок кода ниже можно открыть рядом с текстом.

О чём этот гайд: какие эндпоинты мы вызываем и с какими телами, какие поля ответа реально читаем,
сколько стоит каждый вызов по официальному прайсу, какие ловушки поймали живыми пробами и как их
обошли. У каждого числа есть источник: живая проба 27 сентября 2026 (два прогона на ключе
владельца, 49 + 146 кредитов, записаны в `docs/journal/2026-09-27-nansen-review.md`, раздел 9),
замеры из `docs/journal/2026-09-26-sentinel-v2.md` или сам код. Где цена не опубликована, гайд
так и говорит, а не угадывает.

Английская версия: [`ARTICLE_TECH_GUIDE.md`](ARTICLE_TECH_GUIDE.md). Гайд для пользователя
(экраны и кнопки): [`ARTICLE_USER_GUIDE_ru.md`](ARTICLE_USER_GUIDE_ru.md); собранный машиной
каталог всех экранов: [`CATALOG_ru.md`](CATALOG_ru.md).

Адреса кошельков в примерах ответов заменены метками `addr-N`. Контракты токенов публичны и
оставлены как есть.

---

## 1. Установка: одно горло, одна коробка, семь видов «нет»

### Базовый URL и заголовок ключа

Всё - `POST` с JSON-телом. Ключ едет в заголовке `apikey`; никакого `Authorization: Bearer` нет.
Из `nansen_api.py`:

```python
_BASE = "https://api.nansen.ai/api/v1"
_CACHE_TTL = 1800  # 30 мин кэш на одинаковые запросы

def _headers():
    return {"Content-Type": "application/json", "apikey": _key()}
```

Бета-маршруты (`tgm/historical-*`, `token-screener/historical`) живут под
`https://api.nansen.ai/api/v1beta1` и идут через `_post_beta`; форма тела отличается от v1
(см. `hist_token_screener` ниже).

### Каждый вызов идёт через одно горло

Сетевой запрос делается ровно в одном месте, `_http_once`. Оно выполняет HTTP-вызов, читает
заголовки кредитов, классифицирует отказ и пишет одну строку телеметрии. Всё остальное
(`_post`, `_post_fix`, `_post_beta`, `ask_agent`) - обёртки над ним. Именно поэтому на вопрос
«куда ушли кредиты» есть ответ:

```python
    try:
        r = httpx.post("%s/%s" % (base, path), headers=_headers(), json=body, timeout=timeout)
        http = r.status_code
        _note_credits(r.headers)
        if http != 200:
            _cls = _classify(http, r.text)
```

### Кэш: 30 минут по умолчанию, короче для живого наблюдателя

Одинаковые запросы 30 минут отдаются из JSON-кэша (`_CACHE_TTL`). Алертеру нужны данные свежее,
поэтому `_post` принимает `ttl` на каждый вызов: читатель живой ленты берёт 20 секунд и свой ключ
кэша, а задачи дайджеста и твитов сохраняют свой 30-минутный кэш и свой бюджет кредитов.
Из `sm_dex_trades`:

```python
    return _rows(_post("smart-money/dex-trades",
                       {"chains": chains,
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "block_timestamp", "direction": "DESC"}]},
                       ckey=f"{_k}:{','.join(chains)}:{per_page}",
                       ttl=(ttl if ttl is not None else (20 if live else None))))
```

### Повтор: ровно один, и только когда площадка сама так сказала

На не-200 клиент повторяет запрос один раз, и только для кодов ошибок, которые сам Nansen
помечает как повторяемые, или для 5xx без тела (так выглядит 503 с их edge). Он никогда не
повторяет 400/422 (то же тело даст тот же ответ) и никогда 402 (нет денег значит нет денег). Если
площадка просит подождать больше трёх секунд, клиент не ждёт: он говорит об этом человеку.
Из `nansen_api.py`:

```python
_ERR_RETRY = ('rate_limit_exceeded', 'query_timeout', 'upstream_unavailable', 'internal_error')
_HTTP_RETRY = (500, 502, 503, 504)
_RETRY_MAX_WAIT = 3.0
```

### Пусто или отказ: коробка вызова

Пустой список после 402 выглядит ровно так же, как пустой список «сегодня сделок не было». Клиент
различает их коробкой на сцену в `nansen_log.py`: каждый вызов отмечает в коробке свой исход, и
худший исход в коробке - то, что сообщает экран. Классы из `nansen_log._SEV`, по возрастанию
тяжести:

```python
_SEV = {'ok': 0, 'empty': 1, 'unsupported': 2, 'http': 3, 'badreq': 4, 'timeout': 5,
        'ratelimit': 6, 'nocredits': 7, 'nokey': 8}
```

Одного HTTP-статуса для классификации мало. 422 означает две разные вещи: «у вас неверное тело»
(наш баг, чинится) и «этот эндпоинт не покрывает этот актив» (граница покрытия, чинить нечего).
Различает их только текст, и `_classify` первым делом читает собственный код ошибки площадки:

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

Правило, которое отсюда следует: **класс отказа читается внутри блока `with scene(...)`.**
На выходе коробка сбрасывается. Ровно здесь у нас и был баг: `sentinel/ignition.py` читал
`fail_reason()` после блока, получал дефолтный `empty` и печатал 402 как «смарт-мани молчат».
Фикс: одна коробка на каждую сторону, и причина читается внутри неё (`ignition.confirm`, починено
27 сентября).

### Кредиты: заголовок, а не таблица

Каждый ответ несёт `x-nansen-credits-cost`, `x-nansen-credits-remaining` и
`x-nansen-credits-used`, включая ответы 422 и 404 (проба 27 сентября: 422 на
`tgm/perp-pnl-leaderboard` стоил 5, 404 на `tgm/token-transfers` стоил 1). Клиент читает
заголовок стоимости в строку телеметрии как замер (`est=0`); таблица опубликованных цен - запасной
вариант, а маршрут без опубликованной цены считается отдельно как «цена неизвестна», а не
получает выдуманное число (`nansen_log._EP_EST`, `_EP_UNKNOWN`).

### Починка схемы словами самой площадки

Часть эндпоинтов никогда не была задокументирована так, чтобы этому можно было верить, поэтому
`_post_fix` отправляет тело, читает текст 422 («Field 'x' is not recognized», «Required field
'body -> y' is missing»), правит тело по нему, повторяет до `_FIX_ROUNDS = 3` раз и закрепляет
выученное тело на диске (`nansen_schema.json`), чтобы следующий рестарт не повторял раунды. Он
честно останавливается, когда площадка просит поле, которое ему неоткуда взять: именно такая
остановка и научила нас, что `tgm/perp-positions` хочет `token_symbol` (см. ловушки).

---

## 2. Эндпоинты по группам

Для каждого эндпоинта: минимальное тело, которое мы шлём, поля ответа, которые реально читаем,
цена и одна строка о том, зачем это трейдеру. Цены: **прайс** значит официальный прайс-лист;
**заголовок** значит замер 27 сентября по `x-nansen-credits-cost`; **openapi** значит поле
`x-credit-cost` документа `https://api.nansen.ai/openapi.json`, прочитанного 27 сентября
(проба №1); **не измерена** значит ни то, ни другое, ни третье, и клиент считает вызов как «цена
неизвестна». Имена функций клиента - из `nansen_api.py`.

### Smart Money

| Эндпоинт | Тело, которое шлём | Поля, которые читаем | Цена | Зачем трейдеру |
|---|---|---|---|---|
| `token-screener` (`smart_money_netflow`) | `chains`, `timeframe` (`24h`), `filters.only_smart_money`, `order_by netflow`, `pagination` | `token_symbol`, `chain`, поля `netflow` по окнам | 1 (прайс) | Куда смарт-мани сдвинулись нетто за окно |
| `smart-money/netflow` | `chains`, `filters.include_stablecoins: false`, `pagination` | `token_symbol`, `chain`, `net_flow_1h_usd`, `net_flow_24h_usd`, `net_flow_7d_usd`, `net_flow_30d_usd`, `trader_count`, `token_age_days`, `market_cap_usd` | 5 (заголовок) | Тот же вопрос с четырьмя окнами и числом трейдеров в одной строке |
| `smart-money/holdings` (`smart_money_holdings`) | `chains`, `filters.value_usd.min`, `filters.include_stablecoins`, `pagination`, `order_by value_usd` | `token_symbol`, `value_usd`, `holders_count`, `balance_24h_percent_change`, `share_of_holdings_percent` | 5 (заголовок) | Что они держат, а не что наторговали сегодня |
| `smart-money/dex-trades` (`sm_dex_trades`) | `chains`, `pagination` (100 для наблюдателя), `order_by block_timestamp DESC` | `token_bought_symbol`, `token_bought_address`, `trade_value_usd`, `token_bought_market_cap`, `token_bought_age_days`, `trader_address`, `trader_address_label`, `block_timestamp`, `transaction_hash` | 5 (заголовок) | Отдельные входы: кто что купил, с капитализацией и возрастом токена в той же строке |
| `smart-money/perp-trades` (`sm_perp_trades`) | `pagination`, `order_by block_timestamp DESC` | `token_symbol`, `side`, `action`, `value_usd`, `price_usd`, `token_amount`, `trader_address_label` | 5 (заголовок) | Перп-входы смарт-мани на Hyperliquid, одна сторона на строку |
| `smart-money/dcas` (`smart_money_dcas`) | только `pagination` (маршрут отвергает `chains`) | строки как есть | 5 (openapi) | Кто набирает позицию равными долями |

Живой пример, `smart-money/netflow`, 27 сентября, per_page 3 (первые две строки):

```json
{"chain": "solana", "token_symbol": "🌱 E/ACC", "net_flow_24h_usd": 207520.29, "net_flow_7d_usd": 572729.81, "trader_count": 41}
{"chain": "solana", "token_symbol": "STONK", "net_flow_24h_usd": 138602.51, "net_flow_7d_usd": -3685700.51, "trader_count": 364}
```

### Token God Mode (`tgm/*`)

| Эндпоинт | Тело, которое шлём | Поля, которые читаем | Цена | Зачем трейдеру |
|---|---|---|---|---|
| `tgm/flow-intelligence` (`tgm_flow_intelligence`) | `chain`, `token_address`, `timeframe` (`1d`) | `smart_trader_net_flow_usd`, `whale_net_flow_usd`, `fresh_wallets_net_flow_usd`, `exchange_net_flow_usd`, `public_figure_*`, `top_pnl_*`, у каждого `_avg_flow_usd` и `_wallet_count` | 1 (прайс) | Кто двигает токен, по сегментам держателей |
| `tgm/who-bought-sold` (`tgm_who_bought_sold`) | `chain`, `token_address`, `buy_or_sell`, `date.from/to` (часы допустимы), `pagination`, `order_by bought_volume_usd` или `sold_volume_usd` по стороне | `address`, `address_label`, `bought_volume_usd`, `sold_volume_usd`, `trade_volume_usd` | 1 (прайс) | Кто нетто покупает и кто нетто продаёт в окне |
| `tgm/holders` (`tgm_holders`) | `chain`, `token_address`, `label_type` (`all_holders`), `aggregate_by_entity: false`, `pagination`, `order_by value_usd` | `address`, `address_label`, `value_usd`, `ownership_percentage`, `balance_change_24h/7d/30d` | 5 (прайс) | Кто держит токен, с метками и долей |
| `tgm/pnl-leaderboard` (`tgm_pnl_leaderboard`) | `chain`, `token_address`, `date`, `pagination` | `trader_address`, `trader_address_label`, `pnl_usd_realised`, `pnl_usd_total`, `roi_percent_total`, `nof_trades`, `still_holding_balance_ratio` | 5 (прайс) | Кто на этом токене реально заработал |
| `tgm/token-information` (`tgm_token_information`) | `chain`, `token_address`, `timeframe` | верхний уровень: `symbol`, `name`, `contract_address`; вложенные `token_details` и `spot_metrics` | 1 (прайс) | Справка одним вызовом (см. ловушки: числа вложены) |
| `tgm/indicators` (`tgm_indicators`) | `chain`, `token_address` | `risk_indicators`, `reward_indicators` | 5 (прайс) | Разложение Nansen Score |
| `tgm/perp-positions` (`perp_positions`) | `token_symbol` (обязательно), `pagination`, `order_by position_value_usd` | `address`, `address_label`, `side`, `position_value_usd`, `entry_price`, `liquidation_price`, `leverage`, `mark_price`, `upnl_usd`, `funding_usd` | 5 (заголовок) | Где стоят чужие плечи и цены ликвидации |
| `tgm/position-intelligence` (`perp_positioning`) | только `token_address`, и значение должно быть перп-тикером (`ETH`), а не контрактом | `smart_trader_longs_usd`, `smart_trader_shorts_usd`, `whale_longs_usd`, `whale_shorts_usd`, `public_figure_*`, `*_total_usd` | 1 (заголовок) | Лонги против шортов по сегментам: кто против кого |
| `tgm/perp-pnl-leaderboard` (`perp_pnl_leaderboard`) | `token_symbol`, `date`, `pagination`, `order_by pnl_usd_total` | как у `pnl-leaderboard` | 5 (прайс) | Кто зарабатывает на этом перп-рынке |
| `tgm/transfers`, `tgm/token-ohlcv`, `tgm/flows`, `tgm/dex-trades`, `tgm/jup-dca` | тела в `nansen_api.py` | зарегистрированы, экрана для пользователя пока нет | 1 (openapi у `flows`, `dex-trades`, `jup-dca`; заголовок у `transfers`, `token-ohlcv`) | Задел на стороне клиента, в `CATALOG_ru.md` числятся без пользовательской двери |

Живой пример, `tgm/who-bought-sold`, WETH на Base, `BUY`, окно с `00:00` до `04:43` UTC
27 сентября:

```json
{"address": "addr-1", "address_label": "Token Millionaire", "bought_volume_usd": 8209130.55, "sold_volume_usd": 5453679.78}
{"address": "addr-2", "address_label": "Token Millionaire", "bought_volume_usd": 3098666.86, "sold_volume_usd": 2191752.59}
```

Живой пример, `tgm/perp-positions`, `token_symbol: BTC`, 27 сентября:

```json
{"address": "addr-7", "side": "Short", "position_value_usd": 238408587.02, "entry_price": 75949.4, "liquidation_price": 139297.91, "leverage": "5X"}
{"address": "addr-8", "side": "Short", "position_value_usd": 147645336.70, "entry_price": 74443.4, "liquidation_price": 149999.23, "leverage": "5X"}
```

### Перпы (верхний уровень)

| Эндпоинт | Тело, которое шлём | Поля, которые читаем | Цена | Зачем трейдеру |
|---|---|---|---|---|
| `perp-screener` (`perp_screener`) | `date` (обязательно), `pagination`, `order_by volume` | `token_symbol`, `volume`, `open_interest`, `funding`, `mark_price`, `buy_sell_pressure`, `trader_count` | 1 (заголовок) | Какие перп-рынки оживлены и куда наклонены |
| `perp-leaderboard` (`perp_leaderboard`) | `date` (только даты), `pagination`, `filters.account_value` | `trader_address`, поля PnL и счёта | 5 (прайс) | У кого самые большие и самые удачные счета |
| `profiler/perp-positions` (`profiler_perp_positions`) | только `address` (без `pagination`) | `data` - объект: `asset_positions[].position.{coin, szi, leverage.value, liquidation_px, position_value, unrealized_pnl}`, `margin_summary_account_value_usd`, `margin_summary_total_margin_used_usd`, `withdrawable_usd` | 1 (заголовок) | Весь перп-счёт кошелька и его расстояние до ликвидации |

Живой пример, `perp-screener`, 27 сентября:

```json
{"token_symbol": "BTC", "volume": 995803347.36, "open_interest": 3126957894.95, "funding": 1.25e-05}
{"token_symbol": "ZEC", "volume": 367999861.78, "open_interest": 845728495.85, "funding": 1.25e-05}
```

### Profiler (кошельки)

| Эндпоинт | Тело, которое шлём | Поля, которые читаем | Цена | Зачем трейдеру |
|---|---|---|---|---|
| `profiler/address/labels` (`profiler_labels`) | `address`, `chain`, `pagination` | `label`, `category`, `kind` | **100 (заголовок)** | Кто этот кошелёк; обратите внимание на цену |
| `profiler/address/premium-labels` | то же, премиум | то же плюс метки смарт-мани | 500 (openapi) | Метки Smart Money / Fund, по настоящей цене |
| `profiler/address/pnl-summary` (`profiler_pnl_summary`) | `address`, `chain`, `date` (обязательно) | `realized_pnl_usd`, `win_rate`, счётчики сделок, топ токенов | 1 (openapi) | Выигрывает ли этот кошелёк вообще |
| `profiler/address/related-wallets` (`profiler_related_wallets`) | `address`, `chain`, `pagination` | `address`, `address_label`, вид связи | 1 (openapi) | Кластер за адресом |
| `profiler/address/counterparties` (`profiler_counterparties`) | `address`, `chain`, `date`, `pagination` | строки контрагентов (27 сентября: пусто для адреса пробы) | 5 (заголовок) | С кем этот кошелёк торгует |
| `profiler/address/current-balance` (`profiler_current_balance`) | `address`, `chain`, `hide_spam_token: true`, `pagination` | балансы токенов | 1 (openapi) | Что лежит в кошельке сейчас |
| `profiler/perp-trades`, `profiler/address/historical-balances`, `profiler/address/transactions`, `profiler/dex-trades` | тела в `nansen_api.py` | зарегистрированы, экрана для пользователя пока нет | 1 (openapi у `transactions`, `dex-trades`; заголовок у `perp-trades`, `historical-balances`) | История адреса |

Живой пример, `profiler/address/labels`, публичный билдер блоков Ethereum, 27 сентября. Этот
один вызов стоил 100 кредитов:

```json
{"label": "biacc.eth*", "category": "social"}
{"label": "biacc.eth", "category": "social"}
```

### Рынки предсказаний (Polymarket)

| Эндпоинт | Тело, которое шлём | Поля, которые читаем | Цена | Зачем трейдеру |
|---|---|---|---|---|
| `prediction-market/market-screener` (`pm_market_screener`) | `query`, `status` (`active`), `pagination`, `order_by volume_24hr` | `market_id`, `question`, `volume_24hr`, `liquidity`, цены исходов | 1 (openapi) | Какие рынки живы и ликвидны |
| `prediction-market/top-holders` (`pm_top_holders`) | `market_id`, `pagination`, `order_by position_size` | `address`, `address_label`, `outcome`, `position_size`, `avg_entry_price` | 5 (openapi) | Чьи деньги стоят на какой стороне |
| `prediction-market/pnl-by-market` (`pm_pnl_by_market`) | `market_id`, `pagination`, `order_by` | PnL по трейдерам на рынке | 5 (openapi) | Кто на этом рынке уже бывал прав |
| `prediction-market/pnl-by-address`, `address-summary`, `orderbook`, `ohlcv`, `position-detail`, `categories` | тела в `nansen_api.py` | см. функции `pm_*` | от 1 до 5 (openapi) | Профиль трейдера, глубина стакана, история цены |
| `prediction-market/event-screener`, `trades-by-market`, `trades-by-address` | зарегистрированы после пробы 27 сентября (старые пути отвечали 404) | экраном пока не читаются | 1 (заголовок) у `event-screener` и `trades-by-market`; `trades-by-address` не пробовался, цена не измерена | События и лента сделок |

Экран репутации в боте (`pm_reputation`) соединяет `top-holders` с `address-summary` по каждому
держателю, чтобы ответить «чья это уверенность»: цена читается рядом с тем, как деньги за каждой
стороной показывали себя раньше. Это история продукта; история API в том, что оба вызова стоят
от 1 до 5 кредитов по списку openapi, а цикл по адресам - та часть, которая умножает, поэтому экран
ограничен пятью адресами (`PM_REP_TOP = 5`) и забирает их параллельно.

### Агент

`agent/fast` (200 кредитов, прайс) и `agent/expert` (750 кредитов, прайс) принимают одно
обязательное поле `text` и стримят SSE-события (`delta` с текстом, `finish` с `conversation_id`,
который можно передать обратно, чтобы продолжить разговор). `ask_agent` в `nansen_api.py` шлёт
`{"text": question}`. Это единственные два вызова, которые клиент никогда не делает сам: они стоят
за явным действием пользователя и подтверждением, а инструмент обхода отказывается запускать их
без `--include-agents`.

---

## 3. Ловушки, пойманные живыми пробами

Каждая ловушка ниже подтверждена записанной пробой. «27.09» - проба 27 сентября из двух прогонов
(`docs/journal/2026-09-27-nansen-review.md`, раздел 9); «sentinel-v2» -
`docs/journal/2026-09-26-sentinel-v2.md`. Где ловушка закрыта тестом, тест назван.

### 3.1 `price_usd` - цена одного токена, а не размер сделки

В `smart-money/perp-trades` строка несёт и `price_usd`, и `value_usd`. Проба 27.09 показывает,
что их отношение - в точности количество токенов:

```text
{"token_symbol": "xyz:NCLD", "side": "Short", "price_usd": 25.166, "value_usd": 130.10822, "token_amount": 5.17}
value_usd / price_usd = 5.1700
{"token_symbol": "PURR", "side": "Short", "price_usd": 0.13061, "value_usd": 13.061, "token_amount": 100.0}
value_usd / price_usd = 100.0000
```

Значит размер - это `value_usd`, а `price_usd` - цена входа. В DEX-ленте цены нет вовсе; её
размер - `trade_value_usd`. Общий искатель денег в клиенте отвергает всё, что похоже на цену,
комиссию или баланс:

```python
_NOT_MONEY = ('price', 'pnl', 'fee', 'gas', 'balance', 'market_cap', 'mcap', 'fdv',
              'liquidity', 'supply', 'net_worth', 'networth', 'roi', 'apy')
```

А читатель ленты берёт поле размера по имени, с перп-полем как запасным (`sentinel/ignition.py`,
`rows_from_feed`):

```python
            'usd': _f(t.get('trade_value_usd')) or _f(t.get('value_usd')),
```

Тесты: `tests/test_nansen_contest.py::t_probe_19_09_schemas_are_pinned_and_dead_ends_buried`
(«у перп-сделок сумма это value_usd»).

### 3.2 `who-bought-sold`: поле объёма зависит от направления

Каждая строка несёт и `bought_volume_usd`, и `sold_volume_usd`. Какое из них ответ, зависит от
`buy_or_sell`, и поле сортировки тоже. Проба 27.09, WETH на Base:

```text
BUY  (order_by bought_volume_usd): addr-1 bought 8209130.55, sold 5453679.78
SELL (order_by sold_volume_usd):   addr-4 bought  982498.52, sold 2036729.13
```

Чтение не той колонки дало нам карточку, где кошелёк стоял под «продали» со своей цифрой покупки
(sentinel-v2, 26 сентября). Клиент сортирует по стороне и читает по стороне:

```python
            "order_by": [{"field": "%s_volume_usd" % ("bought" if buy_or_sell == "BUY" else "sold"),
                          "direction": "DESC"}]}
```

```python
    want = 'sold_volume_usd' if str(side).upper() == 'SELL' else 'bought_volume_usd'
```

Обратите внимание на метки в примере: `Token Millionaire`. В теле нет фильтра по метке смарт-мани,
так что это крупные адреса, а не смарт-мани, и карточка бота говорит «крупные адреса за 3 ч».
Тест: `tests/test_sentinel.py::t_wallet_sizes_are_read_not_lost`.

### 3.3 `date.from/to` принимает часы; `days=1` был окном в 30 с лишним часов с заходом в будущее

Официальный CLI шлёт только `YYYY-MM-DD`, а наш старый `days=1` слал со вчерашних `00:00:00Z` до
сегодняшних `23:59:59Z`: больше тридцати часов, часть из них в будущем, под подписью «24 ч».
Проба 27.09 закрыла вопрос, учитывает ли эндпоинт время:

```text
окно 00:00-02:00 UTC: 10 строк, куплено $10,416,447
окно 02:00-04:00 UTC: 10 строк, куплено  $4,699,545
окно 3 ч: 20 строк $12,812,346 | календарное «сегодня»: 20 строк $15,994,597
```

Два непересекающихся окна одного дня возвращают разные строки, значит часы учитываются. Клиент
строит окно от «сейчас минус N часов», когда передан `hours` (`_date_range`), а ончейн-контекст
алертера - окно в 3 часа (`sentinel/ignition.py`, `CONFIRM_HOURS = 3`). Время принимает не каждый
маршрут: `smart-money/historical-holdings` ответил 422 «Time components (T, :, Z, +) are not
supported for this endpoint» (`sentinel/lab.py`).

### 3.4 `position-intelligence` работает по символу; по контракту возвращает нули

Поле называется `token_address`, но данные за ним - позиционирование перпов Hyperliquid, а ключ
перп-рынка - его тикер. Проба 27.09, три вызова, по одному кредиту каждый:

```text
ETH                                          -> smart_trader_longs_usd 82104399.45, whale_longs_usd 1270977664.77
WETH                                         -> smart_trader_longs_usd 0.0, whale_longs_usd 0.0
0x4200000000000000000000000000000000000006   -> smart_trader_longs_usd 0.0, whale_longs_usd 0.0
```

200 со строкой нулей - это не «плеча нет», это не тот ключ. Отсюда два следствия. Экран
спрашивает по тикеру, а когда начинает с контракта, берёт символ, который этому контракту даёт
DexScreener. И обёртки сводятся к перп-тикеру, потому что DexScreener говорит `WETH`, а перп-рынок
называется `ETH` (`nansen_api.py`, `positioning_key`):

```python
_PERP_WRAPPERS = {
    'WETH': 'ETH', 'STETH': 'ETH', 'WSTETH': 'ETH', 'WEETH': 'ETH', 'RETH': 'ETH', 'CBETH': 'ETH',
    'WBTC': 'BTC', 'CBBTC': 'BTC', 'TBTC': 'BTC',
    'WSOL': 'SOL', 'WBNB': 'BNB', 'WMATIC': 'POL', 'WPOL': 'POL', 'WAVAX': 'AVAX',
}
```

Тест: `tests/test_nansen_contest.py::t_positioning_key_folds_wrappers_to_the_perp_ticker_d8`.

### 3.5 `tgm/perp-positions` требует `token_symbol`

Проба 27.09, один маршрут с двумя телами:

```text
POST tgm/perp-positions {"token_symbol": "BTC", ...} -> 200, 3 rows
POST tgm/perp-positions {"token_address": "BTC", ...} -> 422
{"error":"Missing field","message":"Required field 'body -> token_symbol' is missing","code":"missing_field","param":"token_symbol", ...}
```

Оба вызова стоили по 5 кредитов: 422 не бесплатен. Цикл починки в `_post_fix` читает ровно это
сообщение; он умеет переименовать поле, которое площадка называет неизвестным, но не умеет
выдумать обязательное, и именно так имя было выучено в первый раз (19 сентября) и закреплено в
клиенте:

```python
    return _rows(_post_fix("tgm/perp-positions",
                       {"token_symbol": str(token).upper(),
```

Та же ловушка сидела по соседству: `tgm/perp-pnl-leaderboard` тоже хочет `token_symbol`, а его
поле сортировки - `pnl_usd_total`, а не `total_pnl` (проба 27.09, №4: 422 перечисляет допустимые
варианты). Тест: `t_paths_and_bodies_match_the_live_probe_of_27_09`.

### 3.6 Одна страница `smart-money/dex-trades` покрывает около 40 минут

Лента - это лента, и одна страница в 100 сделок короче любого полезного окна. Измерено дважды:

```text
sentinel-v2, 26.09: 100 сделок покрывают 44 минуты; 4 страницы покрывают 128 минут
проба 27.09:        100 сделок покрывают 38 минут (с 04:04:13 до 04:42:33 UTC)
```

Событию Smart Ignition нужно 180 минут (`sentinel/config.py`, `ign_window_min`). Поэтому алертер
кладёт каждую страницу в свою таблицу и строит окно из базы, а не из ответа
(`sentinel/ignition.py`, `scan`):

```python
    rows = rows_from_feed(trades)
    store.sm_trades_put(rows, feed='dex', now=now)
    win_s = int(config.ign_window_min()) * 60
    stored = store.sm_trades_window(now - win_s, feed='dex')
    groups = group(stored or rows, now=now)
```

Тест: `tests/test_sentinel.py::t_feed_is_stored_because_window_is_longer_than_page`.

### 3.7 Метка 🌱 внутри символов новых токенов

Nansen ставит перед символом молодого токена росток. Проба 27.09: 11 из 100 сделок на одной
странице несли его (`🌱 AAF`, `🌱 BAG`, `🌱 BOAR`), а `⚠️ JIZZ` показал, что бывают и другие метки.
Тот же символ приходит в `smart-money/netflow` (`🌱 E/ACC`). Если вы что-то ключуете по символу,
снимайте метку, иначе один токен живёт под двумя именами; если показываете человеку, оставляйте:
«ноль дней от роду» - самое важное, что есть про этот токен. Из `sentinel/assets.py`:

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

### 3.8 Обёрнутые нативы на чужих сетях

Нативная монета на EVM-сети живёт в виде обёртки, а DEX-поток обёртки отвечает на вопрос «сколько
перебросили мостом», а не «что делают с активом». Для алертера это решение, а не замер: активы без
собственного DEX-следа исключаются из ончейн-блока до того, как потрачен хоть один кредит
(`sentinel/assets.py`, `NATIVE_L1`, `onchain_refusal`). BTC в этом списке с 27 сентября (его
«обёртка» WBTC - мост); ETH и SOL - нет, потому что WETH и wSOL живут на своих родных сетях.
Живой случай, который поставил HYPE в список: сопоставление по цене нашло Solana-токен с тем же
символом и напечатало трёхчасовой след в $6 для натива Hyperliquid (sentinel-v2, 26 сентября).

### 3.9 Семь путей, отвечавших 404, и пути из спецификации

Проба 27.09, №6: семь зарегистрированных путей были мертвы. У шести из них соседний путь из
документа openapi ответил 200 в той же пробе, по одному кредиту каждый; седьмой,
`prediction-market/trades-by-address`, взят из документа openapi и живьём ещё не пробовался.

| 404 | путь в документе openapi |
|---|---|
| `tgm/token-transfers` | `tgm/transfers` |
| `tgm/price-ohlcv` | `tgm/token-ohlcv` |
| `profiler/address/perp-trades` | `profiler/perp-trades` |
| `profiler/address/historical-token-balances` | `profiler/address/historical-balances` |
| `prediction-market/events` | `prediction-market/event-screener` |
| `prediction-market/trades` | `prediction-market/trades-by-market` |
| `prediction-market/wallet-trades` | `prediction-market/trades-by-address` (не пробовался) |

404 стоит один кредит и ничего не говорит о том, существует ли функция. Отличить «исчезло» от
«переехало» помогает `https://api.nansen.ai/openapi.json`: он перечисляет каждый маршрут с его
`x-credit-cost`, и инструмент обхода сверяет с ним реестр (проба 27.09, №1).

---

## 4. Архитектура алертера поверх Nansen

Дозорный смотрит за тремя перп-площадками (Variational Omni, Hyperliquid, Lighter) через их
публичные эндпоинты и использует Nansen для двух вещей: контекста к движению и двух собственных
событий. Модель не участвует ни в одном решении; каждый порог - число из замера, названное в
`sentinel/config.py`.

```text
 публичные площадки (каждые 30 с)              Nansen (каждые 180 с)
 Variational / Hyperliquid / Lighter           smart-money/dex-trades, per_page 100
        |                                              |
        v                                              v
 кольцо снимков на (площадка, тикер)           таблица sentinel_sm_trades
 mark, объём, OI, фандинг, спред               (окно 180 мин строится из БД,
        |                                       одна страница покрывает ~40 мин)
        v                                              |
 detector.detect(listing, rows, ring)                  v
   move_15m >= 1.2 % или move_60m >= 2.5 %     ignition.group(): 3+ разных смарт-адресов,
   И z >= 2.5 по >= 20 своим точкам            $100k+, >= 5 bps капитализации -> Smart Ignition
   всплеск OI, всплеск объёма, хвост фандинга, smart-money/perp-trades: 2+ адреса, одна сторона,
   шок спреда, толпа                           $250k+ за 30 мин -> Smart Perp
        |                                              |
        +------------------ события -------------------+
                              |
                              v
                 outbox: один тред на инструмент,
                 дедуп, кулдаун, предохранитель на человека,
                 тихие часы, дайджест для остального
                              |
                              v
                 карточка уходит в Telegram (числа с площадки)
                              |
                              v  (enrich_tick, бюджет: один на (площадка, тикер) в час)
                 ignition.confirm(): контракт по совпадению цены (DexScreener),
                   tgm/who-bought-sold BUY + SELL, окно 3 ч, одна коробка на сторону
                 _perp_lines(): tgm/position-intelligence по перп-тикеру,
                   tgm/perp-positions: два ближайших кластера ликвидаций от $100k
                 verdict_lines(): считает код
                              |
                              v
                 edit_message_text на ТОЙ ЖЕ карточке (телефон не жужжит дважды)
```

Что здесь важно любому, кто строит поверх API:

* **Кольцо и есть сигма.** У каждого инструмента своя история; движение становится событием
  только когда оно необычно для этого инструмента (`z >= 2.5` не меньше чем по 20 своим точкам,
  `sigma_min_points`). Нет сигмы - нет события.
* **Треды, а не потоп.** Один тред Telegram на инструмент; следующие события по тому же движению
  приходят ответами («усилилось», «откат»), не больше двух на каждый вид (`THREAD_MAX_REPLIES`).
* **Обогащение - это правка.** Контекст Nansen добавляется правкой уже отправленной карточки
  (`sentinel/outbox.py`, `edit_message_text`), так что человек получает одно уведомление, а числа
  с площадки никогда не ждут Nansen.
* **Бюджет на инструмент в час.** `store.enrich_recent` отказывает во втором обогащении той же
  пары (площадка, тикер) внутри `ENRICH_EVERY_S = 3600`; 26 сентября владелец получил 279
  обогащений за сутки, по одному на событие, большинство по одним и тем же инструментам.
* **Отказ печатается как отказ.** 402 или 429 на любой из сторон `who-bought-sold` даёт вердикт
  «ончейн не прочитан: <причина>» и никакой нетто-цифры; «молчат» - только настоящий пустой ответ.
* **Кредиты - это заголовок.** Дневной расход алертера - сумма заголовков `x-nansen-credits-cost`,
  ноль за попадания в кэш, а таблица цен - только запасной вариант, когда заголовка нет.

---

## 5. Запустить самому

Всё, что ниже, лежит в публичном репозитории
[nansen-undertaker](https://github.com/RenatMursalimov/nansen-undertaker).

### Без ключа

```bash
git clone https://github.com/RenatMursalimov/nansen-undertaker
cd nansen-undertaker
pip install -r requirements.txt
python3 tests/test_public.py          # офлайн-набор: подменён только сетевой провод
python3 tests/test_sentinel.py        # алертер: детектор, доставка, карточки, отказы
python3 scrub.py                      # в дереве нет путей сервера, кошельков, ручек и ключей
python3 cli.py doctor                 # что есть в окружении
python3 cli.py sentinel-card BTC hyperliquid   # живая карточка инструмента с публичных площадок
python3 cli.py sentinel-demo          # каждый вид алерта, собранный настоящим форматтером
python3 cli.py sentinel-presets       # что меняет каждый пресет
python3 tools/nansen_endpoint_sweep.py --profile complete   # только ПЛАН: ноль вызовов
```

Мини-апп открывается в браузере на записанных ответах, без ключа:

```bash
python3 -m http.server 8080
# http://127.0.0.1:8080/webapp/index.html?rehearsal=1
```

### С ключом

```bash
cp .env.example .env                  # NANSEN_API_KEY кладётся в этот локальный игнорируемый файл
python3 cli.py flows 24h
python3 cli.py who base 0x4200000000000000000000000000000000000006
python3 cli.py info base 0x4200000000000000000000000000000000000006
python3 cli.py perps BTC
python3 cli.py wallet-perps <address>
python3 cli.py pm
python3 tools/nansen_live_smoke.py --run       # только чтение, с потолком: один рынок, его держатели, <= 3 историй
python3 cli.py cost                            # расход за сегодня по сценам, из строк телеметрии
```

Каждая команда CLI печатает тот же блок, который шлёт бот, собранный тем же форматтером, а каждый
вызов ложится в `nansen_tele/<день>.log` со своим эндпоинтом, классом исхода и кредитами.

---

## 6. Что ещё есть в API

Документ openapi от 27 сентября перечислил 44 маршрута вне реестра клиента
(`tools/nansen_endpoint_sweep.py`). Семь из них - пути, принятые в 3.9; остальные 37 перечислены
здесь, чтобы никто не принял наше покрытие за покрытие API:

* **Аккаунт и поиск:** `account`, `search/general`, `search/entity-name`,
  `search/token-sectors`, `nansen-score/top-tokens`, `transaction-with-token-transfer-lookup`.
* **Смарт-алерты:** `smart-alert`, `smart-alert/list`, `smart-alert/toggle`,
  `smart-alert/{alert_id}`.
* **Smart Money, ещё:** `smart-money/historical-holdings`, `smart-money/pnl-leaderboard`,
  `v1beta1/smart-money/historical-token-balances`.
* **Token God Mode, ещё:** `tgm/perp-trades`, `v1beta1/tgm/historical-dex-trades`,
  `v1beta1/tgm/historical-pnl-leaderboard`.
* **Profiler, ещё:** `profiler/address/pnl`, `profiler/address/first-funder`,
  `profiler/address/counterparties/batch`, `profiler/perp-pnl-summary`,
  `v1beta1/profiler/address/historical-transactions`,
  `v1beta1/profiler/historical-transaction-lookup`.
* **Торговля перпами (исполнение):** `perp/account`, `perp/meta`, `perp/positions`,
  `perp/orders`, `perp/order`, `perp/cancel`, `perp/close`, `perp/leverage`, `perp/transfer`,
  `perp/execute`, `perp/builder-fee`, `perp/approve-builder-fee`, `perp/bridge/quote`,
  `perp/bridge/execute`, `perp/bridge/status`.

Семейство исполнения перпов сознательно вне этого бота: он не торгует и не советует.
`smart-alert` - первое, на что мы посмотрели бы, если бы Дозорный когда-нибудь переехал на
сторону сервера.

---

*У каждого числа в этом гайде есть источник: журнал проб 27 сентября 2026, журнал 26 сентября или
код. Где цена не опубликована, так и написано.*
