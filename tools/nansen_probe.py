#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/nansen_probe.py — снять СХЕМУ спорных эндпоинтов Nansen живым ключом.

ЗАЧЕМ. Живой прогон 14.09 дал два факта, которые из контейнера разработки не устанавливаются
(там нет ни сети к площадке, ни ключа), и оба про схему запроса, а не про данные:

  1. «кто входил <USDC на Base> 7» ответил ПУСТО четыре раза из четырёх. USDC - один из самых
     торгуемых токенов вообще; отсутствие сделок по нему за неделю невозможно. Значит дело в
     теле запроса, а не в покрытии. Клиент `tgm_who_bought_sold` был написан давно и НИ РАЗУ
     не вызывался (аудит: «клиент написан, провода нет») - то есть его схему никто не проверял
     живым ключом ни минуты.
  2. Профиль кошелька: два запроса из трёх вернули 422, то есть площадка ОТВЕРГЛА наш запрос.

Гадать тут нельзя: у Nansen уже был случай, когда в примере ИЗ ЕГО ЖЕ документации стояло
невалидное значение (`label_type='all'`, API принимает `'all_holders'`). Поэтому здесь перебор
вариантов с печатью КОДА и СЫРОГО ТЕЛА ответа - веду по ответу провода, а не по теории.

ЧТО ЭТО СТОИТ. Только чтение, ничего не меняет. Полный перебор - около 20 запросов
структурного слоя, это единицы кредитов (порядок 20-40 из 70 тысяч). Агента (200 кредитов за
вопрос) проба НЕ ТРОГАЕТ ВОВСЕ. По умолчанию печатает ПЛАН и не отправляет ничего: чтобы
отправлять, нужен явный флаг --run (кредиты не мои, и снимать предохранитель за человека
нельзя).

ГРУППА `new` (добавлена после живого прогона 15.09) - эндпоинты, чья схема НИ РАЗУ не снята
живым ключом: перп-позиции по токену, перп-скринер, потоки, сделки smart money, перп-сделки,
перп-позиции адреса, DeFi-позиции и скринер рынков Polymarket. В ней проба не перебирает
угаданные варианты, а ПРАВИТ тело по тексту ошибки самой площадки (как боевой `_post_fix`) и
печатает ИМЕНА ПОЛЕЙ ответа - без имён «строки есть» остаётся признаком наличия, а не пользы.

Запуск:
    ./venv/bin/python3 tools/nansen_probe.py                 # план, ни одного запроса
    ./venv/bin/python3 tools/nansen_probe.py --run           # снять схему живым ключом
    ./venv/bin/python3 tools/nansen_probe.py --run --only new # восемь неснятых схем + ремонт
    ./venv/bin/python3 tools/nansen_probe.py --run --only wbs
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nansen_api as N          # noqa: E402

#: публичные сущности, не адреса людей (OPSEC): USDC на Base и публичный билдер блоков ETH
TOKEN = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
WALLET = '0x1f9090aaE28b8a3dCeaDf281B0F12828e676c326'
#: НЕ СТЕЙБЛКОИН, и это отдельная сущность не для красоты. Проба 19.09 на USDC получила от
#: `tgm/flows` содержательный отказ: «этот токен стейблкоин, потоки стейблкоинов эндпоинт не
#: поддерживает». То есть тем токеном этот эндпоинт проверить НЕЛЬЗЯ В ПРИНЦИПЕ, и прошлый
#: прогон измерил не схему, а неудачный выбор токена. WETH на Base - публичный контракт.
TOKEN_NONSTABLE = '0x4200000000000000000000000000000000000006'
#: СОЛАНОВЫЙ ТОКЕН И РЫНОК POLYMARKET ДЛЯ ГРУППЫ `next`. Оба - публичные сущности: mint WSOL и
#: адрес публичного билдера в роли «какого-нибудь кошелька». Рынок берём НЕ фиксированным
#: числом из головы: id рынков живут недолго, и проба на мёртвом id вернула бы «пусто», которое
#: мы прочитали бы как «схема верна, данных нет» - худший вид ложного успеха. Поэтому id
#: спрашивается у скринера в момент прогона (см. `_pm_market_for_probe`).
TOKEN_SOL = 'So11111111111111111111111111111111111111112'
#: WETH на Ethereum - публичный контракт. Нужен ручкам, которые просят именно `token_address` с
#: сетью и на стейблкоине/солановом адресе отвечать не обязаны.
TOKEN_ETH_WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
PM_WALLET = WALLET
#: МЕТКА-ЗАПОЛНИТЕЛЬ: её видит план, а живой id встаёт на её место перед отправкой.
LIVE_PM_MARKET = '<живой id рынка со скринера>'


def _pm_market_for_probe():
    """Живой id рынка Polymarket для пробы. -> str.

    Один дешёвый вызов скринера вместо константы: рынок, закрывшийся месяц назад, отдаёт
    пустоту по любой схеме, и проба измерила бы не тело запроса, а смерть рынка.
    """
    try:
        rows = N.pm_market_screener(per_page=3) or []
        for r in rows:
            _mid = N.pm_market_id(r)
            if _mid:
                return str(_mid)
    except Exception as e:                        # noqa: BLE001
        print('[probe] id рынка не взялся (%s) - шлю заведомо старый, отказ будет про схему'
              % str(e)[:80])
    return '654412'


def _cases_wbs():
    """Варианты схемы для tgm/who-bought-sold. Отличаются РОВНО одним признаком каждый."""
    base = {"chain": "base", "token_address": TOKEN,
            "pagination": {"page": 1, "per_page": 5}}
    d7 = N._date_range(7)
    out = [
        ('как в коде: BUY + date + order_by bought_volume_usd',
         dict(base, buy_or_sell="BUY", date=d7,
              order_by=[{"field": "bought_volume_usd", "direction": "DESC"}])),
        ('без order_by', dict(base, buy_or_sell="BUY", date=d7)),
        ('без date', dict(base, buy_or_sell="BUY",
                          order_by=[{"field": "bought_volume_usd", "direction": "DESC"}])),
        ('строчное buy', dict(base, buy_or_sell="buy", date=d7)),
        ('side вместо buy_or_sell', dict(base, side="BUY", date=d7)),
        ('вообще без признака стороны', dict(base, date=d7)),
        ('date как date_range', dict(base, buy_or_sell="BUY", date_range=d7)),
        ('только даты YYYY-MM-DD', dict(base, buy_or_sell="BUY",
                                        date={"from": d7["from"][:10], "to": d7["to"][:10]})),
        ('timeframe вместо date', dict(base, buy_or_sell="BUY", timeframe="7d")),
        ('order_by volume_usd', dict(base, buy_or_sell="BUY", date=d7,
                                     order_by=[{"field": "volume_usd", "direction": "DESC"}])),
    ]
    return [('tgm/who-bought-sold', t, b) for t, b in out]


def _cases_profiler():
    """Три запроса профиля - ровно тем телом, каким их шлёт клиент сегодня."""
    return [
        ('profiler/address/labels', 'как в коде',
         {"address": WALLET, "chain": "ethereum", "pagination": {"page": 1, "per_page": 100}}),
        ('profiler/address/labels', 'без pagination', {"address": WALLET, "chain": "ethereum"}),
        ('profiler/address/pnl-summary', 'как в коде',
         {"address": WALLET, "chain": "ethereum"}),
        ('profiler/address/pnl-summary', 'с date за 30д',
         {"address": WALLET, "chain": "ethereum", "date": N._date_range(30)}),
        ('profiler/address/related-wallets', 'как в коде',
         {"address": WALLET, "chain": "ethereum", "pagination": {"page": 1, "per_page": 10},
          "order_by": [{"field": "order", "direction": "ASC"}]}),
        ('profiler/address/related-wallets', 'без order_by',
         {"address": WALLET, "chain": "ethereum", "pagination": {"page": 1, "per_page": 10}}),
        ('profiler/address/counterparties', 'как в коде',
         {"address": WALLET, "chain": "ethereum", "date": N._date_range(30),
          "group_by": "wallet", "source_input": "Combined",
          "pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "total_volume_usd", "direction": "DESC"}]}),
        ('profiler/address/current-balance', 'как в коде',
         {"address": WALLET, "chain": "ethereum", "hide_spam_token": True,
          "pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "value_usd", "direction": "DESC"}]}),
    ]


def _cases_tinfo():
    return [
        ('tgm/token-information', 'как в коде',
         {"chain": "base", "token_address": TOKEN, "timeframe": "1d"}),
        ('tgm/token-information', 'без timeframe', {"chain": "base", "token_address": TOKEN}),
    ]


def _cases_new():
    """ЭНДПОИНТЫ, ЧЬЯ СХЕМА НИ РАЗУ НЕ СНЯТА ЖИВЫМ КЛЮЧОМ - тем телом, каким их шлёт клиент.

    Живой прогон 15.09 дал по ним два разных отказа, и оба про схему, а не про данные:
      * `tgm/perp-positions` -> 422: площадка отвергла запрос («перп позиции BTC»);
      * `smart-money/dex-trades` -> 200 и строки, но объём во ВСЕХ строках прочерком, то есть
        имя поля с деньгами у ответа другое, чем мы читаем.
    Отсюда две задачи пробы, и вторая не менее важная: не только ДОБИТЬСЯ 200, но и напечатать
    ИМЕНА ПОЛЕЙ первой строки. Без имён «строки есть» - это опять признак наличия, а не
    пользы: строки приехали, а прочитать из них нечего.

    Здесь варианты НЕ перебираются вручную: тело правится по тексту ошибки самой площадки
    (`--fix`), как это делает боевой `_post_fix`. Nansen называет ошибку машиночитаемо, и
    один прогон по инструкции стоит дешевле десяти догадок.
    """
    return [
        # СХЕМА СНЯТА: поле называется `token_symbol`, а не `token` (проба 19.09). Оставлено в
        # пробе, чтобы следующий прогон подтвердил ПОЛНОЕ тело - про order_by и pagination
        # этого эндпоинта мы всё ещё знаем только по образцу соседей.
        ('tgm/perp-positions', 'со снятым полем token_symbol (было token -> 422)',
         {"token_symbol": "BTC", "pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "position_value_usd", "direction": "DESC"}]}),
        ('tgm/perp-positions', 'без order_by - вдруг он и есть лишний',
         {"token_symbol": "BTC", "pagination": {"page": 1, "per_page": 5}}),
        # СХЕМА СНЯТА: нужен `date`, поля `timeframe` эндпоинт не знает. И токен ДРУГОЙ:
        # на стейблкоине этот эндпоинт не отвечает по определению.
        ('tgm/flows', 'со снятым date, без timeframe, НЕ стейблкоин',
         {"chain": "base", "token_address": TOKEN_NONSTABLE, "date": N._date_range(1),
          "pagination": {"page": 1, "per_page": 5}}),
        ('smart-money/dex-trades', 'подтверждено 19.09: деньги в trade_value_usd',
         {"chains": ["ethereum", "base"], "pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "block_timestamp", "direction": "DESC"}]}),
        ('smart-money/perp-trades', 'подтверждено 19.09: деньги в value_usd',
         {"pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "block_timestamp", "direction": "DESC"}]}),
        ('prediction-market/market-screener', 'подтверждено 19.09: id рынка в market_id',
         {"order_by": [{"direction": "DESC", "field": "volume_24hr"}], "query": "",
          "status": "active", "pagination": {"page": 1, "per_page": 3}}),
    ]


def _cases_next():
    """ВОСЕМЬ РУЧЕК СЛЕДУЮЩИХ ФИЧ. ПЕРВЫЙ КРУГ ПРОЙДЕН 24.09 - НИЖЕ ЕГО РЕЗУЛЬТАТЫ.

    ЧТО СКАЗАЛ ПРОВОД (живой прогон 24.09, ключ Ren, остаток кредитов после прогона 57540):
      * `smart-money/dcas` - ПОЛЕ `chains` НЕ СУЩЕСТВУЕТ («Field 'chains' is not recognized»),
        а БЕЗ него ручка отдаёт 200 и строки. Схема снята, фича подключена (`smart_money_dcas`);
      * `chains/chain-rank` - 200 и 37 строк на пустом теле с пагинацией. Схема снята,
        подключено (`chain_rank`);
      * `tgm/jup-dca` - поля `chain` не знает вовсе;
      * `prediction-market/position-detail` - поля `address` не знает вовсе;
      * `tgm/position-intelligence` - требует `token_address` (симвОл не подходит);
      * `ra-agent/posts-by-user` - требует `date` в форме {"from","to"};
      * `search/web-search` - требует `queries` (множественное число!), а не `query`;
      * `portfolio/defi-holdings` - требует `wallet_address`, а не `address`.
    Каждый из этих пяти отказов НАЗВАЛ имя поля, поэтому второй круг идёт не догадками, а по
    словам площадки - ниже уже исправленные тела. Это и есть причина, по которой ремонт для
    группы выключен: сырой отказ полезнее «успешного» 200 с выброшенным вопросом.
    """

    _pg = {"pagination": {"page": 1, "per_page": 5}}
    return [
        # ── СХЕМЫ, УЖЕ СНЯТЫЕ 24.09. Оставлены в пробе как эталон: если площадка их изменит,
        #    следующий прогон это покажет, а не живой человек на экране.
        ('smart-money/dcas', 'СНЯТО 24.09: без chains, 200 + строки', dict(_pg)),
        ('chains/chain-rank', 'СНЯТО 24.09: пустое тело + пагинация, 200 + 37 строк', dict(_pg)),
        # ── ВТОРОЙ КРУГ ПО СЛОВАМ ПЛОЩАДКИ ─────────────────────────────────────────────
        # jup-dca: `chain` не знает. Пробуем БЕЗ него - по образцу dcas, где лишним оказался
        # ровно признак сети (у Jupiter она одна, Solana, и указывать её незачем).
        ('tgm/jup-dca', '24.09 сказал: chain не знает -> шлём только token_address',
         dict(_pg, token_address=TOKEN_SOL)),
        ('tgm/jup-dca', 'и вариант совсем без токена - вдруг это список программ', dict(_pg)),
        # position-detail: `address` не знает. Соседи этого семейства принимают
        # `wallet_address`, поэтому берём его, а не придумываем третье имя.
        # `market_id` НАРОЧНО ПОДСТАВЛЯЕТСЯ ЖИВЫМ ПЕРЕД ОТПРАВКОЙ, а не при сборке плана: спроси
        # мы скринер здесь - печать плана сама сделала бы сетевой вызов, и «ничего не отправлено»
        # перестало бы быть правдой.
        ('prediction-market/position-detail', '24.09 сказал: address не знает -> wallet_address',
         {"wallet_address": PM_WALLET, "market_id": LIVE_PM_MARKET}),
        # position-intelligence: требует `token_address` (симвОл не подходит) - значит и сеть
        # почти наверняка обязательна, как у остальных tgm-ручек.
        ('tgm/position-intelligence', '24.09 сказал: нужен token_address -> с сетью и адресом',
         dict(_pg, chain="ethereum", token_address=TOKEN_ETH_WETH)),
        # posts-by-user: требует `date` в форме {"from","to"}.
        ('ra-agent/posts-by-user', '24.09 сказал: нужен date {from,to} -> с датой и username',
         dict(_pg, username="nansen_ai", date=N._date_range(7))),
        # web-search: требует `queries` во МНОЖЕСТВЕННОМ числе.
        ('search/web-search', '24.09 сказал: нужен queries (мн.ч.), а не query',
         dict(_pg, queries=["smart money"])),
        # defi-holdings: требует `wallet_address`.
        ('portfolio/defi-holdings', '24.09 сказал: нужен wallet_address, а не address',
         dict(_pg, wallet_address=WALLET)),
    ]


def _cases_perp():
    """КАНДИДАТЫ ПУТЕЙ ДЛЯ ТРЁХ ЭНДПОИНТОВ, ОТВЕТИВШИХ 404.

    Проба 19.09 похоронила `tgm/perp-screener`, `profiler/address/perp-positions` и
    `portfolio/positions`: 404 Not Found на все три. Клиенты и экран удалены - дверь в стену
    хуже отсутствия двери.

    НО 404 БЫВАЕТ ДВУХ СОРТОВ: «такого нет» и «переехало». Отличить их можно только перебором
    соседних путей, и это ровно то, что здесь. Найдётся - вернём из git одной командой, и это
    будет решение по факту. Не найдётся - 404 подтверждён вторым способом, и вопрос закрыт.

    Запросы дешёвые и их мало: 404 кредитов не стоит вовсе.
    """
    _pg = {"pagination": {"page": 1, "per_page": 5}}
    return [
        ('tgm/perp-screener', 'как было (404)', dict(_pg)),
        ('tgm/perp-token-screener', 'кандидат: token-screener для перпов', dict(_pg)),
        ('perp-screener', 'кандидат: без префикса tgm', dict(_pg)),
        ('tgm/perp-tokens', 'кандидат: perp-tokens', dict(_pg)),
        ('profiler/address/perp-positions', 'как было (404)', dict(_pg, address=WALLET)),
        ('profiler/perp-positions', 'кандидат: без address в пути', dict(_pg, address=WALLET)),
        ('profiler/address/perp', 'кандидат: короткий хвост', dict(_pg, address=WALLET)),
        ('perp-positions', 'кандидат: верхний уровень', dict(_pg, address=WALLET)),
        ('portfolio/positions', 'как было (404)', {"address": WALLET}),
        ('profiler/address/portfolio', 'кандидат: портфель у профайлера',
         dict(_pg, address=WALLET)),
        ('portfolio/address/positions', 'кандидат: address в пути', {"address": WALLET}),
    ]


def _cases_pm():
    """СХЕМЫ POLYMARKET, НА КОТОРЫХ СТОИТ ЭКРАН РЕПУТАЦИИ ДЕРЖАТЕЛЕЙ.

    Экран «кто держит рынок и как угадывал раньше» опирается на два эндпоинта, которых живая
    проба ещё не касалась: `top-holders` (кто держит) и `address-summary` (винрейт и PnL за всё
    время). Оба написаны по образцу соседей, то есть по догадке - а на этом экране догадка
    особенно дорога: он стоит шесть запросов, и если имя поля с винрейтом другое, человек
    получит «истории нет» по ВСЕМ держателям и решит, что у Nansen нет данных.

    `market_id` В ПРОБЕ НЕТ И БЫТЬ НЕ МОЖЕТ: он живёт ровно столько, сколько открыт рынок.
    Поэтому проба СНАЧАЛА берёт свежий id из скринера (он подтверждён 19.09) и подставляет его
    в остальные запросы. Прошитый id дал бы 404 через неделю, и мы бы искали ошибку в схеме,
    которой нет, - тот же ложный след, что с 404 на несуществующих путях.
    """
    mid = None
    try:
        rows = N.pm_market_screener(per_page=1)
        mid = N.pm_market_id(rows[0]) if rows else None
    except Exception as e:
        print('    (свежий market_id не взялся: %s - пробую без него)' % str(e)[:80])
    if not mid:
        # БЕЗ ID ПРОБА БЕССМЫСЛЕННА, И ЭТО ГОВОРИТСЯ ПРЯМО, а не подставляется «например 1»:
        # ответ на выдуманный id ничего не скажет о схеме.
        return [('prediction-market/market-screener',
                 'сперва нужен свежий market_id - без него остальное не проверить',
                 {"order_by": [{"direction": "DESC", "field": "volume_24hr"}], "query": "",
                  "status": "active", "pagination": {"page": 1, "per_page": 3}})]
    _pg = {"pagination": {"page": 1, "per_page": 5}}
    return [
        ('prediction-market/top-holders', 'как в коде (ищем поля адреса и размера позиции)',
         dict(_pg, market_id=str(mid),
              order_by=[{"field": "position_size", "direction": "DESC"}])),
        ('prediction-market/top-holders', 'без order_by - вдруг он лишний',
         dict(_pg, market_id=str(mid))),
        ('prediction-market/holders-positions', 'как в коде', dict(_pg, market_id=str(mid))),
        ('prediction-market/pnl-by-market', 'как в коде',
         dict(_pg, market_id=str(mid),
              order_by=[{"direction": "DESC", "field": "total_pnl_usd"}])),
        # ВИНРЕЙТ - ГЛАВНОЕ ПОЛЕ ЭКРАНА РЕПУТАЦИИ. Адрес публичный: билдер блоков.
        ('prediction-market/address-summary', 'ищем поле винрейта и лайфтайм-PnL',
         {"address": WALLET, "pagination": {"page": 1, "per_page": 10}}),
        ('prediction-market/ohlcv', 'свечи рынка (под кнопку графика)',
         {"market_id": str(mid), "hours": 48}),
        ('prediction-market/orderbook', 'стакан (под кнопку стакана)',
         {"market_id": str(mid)}),
    ]


def _cases_ra():
    """RESEARCH AGENT: посты X по токену. ЕСТЬ ЛИ ЭТА РУЧКА ВООБЩЕ - вопрос открытый.

    ЗАЧЕМ ПРОБА, А НЕ СРАЗУ ЭКРАН. Ниша «что говорят против того, что делают» (нарратив рядом
    с потоком денег) в клиенте не подключена, и у неё есть ровно одно неизвестное: отвечает ли
    `ra-agent/posts-by-token` и есть ли в ответе ЯЗЫК поста. Без языка гибрид с нашим китайским
    срезом не собрать, и тогда экран не нужен вовсе.

    ЧТО НАДО ПРОЧИТАТЬ В ОТВЕТЕ (глазами, по строке `поля ответа`):
      * код: 200 (жива), 404 (пути нет), 422 (путь есть, тело не то - см. подсказку площадки);
      * есть ли поле языка (`lang`, `language`, `locale`);
      * есть ли китайские посты вовсе.
    Решение по части C принимается ПО ЭТОМУ ВЫВОДУ, а не по желанию добавить экран.
    """
    # ═══ ЧТО МЫ УЖЕ ЗНАЕМ ИЗ ДВУХ ЖИВЫХ ПРОГОНОВ 22.09 ═══
    #  1. путь СУЩЕСТВУЕТ: первый заход дал 422 с инструкцией, а не 404;
    #  2. обязательно окно `date` в формате {"from","to"} - площадка назвала его сама;
    #  3. `chain` и `token_address` площадка НЕ ЗНАЕТ: ремонт снял оба, и запрос без них
    #     вернул `200 data:[]`. То есть мы спросили «дай посты» вообще без фильтра по токену.
    #
    # ОТКРЫТЫЙ ВОПРОС РОВНО ОДИН: КАК НАЗЫВАЕТСЯ ПОЛЕ ТОКЕНА. Пока он открыт, экрана быть не
    # может: «посты по токену», которые не умеют выбрать токен, это не экран.
    #
    # ПОЭТОМУ КЕЙСЫ НИЖЕ - НЕ ГАДАНИЕ, А ИЗМЕРЕНИЕ. Каждый посылает ОДНО имя-кандидат, и
    # площадка отвечает одним из двух: «не знаю такое поле» (имя неверное - это факт, а не
    # мнение) либо 200 со строками (имя верное). Ремонт для этой группы ВЫКЛЮЧЕН нарочно:
    # включённый, он снял бы кандидата и вернул пустоту, то есть съел бы ответ.
    #
    # КОНТРОЛЬНЫЙ КЕЙС ИДЁТ ПЕРВЫМ. Он посылает уже отвергнутое `token_address`: если вдруг
    # ответ изменится, значит дело не в имени поля, и все остальные выводы под вопросом.
    _eth = '0x1f9090aaE28b8a3dCeaDf281B0F12828e676c326'
    _d7 = N._date_range(7)
    _cands = [
        ('token_address', 'КОНТРОЛЬ: уже отвергнутое имя (ожидаем «не знаю поле»)'),
        ('token_addresses', 'список адресов (у площадки так устроены другие ручки)'),
        ('tokens', 'просто tokens'),
        ('token', 'единственное число'),
        ('address', 'как в profiler-разделе'),
        ('token_symbol', 'по тикеру, как у перп-позиций'),
    ]
    out = []
    for _name, _why in _cands:
        _body = {"date": _d7, "pagination": {"page": 1, "per_page": 10}}
        _body[_name] = ['ETH'] if _name in ('tokens',) else (
            [_eth] if _name == 'token_addresses' else ('ETH' if _name == 'token_symbol' else _eth))
        out.append(('ra-agent/posts-by-token', 'поле %r: %s' % (_name, _why), _body))
    # И ОДИН КЕЙС БЕЗ ФИЛЬТРА ВОВСЕ - ЭТАЛОН ПУСТОТЫ. Если и он пуст, то «пусто» у этой ручки
    # означает «на нашем плане постов нет вообще», а не «имя поля не то», и тогда перебор имён
    # бессмыслен. Без этого эталона мы приняли бы отсутствие покрытия за неверную схему.
    out.append(('ra-agent/posts-by-token', 'ЭТАЛОН: без фильтра токена (что значит «пусто»)',
                {"date": _d7, "pagination": {"page": 1, "per_page": 10}}))
    return out


GROUPS = {'wbs': _cases_wbs, 'profiler': _cases_profiler, 'tinfo': _cases_tinfo,
          'new': _cases_new, 'perp': _cases_perp, 'pm': _cases_pm, 'ra': _cases_ra,
          'next': _cases_next}
#: группы, где схема не снята и починку по словам площадки включаем сразу.
#: `perp` ремонт НЕ включает нарочно: там проверяется САМО СУЩЕСТВОВАНИЕ пути, а 404 ремонту
#: не подлежит - чинить тело эндпоинта, которого нет, значит перебирать догадки вслепую.
#: `ra` РЕМОНТ НЕ ВКЛЮЧАЕТ, И ЭТО ИСПРАВЛЕНИЕ ПО ЖИВОМУ ПРОГОНУ 22.09.
#: Ремонт снимает поля, которых площадка не знает. На этой ручке он снял `chain` и
#: `token_address` - то есть ровно те поля, которые несут САМ ВОПРОС «по какому токену», - и
#: вернул `200 data:[]`. Формально успех, по существу мы спросили «дай посты» без фильтра и
#: получили пустоту, которая читается как «постов нет». Это тот же запрет, что у нас на
#: «пустота под видом проверки», только пришедший со стороны ремонта.
#: ВЫВОД ОБЩЕГО ВИДА: ремонт хорош, когда площадка говорит «не хватает поля» (можно дослать),
#: и ВРЕДЕН, когда она говорит «не знаю твоё поле» - тогда он выкидывает вопрос и оставляет
#: синтаксически верный запрос без смысла. Для поиска ИМЕНИ поля ремонт обязан быть выключен:
#: нам нужен сырой отказ, который это имя называет.
FIX_DEFAULT = ('new', 'pm')


def _one(path, title, body):
    """Один запрос напрямую, МИМО кэша и мимо форматтеров: нам нужен сырой ответ провода."""
    import httpx
    try:
        r = httpx.post('%s/%s' % (N._BASE, path), headers=N._headers(), json=body, timeout=60)
    except Exception as e:
        return {'path': path, 'title': title, 'http': 0, 'rows': None,
                'body': '%s: %s' % (type(e).__name__, str(e)[:160])}
    rows, keys = None, None
    if r.status_code == 200:
        try:
            j = r.json()
            _rr = N._rows(j)
            rows = len(_rr) if not isinstance(j, dict) or 'data' in j or 'result' in j \
                else ('dict:%d полей' % len(j))
            # ИМЕНА ПОЛЕЙ - ВТОРАЯ ПОЛОВИНА ОТВЕТА, и без неё проба бесполезна там, где
            # площадка отвечает 200. «Строки есть» это признак наличия; какое поле нести в
            # карточку - признак пользы. Ровно на этом сгорели «смарт сделки»: 12 строк и
            # прочерк в каждой, потому что имя денежного поля другое.
            _first = (_rr[0] if _rr and isinstance(_rr[0], dict)
                      else (j if isinstance(j, dict) and not _rr else None))
            if isinstance(_first, dict):
                keys = sorted(_first.keys())
        except Exception:
            rows = 'не JSON'
    return {'path': path, 'title': title, 'http': r.status_code, 'rows': rows,
            'keys': keys, 'body': r.text[:300]}


def _one_fixing(path, title, body, rounds=4):
    """Тот же запрос, но при 400/422 тело правится ПО ТЕКСТУ ОШИБКИ ПЛОЩАДКИ, как в бою
    (`nansen_api._post_fix`). -> (итоговый результат, [шаги], рабочее тело).

    ЗАЧЕМ ИМЕННО ТАК, А НЕ СПИСКОМ ВАРИАНТОВ. Перебор угаданных вариантов - десять запросов и
    вера в то, что нужный вариант мы придумали. Nansen же сам называет, что не так («Field 'x'
    is not recognized», «Required field 'body -> date' is missing», «Did you mean 'BUY'?») -
    это инструкция, и по ней путь до рабочего тела короче и не зависит от нашей фантазии.
    Печатаем КАЖДЫЙ шаг: важно не только рабочее тело, но и чем оно отличается от нашего.
    """
    b, steps = dict(body or {}), []
    res = None
    for i in range(rounds + 1):
        res = _one(path, title, b)
        if res['http'] == 200 or res['http'] not in (400, 422) or i >= rounds:
            break
        nb, why = N._apply_hint(b, res['body'])
        if nb is None:
            steps.append('остановка: %s' % why)
            break
        steps.append(why)
        b = nb
    return res, steps, b


def main(argv):
    run = '--run' in argv
    only = None
    if '--only' in argv:
        try:
            only = argv[argv.index('--only') + 1]
        except IndexError:
            print('после --only нужна группа: %s' % ', '.join(GROUPS))
            return 1
        if only not in GROUPS:
            # ОПЕЧАТКА В ИМЕНИ ГРУППЫ НЕ ДОЛЖНА ТИХО ЗАПУСКАТЬ ВСЁ. Раньше `--only nwe`
            # прогоняло ВСЕ группы (двадцать с лишним запросов вместо восьми), потому что
            # неизвестное имя молча падало в «значит, все». Это не экономия, а сюрприз за
            # чужие кредиты.
            print('группы «%s» нет. Есть: %s' % (only, ', '.join(sorted(GROUPS))))
            return 1
    groups = {only: GROUPS[only]} if only else GROUPS
    fix = ('--fix' in argv) or (only in FIX_DEFAULT)
    cases = []
    for g in groups.values():
        cases += g()

    if not run:
        print('ПЛАН (ничего не отправлено). Запросов: %d, только чтение.' % len(cases))
        print('Цена: структурный слой, порядок %d-%d кредитов. Агента не трогаем.\n'
              % (len(cases), len(cases) * 2))
        for path, title, body in cases:
            print('  %-38s %s' % (path, title))
        # КОМАНДА ДЛЯ КОПИПАСТА ПОВТОРЯЕТ ВЫБРАННУЮ ГРУППУ. Печатать общий `--run` там, где
        # человек просил одну группу, - способ отправить в три раза больше запросов, чем он
        # смотрел в плане.
        print('\nОтправить: ./venv/bin/python3 tools/nansen_probe.py --run%s'
              % ((' --only ' + only) if only else ''))
        return 0

    if not N._key():
        print('НЕТ КЛЮЧА (NANSEN_API_KEY) - проба ничего не скажет. Это не «схема плохая».')
        return 2

    print('Проба схемы, запросов %d%s. Ключ есть, префикс НЕ печатаю.\n'
          % (len(cases), ' (+ремонт тела по словам площадки)' if fix else ''))
    ok_rows, learned = [], []
    # ЖИВОЙ ID РЫНКА ПОДСТАВЛЯЕМ ЗДЕСЬ - ПОСЛЕ проверки ключа и ТОЛЬКО при `--run`. Скринер
    # спрашивается один раз на прогон, даже если случаев с ним несколько.
    if any(LIVE_PM_MARKET in str(b.values()) for _p, _t, b in cases):
        _live_mid = _pm_market_for_probe()
        print('живой id рынка для пробы: %s\n' % _live_mid)
        for _p, _t, b in cases:
            for k, v in list(b.items()):
                if v == LIVE_PM_MARKET:
                    b[k] = _live_mid
    for path, title, body in cases:
        if fix:
            res, steps, final = _one_fixing(path, title, body)
            for s in steps:
                print('    правка: %s' % s)
            if steps and res['http'] == 200:
                learned.append((path, final, steps))
        else:
            res = _one(path, title, body)
        mark = '·'
        if res['http'] == 200 and isinstance(res['rows'], int) and res['rows'] > 0:
            mark = '✔ СТРОКИ ЕСТЬ'
            ok_rows.append((path, title, res['rows']))
        elif res['http'] == 200:
            mark = 'пусто'
        elif res['http'] in (400, 422):
            mark = 'ОТВЕРГ ЗАПРОС'
        elif res['http']:
            mark = 'HTTP %s' % res['http']
        else:
            mark = 'исключение'
        print('%-38s %-46s http=%-4s строк=%-10s %s'
              % (path, title[:44], res['http'], res['rows'], mark))
        # ПОЛЯ ПЕЧАТАЕМ ВСЕГДА, КОГДА ОНИ ЕСТЬ, а не только при отказе: именно из этой
        # строки берутся имена для форматтера, и именно её не хватало 15.09.
        if res.get('keys'):
            print('    поля:  %s' % ', '.join(res['keys'][:18]))
            _usd = [k for k in res['keys'] if str(k).lower().endswith('usd')]
            if _usd:
                print('    деньги (*_usd): %s' % ', '.join(_usd[:10]))
        if res['http'] != 200 or mark == 'пусто':
            print('    ответ: %s' % res['body'].replace('\n', ' ')[:220])
            print('    тело:  %s' % json.dumps(body, ensure_ascii=False)[:220])

    print('\n─── ВЕРДИКТ ───')
    if learned:
        print('СХЕМЫ, СНЯТЫЕ РЕМОНТОМ (это тело надо пришпилить в клиент, чтобы ремонт')
        print('перестал тратить круги на каждый холодный старт):')
        for path, final, steps in learned:
            print('  %s' % path)
            print('    правки: %s' % '; '.join(steps))
            print('    тело:   %s' % json.dumps(final, ensure_ascii=False)[:300])
        print('')
    if ok_rows:
        print('Схемы, которые ОТДАЛИ СТРОКИ (их и ставить в клиент):')
        for path, title, n in ok_rows:
            print('  %-38s %-46s строк %d' % (path, title[:44], n))
    else:
        print('НИ ОДИН вариант не отдал строк. Это не приговор схеме: возможен и отказ по')
        print('плану/кредитам - смотри коды выше. Если везде 200 и пусто, значит покрытия')
        print('по этому токену у Nansen правда нет, и тогда нужен другой токен для пробы.')
    print('\nОстаток кредитов после пробы: %s' % N.credits_left())
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
