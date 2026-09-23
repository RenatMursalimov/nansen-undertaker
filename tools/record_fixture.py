#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/record_fixture.py — ЗАПИСАТЬ ОТВЕТ СЦЕНЫ ДЛЯ РЕЖИМА РЕПЕТИЦИИ.

    python3 tools/record_fixture.py --scene pm_reputation --market 1130012 --run
    python3 tools/record_fixture.py --scene liq_map --token BTC --run
    python3 tools/record_fixture.py --scene smart_trades --run
    python3 tools/record_fixture.py --list

БЕЗ `--run` НЕ ДЕЛАЕТ НИ ОДНОГО ВЫЗОВА и печатает план: что спросит и во что запишет. Это то
же правило, что у остальных живых инструментов проекта - инструмент, который тратит кредиты от
одного запуска без флага, однажды потратит их в чужих руках.

ЗАЧЕМ ФИКСТУРЫ ВООБЩЕ. Перед записью видео маршрут надо пройти пальцем несколько раз: проверить
порядок тапов, попадание в кадр, длину паузы. Делать это живыми вызовами значит жечь кредиты и
рисковать тем, что площадка ответит отказом ровно в кадре. Поэтому `?rehearsal=1` читает
записанные ответы, а шлюз помечает их несводимо (`rehearsal: true` + время записи) - чтобы
репетиция физически не могла выдать себя за живой прогон.

ЧТО ЗАПИСЫВАЕТСЯ: РОВНО КОНВЕРТ СЦЕНЫ, тот же, что уезжает в мини-апп. Не сырой ответ площадки
и не скриншот: конверт - это и есть контракт между ботом и экраном, и репетировать надо на нём.

ЧТО ВЫЧИЩАЕТСЯ ПЕРЕД ЗАПИСЬЮ. Полные адреса кошельков убирает тот же `nansen_gate._strip_private`,
что и на живом пути, - вторая реализация вычистки разошлась бы с первой молча. Плюс здесь стоит
СВОЯ ПРОВЕРКА РЕЗУЛЬТАТА: файл перечитывается и в нём ищется форма адреса. Проверять надо то,
что легло на диск, а не то, что мы собирались записать.
"""

import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'onchain'))
os.environ.setdefault('DB_BACKEND', 'sqlite')

OUT_DIR = os.path.join(ROOT, 'nansen', 'fixtures')

#: ФОРМЫ, КОТОРЫМ НЕЛЬЗЯ ЛЕЖАТЬ В ФИКСТУРЕ. Ищем ПРИЗНАК КЛАССА, а не список конкретных
#: адресов: список отстаёт, признак - нет (то же правило, что у публичного скруббера).
FORBIDDEN = (
    (r'0x[a-fA-F0-9]{40}', 'полный EVM-адрес'),
    (r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', 'похоже на адрес Solana'),
    (r'NANSEN_API_KEY', 'имя ключа'),
)


def _scrub_check(path):
    """Перечитать записанное и поискать запретное. -> [str] нарушений."""
    txt = open(path, encoding='utf-8').read()
    bad = []
    for rx, why in FORBIDDEN:
        for m in re.finditer(rx, txt):
            bad.append('%s: %s' % (why, m.group(0)[:20]))
    return bad


def _plan(scene, market, token):
    L = ['PLAN: записать конверт сцены %r, ни одного вызова без --run' % scene]
    if scene == 'pm_reputation':
        L.append('  спросит: держателей рынка %s + лайфтайм-историю пяти (6 запросов)'
                 % (market or '<нужен --market>'))
    elif scene == 'liq_map':
        L.append('  спросит: позиции с плечом по %s (1 запрос)' % (token or '<нужен --token>'))
    elif scene == 'smart_trades':
        L.append('  спросит: сделки smart money за сутки (1 запрос)')
    elif scene == 'smart_dca':
        L.append('  спросит: программы DCA умных денег (1 запрос)')
    elif scene == 'chain_rank':
        L.append('  спросит: рейтинг сетей (1 запрос)')
    elif scene == 'pm_positions':
        L.append('  спросит: держателей рынка %s с их PnL (1 запрос)'
                 % (market or '<нужен --market>'))
    L.append('  запишет: %s' % os.path.join('nansen', 'fixtures', '%s.json' % scene))
    L.append('  вычистит: полные адреса кошельков (тем же кодом, что живой путь)')
    return '\n'.join(L)


def _synthetic(scene):
    """Фикстура на ВЫМЫШЛЕННЫХ числах, но в настоящей форме. -> код возврата.

    Входы берутся из `tools/scene_text_baseline.py` - того же файла, на котором стоит
    проверка «текст сцен не изменился». Один набор входов на обе задачи: иначе форма в
    репетиции и форма в baseline разъехались бы, и репетиция перестала бы репетировать то,
    что работает.
    """
    import importlib.util as _iu
    import nansen_api as N
    import nansen_gate as G
    _spec = _iu.spec_from_file_location('_bl', os.path.join(ROOT, 'tools',
                                                            'scene_text_baseline.py'))
    BL = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(BL)
    _keep = (N._post_fix, N.pm_address_summary, N.perp_positions, N.sm_dex_trades, N._key,
             N.pm_market_screener)
    # ТРИ НОВЫЕ РУЧКИ ПОДМЕНЯЮТСЯ ТАК ЖЕ, КАК ОСТАЛЬНЫЕ: без подмены «полностью синтетическая»
    # фикстура пошла бы в живой Nansen за DCA, сетями и держателями рынка - то есть потратила бы
    # кредиты и подмешала настоящие числа к выдуманным. Смесь выглядит как замер и потому хуже
    # чистой выдумки (этот промах здесь уже ловили на ценах Hyperliquid).
    _keep_new = (N.smart_money_dcas, N.chain_rank, N.pm_positions)
    _keep_mark = (G._mark_price, G._hl_universe)
    try:
        N._key = lambda: 'synthetic'
        N._post_fix = lambda p, b, **k: (list(BL.PM_HOLDERS)
                                         if 'top-holders' in str(p) else None)
        N.pm_address_summary = lambda a, **k: BL.PM_SUMMARIES.get(a)
        N.perp_positions = lambda t, n=50: list(BL.PERP_ROWS)
        N.sm_dex_trades = lambda chains=None, per_page=15: list(BL.SM_TRADE_ROWS)
        N.pm_market_screener = lambda query='', per_page=12, **k: list(BL.PM_MARKETS)
        N.smart_money_dcas = lambda per_page=20: list(BL.SM_DCA_ROWS)
        N.chain_rank = lambda per_page=20: list(BL.CHAIN_ROWS)
        N.pm_positions = lambda mid, per_page=20: list(BL.PM_POS_ROWS)
        # ЦЕНУ ТОЖЕ ПОДМЕНЯЕМ, И ЭТО ВАЖНО ДЛЯ БОРДА РИСКА: без подмены `_mark_price` пошёл бы
        # в живой Hyperliquid, и в «полностью синтетической» фикстуре оказалась бы ОДНА
        # настоящая величина - расстояние до скопления, то есть главное число экрана. Смесь
        # выдуманных позиций с настоящей ценой хуже чистой выдумки: она выглядит как замер.
        G._mark_price = lambda tok: (BL.PERP_MARK if str(tok).upper() == 'BTC'
                                     else (3000.0 if str(tok).upper() == 'ETH' else None))
        # ВСЕЛЕННУЮ ПЕРПОВ ТОЖЕ ПОДМЕНЯЕМ. ПОЙМАНО РЕНДЕРОМ ФИКСТУРЫ: борд стал брать цены и
        # состав токенов из ЖИВОГО Hyperliquid, и в «полностью синтетическую» фикстуру приехали
        # настоящие тикеры с настоящими ценами - вместе с синтетическими ценами ликвидации от
        # BTC. Итог: «скопление в 64065% выше цены». Смесь выдуманного с измеренным хуже чистой
        # выдумки: она выглядит как замер.
        G._hl_universe = lambda: {'BTC': {'mark': BL.PERP_MARK, 'vol24': 9e9},
                                  'ETH': {'mark': 3000.0, 'vol24': 5e9},
                                  'SOL': {'mark': 150.0, 'vol24': 2e9},
                                  'HYPE': {'mark': 40.0, 'vol24': 1e9}}
        req = {'sc': scene, 'lg': 'en'}
        if scene == 'pm_reputation':
            req['mk'] = '654412'
        if scene == 'liq_map':
            req['tk'] = 'BTC'
        if scene == 'pm_positions':
            req['mk'] = '654412'
        env = G.handle(req, uid=0, lang='en')
    finally:
        (N._post_fix, N.pm_address_summary, N.perp_positions,
         N.sm_dex_trades, N._key, N.pm_market_screener) = _keep
        (N.smart_money_dcas, N.chain_rank, N.pm_positions) = _keep_new
        G._mark_price, G._hl_universe = _keep_mark
    env['recorded_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    env['rehearsal'] = True
    env['provenance'] = 'synthetic'
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, '%s.json' % scene)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(env, fh, ensure_ascii=False, indent=1, sort_keys=True)
    bad = _scrub_check(p)
    if bad:
        os.remove(p)
        print('ЗАПИСЬ ОТМЕНЕНА: запретное в конверте (%d), файл удалён' % len(bad))
        for b in bad[:10]:
            print('  ' + b)
        return 3
    print('записан %s (synthetic, outcome=%s)' % (p, env.get('outcome')))
    return 0


def main(argv):
    import nansen_scene as S
    scene = market = token = ''
    for i, a in enumerate(argv):
        if a == '--scene' and i + 1 < len(argv):
            scene = argv[i + 1]
        elif a == '--market' and i + 1 < len(argv):
            market = argv[i + 1]
        elif a == '--token' and i + 1 < len(argv):
            token = argv[i + 1]
    if '--list' in argv:
        print('сцены: %s' % ', '.join(S.SCENES))
        if os.path.isdir(OUT_DIR):
            for fn in sorted(os.listdir(OUT_DIR)):
                p = os.path.join(OUT_DIR, fn)
                try:
                    d = json.load(open(p, encoding='utf-8'))
                    print('  %-22s записано %s, outcome=%s'
                          % (fn, d.get('recorded_at'), d.get('outcome')))
                except Exception as e:                       # noqa: BLE001
                    print('  %-22s НЕ ЧИТАЕТСЯ: %s' % (fn, str(e)[:60]))
        else:
            print('  фикстур пока нет')
        return 0
    if scene not in S.SCENES:
        print('нужна --scene из: %s' % ', '.join(S.SCENES))
        return 1
    if '--synthetic' in argv:
        # СИНТЕТИЧЕСКАЯ ФИКСТУРА: форма настоящая, числа вымышленные. Нужна для того, чтобы
        # экран можно было открыть БЕЗ КЛЮЧА - и судье на чистой машине, и нам в тесте.
        # ПРОВЕНАНС НАЗЫВАЕТСЯ ПРЯМО В ФАЙЛЕ (`provenance: synthetic`) и попадает на плашку:
        # «записано» и «выдумано» - разные утверждения, и путать их нельзя даже в репетиции.
        return _synthetic(scene)
    if '--run' not in argv:
        print(_plan(scene, market, token))
        print('\nНичего не отправлено. Добавь --run, когда готов потратить запросы.')
        print('Без ключа можно собрать форму: --synthetic (числа вымышленные, так и помечено).')
        return 0
    if scene == 'pm_reputation' and not market:
        print('этой сцене нужен --market <id>')
        return 1
    if scene == 'liq_map' and not token:
        print('этой сцене нужен --token <TICKER>')
        return 1

    import nansen_gate as G
    import nansen_log as T
    req = {'sc': scene, 'lg': 'en'}
    if market:
        req['mk'] = market
    if token:
        req['tk'] = token.upper()
    # ЗАПИСЬ ИДЁТ ТЕМ ЖЕ ПУТЁМ, ЧТО ЖИВОЙ ЭКРАН (`nansen_gate.handle`), включая вычистку
    # адресов и телеметрию: репетировать надо на том, что правда уезжает в браузер, а не на
    # его реконструкции. Поверхность при этом остаётся 'miniapp' - вызовы были настоящие.
    env = G.handle(req, uid=0, lang='en')
    env['recorded_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    env['rehearsal'] = True
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, '%s.json' % scene)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(env, fh, ensure_ascii=False, indent=1, sort_keys=True)
    bad = _scrub_check(p)
    if bad:
        # НАШЛИ ЗАПРЕТНОЕ - ФАЙЛ УДАЛЯЕМ. Оставить его «пока разберёмся» значит однажды
        # закоммитить: фикстуры лежат рядом с кодом, и `git add -A` не спрашивает.
        os.remove(p)
        print('ЗАПИСЬ ОТМЕНЕНА: в конверте осталось запретное (%d), файл удалён:' % len(bad))
        for b in bad[:10]:
            print('  ' + b)
        return 3
    print('записан %s' % p)
    print('outcome=%s запросов=%s свежесть=%s'
          % (env.get('outcome'), env.get('cost_requests'), env.get('freshness_seconds')))
    print('телеметрия: строк сегодня %d' % len(T.read_day(T._day()) or []))
    print('\nпроверить на телефоне: открыть мини-апп с ?rehearsal=1 — вверху обязана быть '
          'плашка REHEARSAL. В финальной записи она запрещена.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
