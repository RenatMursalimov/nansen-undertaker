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


#: РЕЕСТР ПЛОЩАДОК. `fetch=None` - площадка ОБЪЯВЛЕНА и ВЫКЛЮЧЕНА с причиной: список, в котором
#: молчаливо нет строки, читается как «про неё не думали».
VENUES = {
    'variational': {'title': 'Variational', 'fetch': var_fetch, 'why_off': None,
                    'url': 'https://omni.variational.io/'},
    'hyperliquid': {'title': 'Hyperliquid', 'fetch': hl_fetch, 'why_off': None,
                    'url': 'https://app.hyperliquid.xyz/trade'},
    # ПРИЧИНА ВЫКЛЮЧЕНИЯ - ДВУЯЗЫЧНАЯ, потому что она попадает НА ЭКРАН, а по экранам бота
    # ходит автоматический обходчик e2e и требует, чтобы на lang=en не было кириллицы.
    'lighter': {'title': 'Lighter', 'fetch': None,
                'why_off': 'у движка есть чтение позиций по адресу, а не список рынков; '
                           'ручка весит 300 и её просили не спамить',
                'why_off_en': 'the engine reads positions by address, not a market list; '
                              'that endpoint is heavy and we were asked not to spam it',
                'url': 'https://app.lighter.xyz/'},
}

#: ЧТО ВКЛЮЧЕНО ПО УМОЛЧАНИЮ. Variational - потому что проверена живьём; Hyperliquid - потому
#: что там 234 перпа с настоящим оборотом, то есть событий будет больше, а это ровно то, что
#: просил владелец («какие настройки выставить, чтобы побольше алертов словить»).
DEFAULT_VENUES = ('variational', 'hyperliquid')


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


def why_off(venue, lang='ru'):
    """Почему площадка выключена. -> str | None."""
    v = VENUES.get(venue) or {}
    return (v.get('why_off_en') if lang == 'en' else None) or v.get('why_off')


def title(venue):
    return (VENUES.get(venue) or {}).get('title') or venue


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
