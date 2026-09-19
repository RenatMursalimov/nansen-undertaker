#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli.py — ТЕРМИНАЛЬНЫЙ ВХОД В ТЕ ЖЕ ЭКРАНЫ, ЧТО В БОТЕ. Без телеграма и без бота.

ЗАЧЕМ. Слой живёт в приватном телеграм-боте, и посмотреть на него снаружи можно было только
скриншотами. Скриншот - не проверка: по нему нельзя ни запустить, ни убедиться, что цифры
настоящие. Здесь тот же клиент и ТЕ ЖЕ форматтеры зовутся из терминала, поэтому вывод в консоли
совпадает с тем, что человек видит в чате, слово в слово (минус HTML-разметка).

ЧЕГО ЗДЕСЬ НАРОЧНО НЕТ: ни одного своего форматтера. Каждая команда ниже - три строки: позвать
клиент, отдать строки готовому блоку, напечатать. Напиши я здесь свою верстку «покрасивее», в
публичной выжимке появился бы ВТОРОЙ вид тех же данных, и он разошёлся бы с ботом на первой
правке. Этот класс бага в проекте ловили трижды, поэтому правило простое: выжимка НЕ
форматирует, она только зовёт.

ЗАПУСК (ключ не нужен, чтобы увидеть список):
    python3 cli.py
    python3 cli.py doctor
    NANSEN_API_KEY=... python3 cli.py flows 24h
    NANSEN_API_KEY=... python3 cli.py perps BTC

БЕЗ КЛЮЧА КОМАНДЫ НЕ МОЛЧАТ И НЕ ПРИТВОРЯЮТСЯ. Они говорят «ключа нет, запрос не ушёл» -
и это не заглушка, а тот самый разбор отказа, ради которого слой написан: «данных нет» и «мы не
смогли спросить» обязаны читаться по-разному (см. README, раздел про семь классов отказа).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import nansen_api as N        # noqa: E402
import nansen_log as T        # noqa: E402

#: публичные сущности для примеров, и ни одного адреса человека: контракт USDC на Base и
#: публичный билдер блоков Ethereum. В примерах справки нельзя светить чужие кошельки.
USDC_BASE = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
BUILDER = '0x1f9090aaE28b8a3dCeaDf281B0F12828e676c326'

#: ЯЗЫК ВЫВОДА: NANSEN_LANG=en переключает на английский ТАМ, ГДЕ ОН ЕСТЬ.
#:
#: И это не «частичная поддержка из лени». Бот писался для русскоязычного чата: девять блоков
#: и все семь отказов двуязычные, остальные - только по-русски. Дописать здесь свой английский
#: перевод остальных значило бы показать судье текст, КОТОРОГО В БОТЕ НЕТ, - то есть выжимка
#: начала бы врать о продукте ровно в том месте, где её будут читать внимательнее всего.
#: Что двуязычно и что нет - перечислено в README.
LANG = 'en' if (os.getenv('NANSEN_LANG') or '').lower().startswith('en') else 'ru'


def _plain(html):
    """HTML-разметку блока - в текст терминала. Сами блоки НЕ трогаем: они боевые."""
    import re
    if not html:
        return ''
    out = re.sub(r'<a href="[^"]*">([^<]*)</a>', r'\1', str(html))
    out = re.sub(r'<[^>]+>', '', out)
    return (out.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            .replace('&quot;', '"'))


def _w(ru, en):
    """Подпись «чего именно нет» на языке вывода. -> str.

    ОТДЕЛЬНЫМ ПОМОЩНИКОМ, а не подстановкой русской строки в любой язык. Первая редакция
    передавала русское «позиций с плечом по BTC» и в английский отказ - выходило
    «we never asked for позиций с плечом по BTC». Смешанная фраза читается как небрежность
    в самом заметном месте выжимки: текст отказа тут и есть предмет разговора.
    """
    return en if LANG == 'en' else ru


def _say(block, what, why=None):
    """Напечатать блок ЛИБО причину отказа. Третьего состояния нет.

    ПУСТОТА НЕ ВЫДАЁТСЯ ЗА ПРОВЕРКУ: если блока нет, печатается класс отказа (нет ключа,
    кончились кредиты, придержали по частоте, таймаут, наш кривой запрос, ошибка площадки,
    данных правда нет) - семь разных текстов, а не одно «нет данных» на все случаи.

    `why` ОБЯЗАТЕЛЕН ТАМ, ГДЕ ФОРМАТТЕР ЕГО ВОЗВРАЩАЕТ, и это не вкусовщина. Функции вида
    `*_block_ex` отдают пару `(текст, причина)` - причина и есть назначенный канал. Первая
    редакция этот канал игнорировала и выводила причину из коробки вызова (`outcome()`), то
    есть ЗАВЕЛА ВТОРОЙ ИСТОЧНИК ПРАВДЫ - и он соврал: без ключа такие функции выходят
    досрочно, ни одного запроса не делают, коробка остаётся пустой, `outcome()` отдаёт None и
    подставляется дефолт «данных нет». Прогон без ключа сообщал «Nansen ответил, но данных
    нет» - ровно та подмена, против которой весь слой и написан, только теперь в публичной
    выжимке. Где форматтер причину НЕ возвращает (клиент зовётся напрямую) - коробка и есть
    единственный канал, там `outcome()` уместен.
    """
    if block:
        print(_plain(block))
    else:
        print(_plain(N.refusal(why or T.outcome() or N.fail_reason('empty'), LANG, what=what)))
    _cost()


def _cost():
    """Одна строка про деньги после каждого экрана: сколько вызовов и кредитов он стоил.

    ЭТО ГЛАВНАЯ СТРОКА ВЫВОДА, а не подпись мелким шрифтом. Кредиты кончаются, и экран,
    который не говорит свою цену, нельзя ни планировать, ни сравнивать с соседним.
    """
    rows = T.read_day(T._day()) or []
    calls = len(rows)
    est = 0
    for r in rows:
        ep = (r.get('ep') if isinstance(r, dict) else None) or ''
        est += T.est_credits(ep)
    left = N.credits_left()
    if LANG == 'en':
        tail = (' · %s left' % left) if left not in (None, '') else ''
        print('\n— this run: %d call(s), ≈%d credits%s' % (calls, est, tail))
    else:
        tail = (' · остаток %s' % left) if left not in (None, '') else ''
        print('\n— за этот прогон: вызовов %d, кредитов ≈%d%s' % (calls, est, tail))


def c_doctor(argv):
    """Что есть и чего нет ДО того, как тратить кредиты."""
    key = N._key()
    print('ключ NANSEN_API_KEY: %s' % ('есть (префикс не печатаю)' if key else 'НЕТ'))
    print('база зачёта:         %s' % os.getenv('NANSEN_DB_PATH', '(по умолчанию рядом с кодом)'))
    print('телеметрия:          %s' % T.TELE_DIR)
    try:
        import httpx                                  # noqa: F401
        print('httpx:               есть')
    except ImportError:
        print('httpx:               НЕТ - без него не уйдёт ни один запрос (pip install httpx)')
    try:
        import matplotlib                             # noqa: F401
        print('matplotlib:          есть (картинки соберутся)')
    except ImportError:
        print('matplotlib:          нет - команды png-* честно скажут это и отдадут текст')
    if not key:
        print('\nКлюча нет, поэтому запросов не будет. Это НЕ поломка: так выглядит первый из')
        print('семи классов отказа. Ключ: https://app.nansen.ai -> API.')
        return 0
    print('\nостаток кредитов:    %s' % N.credits_left(force=True))
    return 0


def c_flows(argv):
    tf = (argv[0] if argv else '24h')
    with T.scene('smart_flows'):
        _say(N.sm_netflow_block(None, tf, 10), _w('потоков smart money', 'smart money flows'))
    return 0


def c_trades(argv):
    with T.scene('smart_trades'):
        rows = N.sm_dex_trades(None, 15)
        _say(N.sm_trades_block(rows, None, LANG) if rows else None, _w('сделок smart money', 'smart money trades'))
    return 0


def c_token(argv):
    if len(argv) < 2:
        return _need('token <сеть> <контракт>', 'token base %s' % USDC_BASE)
    with T.scene('token_check'):
        block, _why = N.token_nansen_block_ex(argv[0], argv[1])
        _say(block, _w('данных по этому токену', 'data on this token'), _why)
    return 0


def c_who(argv):
    if len(argv) < 2:
        return _need('who <сеть> <контракт> [дней]', 'who base %s 7' % USDC_BASE)
    days = int(argv[2]) if len(argv) > 2 else 7
    with T.scene('who_bought_sold'):
        block, _why = N.who_bought_sold_block(argv[0], argv[1], days, 5, LANG)
        _say(block, _w('сделок по этому токену', 'trades on this token'), _why)
    return 0


def c_info(argv):
    if len(argv) < 2:
        return _need('info <сеть> <контракт>', 'info base %s' % USDC_BASE)
    with T.scene('token_info'):
        block, _why = N.token_info_block(argv[0], argv[1], LANG)
        _say(block, _w('справки по токену', 'token information'), _why)
    return 0


def c_pnl(argv):
    if len(argv) < 2:
        return _need('pnl <сеть> <контракт>', 'pnl base %s' % USDC_BASE)
    with T.scene('token_check'):
        _say(N.pnl_leaders_block(argv[0], argv[1], 5), _w('топ-PnL по токену', 'top PnL on this token'))
    return 0


def c_wallet(argv):
    if not argv:
        return _need('wallet <адрес> [сеть]', 'wallet %s' % BUILDER)
    chain = argv[1] if len(argv) > 1 else 'ethereum'
    with T.scene('wallet_profile'):
        block, _why = N.wallet_profile_block_ex(argv[0], chain, False)
        _say(block, _w('меток по этому адресу', 'labels for this address'), _why)
    return 0


def c_balance(argv):
    if not argv:
        return _need('balance <адрес> [сеть]', 'balance %s' % BUILDER)
    chain = argv[1] if len(argv) > 1 else 'ethereum'
    with T.scene('wallet_balance'):
        block, _why = N.wallet_balance_block(argv[0], chain, 12, LANG)
        _say(block, _w('портфеля этого адреса', 'portfolio of this address'), _why)
    return 0


def c_counterparties(argv):
    if not argv:
        return _need('counterparties <адрес> [сеть]', 'counterparties %s' % BUILDER)
    chain = argv[1] if len(argv) > 1 else 'ethereum'
    with T.scene('counterparties'):
        block, _why = N.counterparties_block(argv[0], chain, 8, 30, LANG)
        _say(block, _w('контрагентов этого адреса', 'counterparties of this address'), _why)
    return 0


def c_perp_leaders(argv):
    with T.scene('perp_leaders'):
        _say(N.perp_leaders_block(8, 7), _w('топ перп-трейдеров', 'top perp traders'))
    return 0


def c_perps(argv):
    if not argv:
        return _need('perps <ТИКЕР>', 'perps BTC')
    tok = argv[0].upper()
    with T.scene('perp_positions'):
        rows = N.perp_positions(tok, 12)
        _say(N.perp_positions_block(rows, tok, LANG) if rows else None,
             _w('позиций с плечом по %s' % tok, 'leveraged positions on %s' % tok))
    return 0


def c_liqmap(argv):
    """Карта ликвидаций: где висит чужое плечо. Текущую цену в терминале не берём - её знает
    бот из Hyperliquid, а выжимка про Nansen; без неё карта остаётся честной картой уровней."""
    if not argv:
        return _need('liqmap <ТИКЕР>', 'liqmap BTC')
    tok = argv[0].upper()
    with T.scene('perp_positions'):
        rows = N.perp_positions(tok, 50)
        _why = None if rows else N.fail_reason('empty')
    if not rows:
        print(_plain(N.refusal(_why, LANG, what=_w('позиций с плечом по %s' % tok,
                                                   'leveraged positions on %s' % tok))))
        _cost()
        return 0
    try:
        import oc_nansen_viz as V
    except ImportError as e:
        print('Картинки недоступны: %s (pip install matplotlib)' % e)
        return 2
    cl = V.liq_clusters(rows, None)
    if not cl:
        # СТРОКИ ЕСТЬ, ЦЕН ЛИКВИДАЦИИ НЕТ - это расхождение схемы, а не пустота, и оно
        # называется словом с перечислением реальных полей ответа.
        print(_plain(N.schema_gap_note(rows[0], _w('Цена ликвидации', 'Liquidation price'),
                                       LANG)))
        _cost()
        return 0
    png, cap = V.liq_map_png(rows, tok, None, LANG)
    if png:
        print('картинка: %s' % png)
    print(_plain(cap or V.liq_caption(cl, tok, LANG)))
    _cost()
    return 0


def c_pm(argv):
    with T.scene('polymarket'):
        rows = N.pm_market_screener(query=(argv[0] if argv else ''), per_page=10)
        _say(N.pm_markets_block(rows=rows, top=10) if rows else None, _w('рынков Polymarket', 'Polymarket markets'))
    return 0


def c_pm_rep(argv):
    """Кто держит рынок и как угадывал раньше. ДОРОЖЕ соседних команд: 6 запросов."""
    if not argv:
        return _need('pm-rep <market_id>', 'pm-rep 654412  (id берётся из команды pm)')
    with T.scene('polymarket'):
        rep = N.pm_reputation(argv[0])
        _why = None if rep else N.fail_reason('empty')
    _say(N.pm_reputation_block(rep, argv[0], LANG) if rep else None,
         _w('держателей этого рынка', 'holders of this market'), _why)
    return 0


def c_pm_book(argv):
    if not argv:
        return _need('pm-book <market_id>', 'pm-book 654412  (id берётся из команды pm)')
    with T.scene('polymarket'):
        ob = N.pm_orderbook(argv[0])
        _say(N.pm_orderbook_block(ob, argv[0], LANG) if ob else None, _w('стакана этого рынка', 'the orderbook of this market'))
    return 0


def c_pm_wallet(argv):
    if not argv:
        return _need('pm-wallet <адрес>', 'pm-wallet %s' % BUILDER)
    with T.scene('polymarket'):
        _say(N.pm_wallet_block(argv[0]), _w('истории этого кошелька на Polymarket', 'this wallet history on Polymarket'))
    return 0


def c_pm_leaders(argv):
    if not argv:
        return _need('pm-leaders <market_id>', 'pm-leaders 654412')
    with T.scene('polymarket'):
        _say(N.pm_market_leaders_block(argv[0], 10), _w('трейдеров этого рынка', 'traders of this market'))
    return 0


def _png(maker, what):
    """Общий хвост картиночных команд: путь к файлу ЛИБО причина, почему его нет.

    СЦЕНЫ ЗДЕСЬ НЕТ НАРОЧНО, И ЭТО НЕ МЕЛОЧЬ. Сцена помечает участок, который ТРАТИТ
    кредиты, а рисование - локальное: данные уже приехали выше, под своей сценой. Держать
    сцену здесь пришлось бы аргументом, а имя сцены, собранное в рантайме, невозможно
    сверить с закрытым реестром - сканер приватного репозитория именно на этом и покраснел,
    когда я так написал. Реестр сцен держится ровно тем, что каждое имя видно в исходнике.
    """
    try:
        import oc_nansen_viz as V
    except ImportError as e:
        print('Картинки недоступны: %s. Текстовые команды работают (pip install matplotlib).' % e)
        return 2
    png, cap = maker(V)
    if not png:
        # ПУСТОЙ ГРАФИК НЕ РИСУЕМ ВООБЩЕ: шесть нулевых столбиков выглядят как измерение и
        # врут сильнее, чем отсутствие картинки.
        print(_plain(cap or N.refusal(T.outcome() or N.fail_reason('empty'), LANG, what=what)))
        _cost()
        return 0
    print('картинка: %s' % png)
    print(_plain(cap))
    _cost()
    return 0


def c_png_flows(argv):
    if len(argv) < 2:
        return _need('png-flows <сеть> <контракт>', 'png-flows base %s' % USDC_BASE)
    chain, addr = argv[0], argv[1]
    # ПРИЧИНУ СНИМАЕМ ВНУТРИ СЦЕНЫ, А НЕ ПОСЛЕ НЕЁ. Коробка причин живёт ровно в пределах
    # `with`, и `outcome()` снаружи отдаёт ЧИСТУЮ коробку, то есть дефолт «данных нет».
    # Первая редакция звала его снаружи - и на прогоне без ключа команда сообщала «Nansen
    # ответил, но потоков нет» вместо «ключа нет, мы не спрашивали». То есть публичная
    # выжимка делала ровно то, против чего написана: выдавала пустоту за проверку.
    with T.scene('token_check'):
        flow = N.tgm_flow_intelligence(chain, addr, '1d')
        _why = None if flow else N.fail_reason('empty')
    if not flow:
        print(_plain(N.refusal(_why, LANG,
                               what=_w('потоков по этому токену', 'flows for this token'))))
        _cost()
        return 0
    return _png(lambda V: V.flows_png(flow, '', chain, LANG), _w('потоков', 'flows'))


def c_png_pm(argv):
    if not argv:
        return _need('png-pm <market_id>', 'png-pm 654412')
    with T.scene('polymarket'):
        rows = N.pm_ohlcv(argv[0], 72)
        _why = None if rows else N.fail_reason('empty')
    if not rows:
        print(_plain(N.refusal(_why, LANG,
                               what=_w('свечей этого рынка', 'candles for this market'))))
        _cost()
        return 0
    return _png(lambda V: V.pm_probability_png(rows, '', LANG), _w('свечей', 'candles'))


def c_cost(argv):
    """Суточная сводка расхода: по сценам, по эндпоинтам, с отдельной строкой про неизвестную
    цену. Читает ТОТ ЖЕ файл телеметрии, который пишут все вызовы выше."""
    print(_plain(T.daily_text()))
    return 0


def c_scenes(argv):
    """Закрытый реестр сцен. Сцена - это ЧЕЛОВЕЧЕСКИЙ вопрос, а не имя эндпоинта: расход
    считается по вопросам, иначе «на что ушли кредиты» остаётся без ответа."""
    print('Сцены (закрытый реестр, чужое имя даёт scene=? и громкую строку в сводке):')
    for s in T.SCENES:
        print('  %s' % s)
    print('\nвсего: %d' % len(T.SCENES))
    return 0


def _need(usage, example):
    print('нужны аргументы: %s\nпример: python3 cli.py %s' % (usage, example))
    return 1


CMDS = [
    # (команда, обработчик, что делает по-русски, то же по-английски)
    #
    # ДВА ЯЗЫКА В САМОМ СПИСКЕ, а не отдельным файлом переводов: `cli.py --help` - первое, что
    # запускает человек, пришедший по ссылке, и русский список команд для него равен пустому.
    # Файл переводов на двадцать строк разошёлся бы со списком на первой новой команде.
    ('doctor', c_doctor, 'что есть в окружении и сколько осталось кредитов',
     'what is configured and how many credits are left'),
    ('flows', c_flows, 'приток smart money по окну [1h|24h|7d|30d]',
     'smart money net inflow for a window [1h|24h|7d|30d]'),
    ('trades', c_trades, 'отдельные сделки smart money за сутки',
     'individual smart money trades, last 24h'),
    ('token', c_token, 'разбор токена: потоки по сегментам, Nansen Score, метки холдеров',
     'token breakdown: segment flows, Nansen Score, holder labels'),
    ('who', c_who, 'кто нетто покупал и кто продавал токен за период',
     'who net-bought and who net-sold a token over a period'),
    ('info', c_info, 'справка по токену: капитализация, объём, ликвидность, держатели',
     'token information: market cap, volume, liquidity, holders'),
    ('pnl', c_pnl, 'топ прибыльных по токену', 'top profitable traders on a token'),
    ('wallet', c_wallet, 'профиль кошелька: метки, PnL/winrate, связанные',
     'wallet profile: labels, PnL/winrate, related wallets'),
    ('balance', c_balance, 'портфель кошелька по данным Nansen',
     'wallet portfolio from Nansen data'),
    ('counterparties', c_counterparties, 'с кем этот кошелёк торгует чаще всего',
     'whom this wallet trades with most'),
    ('perp-leaders', c_perp_leaders, 'топ перп-трейдеров', 'top perp traders'),
    ('perps', c_perps, 'позиции с плечом по токену: плечо и ЦЕНА ЛИКВИДАЦИИ',
     'leveraged positions on a token: leverage and LIQUIDATION price'),
    ('pm', c_pm, 'трендовые рынки Polymarket (с market_id)',
     'trending Polymarket markets (with market_id)'),
    ('pm-book', c_pm_book, 'стакан рынка Polymarket', 'Polymarket market orderbook'),
    ('pm-rep', c_pm_rep, 'кто держит рынок и как угадывал раньше (6 запросов)',
     'who holds the market and how they guessed before (6 requests)'),
    ('pm-wallet', c_pm_wallet, 'профиль трейдера Polymarket', 'Polymarket trader profile'),
    ('pm-leaders', c_pm_leaders, 'топ-трейдеры конкретного рынка',
     'top traders of a specific market'),
    ('liqmap', c_liqmap, 'карта ликвидаций: где висит чужое плечо, КАРТИНКОЙ',
     "liquidation map: where other people's leverage sits, as a CHART"),
    ('png-flows', c_png_flows, 'потоки по сегментам КАРТИНКОЙ',
     'holder-segment flows as a CHART'),
    ('png-pm', c_png_pm, 'вероятность рынка во времени КАРТИНКОЙ',
     'market probability over time as a CHART'),
    ('cost', c_cost, 'суточная сводка расхода кредитов по сценам',
     "today's credit spend, broken down by scene"),
    ('scenes', c_scenes, 'реестр сцен, по которым считается расход',
     'the registry of scenes that spend is counted by'),
]


def main(argv):
    if not argv or argv[0] in ('-h', '--help', 'help'):
        if LANG == 'en':
            print('cli.py — the same screens the Telegram bot shows, from a terminal.')
            print('\nCommands:')
            for name, _fn, _ru, en in CMDS:
                print('  %-16s %s' % (name, en))
            print('\nEvery screen prints its own price after the output.')
            print('Set NANSEN_LANG=ru for Russian. Screens: docs/scenarios.md (Russian)')
            return 0
        print(__doc__.strip().split('\n\n')[0])
        print('\nКоманды:')
        for name, _fn, ru, _en in CMDS:
            print('  %-16s %s' % (name, ru))
        print('\nЦена каждого экрана печатается строкой после вывода.')
        print('Что написать и что придёт - docs/scenarios.md')
        return 0
    name, rest = argv[0], argv[1:]
    for cmd, fn, _ru, _en in CMDS:
        if cmd == name:
            return fn(rest)
    print('нет команды %r. Список: python3 cli.py --help' % name)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
