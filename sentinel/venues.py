# -*- coding: utf-8 -*-
"""sentinel/venues.py — ПЛОЩАДКИ КАК ДАННЫЕ: одна таблица, один интерфейс, ноль правок в ядре.

ЗАЧЕМ. Просьба владельца: «разные площадки бы потестил и включил бы в настройки (Variational уже
работает, дальше бы HL, Lighter — у них все есть уже готовые движки у нас)». Ключевое здесь —
«готовые движки»: транспорт Hyperliquid и Lighter в проекте уже написан (`onchain/oc_perps.py`) и
используется бордом риска и перп-монитором. Второй фетчер к тем же ручкам был бы дублем
транспорта, то есть нарушением закона №40, и разъехался бы с первым на первой правке.

ПОЭТОМУ ЗДЕСЬ НЕ КЛИЕНТЫ, А ПЕРЕХОДНИКИ: каждая функция берёт то, что чужой движок уже отдаёт, и
приводит к `variational_feed.Listing` — единственной форме, которую понимают детектор, кольца и
карточка. Добавить площадку = добавить строку в `VENUES`; ни детектор, ни кольца, ни меню при
этом не правятся.

ИДЕНТИЧНОСТЬ ИНСТРУМЕНТА ТЕПЕРЬ ПАРНАЯ: «BTC» на Variational и «BTC» на Hyperliquid — РАЗНЫЕ
инструменты с разной ценой, спредом и фандингом. Ключ кольца и ключ события содержат площадку
(`hl:BTC`), иначе два рынка слиплись бы в один ряд и дали бы выдуманные «движения» на стыке.
Этот класс ошибки в проекте уже стоил трёх экранов (однофамильцы токенов), и повторять его на
площадках нельзя.

ЧЕГО ЗДЕСЬ НЕТ: ТОРГОВЛИ. Ни одна площадка не подключается ключом, ни одна функция не умеет
отправить ордер. Только публичное чтение — как и у всего дозорного.

СОСТОЯНИЕ ПЛОЩАДОК (замеры 25.09.2026):
  * variational — 553 инструмента одним GET, 283 КБ, 35-140 мс. Полный набор полей.
  * hyperliquid — 234 перпа одним POST (`metaAndAssetCtxs`), 72 КБ. Есть цена, объём 24ч,
    открытый интерес, фандинг и спред из `impactPxs`; НЕТ разбивки интереса на лонги и шорты -
    поля остаются пустыми, и карточка честно их не печатает.
  * lighter — ОТКЛЮЧЕНА НАМЕРЕННО. В `oc_perps` для неё есть чтение ПОЗИЦИЙ по адресу, а не
    список рынков, и докстринг там прямо предупреждает: ручка весит 300, «не спамить». Опрос
    раз в полминуты сжёг бы чужой лимит ради данных, которых у нас пока нет. Строка ниже
    оставлена с `None` и названной причиной: «площадки нет» и «площадка не сделана» - разные
    новости, и вторая должна быть видна в коде, а не жить в чьей-то памяти.
"""

import asyncio
import os
import sys

from .variational_feed import FeedError, Listing
from .variational_feed import fetch as _var_fetch

_ONCHAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'onchain')


def _oc_perps():
    """Общая дверь к чужому движку перпов. Свой транспорт не пишем (закон №40)."""
    if _ONCHAIN not in sys.path:
        sys.path.insert(0, _ONCHAIN)
    import oc_perps
    return oc_perps


async def var_fetch():
    """Variational Omni. -> (list[Listing], meta)."""
    rows, meta = await asyncio.to_thread(_var_fetch)
    for r in rows:
        r.venue = 'variational'
    meta['venue'] = 'variational'
    return rows, meta


async def hl_fetch():
    """Hyperliquid. -> (list[Listing], meta). Бросает FeedError, как и остальные площадки.

    ЧТО НЕ ПРИХОДИТ И ПОЧЕМУ ЭТО НЕ ЗАМАЛЧИВАЕТСЯ: `metaAndAssetCtxs` отдаёт открытый интерес
    ОДНИМ числом, без разбивки на лонги и шорты. Значит `oi_long`/`oi_short` остаются None, поле
    названо в `missing`, и карточка про перекос сторон просто молчит - вместо того чтобы нарисовать
    «лонгов 50%», чего никто не измерял.
    """
    oc = _oc_perps()
    uni = await oc.hl_universe()
    if not uni:
        # ПУСТО = ОТКАЗ, А НЕ «РЫНОК ЗАМЕР». Чужой движок глотает исключение и отдаёт {}, поэтому
        # различить мы можем только здесь - и обязаны, иначе пустота станет утверждением о рынке.
        raise FeedError('net', 'hyperliquid: пустой ответ (движок вернул {})')
    out = []
    for tick, d in uni.items():
        mark = d.get('mark')
        if not mark:
            continue
        out.append(Listing(
            ticker=str(tick).upper(), name=str(tick).upper(),
            mark=mark, volume_24h=d.get('vol24'),
            oi_long=None, oi_short=None,
            funding_raw=d.get('funding'),
            # ИНТЕРВАЛ ФАНДИНГА У HYPERLIQUID - ЧАС, И ЭТО ДОКА, А НЕ ДОГАДКА: их фандинг
            # начисляется ежечасно, поле `funding` - ставка за час.
            funding_interval_s=3600,
            spread_bps=d.get('spread_bps'),
            quote_ts=None,
            quotes={},
            missing=tuple(n for n, v in (('oi_long/oi_short', None),
                                         ('quotes', None),
                                         ('base_spread_bps', d.get('spread_bps'))) if not v)))
        out[-1].venue = 'hyperliquid'
        # ОТКРЫТЫЙ ИНТЕРЕС КЛАДЁМ В ОДНУ СТОРОНУ НЕ МОЛЧА: детектор считает скачок по СУММЕ
        # сторон, и положить весь интерес в `oi_long` значило бы соврать про перекос. Кладём в
        # отдельное поле и говорим об этом в `missing` выше.
        out[-1].oi_total_raw = d.get('oi_base')
    if not out:
        raise FeedError('shape', 'hyperliquid: ни одной строки с ценой')
    return out, {'venue': 'hyperliquid', 'num_markets': len(out), 'fetched_at': None}


# ══════════════════════════════════════════════════════════════════════════════════════════
# LIGHTER: ДОЛГ ЗАКРЫТ ЗАМЕРОМ, А НЕ РЕШЕНИЕМ «НЕ БЕРЁМ»
#
# ПРЕЖНЯЯ ПРИЧИНА ВЫКЛЮЧЕНИЯ БЫЛА ВЕРНОЙ ПО ФАКТУ И ЛЕНИВОЙ ПО МЕТОДУ - в точности как долг по
# ссылке на инструмент двумя кругами раньше. Записано было: «у движка есть чтение позиций по
# адресу, а не список рынков; ручка весит 300 и её просили не спамить». Всё это правда про
# `oc_perps`, но вывод «значит площадку взять нельзя» из этого не следует: у Lighter есть
# ПУБЛИЧНЫЙ REST, и его надо было просто попробовать.
#
# ЗАМЕР 26.09 (три запроса curl, ни одного ключа):
#   * `/api/v1/orderBookDetails` -> 200, 370 КБ, 22 мс, 235 рынков. Есть `mark_price`,
#     `index_price`, `last_trade_price`, `daily_quote_token_volume` (оборот 24ч В ДОЛЛАРАХ),
#     `open_interest` (в базовом активе), `daily_price_change`, `daily_trades_count`, `status`.
#   * `/api/v1/orderBooks` -> 200, 167 КБ: то же без суточных чисел, нам не нужно.
#   * `/api/v1/funding-rates` -> 200, 52 КБ: ставки ПО НЕСКОЛЬКИМ БИРЖАМ в одном ответе
#     (поле `exchange`: binance 195 строк, bybit 197, hyperliquid 135, lighter 210).
#
# ОДИН GET НА ВСЕ 235 РЫНКОВ - то есть темп опроса тот же, что у двух других площадок, и
# «не спамить» соблюдено буквально: 2 запроса за тик против 235.
#
# ЧЕГО У ПЛОЩАДКИ НЕТ И ЧТО МЫ НЕ ВЫДУМЫВАЕМ: разбивки открытого интереса на лонги и шорты
# (как и у Hyperliquid) и котировок на объём. Оба поля идут в `missing`, и карточка про них
# молчит - вместо того чтобы нарисовать «лонгов 50%», чего никто не мерил.
# ══════════════════════════════════════════════════════════════════════════════════════════
LG_BASE = os.getenv('SENTINEL_LG_BASE') or 'https://mainnet.zklighter.elliot.ai'


def _lg_get(path, timeout=20):
    """GET к публичному REST Lighter. -> распарсенный JSON. Бросает FeedError.

    СВОЙ МАЛЕНЬКИЙ GET, А НЕ ВТОРОЙ КЛИЕНТ. Закон №40 запрещает дубль ТРАНСПОРТА к одной и той
    же ручке; здесь ручка НОВАЯ - в `oc_perps` её нет вовсе (там чтение позиций по адресу).
    Форма запроса та же, что у `variational_feed.fetch`, чтобы отказы выглядели одинаково.
    """
    import json as _json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(LG_BASE + path,
                                 headers={'User-Agent': _UA, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
            raw = resp.read()
            code = getattr(resp, 'status', 200) or 200
    except urllib.error.HTTPError as e:
        raise FeedError('http', 'lighter %s: HTTP %s' % (path, e.code), http=e.code)
    except Exception as e:
        raise FeedError('net', 'lighter %s: %s: %s' % (path, type(e).__name__, str(e)[:90]))
    if code != 200:
        raise FeedError('http', 'lighter %s: HTTP %s' % (path, code), http=code)
    try:
        return _json.loads(raw.decode('utf-8', 'replace')), len(raw)
    except Exception as e:
        raise FeedError('json', 'lighter %s: %s' % (path, str(e)[:90]))


#: User-Agent берём тот же, что у Variational: пустой UA там давал 403 (замер), и привычка
#: ходить без него однажды стоила бы круга и здесь.
_UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/131.0.0.0 Safari/537.36')

#: ЕДИНИЦА ФАНДИНГА LIGHTER - ВЫВЕДЕНА СВЕРКОЙ, А НЕ ВЗЯТА ИЗ ДОКИ (её там нет).
#: ЗАМЕР 26.09: в ленте `/funding-rates` есть строки `exchange=hyperliquid` - то есть
#: ПЕРЕСКАЗ площадки, чья единица нам известна документально (доля за ЧАС). Отношение этих
#: строк к нашему собственному чтению Hyperliquid дало РОВНО 8.000 на 95 из 95 общих пар
#: (100% в пределах x0.5..x2 от медианы). Значит Lighter публикует долю за 8 ЧАСОВ.
#: Для сравнения: собственные строки `exchange=lighter` дали медиану 7.68 с широким разбросом -
#: это уже настоящая рыночная разница между площадками, а не единица измерения. Разделять эти
#: два числа важно: первое - калибровка, второе - рынок.
LG_FUNDING_INTERVAL_S = 8 * 3600


async def lg_fetch():
    """Lighter. -> (list[Listing], meta). Бросает FeedError, как и остальные площадки."""
    det, n1 = await asyncio.to_thread(_lg_get, '/api/v1/orderBookDetails')
    rows = (det or {}).get('order_book_details') or []
    if not rows:
        # ПУСТО = ОТКАЗ, А НЕ «РЫНОК ЗАМЕР»: тот же закон, что у двух других площадок.
        raise FeedError('shape', 'lighter: order_book_details пуст')
    # ФАНДИНГ - ВТОРЫМ ЗАПРОСОМ, И ЕГО ОТКАЗ НЕ РОНЯЕТ ЦЕНЫ. Ставка это ОДНО поле из
    # двенадцати; уронив из-за неё весь снимок, мы потеряли бы 235 рынков ради одной колонки.
    fund, n2 = {}, 0
    try:
        fr, n2 = await asyncio.to_thread(_lg_get, '/api/v1/funding-rates')
        for r in (fr or {}).get('funding_rates') or []:
            # ТОЛЬКО СВОИ СТРОКИ. В ответе лежат ставки binance/bybit/hyperliquid - это
            # СПРАВОЧНАЯ лента площадки, и взять чужую ставку за свою значило бы показать
            # человеку фандинг биржи, на которой он не стоит.
            if str(r.get('exchange') or '').lower() == 'lighter':
                fund[str(r.get('symbol') or '').upper()] = r.get('rate')
    except FeedError as e:
        print('[sentinel] lighter: ставки не прочитаны (%s) - цены и объёмы беру' % e)
    out = []
    for d in rows:
        if str(d.get('status') or '').lower() != 'active' or d.get('is_frozen'):
            # ЗАМОРОЖЕННЫЙ РЫНОК В ДОЗОР НЕ БЕРЁМ: цена там стоит по причине площадки, а не
            # рынка, и «движения» на разморозке были бы выдуманными.
            continue
        t = str(d.get('symbol') or '').upper()
        mark = _f(d.get('mark_price'))
        if not t or not mark:
            continue
        # ОТКРЫТЫЙ ИНТЕРЕС ПЛОЩАДКА ОТДАЁТ В БАЗОВОМ АКТИВЕ - переводим в доллары марк-ценой,
        # иначе 3 010 044 контрактов STBL и 86 контрактов DELL сравнивались бы как числа.
        _oi = _f(d.get('open_interest'))
        lst = Listing(
            ticker=t, name=t, mark=mark,
            volume_24h=_f(d.get('daily_quote_token_volume')),
            oi_long=None, oi_short=None,
            funding_raw=_f(fund.get(t)),
            funding_interval_s=(LG_FUNDING_INTERVAL_S if t in fund else 0),
            # СПРЕДА ПЛОЩАДКА В ЭТОЙ РУЧКЕ НЕ ДАЁТ. `mark - index` это НЕ спред (это базис), и
            # подставить его значило бы назвать одно другим - ровно та подмена, от которой
            # карточка защищается словом `raw` в имени поля фандинга.
            spread_bps=None,
            quote_ts=None, quotes={},
            missing=tuple(n for n, v in (('oi_long/oi_short', None),
                                         ('quotes', None),
                                         ('base_spread_bps', None),
                                         ('funding_rate', fund.get(t))) if not v))
        lst.venue = 'lighter'
        lst.oi_total_raw = (_oi * mark) if _oi else None
        out.append(lst)
    if not out:
        raise FeedError('shape', 'lighter: ни одной активной строки с ценой')
    return out, {'venue': 'lighter', 'num_markets': len(out), 'bytes': n1 + n2,
                 'fetched_at': None}


def _f(x):
    """Число из строки/числа. -> float | None. Площадка отдаёт часть чисел СТРОКАМИ."""
    if x is None or x == '':
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None          # NaN отсекаем: он пролез бы во все сравнения


#: РЕЕСТР ПЛОЩАДОК. `fetch=None` - площадка ОБЪЯВЛЕНА и ВЫКЛЮЧЕНА с причиной: список, в котором
#: молчаливо нет строки, читается как «про неё не думали».
VENUES = {
    'variational': {'title': 'Variational', 'fetch': var_fetch, 'why_off': None,
                    'url': 'https://omni.variational.io/'},
    'hyperliquid': {'title': 'Hyperliquid', 'fetch': hl_fetch, 'why_off': None,
                    'url': 'https://app.hyperliquid.xyz/trade'},
    # ПРИЧИНА ВЫКЛЮЧЕНИЯ - ДВУЯЗЫЧНАЯ, потому что она попадает НА ЭКРАН, а по экранам бота
    # ходит автоматический обходчик e2e и требует, чтобы на lang=en не было кириллицы.
    # ВКЛЮЧЕНА В КРУГЕ 9 ПО ЗАМЕРУ. Прежняя причина выключения («у движка нет списка рынков»)
    # была правдой про `oc_perps` и неправдой про площадку: публичный REST отдаёт 235 рынков
    # одним GET. Разбор - во врезке выше.
    'lighter': {'title': 'Lighter', 'fetch': lg_fetch, 'why_off': None,
                'url': 'https://app.lighter.xyz/'},
}

#: ЧТО ВКЛЮЧЕНО ПО УМОЛЧАНИЮ. Все три площадки проверены живыми запросами: Variational (553
#: инструмента), Hyperliquid (234 перпа), Lighter (235 рынков). Больше площадок - больше
#: событий и, главное, больше РАСХОЖДЕНИЙ между ними: третий источник цены превращает сверку
#: из «один против одного» (кто из двух прав - неизвестно) в «двое против одного».
DEFAULT_VENUES = ('variational', 'hyperliquid', 'lighter')


def enabled():
    """Площадки, включённые окружением. -> tuple. Мусор в переменной -> дефолт + строка в лог."""
    raw = (os.getenv('SENTINEL_VENUES') or '').strip()
    if not raw:
        return tuple(DEFAULT_VENUES)
    got = tuple(v.strip().lower() for v in raw.split(',') if v.strip() in VENUES)
    if not got:
        print('[sentinel] SENTINEL_VENUES=%r не содержит известных площадок - беру дефолт' % raw)
        return tuple(DEFAULT_VENUES)
    return got


def live():
    """Площадки, которые реально умеют отдать список рынков. -> tuple."""
    return tuple(v for v in enabled() if (VENUES.get(v) or {}).get('fetch'))


def key(venue, ticker):
    """Ключ инструмента В КОЛЬЦЕ И В СОБЫТИИ. -> 'venue:TICKER'.

    Пара, а не тикер: «BTC» на двух площадках - разные инструменты с разной ценой и спредом, и
    один ряд на двоих дал бы выдуманные скачки на каждом переключении источника.
    """
    return '%s:%s' % (venue, str(ticker or '').upper())


def split(k):
    """'venue:TICKER' -> (venue, TICKER). Ключ без площадки считаем Variational: так выглядят
    строки, записанные до появления второй площадки, и терять их историю незачем."""
    s = str(k or '')
    if ':' in s:
        v, _, t = s.partition(':')
        if v in VENUES:
            return v, t
    return 'variational', s


# ══════════════════════════════════════════════════════════════════════════════════════════
# ЕДИНИЦА ФАНДИНГА: ДОЛГ ВЕРИФИКАЦИИ №1 ЗАКРЫТ ЗАМЕРОМ (26.09.2026)
#
# ДЕВЯТЬ КРУГОВ ЧИСЛО ЕХАЛО В КАРТОЧКУ ПОД ИМЕНЕМ ПОЛЯ ПРОВАЙДЕРА («поле funding_rate:
# 0.1095»), и это было правильно: единица не была названа ни докой, ни замером, а назвать
# проценты процентами, не измерив, значит выдумать человеку цифру, по которой он считает деньги.
# Гипотеза в шапке `variational_feed` звучала «похоже на годовые проценты» - и оказалась БЛИЗКОЙ,
# НО НЕВЕРНОЙ: это годовая ДОЛЯ, а не проценты (0.4427 = 44.27% годовых, а не 0.44%).
#
# ЧЕМ ИЗМЕРЕНО (инструмент `tools/sentinel_funding_unit.py`, воспроизводится одной командой):
#  ШАГ 1, КАЛИБРОВКА МЕТОДА НА ИЗВЕСТНОМ ОТВЕТЕ. В ленте Lighter `/funding-rates` есть строки
#    `exchange=hyperliquid` - пересказ площадки, чья единица ДОКУМЕНТИРОВАНА (доля за час).
#    Сверка с нашим собственным чтением Hyperliquid дала РОВНО ×8.0000 на 95 из 95 пар (100% в
#    узком облаке) - то есть метод воспроизводит заранее известный ответ.
#  ШАГ 2, СУД. Медиана |Variational / HL за тот же интервал| = 2190.00 на 93 парах.
#  ШАГ 3, ПРОВЕРКА, КОТОРУЮ ПОДГОНКА НЕ ПРОЙДЁТ. Гипотеза «годовая ставка» предсказывает для
#    каждой группы инструментов СВОЁ число (интервалов в году), и совпасть должны ОБЕ:
#      4-часовые: медиана 2190.00 против предсказанных 2190.00 - мимо в 1.0000 раза;
#      8-часовые: медиана 1046.03 против предсказанных 1095.00 - мимо в 1.047 раза.
#    Одна подогнанная константа обе группы объяснить НЕ МОЖЕТ. Значит единица измерена.
#  ПРОВЕРКА ЗДРАВЫМ СМЫСЛОМ (она тоже часть замера): ETH 10.95% годовых, BTC 1.36%, XAU 5.19%,
#    US500 ноль - правдоподобные ставки. И справка площадки «0.005% за 8-часовой интервал» даёт
#    0.005% × 1095 = 5.48% годовых, то есть ТОТ ЖЕ порядок: справка не противоречила замеру, она
#    просто говорила о другом (о фиксированной ставке RWA), а мы читали её как противоречие.
#
# ЗАЧЕМ ЕДИНИЦА ЗДЕСЬ, А НЕ В КАРТОЧКЕ: площадок три, у каждой своя, и знание об этом обязано
# жить РЯДОМ С ПЛОЩАДКОЙ. Иначе карточка, детектор и отчёт завели бы по своей копии, и первая же
# новая площадка развела бы их.
# ══════════════════════════════════════════════════════════════════════════════════════════
_YEAR_S = 365 * 24 * 3600

#: КАК ПОНИМАТЬ `funding_raw` КАЖДОЙ ПЛОЩАДКИ. Значение - («что это», источник знания).
#: Источник пишем ВСЛУХ: «дока» и «замер» - разной прочности, и через месяц это различие
#: понадобится тому, кто будет спорить с числом на экране.
FUNDING_UNIT = {
    # 0.1095 = 10.95% годовых. Измерено сверкой (см. врезку).
    'variational': ('apr_fraction', 'замер 26.09: сверка с Hyperliquid, две группы интервалов'),
    # Доля за ЧАС - документировано площадкой, фандинг начисляется ежечасно.
    'hyperliquid': ('interval_fraction', 'дока площадки: начисление ежечасно'),
    # Доля за 8 часов - выведено тем же методом (×8.000 на 95 из 95 пар).
    'lighter': ('interval_fraction', 'замер 26.09: пересказ HL в их же ленте дал ровно x8'),
}


def funding_apr_pct(venue, funding_raw, interval_s):
    """Фандинг в ГОДОВЫХ ПРОЦЕНТАХ. -> float | None (None = единица неизвестна).

    None - ПОЛНОПРАВНЫЙ ОТВЕТ, а не «ноль»: у новой площадки единицы может не быть, и тогда
    карточка обязана показать сырое поле с его именем, а не нарисовать «0% годовых». Ровно та
    дисциплина, которая девять кругов держала это число незаявленным.
    """
    kind = (FUNDING_UNIT.get(venue) or (None, None))[0]
    if kind is None or funding_raw is None:
        return None
    try:
        v = float(funding_raw)
    except (TypeError, ValueError):
        return None
    if kind == 'apr_fraction':
        # УЖЕ ГОДОВАЯ ДОЛЯ - интервал не нужен вовсе, и это важно: умножив её на число
        # интервалов «для приведения», мы завысили бы ставку в тысячу раз.
        return v * 100.0
    if kind == 'interval_fraction':
        if not interval_s:
            return None
        return v * (_YEAR_S / float(interval_s)) * 100.0
    return None


def funding_unit_note(venue, lang='ru'):
    """Откуда мы знаем единицу этой площадки. -> str | ''. Для карточки и справки."""
    src = (FUNDING_UNIT.get(venue) or (None, None))[1]
    if not src:
        return ''
    return src if lang != 'en' else {
        'variational': 'measured 26.09 by cross-check against Hyperliquid, two interval groups',
        'hyperliquid': 'documented by the venue: hourly accrual',
        'lighter': 'measured 26.09: their own feed restates HL at exactly x8',
    }.get(venue, src)


def why_off(venue, lang='ru'):
    """Почему площадка выключена. -> str | None."""
    v = VENUES.get(venue) or {}
    return (v.get('why_off_en') if lang == 'en' else None) or v.get('why_off')


def title(venue):
    return (VENUES.get(venue) or {}).get('title') or venue


#: ПУТЬ К ИНСТРУМЕНТУ. ИЗМЕРЕН 25.09 БРАУЗЕРОМ, а не угадан: открытие корня с параметром
#: `?market=ENA` САМО перебросило на `/perpetual/BTC`, и заголовок страницы стал
#: «BTC PERP | Variational Omni». Дальше проверено пятью тикерами разных классов (BTC, ENA,
#: MSTR, XAU, US500) - все 200, и заголовок называет нужный инструмент.
#: ПОЧЕМУ ЭТОГО НЕ НАШЛОСЬ РАНЬШЕ: я пробовал `/trade/<T>` и `/markets/<T>` (оба 403) и
#: сделал вывод «формат не измерен». Вывод был верным по факту и ленивым по методу: у
#: одностраничного приложения путь видно из САМОГО приложения, и один запуск браузера
#: закрыл вопрос, который три круга стоял долгом. Урок: «403 на двух путях» не равно
#: «прямой ссылки нет» - ровно как «404» в этом проекте уже не значило «фичи нет».
#: LIGHTER: `/trade/<TICKER>` - ИЗМЕРЕНО БРАУЗЕРОМ 26.09, И ТОЛЬКО ИМ.
#: Сначала пять путей проверены обычным GET: `/trade/BTC`, `/perps/BTC`, `/market/BTC`,
#: `/trade?market=BTC`, `/BTC` - ВСЕ вернули 200 и РОВНО 9920 байт с заголовком «Lighter».
#: То есть одностраничное приложение отдаёт один и тот же каркас на любой путь, и код 200 не
#: доказывает НИЧЕГО - тот же капкан, что уже описан выше про `?market=` у Variational.
#: Доказательство дал только браузер: после отрисовки заголовок страницы становится
#: «2,701.35 • ETH • Lighter», то есть называет ИМЕННО запрошенный инструмент и его цену.
#: Проверено четырьмя тикерами разных классов: ETH, BTC (84,130.8), XRP (1.589066),
#: PAXG (4,275.45) - каждый назвал себя.
#: УРОК, КОТОРЫЙ ДОРОЖЕ САМОЙ СТРОКИ: у SPA «200 на пути» и «путь работает» - разные
#: утверждения, и различить их можно только исполнив страницу.
_MARKET_PATH = {'variational': 'https://omni.variational.io/perpetual/%s',
                'hyperliquid': 'https://app.hyperliquid.xyz/trade/%s',
                'lighter': 'https://app.lighter.xyz/trade/%s'}


def market_url(venue, ticker):
    """Прямая ссылка на инструмент. -> str | None.

    None, А НЕ КОРЕНЬ ПЛОЩАДКИ: если формат для площадки не измерен, честнее дать ссылку на
    площадку целиком (это делает вызывающий), чем подсунуть путь, который может вести в
    никуда в момент, когда человек спешит.
    """
    tpl = _MARKET_PATH.get(venue)
    t = str(ticker or "").strip().upper()
    if not tpl or not t:
        return None
    return tpl % t


def url(venue):
    return (VENUES.get(venue) or {}).get('url') or ''


async def fetch_all(venues=None):
    """Опрос всех включённых площадок. -> (list[Listing], {venue: meta|FeedError}).

    ОДНА ПЛОЩАДКА НЕ РОНЯЕТ ОСТАЛЬНЫЕ. Отказ каждой сохраняется ПОИМЁННО: «Hyperliquid молчит»
    и «дозорный сломался» - разные новости, и первую человек должен увидеть отдельной строкой.
    """
    out, notes = [], {}
    for v in (venues or live()):
        fn = (VENUES.get(v) or {}).get('fetch')
        if not fn:
            continue
        try:
            rows, meta = await fn()
            out += rows
            notes[v] = meta
        except FeedError as e:
            notes[v] = e
        except Exception as e:                    # noqa: BLE001
            notes[v] = FeedError('net', '%s: %s' % (type(e).__name__, str(e)[:100]))
    return out, notes
