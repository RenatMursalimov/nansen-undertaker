# -*- coding: utf-8 -*-
"""sentinel/ignition.py — СМАРТ-ЗАЖИГАНИЕ: не «кто-то купил», а «несколько РАЗНЫХ умных
адресов зашли в один токен за короткое окно».

ЗАЧЕМ ОТДЕЛЬНЫЙ СИГНАЛ РЯДОМ С ДВИЖЕНИЕМ ЦЕНЫ. Движение — это уже следствие: к моменту, когда
цена ушла на 6%, вход стоит дороже. Зажигание — попытка увидеть причину: деньги с историей
заходят ДО или ВМЕСТЕ с движением. Поэтому дозорный держит два независимых входа (площадка и
ончейн), а совпадение двух входов по одному активу — самый сильный случай, и он назван в
карточке отдельной строкой.

ГЛАВНОЕ ПРАВИЛО: СЧИТАЕМ АДРЕСА, А НЕ СДЕЛКИ
Десять сделок одного адреса — это ОДИН человек, режущий вход на части, и называть это
«смарты заходят» было бы ложью того же сорта, что «136 позиций к выкупу» при нулевой выплате.
Порог стоит на ЧИСЛЕ РАЗНЫХ адресов; объём в долларах и доля от капитализации идут рядом —
абсолют без доли бессмысленен ($150k по токену за $10B — шум, по токену за $3M — половина
рынка).

ПЕРВЫЙ ОПРОС НИЧЕГО НЕ АЛЕРТИТ, И ЭТО ЗАКОН, А НЕ ОСТОРОЖНОСТЬ
Лента Nansen трейлинговая: `smart-money/dex-trades` отдаёт ПОСЛЕДНИЕ 24 ЧАСА, а не «что
нового с прошлого раза». Значит первый опрос после чистой базы или после переезда увидел бы
суточный бэклог и выдал его как «прямо сейчас» — сорок алертов о том, что случилось вчера.
Поэтому первый опрос ТОЛЬКО заводит границу (`store.cursor`/`seen_tx`) и честно пишет об этом
строку в лог.

ЧТО СЧИТАЕТСЯ ПОКУПКОЙ. Свап в стейблкоин — это ВЫХОД, а не вход, и попадать в «зажигание»
он не должен: иначе массовая фиксация прибыли выглядела бы как приток. Список стейблов ниже
явный и короткий; всё, чего в нём нет, считается покупкой токена — «угадать по имени» здесь
нельзя (тикер `A` на одной площадке оказался токеном Vaulta, а не Agilent).
"""

import time

import nansen_log as _tele

from . import config, store

#: СТЕЙБЛЫ И КВОТНЫЕ АКТИВЫ: покупка ИХ - это продажа чего-то другого. Список явный: «всё, что
#: начинается на US» отнесло бы в стейблы половину тикеров (в живом списке Variational `US` -
#: это токен Talus).
QUOTE_SYMBOLS = {'USDC', 'USDT', 'DAI', 'USDE', 'FDUSD', 'USDS', 'TUSD', 'PYUSD', 'USD1',
                 'BUSD', 'FRAX', 'LUSD', 'GUSD', 'USDBC', 'USDC.E', 'CRVUSD', 'SUSD',
                 'USDD', 'RLUSD'}

CURSOR = 'sm_dex_ts'


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ts(v):
    """Время сделки из ответа Nansen -> epoch | None. Формат у них ISO-строкой."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace('Z', '+00:00')
    if '.' in s:
        head, _, tail = s.partition('.')
        i = 0
        while i < len(tail) and tail[i].isdigit():
            i += 1
        s = '%s.%s%s' % (head, tail[:i][:6] or '0', tail[i:])
    try:
        import datetime as _dt
        d = _dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            import datetime as _dt2
            d = d.replace(tzinfo=_dt2.timezone.utc)
        return d.timestamp()
    except (ValueError, TypeError):
        return None


def group(trades, now=None, window_min=None):
    """Сделки -> сгруппированное по токену. -> {ключ: агрегат}. ЧИСТАЯ ФУНКЦИЯ, без сети.

    Ключ группы — (сеть, адрес контракта), а НЕ символ: однофамильцы с одним тикером в разных
    сетях — обычное дело, и склеив их по символу, мы сложили бы покупки двух разных токенов
    в одно «зажигание». Этот класс ошибки в проекте уже стоил трёх экранов подряд (LIT на
    Solana вместо Lighter).
    """
    now = float(now if now is not None else time.time())
    win = float(window_min if window_min is not None else config.ign_window_min()) * 60.0
    out = {}
    for t in trades or []:
        sym = str(t.get('token_bought_symbol') or '').strip().upper()
        addr = str(t.get('token_bought_address') or '').strip()
        chain = str(t.get('chain') or '').strip().lower()
        if not addr or sym in QUOTE_SYMBOLS:
            continue
        ts = _ts(t.get('block_timestamp'))
        if ts is not None and (now - ts) > win:
            continue
        usd = _f(t.get('trade_value_usd')) or 0.0
        who = str(t.get('trader_address') or '').strip().lower()
        k = (chain, addr.lower())
        g = out.setdefault(k, {'chain': chain, 'address': addr, 'symbol': sym,
                               'wallets': set(), 'labels': [], 'usd': 0.0, 'trades': 0,
                               'mcap': None, 'age_days': None, 'last_ts': None,
                               'txs': set(),
                               # ОБЪЁМ ПО КАЖДОМУ АДРЕСУ. Нужен проверке связей (`clusters`):
                               # она смотрит не все адреса, а три САМЫХ КРУПНЫХ - именно они
                               # делают объём, и именно про них важно знать, не один ли это
                               # человек. Без этого поля «три самых крупных» было бы «три
                               # первых по алфавиту», то есть обещанием, которого код не держит.
                               'usd_by': {}})
        if who:
            g['wallets'].add(who)
            g['usd_by'][who] = g['usd_by'].get(who, 0.0) + usd
        lb = str(t.get('trader_address_label') or '').strip()
        if lb and lb not in g['labels']:
            g['labels'].append(lb)
        g['usd'] += usd
        g['trades'] += 1
        g['txs'].add(str(t.get('transaction_hash') or ''))
        mc = _f(t.get('token_bought_market_cap'))
        if mc:
            g['mcap'] = mc if g['mcap'] is None else max(g['mcap'], mc)
        ad = _f(t.get('token_bought_age_days'))
        if ad is not None:
            g['age_days'] = ad if g['age_days'] is None else min(g['age_days'], ad)
        if ts and (g['last_ts'] is None or ts > g['last_ts']):
            g['last_ts'] = ts
    return out


def judge(agg, now=None):
    """Один агрегат -> событие | None. ЧИСТАЯ ФУНКЦИЯ: пороги и штрафы, ни базы, ни сети."""
    now = int(now if now is not None else time.time())
    n = len(agg.get('wallets') or ())
    usd = float(agg.get('usd') or 0)
    mcap = agg.get('mcap')
    bps = (usd / mcap * 10000.0) if mcap else None
    if n < config.ign_wallets() or usd < config.ign_usd():
        return None
    # ДОЛЯ ОТ КАПИТАЛИЗАЦИИ - ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ ТАМ, ГДЕ ОНА ИЗМЕРЕНА. Где не измерена -
    # событие остаётся, но платит штрафом и говорит об этом вслух: молча пропустить проверку
    # и молча её провалить должны выглядеть по-разному.
    if bps is not None and bps < config.ign_mcap_bps():
        return None
    from .detector import confidence
    pen = []
    if mcap is None:
        pen.append(('капитализацию провайдер не дал - долю рынка не проверить', 25))
    if bps is not None and bps > 2000:
        pen.append(('покупки на %.0f%% капитализации - похоже на очень мелкий рынок'
                    % (bps / 100.0), 20))
    age = agg.get('age_days')
    if age is not None and age < 2:
        pen.append(('токену %.1f дня - у него нет истории вовсе' % age, 20))
    if not agg.get('labels'):
        pen.append(('у адресов нет меток - «умные» здесь только по фильтру площадки', 10))
    lag = None
    if agg.get('last_ts'):
        lag = now - int(agg['last_ts'])
        if lag > 30 * 60:
            pen.append(('последняя сделка %d мин назад' % (lag // 60), 15))
    conf, notes = confidence(100, pen)
    step = max(1, int(n // max(1, config.ign_wallets())))
    from .detector import key, _window
    return {'kind': 'ignition', 'ticker': agg.get('symbol') or '?', 'ts': now,
            'key': key('ignition', '%s:%s' % (agg.get('chain'), agg.get('address')),
                       _window(now), step),
            'severity': conf,
            'payload': {'symbol': agg.get('symbol'), 'address': agg.get('address'),
                        'chain': agg.get('chain'), 'wallets': n,
                        'labels': list(agg.get('labels') or ())[:6],
                        'usd': usd, 'trades': agg.get('trades'), 'mcap': mcap,
                        'mcap_bps': bps, 'age_days': age, 'lag_s': lag,
                        'window_min': config.ign_window_min(), 'step': step,
                        # АДРЕСА ПОКУПАТЕЛЕЙ, ОТСОРТИРОВАННЫЕ ПО ОБЪЁМУ - для проверки связей
                        # (`sentinel/clusters.py`, пункт 3.6 роудмапа). В карточку они НЕ
                        # печатаются: человеку нужен вывод («независимых участников 3»), а не
                        # двенадцать хэшей, и место в карточке конечно.
                        'wallet_addrs': _top_wallets(agg, 6),
                        'penalties': notes}}


def _top_wallets(agg, limit=6):
    """Адреса покупателей по убыванию их объёма. -> [str].

    ПО ОБЪЁМУ, А НЕ ПО ПОРЯДКУ ПОЯВЛЕНИЯ: проверка связей смотрит первые три, и «первые» обязаны
    значить «крупнейшие», иначе мы проверяем случайных, а объём делают другие. Множество в
    Python не упорядочено вовсе, так что без сортировки набор менялся бы между запусками.
    """
    by = agg.get('usd_by') or {}
    ws = list(agg.get('wallets') or ())
    # ВТОРОЙ КЛЮЧ СОРТИРОВКИ - САМ АДРЕС: при равных объёмах порядок обязан быть устойчивым,
    # иначе один и тот же набор даёт разные ответы, и расследование расхождения невозможно.
    return sorted(ws, key=lambda a: (-float(by.get(a) or 0.0), a))[:int(limit)]


def scan(now=None, fetch=None):
    """Один круг зажигания: опросить ленту, отсеять уже учтённое, вынести события.
    -> (events, note). `note` — строка для лога: почему событий нет, если их нет.

    `fetch` подменяется в тесте: подставляется список сделок, и весь путь (курсор, дедупликация
    по `transaction_hash`, пороги) проверяется без сети и без кредитов.
    """
    now = int(now if now is not None else time.time())
    first = store.cursor_get(CURSOR) is None
    if fetch is None:
        def fetch():
            import nansen_api as _n
            # СЦЕНА - 'sentinel_watch': расход дозорного обязан быть отдельной строкой в
            # суточной сводке. Ляг он в общую сцену смарт-сделок, и «сколько стоит дозор»
            # стало бы невычислимым ровно там, где на это смотрят.
            with _tele.scene('sentinel_watch', None, surface='sentinel'):
                rows = _n.sm_dex_trades(per_page=100, live=True)
            store.spend_add(credits=_credits_guess(), events=0)
            return rows
    try:
        trades = fetch() or []
    except Exception as e:
        return [], 'лента смарт-сделок не прочитана: %s: %s' % (type(e).__name__, str(e)[:120])
    if not trades:
        return [], 'лента смарт-сделок пуста (отказ площадки или правда тишина)'
    fresh = store.seen_tx([t.get('transaction_hash') for t in trades], ts=now)
    store.cursor_set(CURSOR, now)
    if first:
        # ПЕРВЫЙ ОПРОС ТОЛЬКО ЗАВОДИТ ГРАНИЦУ. Сказать об этом в лог обязательно: иначе
        # «дозорный запущен и молчит» выглядит как поломка, и следующий разбор пойдёт искать
        # её в пороге.
        return [], ('первый опрос: заведена граница по %d сделкам, алертов нет по построению'
                    % len(trades))
    new = [t for t in trades if str(t.get('transaction_hash') or '') in fresh]
    if not new:
        return [], 'новых сделок нет (все %d уже учтены)' % len(trades)
    # ОКНО СЧИТАЕМ ПО ВСЕЙ ЛЕНТЕ, А СОБЫТИЕ - ПО НОВЫМ СДЕЛКАМ. Иначе третий адрес, зашедший
    # через десять минут после первых двух, не увидел бы их вовсе: они уже «учтены», и порог
    # «три разных адреса» не собрался бы никогда. Поэтому агрегат строится по окну целиком, а
    # новизна решает только то, ЕСТЬ ЛИ ПОВОД пересчитать.
    groups = group(trades, now=now)
    touched = {(str(t.get('chain') or '').lower(),
                str(t.get('token_bought_address') or '').lower()) for t in new}
    evs = []
    for k, agg in groups.items():
        if k not in touched:
            continue
        ev = judge(agg, now=now)
        if ev:
            evs.append(ev)
    return evs, ('новых сделок %d, событий %d' % (len(new), len(evs)))


#: ЦЕНА ВЫЗОВА В КРЕДИТАХ - ПО ОФИЦИАЛЬНОЙ СТРАНИЦЕ ЦЕН, ТОЙ ЖЕ, ЧТО У `nansen_log`. Где цена
#: не названа источником, в проекте пишут ноль и считают отдельной строкой; здесь названа (1-5
#: за структурный вызов), берём верхнюю границу - занижать свой же расход хуже, чем завысить.
_CREDITS_SM_DEX = 5


def _credits_guess():
    return _CREDITS_SM_DEX


async def confirm(symbol, price, chain_hint=None):
    """ПОДТВЕРЖДЕНИЕ ОНЧЕЙНОМ для события с площадки. -> dict со строками и с причиной отказа.

    ЗАЧЕМ. Движение на Variational — это движение НА ПЛОЩАДКЕ; вопрос человека другой: «а
    деньги-то куда идут?». Ответ требует адреса контракта, а тикер контрактом НЕ является:
    в живом списке площадки `A` — токен Vaulta, `US` — Talus, и таблица «тикер -> контракт»,
    собранная из знания фондового рынка, соврала бы на первых двух строках.

    ПОЭТОМУ АДРЕС БЕРЁМ ТОЛЬКО ЧЕРЕЗ УЖЕ ПРОВЕРЕННУЮ ДВЕРЬ `oc_passport.canonical_contract`,
    которая сверяет КАНДИДАТОВ С ЦЕНОЙ и выбирает крупнейший по капитализации. Марк-цена
    площадки играет здесь роль биржевой цены — то есть сопоставление ТИКЕР->КОНТРАКТ у нас
    подтверждено числом, а не похожестью строк. Не сошлось — говорим «не сопоставлен» и НЕ
    показываем ончейн вовсе: ончейн не про тот токен хуже отсутствия ончейна.
    """
    out = {'symbol': symbol, 'address': None, 'chain': None, 'refused': None,
           'buyers': [], 'sellers': [], 'credits': 0}
    if not symbol or not price:
        out['refused'] = 'нет тикера или цены — сопоставлять нечего'
        return out
    try:
        import sys
        import os as _os
        _oc = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            'onchain')
        if _oc not in sys.path:
            sys.path.insert(0, _oc)
        import oc_passport as _p
        addr, market, why = await _p.canonical_contract(symbol, float(price))
    except Exception as e:
        out['refused'] = 'сопоставление тикера не сработало: %s' % str(e)[:120]
        return out
    if not addr:
        out['refused'] = why or 'канонический контракт по цене не найден'
        return out
    out['address'] = addr
    out['chain'] = (market or {}).get('chain') if isinstance(market, dict) else chain_hint
    try:
        import asyncio
        import nansen_api as _n
        ch = out['chain'] or 'ethereum'
        with _tele.scene('sentinel_ignition', None, surface='sentinel'):
            buys = await asyncio.to_thread(_n.tgm_who_bought_sold, ch, addr, 'BUY', 6, 1)
            sells = await asyncio.to_thread(_n.tgm_who_bought_sold, ch, addr, 'SELL', 6, 1)
        out['credits'] = 2 * _CREDITS_SM_DEX
        store.spend_add(credits=out['credits'])
        out['buyers'] = buys or []
        out['sellers'] = sells or []
        if not buys and not sells:
            out['refused'] = _fail_words()
    except Exception as e:
        out['refused'] = 'ончейн не прочитан: %s: %s' % (type(e).__name__, str(e)[:100])
    return out


def _fail_words():
    """Почему ончейн пуст — СЛОВАМИ ПЛОЩАДКИ, а не нашим «данных нет».

    Класс отказа лежит в коробке вызова (`nansen_log`), и брать его надо оттуда: «пустота» и
    «нам отказали» выглядят одинаково в `[]`, и именно это в проекте однажды выдало чистую
    страницу вместо сообщения о нехватке кредитов.
    """
    try:
        import nansen_api as _n
        return _n.fail_reason('empty')
    except Exception:
        return 'empty'
