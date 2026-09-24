#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/scene_text_baseline.py — ТЕКСТ ТРЁХ СЦЕН НА ФИКСИРОВАННЫХ ВХОДАХ, БЕЗ СЕТИ.

    python3 tools/scene_text_baseline.py            # напечатать текст
    python3 tools/scene_text_baseline.py --write    # записать в nansen/proofs/scene_text_baseline.txt

ЗАЧЕМ. Мини-апп обязан рисовать ТОТ ЖЕ словарь, из которого бот строит текст (Закон 0). Чтобы
выделить dict-слой и не сломать бота, нужен способ доказать, что текстовый вывод НЕ ИЗМЕНИЛСЯ
ни на символ. «Я посмотрел глазами» здесь не работает: у трёх экранов вместе больше сорока
строк, и сдвиг одного пробела в подписи заметен только диффом.

ПОЧЕМУ ФИКСИРОВАННЫЕ ВХОДЫ, А НЕ ЖИВОЙ ПРОГОН. Живой ответ Nansen меняется каждую минуту, и
diff на нём показывал бы движение рынка, а не последствия правки. Здесь входы - константы в
этом файле, поэтому единственная причина расхождения diff - изменившийся код рендера.

ЧЕГО ЭТОТ ИНСТРУМЕНТ НЕ ДОКАЗЫВАЕТ: что живой экран цел. Он сторожит ФОРМУ текста на
известных данных; живые пути проверяет tools/nansen_live_smoke.py.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'onchain'))
os.environ.setdefault('DB_BACKEND', 'sqlite')

OUT_REL = os.path.join('nansen', 'proofs', 'scene_text_baseline.txt')

#: ВХОДЫ ЗАФИКСИРОВАНЫ ЗДЕСЬ. Числа вымышленные, но форма - ровно та, что приезжает с площадки
#: (имена полей снимались живыми пробами 19-20.09, см. комментарии у форматтеров).
PM_HOLDERS = [
    {'address': '0xaaaa000000000000000000000000000000000001',
     'address_label': 'Whale A', 'position_size': 1800000.0, 'current_price': 0.45,
     'avg_entry_price': 0.12, 'side': 'Yes', 'outcome_index': 0},
    {'address': '0xbbbb000000000000000000000000000000000002',
     'position_size': 1400000.0, 'current_price': 0.45,
     'avg_entry_price': 0.31, 'side': 'Yes', 'outcome_index': 0},
    {'address': '0xcccc000000000000000000000000000000000003',
     'address_label': 'Smart Money', 'position_size': 900000.0, 'current_price': 0.55,
     'avg_entry_price': 0.60, 'side': 'No', 'outcome_index': 1},
    {'address': '0xdddd000000000000000000000000000000000004',
     'position_size': 400000.0, 'current_price': 0.55, 'side': 'No', 'outcome_index': 1},
    {'address': '0xeeee000000000000000000000000000000000005',
     'position_size': 250000.0, 'current_price': 0.45, 'side': 'Yes', 'outcome_index': 0},
    {'address': '0xffff000000000000000000000000000000000006',
     'position_size': 100000.0, 'current_price': 0.45, 'side': 'Yes', 'outcome_index': 0},
]

#: Ответы `prediction-market/address-summary` по адресу. None = истории нет (держатель серый).
PM_SUMMARIES = {
    '0xaaaa000000000000000000000000000000000001':
        {'win_rate': 0.33, 'total_pnl_usd': -120000.0, 'markets_traded': 84},
    '0xbbbb000000000000000000000000000000000002':
        {'win_rate': 0.71, 'total_pnl_usd': 340000.0, 'markets_traded': 210},
    '0xcccc000000000000000000000000000000000003':
        {'win_rate': 0.38, 'total_pnl_usd': -45000.0, 'markets_traded': 51},
    '0xdddd000000000000000000000000000000000004': None,
    '0xeeee000000000000000000000000000000000005':
        {'total_pnl_usd': 1000.0, 'markets_traded': 3},        # есть строка, нет винрейта
}

PERP_ROWS = [
    {'address_label': 'Smart Money', 'side': 'LONG', 'position_value_usd': 10700000.0,
     'leverage': 20, 'unrealized_pnl': -120200.0, 'liquidation_price': 61800.0},
    {'address_label': 'Whale B', 'side': 'LONG', 'position_value_usd': 11800000.0,
     'leverage': 10, 'unrealized_pnl': 240000.0, 'liquidation_price': 62100.0},
    {'address': '0x1111000000000000000000000000000000000011', 'side': 'SHORT',
     'position_value_usd': 5200000.0, 'leverage': 5, 'liquidation_price': 71200.0},
    {'address_label': 'Fund C', 'side': 'SHORT', 'position_value_usd': 3000000.0,
     'leverage': 3, 'liquidation_price': 74500.0},
    {'address_label': 'Trader D', 'side': 'LONG', 'position_value_usd': 900000.0,
     'leverage': 25, 'liquidation_price': 59900.0},
    {'address_label': 'No liq row', 'side': 'LONG', 'position_value_usd': 400000.0,
     'leverage': 2},                                            # без цены ликвидации
]
PERP_MARK = 67250.0

#: ВТОРОЙ ТОКЕН ДЛЯ БОРДА РИСКА. Нужен именно ВТОРОЙ набор: борд сортирует по расстоянию от
#: цены до скопления, и на одинаковых входах сортировка не проверяется - все строки совпадут.
#: Здесь скопление БЛИЖЕ к цене, чем у BTC, и в baseline видно, что ETH встал первым.
PERP_ROWS_ETH = [
    {'address_label': 'Fund Z', 'side': 'SHORT', 'position_value_usd': 5000000.0,
     'leverage': 8, 'liquidation_price': 3070.0},
    {'address': '0x3333000000000000000000000000000000000033', 'side': 'LONG',
     'position_value_usd': 2500000.0, 'leverage': 12, 'liquidation_price': 2840.0},
]

#: Строки скринера рынков: вход в hero. Форма настоящая (поля сняты живой пробой 20.09),
#: числа вымышленные. Третий рынок НАРОЧНО без id - экран обязан назвать это числом, а не
#: тихо укоротить список.
PM_MARKETS = [
    {'question': 'Will the Fed cut rates in September?', 'last_trade_price': 0.90,
     'volume_24hr': 4100000.0, 'id': '654412'},
    {'question': 'Government shutdown before October?', 'last_trade_price': 0.31,
     'volume_24hr': 1882000.0, 'id': '654987'},
    {'question': 'Market with no id in the response', 'last_trade_price': 0.5,
     'volume_24hr': 12000.0},
]

SM_TRADE_ROWS = [
    {'address_label': 'Smart Trader 1', 'token_bought_symbol': 'AAA', 'chain': 'base',
     'token_bought_address': '0x2222000000000000000000000000000000000022',
     'trade_value_usd': 48300.0, 'token_bought_market_cap': 2100000.0,
     'token_bought_age_days': 3},
    {'address_label': 'Smart Trader 2', 'token_bought_symbol': 'BBB', 'chain': 'solana',
     'trade_value_usd': 120000.0, 'token_bought_market_cap': 50000000000.0,
     'token_bought_age_days': 900},
    {'address': '0x3333000000000000000000000000000000000033',
     'token_bought_symbol': 'CCC', 'chain': 'ethereum', 'trade_value_usd': 9000.0},
]

#: ВХОДЫ ТРЁХ ЭКРАНОВ, ПРИШЕДШИХ В МИНИ-АПП. В каждом наборе НАРОЧНО есть неполная строка:
#: baseline сторожит не только «красивый» случай, но и то, как текст говорит о пропущенном
#: числе. Сцена, у которой в тестовых данных всё на месте, однажды напечатает «0%» вместо
#: «не измерено» и никто этого не заметит.
SM_DCA_ROWS = [
    {'trader_address_label': 'Smart Whale 1', 'input_token_symbol': 'USDC',
     'output_token_symbol': 'WETH', 'deposit_value_usd': 2000000.0,
     'deposit_token_amount': 2000000.0, 'token_spent_amount': 400000.0,
     'dca_status': 'active'},
    {'trader_address_label': 'Smart Whale 2', 'input_token_symbol': 'USDT',
     'output_token_symbol': 'SOL', 'deposit_value_usd': 350000.0,
     'deposit_token_amount': 350000.0, 'token_spent_amount': 332500.0,
     'dca_status': 'active'},
    # ДОЛИ ИСПОЛНЕНИЯ НЕТ: в ответе нет одного из двух чисел, и текст обязан сказать это словом.
    {'trader_address': '0x4444000000000000000000000000000000000044',
     'input_token_symbol': 'USDC', 'output_token_symbol': 'AAA',
     'deposit_value_usd': 90000.0, 'dca_status': 'closed'},
]

CHAIN_ROWS = [
    {'chain': 'ethereum', 'tvl_usd': 52000000000.0, 'tvl_usd_percent_change': 1.4,
     'total_dex_volume_usd': 3100000000.0, 'active_address_count_txs': 480000.0},
    {'chain': 'solana', 'tvl_usd': 9400000000.0, 'tvl_usd_percent_change': -2.1,
     'total_dex_volume_usd': 5200000000.0, 'active_address_count_txs': 1200000.0},
    # ИЗМЕНЕНИЯ TVL НЕТ: неподвижность на экране это НАШЕ отсутствующее число.
    {'chain': 'base', 'tvl_usd': 3100000000.0,
     'total_dex_volume_usd': 900000000.0, 'active_address_count_txs': 640000.0},
]

PM_POS_ROWS = [
    {'address': '0x5555000000000000000000000000000000000055', 'outcome': 'Yes',
     'token_pnl_usd': 128000.0, 'avg_entry_price': 0.42, 'current_price': 0.61,
     'unrealized_value_usd': 302000.0,
     'event_title': 'Will the Fed cut rates in September?', 'market_resolved': False},
    {'address': '0x6666000000000000000000000000000000000066', 'outcome': 'No',
     'token_pnl_usd': -81000.0, 'avg_entry_price': 0.55, 'current_price': 0.39,
     'unrealized_value_usd': 0.0,
     'event_title': 'Will the Fed cut rates in September?', 'market_resolved': False},
    # PnL НЕ ПРИЕХАЛ: такой держатель НЕ считается в сумму, и об этом сказано оговоркой.
    {'address': '0x7777000000000000000000000000000000000077', 'outcome': 'Yes',
     'unrealized_value_usd': 4100.0,
     'event_title': 'Will the Fed cut rates in September?', 'market_resolved': False},
]


def _sections():
    """Текст трёх сцен на фиксированных входах. -> [(имя, текст)].

    Сцены зовутся РОВНО теми же функциями, что зовёт бот. Если в них появится второй источник
    правды, это место сломается первым.
    """
    import nansen_api as N
    import oc_nansen_viz as V

    out = []

    # ── 1. pm_reputation: hero. Сеть подменяется на уровне двух клиентских функций, потому
    #    что весь расчёт (доли × цена, порог винрейта, серые держатели) живёт выше них.
    _keep = (N._post_fix, N.pm_address_summary)
    try:
        def _fix(path, body, **k):
            return list(PM_HOLDERS) if 'top-holders' in str(path) else None
        N._post_fix = _fix
        N.pm_address_summary = lambda addr, **k: PM_SUMMARIES.get(addr)
        rep = N.pm_reputation('654412')
        for lang in ('ru', 'en'):
            out.append(('pm_reputation.%s' % lang,
                        N.pm_reputation_block(rep, '654412', lang)))
    finally:
        N._post_fix, N.pm_address_summary = _keep

    # ── 2. liq_map: подпись считается по тем же числам, что рисует картинка.
    cl = V.liq_clusters(PERP_ROWS, PERP_MARK)
    for lang in ('ru', 'en'):
        out.append(('liq_map.%s' % lang, V.liq_caption(cl, 'BTC', lang)))

    # ── 3. smart_trades: доля от капитализации - главное число строки.
    for lang in ('ru', 'en'):
        out.append(('smart_trades.%s' % lang,
                    N.sm_trades_block(SM_TRADE_ROWS, None, lang)))

    # ── 4. sharp_markets: сравнение рынков. Подменяются ТЕ ЖЕ две функции, что в сцене 1,
    #    поэтому по каждому рынку приезжают одни и те же держатели - для baseline это и нужно:
    #    он сторожит ФОРМУ текста, а не разнообразие данных.
    _keep2 = (N._post_fix, N.pm_address_summary, N.pm_market_screener)
    try:
        def _fix2(path, body, **k):
            return list(PM_HOLDERS) if 'top-holders' in str(path) else None
        N._post_fix = _fix2
        N.pm_address_summary = lambda addr, **k: PM_SUMMARIES.get(addr)
        N.pm_market_screener = lambda query='', per_page=12, **k: list(PM_MARKETS)
        d = N.sharp_markets(4, 3)
        for lang in ('ru', 'en'):
            out.append(('sharp_markets.%s' % lang, N.sharp_markets_block(d, lang)))
    finally:
        N._post_fix, N.pm_address_summary, N.pm_market_screener = _keep2

    # ── 5. perp_risk: борд считается ИЗ ТЕХ ЖЕ строк позиций, что карта. Цены заданы здесь
    #    константами: расстояние до скопления - главное число борда, и брать его из живого
    #    Hyperliquid значило бы получать новый baseline каждую минуту.
    _board = {'BTC': {'rows': PERP_ROWS, 'mark': PERP_MARK},
              'ETH': {'rows': PERP_ROWS_ETH, 'mark': 3000.0},
              'SOL': {'rows': [], 'mark': 150.0},
              'HYPE': {'rows': PERP_ROWS, 'mark': None}}
    bd = V.liq_board(_board)
    for lang in ('ru', 'en'):
        out.append(('perp_risk.%s' % lang, V.liq_board_caption(bd, lang)))

    # ── 6-8. ТРИ ЭКРАНА, ПРИШЕДШИЕ В МИНИ-АПП. Зовём ровно то, что зовёт бот, и через
    #    СЛОВАРЬ: `*_data` -> `*_block`. Так baseline сторожит именно тот путь, по которому
    #    ходит картинка, а не второй, оставленный для совместимости.
    for lang in ('ru', 'en'):
        out.append(('smart_dca.%s' % lang,
                    N.sm_dca_block(N.sm_dca_data(SM_DCA_ROWS), None, lang)))
    for lang in ('ru', 'en'):
        out.append(('chain_rank.%s' % lang,
                    N.chain_rank_block(N.chain_rank_data(CHAIN_ROWS), lang)))
    for lang in ('ru', 'en'):
        out.append(('pm_positions.%s' % lang,
                    N.pm_positions_block(N.pm_positions_data(PM_POS_ROWS), '654412', lang)))
    # ── 9. СКВОЗНОЙ ПЕРЕХОД: ТЕ ЖЕ ТРИ ЭКРАНА С ИМЕНЕМ БОТА. Это НЕ повтор предыдущих: с
    #    `bot_un` каждая строка становится ССЫЛКОЙ на карточку (счёта или токена), и ровно на
    #    этом жаловался владелец - «показывается списком без ссылок, а толку если на них не
    #    перейти». Ссылка - часть текста, а не оформление: перепутанный префикс (`acc_` вместо
    #    `tok_`) открыл бы человеку НЕ ТОТ экран, и заметить это можно только тапом. Поэтому
    #    форма перехода стоит в baseline, где её видно строкой.
    for lang in ('ru', 'en'):
        out.append(('smart_trades.linked.%s' % lang,
                    N.sm_trades_block(SM_TRADE_ROWS, 'grobtestbot', lang)))
    for lang in ('ru', 'en'):
        out.append(('smart_dca.linked.%s' % lang,
                    N.sm_dca_block(N.sm_dca_data(SM_DCA_ROWS), 'grobtestbot', lang)))
    for lang in ('ru', 'en'):
        out.append(('pm_positions.linked.%s' % lang,
                    N.pm_positions_block(N.pm_positions_data(PM_POS_ROWS), '654412', lang,
                                         bot_un='grobtestbot')))
    # ── 10. КАРТОЧКА ОДНОГО РЫНКА - НОВЫЙ ЭКРАН ЧАТА, и ведёт он вопросом, а не номером.
    for lang in ('ru', 'en'):
        out.append(('pm_market_card.%s' % lang,
                    N.pm_market_card_block(PM_MARKETS[0], lang)))
    return out


def text():
    """Весь baseline одной строкой. -> str."""
    L = []
    for name, body in _sections():
        L.append('===== %s =====' % name)
        L.append(body if body is not None else '<None>')
        L.append('')
    return '\n'.join(L)


def main(argv):
    txt = text()
    if '--write' in argv:
        p = os.path.join(ROOT, OUT_REL)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(txt)
        print('записан %s (%d строк)' % (p, txt.count('\n') + 1))
        return 0
    if '--check' in argv:
        p = os.path.join(ROOT, OUT_REL)
        if not os.path.exists(p):
            print('baseline ещё не снят: python3 tools/scene_text_baseline.py --write')
            return 1
        old = open(p, encoding='utf-8').read()
        if old != txt:
            import difflib
            print('ТЕКСТ СЦЕН ИЗМЕНИЛСЯ. Diff (baseline -> сейчас):')
            for line in list(difflib.unified_diff(old.splitlines(), txt.splitlines(),
                                                  'baseline', 'now', lineterm=''))[:60]:
                print('  ' + line)
            return 1
        print('текст трёх сцен совпадает с baseline байт-в-байт')
        return 0
    sys.stdout.write(txt)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
