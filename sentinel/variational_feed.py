# -*- coding: utf-8 -*-
"""sentinel/variational_feed.py — ОДНА публичная ручка Variational Omni -> список инструментов.

ЧТО ЧИТАЕМ И ПОЧЕМУ ИМЕННО ЭТО
`GET /metadata/stats` отдаёт ВЕСЬ рынок одним ответом. Живая проба 25.09.2026: HTTP 200,
283 КБ, 553 инструмента, 0.05с. То есть «дозор за всей площадкой» стоит ОДИН запрос, и
опрашивать по инструменту (553 запроса) не нужно вовсе — иначе лимит 10 запросов/10с с
адреса (ДОКА docs.variational.io/technical-documentation/api) кончился бы на первом тике.

ПОЧЕМУ ЗДЕСЬ UA-ЗАГОЛОВОК, А НЕ «CLOUDFLARE РЕЖЕТ ОТПЕЧАТОК»
Первый заход голым urllib дал 403, и напрашивался вывод «нужен curl_cffi/impersonation».
ЗАМЕР опроверг: тот же urllib с обычным `User-Agent` даёт 200 за 0.05с. Ручке не нужен ни
подложный TLS-отпечаток, ни прокси — ей нужен непустой UA. Вывод записан здесь, а не в
голове: без строки следующий разбор снова пойдёт в сторону отпечатка (этот ложный след в
проектах уже стоил круга разбора).

ПОЧЕМУ urllib, А НЕ httpx, КОТОРЫМ ХОДИТ ВЕСЬ БОТ
Запрос один, без ключей, без ретраев сложной формы — httpx здесь не даёт ничего, зато тянет
зависимость в тесты дозорного. Тик и так живёт в `asyncio.to_thread`, так что блокирующий
клиент никому не мешает.

ЧЕГО ЗДЕСЬ НЕТ: ВЫВОДОВ. Модуль ничего не считает и ни о чём не судит — только приводит
строки провайдера к числам и честно говорит, чего в ответе не было. Все пороги и все
решения — в `detector.py`.

ЕДИНИЦА ФАНДИНГА У НАС НЕ ЗАЯВЛЕНА, И ЭТО СОЗНАТЕЛЬНО (долг верификации №1)
Провайдер отдаёт `funding_rate` без единицы, и два его же источника противоречат замеру:
справка говорит «RWA/TradFi фиксировано 0.005% за 8-часовой интервал»
(help.variational.io/en/articles/16038203), а в живом ответе у MRNA стоит 0.442690, у MSTR
0.455416, у US500 ноль. Ни «процент за интервал», ни «0.005 фикс» замеру не соответствуют;
похоже на годовые проценты, но ПОХОЖЕ — не замер. Поэтому число едет в карточку под ИМЕНЕМ
ПОЛЯ ПРОВАЙДЕРА и вместе с интервалом, приведения к годовым НЕТ, а события по фандингу
ловятся распределением инструмента относительно САМОГО СЕБЯ (проценти́ль по нашему кольцу) —
такой критерий не зависит от единицы вовсе.
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

#: База читается из окружения ровно для одного: подменить её в тесте на локальный фикстур-URL
#: и прогнать разбор на настоящем теле ответа, не выходя в сеть.
BASE = (os.getenv('SENTINEL_VAR_BASE')
        or 'https://omni-client-api.prod.ap-northeast-1.variational.io').rstrip('/')
STATS_PATH = '/metadata/stats'

#: НЕПУСТОЙ UA — ЕДИНСТВЕННОЕ ТРЕБОВАНИЕ РУЧКИ (замер выше). Не маскируемся под браузер ради
#: обхода защиты: строка называет нас и даёт площадке кого позвать, если мы мешаем.
UA = (os.getenv('SENTINEL_VAR_UA')
      or 'Mozilla/5.0 (compatible; UndertakerSentinel/1.0; +telegram bot, read-only)')

TIMEOUT = float(os.getenv('SENTINEL_VAR_TIMEOUT') or 20)


class FeedError(Exception):
    """Отказ фида С ИМЕНЕМ КЛАССА, а не просто текстом.

    Класс отказа едет на экран человеку и в телеметрию: «дозорный молчит» и «площадка не
    отвечает» — разные новости, и различить их должен уметь тот, кто читает карточку, а не
    только тот, у кого есть ssh.
    """

    def __init__(self, kind, detail='', http=0):
        self.kind = kind          # 'http' | 'net' | 'json' | 'shape'
        self.detail = str(detail)[:200]
        self.http = int(http or 0)
        super().__init__('%s: %s' % (kind, self.detail))


def _num(v):
    """Строка провайдера -> float | None. Провайдер отдаёт ВСЕ числа строками (ЗАМЕР)."""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts(iso):
    """'2026-09-25T00:23:32.422937751Z' -> epoch | None.

    ДРОБНАЯ ЧАСТЬ У ПРОВАЙДЕРА НАНОСЕКУНДНАЯ (9 знаков), и `datetime.fromisoformat` на таком
    падает в версиях до 3.11. Обрезаем до микросекунд руками: возраст котировки — величина,
    от которой зависит отправка события, и терять её из-за трёх лишних цифр нельзя.
    """
    if not iso:
        return None
    s = str(iso).strip().replace('Z', '+00:00')
    if '.' in s:
        head, _, tail = s.partition('.')
        # ДРОБНУЮ ЧАСТЬ БЕРЁМ ПОДРЯД ИДУЩИМИ ЦИФРАМИ, А НЕ «ВСЕМИ ЦИФРАМИ ХВОСТА». Первая
        # редакция фильтровала `isdigit` по всему хвосту и склеивала наносекунды со смещением
        # зоны ('422937751' + '0000'), после чего `fromisoformat` падал, возраст котировки
        # выходил None — и штраф за свежесть НИКОГДА не срабатывал. Дефект тихий: карточка
        # печаталась, поле возраста просто молчало.
        i = 0
        while i < len(tail) and tail[i].isdigit():
            i += 1
        frac, rest = tail[:i], tail[i:]
        s = '%s.%s%s' % (head, (frac[:6] or '0'), rest)
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


@dataclass
class Listing:
    """Инструмент площадки в наших единицах. Ни одного посчитанного вывода — только замеры."""
    ticker: str
    name: str = ''
    mark: float = None
    volume_24h: float = None
    oi_long: float = None
    oi_short: float = None
    funding_raw: float = None         # ИМЕННО raw: единица провайдером не названа (см. шапку)
    funding_interval_s: int = 0
    spread_bps: float = None
    quote_ts: float = None
    quotes: dict = field(default_factory=dict)   # {'base': (bid, ask), 'size_1k': …}
    missing: tuple = ()                # чего в ответе не было — поимённо, а не «данных нет»
    #: ПЛОЩАДКА В САМОМ ИНСТРУМЕНТЕ. Появилась вместе со второй площадкой: «BTC» на
    #: Variational и «BTC» на Hyperliquid - РАЗНЫЕ рынки с разной ценой и спредом, и без
    #: этого поля они слиплись бы в один ряд кольца, породив выдуманные «движения» на
    #: каждом переключении источника.
    venue: str = 'variational'
    #: ОТКРЫТЫЙ ИНТЕРЕС ОДНИМ ЧИСЛОМ - для площадок, которые не разбивают его на стороны
    #: (Hyperliquid). Положить весь интерес в `oi_long` значило бы соврать про перекос.
    oi_total_raw: float = None

    @property
    def oi_total(self):
        a, b = self.oi_long, self.oi_short
        if a is None and b is None:
            return self.oi_total_raw
        return (a or 0.0) + (b or 0.0)

    @property
    def oi_skew(self):
        """Доля лонгов в открытом интересе, 0..1. None — если сторон нет или интерес нулевой."""
        tot = self.oi_total
        if not tot:
            return None
        return (self.oi_long or 0.0) / tot

    def quote_age(self, now=None):
        if self.quote_ts is None:
            return None
        return max(0.0, (now if now is not None else time.time()) - self.quote_ts)

    def depth_bps(self, size='size_100k'):
        """Полуспред на заданный объём, б.п. от середины. None — если такой котировки нет.

        ЗАЧЕМ ОТДЕЛЬНО ОТ `spread_bps`. Базовый спред — цена сделки на копейку; человек же
        заходит на сумму, и по 18 инструментам из 553 площадка вообще котирует объём $1M, а
        по остальным — нет. «Ёмкость есть» и «ёмкость такая-то» — разные утверждения.
        """
        q = (self.quotes or {}).get(size)
        if not q:
            return None
        bid, ask = q
        if not bid or not ask or (bid + ask) <= 0:
            return None
        mid = (bid + ask) / 2.0
        return (ask - bid) / 2.0 / mid * 10000.0


def parse(payload):
    """Тело ответа -> (list[Listing], meta). Бросает FeedError('shape') на чужой форме."""
    if not isinstance(payload, dict):
        raise FeedError('shape', 'ответ не объект: %s' % type(payload).__name__)
    rows = payload.get('listings')
    if not isinstance(rows, list) or not rows:
        raise FeedError('shape', 'listings пуст или не список')
    meta = {'total_volume_24h': _num(payload.get('total_volume_24h')),
            'open_interest': _num(payload.get('open_interest')),
            'tvl': _num(payload.get('tvl')),
            'num_markets': payload.get('num_markets'),
            'fetched_at': time.time()}
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get('ticker'):
            continue
        oi = r.get('open_interest') or {}
        q = r.get('quotes') or {}
        quotes = {}
        for k in ('base', 'size_1k', 'size_100k', 'size_1m'):
            side = q.get(k) or {}
            bid, ask = _num(side.get('bid')), _num(side.get('ask'))
            if bid is not None and ask is not None:
                quotes[k] = (bid, ask)
        # ЧЕГО НЕ ХВАТИЛО — СПИСКОМ ИМЁН. Живая проба: у одного инструмента из 553 нет ни
        # `quotes`, ни `base_spread_bps`, а `size_1m` есть лишь у 18. Отсутствие поля это
        # НЕ ноль: ноль спреда означал бы идеальную книгу, чего не бывает.
        miss = [k for k, v in (('mark_price', r.get('mark_price')),
                               ('quotes', q or None),
                               ('base_spread_bps', r.get('base_spread_bps'))) if not v]
        out.append(Listing(
            ticker=str(r['ticker']).strip().upper(),
            name=str(r.get('name') or '').strip(),
            mark=_num(r.get('mark_price')),
            volume_24h=_num(r.get('volume_24h')),
            oi_long=_num(oi.get('long_open_interest')),
            oi_short=_num(oi.get('short_open_interest')),
            funding_raw=_num(r.get('funding_rate')),
            funding_interval_s=int(r.get('funding_interval_s') or 0),
            spread_bps=_num(r.get('base_spread_bps')),
            quote_ts=_ts(q.get('updated_at')),
            quotes=quotes,
            missing=tuple(miss)))
    if not out:
        raise FeedError('shape', 'ни одной строки с тикером')
    return out, meta


def fetch(timeout=None):
    """Живой снимок площадки. -> (list[Listing], meta). Бросает FeedError.

    БРОСАЕТ, А НЕ ВОЗВРАЩАЕТ ПУСТОТУ: пустой список снимков читался бы детектором как
    «рынок замер» — то есть отказ сети превратился бы в утверждение о рынке.
    """
    url = BASE + STATS_PATH
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Accept': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=float(timeout or TIMEOUT)) as resp:
            raw = resp.read()
            code = getattr(resp, 'status', 200) or 200
    except urllib.error.HTTPError as e:
        raise FeedError('http', 'HTTP %s' % e.code, http=e.code)
    except Exception as e:
        raise FeedError('net', '%s: %s' % (type(e).__name__, e))
    if code != 200:
        raise FeedError('http', 'HTTP %s' % code, http=code)
    try:
        payload = json.loads(raw.decode('utf-8', 'replace'))
    except Exception as e:
        raise FeedError('json', str(e))
    rows, meta = parse(payload)
    meta['latency_ms'] = int((time.time() - t0) * 1000)
    meta['bytes'] = len(raw)
    return rows, meta


# ── КЛАСС АКТИВА: ТОЛЬКО ТО, ЧТО ПРОВАЙДЕР СКАЗАЛ САМ ─────────────────────────────────────
# Разделение нужно человеку (у акции свой график торгов и своя причина движения), но
# УГАДЫВАТЬ его ПО ТИКЕРУ запрещено, и запрет этот ЗАМЕРЕН, а не осторожность: в живом
# ответе тикер `A` — это НЕ Agilent, а токен Vaulta, а `US` — не страна и не индекс, а токен
# Talus. Любая таблица «тикер -> класс», собранная из знания фондового рынка, соврала бы на
# первых же двух строках.
# ЕДИНСТВЕННЫЙ ПРИЗНАК, КОТОРЫЙ ПРОВАЙДЕР ДАЁТ САМ, — поле `name` с юридической формой:
# 'NVIDIA Corporation', 'Moderna, Inc.', 'Invesco QQQ Trust, Series 1'. Всё остальное
# ('Bitcoin', 'Gold', 'WTI Crude Oil', 'SKALE') из имени НЕ различается — 'Gold' с тем же
# правом бывает тикером мема, — и поэтому получает 'unknown'.
_CORP = ('inc', 'corp', 'corporation', 'company', 'co', 'plc', 'ltd', 'limited', 'holdings',
         'nv', 'sa', 'ag', 'incorporated', 'se')
_FUND = ('etf', 'trust', 'fund')


def asset_class(listing):
    """-> 'equity' | 'fund' | 'unknown'. Третье значение — полноправный ответ, а не заглушка.

    'crypto' ЗДЕСЬ НЕТ НАРОЧНО. Объявить криптой всё, что не акция, — это вывод по остатку:
    в том же списке живут металлы, нефть и индексы, и они попали бы в «крипту» молча. Класс,
    который мы не умеем доказать, называется 'unknown', и фильтр подписки по нему НЕ режет.
    """
    nm = (listing.name or '').strip().lower()
    if not nm:
        return 'unknown'
    words = [w.strip('.,()') for w in nm.replace(',', ' ').split() if w.strip('.,()')]
    if words and words[-1] in _CORP:
        return 'equity'
    if any(w in _FUND for w in words):
        return 'fund'
    return 'unknown'
