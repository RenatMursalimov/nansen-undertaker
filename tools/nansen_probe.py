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
        ('tgm/perp-positions', 'как в коде (422 на живом прогоне 15.09)',
         {"token": "BTC", "pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "position_value_usd", "direction": "DESC"}]}),
        ('tgm/perp-screener', 'как в коде',
         {"pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "open_interest_usd", "direction": "DESC"}]}),
        ('tgm/flows', 'как в коде',
         {"chain": "base", "token_address": TOKEN, "timeframe": "1d",
          "pagination": {"page": 1, "per_page": 5}}),
        ('smart-money/dex-trades', 'как в коде (объём читался прочерком 15.09)',
         {"chains": ["ethereum", "base"], "pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "block_timestamp", "direction": "DESC"}]}),
        ('smart-money/perp-trades', 'как в коде',
         {"pagination": {"page": 1, "per_page": 5},
          "order_by": [{"field": "block_timestamp", "direction": "DESC"}]}),
        ('profiler/address/perp-positions', 'как в коде',
         {"address": WALLET, "pagination": {"page": 1, "per_page": 5}}),
        ('portfolio/positions', 'как в коде', {"address": WALLET}),
        # Polymarket: market_id брать НЕОТКУДА, пока не подтверждён скринер - поэтому первым
        # делом снимаем скринер и печатаем ИМЕНА ПОЛЕЙ, среди которых должен быть id рынка.
        # Без него кнопки «график»/«стакан» опираться не на что (см. GROUPS['pm']).
        ('prediction-market/market-screener', 'как в коде - ищем в полях id рынка',
         {"order_by": [{"direction": "DESC", "field": "volume_24hr"}], "query": "",
          "status": "active", "pagination": {"page": 1, "per_page": 3}}),
    ]


GROUPS = {'wbs': _cases_wbs, 'profiler': _cases_profiler, 'tinfo': _cases_tinfo,
          'new': _cases_new}
#: группы, где схема не снята и починку по словам площадки включаем сразу
FIX_DEFAULT = ('new',)


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
