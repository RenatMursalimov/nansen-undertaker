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

from . import assets, config, store

#: СТЕЙБЛЫ И КВОТНЫЕ АКТИВЫ: покупка ИХ - это продажа чего-то другого. Список явный: «всё, что
#: начинается на US» отнесло бы в стейблы половину тикеров (в живом списке Variational `US` -
#: это токен Talus).
QUOTE_SYMBOLS = {'USDC', 'USDT', 'DAI', 'USDE', 'FDUSD', 'USDS', 'TUSD', 'PYUSD', 'USD1',
                 'BUSD', 'FRAX', 'LUSD', 'GUSD', 'USDBC', 'USDC.E', 'CRVUSD', 'SUSD',
                 'USDD', 'RLUSD'}

CURSOR = 'sm_dex_ts'

#: ПОРОГИ СМАРТ-ПЕРПА (ТЗ 1.7). Стоят здесь, а не в `config`, НАМЕРЕННО: это НЕ настройки
#: человека и не то, что крутят кнопкой - это определение события. Числа названы владельцем в
#: ТЗ: два разных адреса, одна сторона, 30 минут, от $250k. Понадобится их менять - менять по
#: замеру распределения из `sentinel_sm_trades`, как договорились про порог зажигания.
PERP_WALLETS = 2
PERP_USD = 250_000.0
PERP_WINDOW_MIN = 30


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


def _meaningful(lbl):
    """Смысловая метка или ''. Одна дверь - `nansen_api.meaningful_label`; своей копии правила
    здесь нет, иначе экран Nansen и карточка дозорного однажды разошлись бы в том, что прятать."""
    try:
        import nansen_api as _n
        return _n.meaningful_label(lbl)
    except Exception:                                    # noqa: BLE001
        return str(lbl or '').strip()


def rows_from_feed(trades):
    """Ответ провайдера -> строки для базы. -> [dict] в форме `store.SMT_FIELDS`.

    ОТДЕЛЬНАЯ ФУНКЦИЯ, ПОТОМУ ЧТО ФОРМА ОТВЕТА - ЭТО ЗНАНИЕ О ПРОВАЙДЕРЕ, и жить оно обязано в
    одном месте. Две ленты (`dex-trades` и `perp-trades`) называют поля по-разному, и разбор,
    размазанный по группировке и записи, однажды разойдётся: одна половина прочитает
    `trade_value_usd`, другая `value_usd`, и деньги молча станут нулём.
    МЕТКУ НОВОГО ТОКЕНА СРЕЗАЕМ ЗДЕСЬ ЖЕ (`assets.clean_symbol`): в ключах и сопоставлении
    «🌱 P(DOOM)» и «P(DOOM)» обязаны быть ОДНИМ токеном, иначе порог по адресам не соберётся
    никогда. Факт новизны не теряется - он приезжает отдельным полем `age_days`.
    """
    out = []
    for t in (trades or ()):
        if not isinstance(t, dict):
            continue
        sym, _new = assets.clean_symbol(t.get('token_bought_symbol') or t.get('token_symbol'))
        out.append({
            'tx_hash': str(t.get('transaction_hash') or '').strip(),
            'chain': str(t.get('chain') or '').strip().lower() or None,
            'token_address': str(t.get('token_bought_address') or '').strip() or None,
            'symbol': sym or None,
            # АДРЕС БЕЗ СМЕНЫ РЕГИСТРА: у Solana base58 чувствителен к регистру, и приведённый
            # к нижнему адрес Nansen не узнаёт (разбор в `clusters._norm`). Сравнивается он ниже
            # отдельным нормализованным ключом.
            'trader': str(t.get('trader_address') or '').strip() or None,
            # МЕТКА ТОЛЬКО СМЫСЛОВАЯ: «Uses "X" HL Referral Code» и доменные имена кошелька
            # не отвечают на «кто это» (разбор в `nansen_api.meaningful_label`).
            'trader_label': _meaningful(t.get('trader_address_label')) or None,
            # ДЕНЬГИ - ТОЛЬКО ИЗ ПОЛЯ ОБЪЁМА. `price_usd` это цена ОДНОГО токена, и спутать их
            # значит показать $0.99 вместо $48K (в проекте уже ловилось).
            'usd': _f(t.get('trade_value_usd')) or _f(t.get('value_usd')),
            'mcap': _f(t.get('token_bought_market_cap')),
            'age_days': _f(t.get('token_bought_age_days')),
            'side': (str(t.get('side') or '').strip().lower() or None),
            # ДЕЙСТВИЕ ПЕРП-СДЕЛКИ: open / add / reduce / close. Без него «сократил лонг» и
            # «открыл лонг» были одной строкой со стороной long (разбор в `scan_perp`).
            'action': (str(t.get('action') or '').strip().lower() or None),
            'price_usd': _f(t.get('price_usd')),
            'block_ts': (int(_ts(t.get('block_timestamp')) or 0) or None),
            # ФАКТ НОВИЗНЫ ЕДЕТ ОТДЕЛЬНЫМ ПОЛЕМ, потому что из символа он уже срезан.
            'is_new': bool(_new),
        })
    return [r for r in out if r['tx_hash']]


def group(trades, now=None, window_min=None):
    """Сделки -> сгруппированное по токену. -> {ключ: агрегат}. ЧИСТАЯ ФУНКЦИЯ, без сети.

    Ключ группы — (сеть, адрес контракта), а НЕ символ: однофамильцы с одним тикером в разных
    сетях — обычное дело, и склеив их по символу, мы сложили бы покупки двух разных токенов
    в одно «зажигание». Этот класс ошибки в проекте уже стоил трёх экранов подряд (LIT на
    Solana вместо Lighter).

    ПРИНИМАЕТ ДВЕ ФОРМЫ СТРОК: сырую из ответа провайдера и нашу из базы (`store.SMT_FIELDS`).
    Так сделано не ради удобства: окно теперь собирается ИЗ БАЗЫ (замер 26.09 - одна страница
    ленты покрывает 44 минуты против окна 180), но тесты и разовые замеры подают ответ напрямую,
    и раздваивать группировку ради этого значило бы проверять не тот код, который работает.
    """
    now = float(now if now is not None else time.time())
    win = float(window_min if window_min is not None else config.ign_window_min()) * 60.0
    out = {}
    for t in trades or []:
        # ДВЕ ФОРМЫ, ОДИН РАЗБОР: наши строки из базы уже нормализованы, сырые - нет.
        sym_raw = t.get('symbol') if 'symbol' in t else t.get('token_bought_symbol')
        sym, _new = assets.clean_symbol(sym_raw)
        addr = str(t.get('token_address') or t.get('token_bought_address') or '').strip()
        chain = str(t.get('chain') or '').strip().lower()
        if not addr or sym in QUOTE_SYMBOLS:
            continue
        ts = t.get('block_ts') if t.get('block_ts') is not None else _ts(t.get('block_timestamp'))
        ts = float(ts) if ts else None
        if ts is not None and (now - ts) > win:
            continue
        usd = _f(t.get('usd')) or _f(t.get('trade_value_usd')) or 0.0
        who_raw = str(t.get('trader') or t.get('trader_address') or '').strip()
        # ПОДСЧЁТ РАЗНЫХ АДРЕСОВ ИДЁТ ПО НОРМАЛИЗОВАННОМУ ВИДУ (один EVM-адрес бывает и в
        # checksum-виде, и без), а наружу уходит исходный - он нужен запросу связей.
        who = who_raw.lower()
        k = (chain, addr.lower())
        g = out.setdefault(k, {'chain': chain, 'address': addr, 'symbol': sym,
                               'wallets': set(), 'labels': [], 'usd': 0.0, 'trades': 0,
                               'mcap': None, 'age_days': None, 'last_ts': None,
                               'txs': set(), 'is_new': False,
                               # ОБЪЁМ ПО КАЖДОМУ АДРЕСУ. Нужен проверке связей (`clusters`):
                               # она смотрит не все адреса, а три САМЫХ КРУПНЫХ - именно они
                               # делают объём, и именно про них важно знать, не один ли это
                               # человек. Без этого поля «три самых крупных» было бы «три
                               # первых по алфавиту», то есть обещанием, которого код не держит.
                               'usd_by': {}})
        if who:
            g['wallets'].add(who)
            g['usd_by'][who] = g['usd_by'].get(who, 0.0) + usd
            g.setdefault('orig', {})[who] = who_raw
        lb = _meaningful(t.get('trader_label') or t.get('trader_address_label'))
        if lb and lb not in g['labels']:
            g['labels'].append(lb)
        g['usd'] += usd
        g['trades'] += 1
        g['txs'].add(str(t.get('tx_hash') or t.get('transaction_hash') or ''))
        mc = _f(t.get('mcap')) or _f(t.get('token_bought_market_cap'))
        if mc:
            g['mcap'] = mc if g['mcap'] is None else max(g['mcap'], mc)
        ad = t.get('age_days') if t.get('age_days') is not None else t.get('token_bought_age_days')
        ad = _f(ad)
        if ad is not None:
            g['age_days'] = ad if g['age_days'] is None else min(g['age_days'], ad)
        # НОВИЗНА - ИЗ ПОЛЯ ИЛИ ИЗ СИМВОЛА. Строки из базы приходят с чистым символом и флагом
        # `is_new`; сырые из ответа провайдера несут метку внутри символа. Оба пути обязаны дать
        # один ответ, иначе карточка теряет «новый токен» на живом пути и сохраняет в тесте.
        if _new or t.get('is_new'):
            g['is_new'] = True
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
    # ═══ МЕЙДЖОРЫ, СТЕЙБЛЫ, ОБЁРТКИ И ГИГАНТЫ ПО КАПИТАЛИЗАЦИИ - НЕ СОБЫТИЕ ═══
    # ЗАМЕР ВЛАДЕЛЬЦА 26.09: единственным токеном ленты, собравшим больше двух разных адресов,
    # оказался SOL - шесть адресов на $6412 при капитализации $1.48B, то есть 0.0 базисного
    # пункта. «Шесть умных кошельков купили солану» это не сигнал, это вторник.
    # ПОЧЕМУ РЕЕСТР ИМЁН РЯДОМ С ПОРОГОМ ПО КАПИТАЛИЗАЦИИ, А НЕ ВМЕСТО: капитализацию провайдер
    # даёт не всегда (в том же замере её нет у всех трёх новых токенов), и порог по ней молча не
    # срабатывал бы ровно там, где имя известно точно.
    _skip = assets.major_reason(agg.get('symbol'), mcap)
    if _skip:
        return None
    if n < config.ign_wallets() or usd < config.ign_usd():
        return None
    # ДОЛЯ ОТ КАПИТАЛИЗАЦИИ - ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ ТАМ, ГДЕ ОНА ИЗМЕРЕНА. Где не измерена -
    # событие остаётся, но платит штрафом и говорит об этом вслух: молча пропустить проверку
    # и молча её провалить должны выглядеть по-разному.
    if bps is not None and bps < config.ign_mcap_bps():
        return None
    from .detector import confidence
    pen = []
    # ═══ КАПИТАЛИЗАЦИЯ НЕИЗВЕСТНА - ЗВОНКА НЕТ, ЕСТЬ СВОДКА (решение владельца 26.09) ═══
    # Замер ленты: у токена SI шесть адресов на $43.8k, а капитализации провайдер не дал. Без неё
    # третий порог (доля рынка) не проверен: $44k по токену за $10B это шум, по токену за $3M -
    # половина рынка. Прежде такое событие звонило со штрафом -25, то есть непроверенный порог
    # подменялся уверенностью похуже (закон 41). Теперь звонит только то, что прошло ВСЕ ТРИ
    # порога; остальное едет в сводку с названной причиной.
    digest_only = None
    if mcap is None:
        digest_only = 'капитализация неизвестна, долю проверить нечем'
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
                        # МЕТКА НОВОГО ТОКЕНА ЕДЕТ В КАРТОЧКУ. Из ключей её срезали (иначе один
                        # токен жил бы под двумя именами), но человеку «токену ноль дней» это
                        # главное, что о нём известно.
                        'is_new': bool(agg.get('is_new')),
                        # ПРИЧИНА «ТОЛЬКО В СВОДКУ». Её читает `outbox.mute_reason`: событие
                        # целиком посчитано и записано, но будить им человека не за что.
                        'digest_only': digest_only,
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
    orig = agg.get('orig') or {}
    # ВТОРОЙ КЛЮЧ СОРТИРОВКИ - САМ АДРЕС: при равных объёмах порядок обязан быть устойчивым,
    # иначе один и тот же набор даёт разные ответы, и расследование расхождения невозможно.
    # НАРУЖУ - ИСХОДНЫЙ РЕГИСТР: эти адреса уходят в запрос связей (`clusters.check`).
    top = sorted(ws, key=lambda a: (-float(by.get(a) or 0.0), a))[:int(limit)]
    return [orig.get(a) or a for a in top]


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
    # ═══ ЛЕНТА ЕДЕТ В БАЗУ, И ОКНО СОБИРАЕТСЯ ИЗ БАЗЫ, А НЕ ИЗ ОТВЕТА ═══
    # ЗАМЕР ВЛАДЕЛЬЦА 26.09: одна страница (100 сделок) покрывает 44 МИНУТЫ, а окно зажигания -
    # 180. Пока агрегат строился по последнему ответу, порог «три разных адреса в одном токене
    # за три часа» проверялся по данным за три четверти часа и был недостижим ПРИ ЛЮБОМ ЧИСЛЕ:
    # истории между опросами не существовало, курсор помнил лишь «эту сделку я видел».
    # Опрос раз в 3 минуты при ленте 44 минуты даёт многократное перекрытие, поэтому догонять
    # страницами ничего не нужно - достаточно не выбрасывать то, что уже приехало.
    rows = rows_from_feed(trades)
    store.sm_trades_put(rows, feed='dex', now=now)
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
    # ОКНО СЧИТАЕМ ПО ВСЕЙ НАКОПЛЕННОЙ ЛЕНТЕ, А СОБЫТИЕ - ПО НОВЫМ СДЕЛКАМ. Иначе третий адрес,
    # зашедший через десять минут после первых двух, не увидел бы их вовсе: они уже «учтены», и
    # порог «три разных адреса» не собрался бы никогда. Поэтому агрегат строится по окну целиком,
    # а новизна решает только то, ЕСТЬ ЛИ ПОВОД пересчитать.
    win_s = int(config.ign_window_min()) * 60
    stored = store.sm_trades_window(now - win_s, feed='dex')
    groups = group(stored or rows, now=now)
    touched = {(str(t.get('chain') or '').lower(),
                str(t.get('token_bought_address') or '').lower()) for t in new}
    evs = []
    for k, agg in groups.items():
        if k not in touched:
            continue
        ev = judge(agg, now=now)
        if ev:
            evs.append(ev)
    # ЧЕСТНО ГОВОРИМ, ХВАТАЕТ ЛИ НАКОПЛЕННОГО НА ОКНО. Пока лента короче окна, ноль событий
    # означает «мерить ещё нечем», а не «рынок тихий» - и эти два ответа человек обязан
    # различать, иначе через сутки тишины он пойдёт искать поломку в пороге (ровно это и было).
    span_s, span_n = store.sm_trades_span('dex')
    note = 'новых сделок %d, событий %d' % (len(new), len(evs))
    if span_s < win_s:
        note += ('; лента накоплена за %d мин из %d нужных (%d сделок) - окно ещё неполное'
                 % (span_s // 60, win_s // 60, span_n))
    return evs, note


def scan_perp(now=None, fetch=None):
    """Круг СМАРТ-ПЕРПА: кто из умных адресов открывает одну сторону по одному токену.
    -> (events, note).

    ═══ ЗАЧЕМ ОТДЕЛЬНЫЙ ВИД РЯДОМ С ЗАЖИГАНИЕМ (ТЗ 1.7) ═══
    Зажигание видит покупку ТОКЕНА в сети, а дозорный смотрит за ПЕРПАМИ. Смарт-адрес, открывший
    лонг на Hyperliquid, не появляется в DEX-ленте вовсе - то есть самый близкий к нашему домену
    ончейн-сигнал раньше не читался ни одним видом.
    ПОРОГИ НИЖЕ, И ЭТО НЕ СМЯГЧЕНИЕ: два адреса и $250k по ОДНОЙ стороне за 30 минут - это уже
    согласованное действие, потому что на перпах вход виден сразу и повторяется редко.
    ХРАНЕНИЕ ТО ЖЕ, ЧТО У ЗАЖИГАНИЯ, И ПО ТОЙ ЖЕ ПРИЧИНЕ: одна страница ленты покрывает
    неизвестно какое время, а окно у нас своё. Мерить окно по ответу провайдера значит мерить
    его длину ленты.
    """
    now = int(now if now is not None else time.time())
    if fetch is None:
        def fetch():
            import nansen_api as _n
            with _tele.scene('sentinel_watch', None, surface='sentinel'):
                rows = _n.sm_perp_trades(per_page=100, live=True)
            store.spend_add(credits=_credits_guess(), events=0)
            return rows
    try:
        trades = fetch() or []
    except Exception as e:
        return [], 'лента смарт-перпов не прочитана: %s: %s' % (type(e).__name__, str(e)[:120])
    if not trades:
        return [], 'лента смарт-перпов пуста (отказ площадки или правда тишина)'
    rows = rows_from_feed(trades)
    # У ПЕРП-СДЕЛКИ КЛЮЧ ГРУППЫ - ТИКЕР И СТОРОНА, А НЕ КОНТРАКТ: контракта у перпа нет вовсе,
    # а сторона здесь и есть смысл события («двое зашли в лонг» против «один купил, другой
    # продал» - противоположные новости, которые без стороны слиплись бы в одну).
    store.sm_trades_put(rows, feed='perp', now=now)
    win_s = int(PERP_WINDOW_MIN) * 60
    stored = store.sm_trades_window(now - win_s, feed='perp') or rows
    agg = {}
    for r in stored:
        sym = str(r.get('symbol') or '').upper()
        side = str(r.get('side') or '').lower()
        who = str(r.get('trader') or '').lower()
        ts = r.get('block_ts')
        if not sym or side not in ('long', 'short', 'buy', 'sell') or not who:
            continue
        # ═══ СЧИТАЕМ ТОЛЬКО ВХОДЫ: OPEN И ADD (замер ленты 26.09) ═══
        # Из 100 перп-сделок одной страницы 25 - `Reduce`, то есть СОКРАЩЕНИЕ позиции, а не вход.
        # Поле `side` у них то же самое («Long»), и прежний код складывал их с входами: смарт-адрес,
        # фиксирующий прибыль по лонгу, считался «открывшим лонг». Это противоположная новость.
        # Строки без `action` (старые записи в базе) принимаются, как и раньше, чтобы не терять
        # накопленное окно; новые строки его несут всегда.
        _act = str(r.get('action') or '').lower()
        if _act and _act not in ('open', 'add'):
            continue
        if ts and (now - float(ts)) > win_s:
            continue
        side = {'buy': 'long', 'sell': 'short'}.get(side, side)
        g = agg.setdefault((sym, side), {'symbol': sym, 'side': side, 'wallets': set(),
                                         'labels': [], 'usd': 0.0, 'trades': 0,
                                         'usd_by': {}, 'last_ts': None, 'price': None})
        g['wallets'].add(who)
        _u = _f(r.get('usd')) or 0.0
        g['usd'] += _u
        g['usd_by'][who] = g['usd_by'].get(who, 0.0) + _u
        g['trades'] += 1
        lb = _meaningful(r.get('trader_label'))
        if lb and lb not in g['labels']:
            g['labels'].append(lb)
        _p = _f(r.get('price_usd'))
        if _p:
            g['price'] = _p
        if ts and (g['last_ts'] is None or float(ts) > g['last_ts']):
            g['last_ts'] = float(ts)
    evs = []
    for (sym, side), g in agg.items():
        n = len(g['wallets'])
        if n < PERP_WALLETS or g['usd'] < PERP_USD:
            continue
        # МЕЙДЖОР НА ПЕРПАХ - НОРМАЛЬНОЕ ДЕЛО, И ЭТО НЕ СОБЫТИЕ. Тот же реестр, что у зажигания:
        # BTC и ETH торгуют все и всегда, согласованности в этом нет.
        if assets.major_reason(sym) and sym in assets.MAJORS:
            continue
        from .detector import confidence, key, _window
        pen = []
        if not g['labels']:
            pen.append(('у адресов нет меток - «умные» здесь только по фильтру площадки', 10))
        lag = int(now - g['last_ts']) if g['last_ts'] else None
        if lag is not None and lag > 15 * 60:
            pen.append(('последняя сделка %d мин назад' % (lag // 60), 15))
        conf, notes = confidence(90, pen)
        step = max(1, int(n // PERP_WALLETS))
        evs.append({'kind': 'sm_perp', 'ticker': sym, 'ts': now,
                    'key': key('sm_perp', '%s:%s' % (sym, side), _window(now), step),
                    'severity': conf,
                    # ПЛОЩАДКА НАЗВАНА ЯВНО: лента `smart-money/perp-trades` - только
                    # Hyperliquid. Без этого поля фильтр площадки подставлял 'variational', и
                    # событие резалось у каждого, у кого Variational выключена (живой случай
                    # владельца 26.09: NEAR лонг трёх китов на $689k не дошёл).
                    'payload': {'symbol': sym, 'side': side, 'wallets': n,
                                'venue': 'hyperliquid',
                                'labels': list(g['labels'])[:6], 'usd': g['usd'],
                                'trades': g['trades'], 'price': g['price'],
                                'window_min': PERP_WINDOW_MIN, 'step': step, 'lag_s': lag,
                                'wallet_addrs': _top_wallets(g, 6), 'penalties': notes}})
    span_s, span_n = store.sm_trades_span('perp')
    note = 'перп-сделок %d, событий %d' % (len(stored), len(evs))
    if span_s < win_s:
        note += ('; лента накоплена за %d мин из %d нужных (%d сделок)'
                 % (span_s // 60, win_s // 60, span_n))
    return evs, note


#: ЦЕНА ВЫЗОВА В КРЕДИТАХ - ПО ОФИЦИАЛЬНОЙ СТРАНИЦЕ ЦЕН, ТОЙ ЖЕ, ЧТО У `nansen_log`. Где цена
#: не названа источником, в проекте пишут ноль и считают отдельной строкой; здесь названа (1-5
#: за структурный вызов), берём верхнюю границу - занижать свой же расход хуже, чем завысить.
_CREDITS_SM_DEX = 5


def _credits_guess():
    return _CREDITS_SM_DEX


#: ОКНО ОНЧЕЙН-КОНТЕКСТА ДЛЯ ЖИВОГО СОБЫТИЯ, ЧАСЫ. Три, а не сутки: контекст пятнадцати-
#: минутного движения обязан быть про последние часы. Замер 26.09 по WLD: суточный след
#: показывал $75k, реальный трёхчасовой - $2.1k, $912 и $880. Разбор в `nansen_api._date_range`.
CONFIRM_HOURS = 3


async def confirm(symbol, price, chain_hint=None, hours=None):
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
        _h = int(hours or CONFIRM_HOURS)
        out['hours'] = _h
        with _tele.scene('sentinel_ignition', None, surface='sentinel'):
            # ОКНО В ЧАСАХ И СВОЙ КОРОТКИЙ КЭШ: общий тридцатиминутный кэш превратил бы «сейчас»
            # в «раз в полчаса» - наблюдатель обязан видеть свежее, иначе он не наблюдатель.
            buys = await asyncio.to_thread(_n.tgm_who_bought_sold, ch, addr, 'BUY', 6, 1,
                                           _h, 20)
            sells = await asyncio.to_thread(_n.tgm_who_bought_sold, ch, addr, 'SELL', 6, 1,
                                            _h, 20)
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
