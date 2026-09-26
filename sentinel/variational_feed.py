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

ЕДИНИЦА ФАНДИНГА: ДОЛГ ВЕРИФИКАЦИИ №1 ЗАКРЫТ ЗАМЕРОМ 26.09.2026
Девять кругов здесь стояло «единица не заявлена, и это сознательно»: провайдер отдаёт
`funding_rate` без единицы, справка говорит «RWA/TradFi фиксировано 0.005% за 8-часовой
интервал» (help.variational.io/en/articles/16038203), а в живом ответе у MRNA 0.442690, у MSTR
0.455416, у US500 ноль. Вывод тогда был «похоже на годовые проценты, но ПОХОЖЕ — не замер», и
он был правильным: назвать проценты процентами, не измерив, значит выдумать человеку цифру,
по которой он считает деньги.

ТЕПЕРЬ ИЗМЕРЕНО, и гипотеза оказалась БЛИЗКОЙ, НО НЕВЕРНОЙ: это годовая ДОЛЯ, а не проценты
(0.4427 = 44.27% годовых, а не 0.44%). Метод — сверка с площадкой, чья единица известна
документально, с калибровкой на заранее известном ответе и проверкой на двух группах
интервалов сразу; разбор и числа — в `sentinel/venues.FUNDING_UNIT`, воспроизводится командой
`python3 tools/sentinel_funding_unit.py`.
СПРАВКА ПЛОЩАДКИ ЗАМЕРУ НЕ ПРОТИВОРЕЧИЛА — она говорила о другом: 0.005% за 8ч это 5.48%
годовых, тот же порядок, что и живые числа. Противоречие было в нашем чтении, не в источнике.

ЧТО ОСТАЛОСЬ КАК БЫЛО: поле по-прежнему называется `funding_raw`, и приведение к годовым живёт
НЕ ЗДЕСЬ, а в `venues.funding_apr_pct` — рядом с таблицей единиц по площадкам. У трёх площадок
единицы разные, и знание об этом обязано лежать в одном месте, иначе первая же новая площадка
разведёт карточку, детектор и отчёт. События по фандингу по-прежнему ловятся проценти́лем
инструмента относительно САМОГО СЕБЯ (критерий от единицы не зависит), но теперь рядом с ним
работает и абсолютный порог в годовых процентах — он девять кругов лежал в конфиге мёртвым.
"""

import json
import os
import re
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
    #: ═══ ОТКРЫТЫЙ ИНТЕРЕС В ДОЛЛАРАХ. ЕДИНИЦУ СТАВИТ СЛОЙ ПЛОЩАДКИ, И ТОЛЬКО ОН ═══
    #: ЗАМЕР 26.09, ТРИ ПЛОЩАДКИ - ТРИ РАЗНЫЕ ЕДИНИЦЫ В ОДНОМ И ТОМ ЖЕ ПОЛЕ:
    #:   * Variational отдаёт `long_open_interest`/`short_open_interest` УЖЕ В ДОЛЛАРАХ
    #:     (проверено сверкой с верхнеуровневым `open_interest`: сумма сторон по всем
    #:     инструментам дала ровно половину от него, то есть обе стороны одного и того же;
    #:     умножение на цену дало 20 триллионов - число, которого на рынке нет);
    #:   * Hyperliquid - в базовом активе (BTC 37 639 = 3.16 млрд долларов);
    #:   * Lighter - в базовом активе (BTC 1953.5 = 163.9 млн долларов).
    #: Детектор умножал на цену ВСЁ и одинаково. Итог на проде: 118 событий из 139 имели
    #: «прирост интереса» больше двух суточных оборотов, то есть физически невозможный; DELL
    #: показывал 174 млн при интересе 310 тысяч.
    #: ПОЧЕМУ ПОЛЕ, А НЕ СВОЙСТВО-ВЫЧИСЛЕНИЕ. Свойство внутри `Listing` не знает, в чём пришло
    #: число, и любое общее правило («если мало - значит контракты») было бы догадкой о рынке.
    #: Единицу знает ровно одно место - тот код, который читает ответ конкретной площадки.
    oi_usd: float = None

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
        # ═══ ИНТЕРЕС В ДОЛЛАРАХ СТАВИТСЯ ЗДЕСЬ, В РАЗБОРЕ ОТВЕТА ПЛОЩАДКИ ═══
        # Единицу знает тот код, который читает конкретный ответ, и ставить её надо ровно там же:
        # первая редакция считала `oi_usd` в обёртке `venues.var_fetch`, и любой, кто звал `parse`
        # напрямую (тесты - в первую очередь), получал инструмент без интереса вовсе. То есть
        # величина существовала только на одном из двух путей к тем же данным.
        # У Variational складываем стороны КАК ЕСТЬ: обе уже в долларах (замер 26.09, разбор в
        # докстринге поля `Listing.oi_usd`).
        _s = (out[-1].oi_long or 0.0) + (out[-1].oi_short or 0.0)
        out[-1].oi_usd = _s or None
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
#: ЮРИДИЧЕСКАЯ ФОРМА ПОСЛЕДНИМ СЛОВОМ ИМЕНИ. Точки внутри формы снимаются до сравнения: живое
#: имя 'Nebius Group N.V.' давало слово 'n.v' и выпадало в 'unknown' (замер 26.09, ТЗ 2.5).
#: ТЗ 2.5 добавил 'technologies', 'systems', 'automotive' (их в реестре Variational носят только
#: компании), замер - 'a/s' (Novo Nordisk A/S), 'oyj' (Nokia Oyj), 'group' (Circle Internet
#: Group). Каждое проверено на ВСЁМ живом ответе: ни одно не заканчивает имя крипто-токена
#: (`tests/fixtures/variational_names_20260926.json`, сторож в t_asset_class_on_live_names).
_CORP = ('inc', 'corp', 'corporation', 'company', 'co', 'plc', 'ltd', 'limited', 'holdings',
         'holding', 'nv', 'sa', 'ag', 'incorporated', 'se', 'a/s', 'oyj', 'technologies',
         'systems', 'automotive', 'group')
#: КЛАСС БУМАГИ В ХВОСТЕ ИМЕНИ: 'CoreWeave, Inc. Class A Common Stock', 'Arm Holdings plc American
#: Depositary Shares'. Юрформа тут не последняя, и прежнее правило отдавало шесть живых акций в
#: 'unknown' - то есть мимо правила «у акции нет контракта» они шли в платный ончейн.
_SHARE_TAIL = re.compile(r'(?:,?\s+class\s+[a-z])?\s+(?:common\s+stock|ordinary\s+shares|'
                         r'american\s+depositary\s+shares|depositary\s+shares)\s*$')
#: ФОНД ТОЛЬКО ПО СЛОВУ ETF ИЛИ ФОРМЕ «TRUST, SERIES N». Прежнее «любое слово trust/fund» живьём
#: отдавало в фонды два крипто-токена: 'Trust Wallet' (TWT) и 'Giggle Fund' (GIGGLE) - и
#: вместе с классом у них отрезался ончейн, хотя контракт в сети у обоих есть.
_FUND_RX = re.compile(r'\betf\b|\btrust,?\s+series\s+\d+')
#: ═══ СЫРЬЁ, МЕТАЛЛЫ, ИНДЕКСЫ - РЕЕСТРОМ ТОЧНЫХ ИМЁН VARIATIONAL, А НЕ СЛОВОМ (ТЗ 2.5) ═══
#: 'Gold' словом угадывать нельзя: в том же ответе живут 'PAX Gold' (PAXG), 'Tether Gold'
#: (XAUT) и 'Adventure Gold' (AGLD) - это ТОКЕНЫ с контрактом в сети, а 'Gas' (GAS) - токен NEO.
#: Поэтому ключ - ПАРА (тикер, имя) ровно так, как их отдала площадка 26.09. Площадка
#: переименует инструмент - он честно уйдёт в 'unknown', а не в чужой класс.
NAMED_CLASS = {
    ('XAU', 'gold'): 'metal', ('XAG', 'silver'): 'metal', ('XPD', 'palladium'): 'metal',
    ('XPT', 'platinum'): 'metal', ('COPPER', 'copper'): 'metal',
    ('XAUS', 'swap on gold spot'): 'metal', ('XAGS', 'swap on silver spot'): 'metal',
    ('CL', 'wti crude oil'): 'commodity', ('BZ', 'brent oil'): 'commodity',
    ('NATGAS', 'natural gas'): 'commodity', ('USOILP', 'swap on wti crude oil'): 'commodity',
    ('UKOILP', 'swap on brent crude oil'): 'commodity',
    ('US500S', 'swap on us 500'): 'index', ('US100S', 'swap on us non-financial 100'): 'index',
    ('TWIS', 'swap on taiwan index'): 'index',
}
#: Классы, у которых НЕТ контракта в сети (ончейн и кэштег-правило X). 'unknown' сюда не входит.
OFFCHAIN_CLASSES = ('equity', 'fund', 'commodity', 'metal', 'index')


def asset_class(listing):
    """-> 'equity' | 'fund' | 'commodity' | 'metal' | 'index' | 'unknown'.

    'unknown' - полноправный ответ, а не заглушка.
    'crypto' ЗДЕСЬ НЕТ НАРОЧНО. Объявить криптой всё, что не акция, - это вывод по остатку:
    в том же списке живут металлы, нефть и индексы, и они попали бы в «крипту» молча. Класс,
    который мы не умеем доказать, называется 'unknown', и фильтр подписки по нему НЕ режет.
    ИМЕНА ПЛОЩАДОК БЕЗ ИМЁН (Hyperliquid, Lighter отдают имя = тикер) получают 'unknown': по
    тикеру класс не угадывается (замер: `A` - это Vaulta, `US` - Talus).
    """
    tick = str(getattr(listing, 'ticker', '') or '').upper()
    # ДРУГИЕ ПЛОЩАДКИ - КЛАССОМ VARIATIONAL ПО ТИКЕРУ (решение владельца 26.09): у Hyperliquid и
    # Lighter имя равно тикеру, и по нему класс не определяется. Нет тикера в справочнике - дальше
    # по имени, то есть почти всегда 'unknown' (Азию и pre-IPO не угадываем).
    if (getattr(listing, 'venue', 'variational') or 'variational') != 'variational':
        try:
            from .assets import book_class
            _bk = book_class(tick)
        except Exception:                                  # noqa: BLE001
            _bk = None
        if _bk:
            return _bk
    nm = re.sub(r'\s+', ' ', (listing.name or '').strip().lower())
    if not nm:
        return 'unknown'
    if (tick, nm) in NAMED_CLASS:
        return NAMED_CLASS[(tick, nm)]
    if _FUND_RX.search(nm):
        return 'fund'
    if _SHARE_TAIL.search(nm):
        return 'equity'
    words = [w.replace('.', '').strip(',()') for w in nm.replace(',', ' ').split()]
    words = [w for w in words if w]
    if words and words[-1] in _CORP:
        return 'equity'
    return 'unknown'
