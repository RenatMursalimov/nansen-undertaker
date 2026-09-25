# -*- coding: utf-8 -*-
"""Тесты дозорного (sentinel/): фикстура ответа площадки -> ЖИВОЙ разбор -> кольца ->
детектор -> дедупликация -> пауза -> потолок -> отправка -> обогащение -> исход.

Запуск: python3 tests/test_sentinel.py    (сети не требует, БД — временный sqlite).

ЧТО ПОДМЕНЕНО И ПОЧЕМУ ИМЕННО ТАМ
  * СЕТЬ, и только она: тело ответа Variational подставляется словарём в `feed.parse` —
    то есть проверяется ЖИВОЙ разбор, а не заглушка вместо него. Лента Nansen подставляется
    в `ignition.scan(fetch=…)` на той же границе.
  * ЧАСЫ: `now` передаётся аргументом во все чистые функции. Тест, который спал бы час ради
    проверки паузы, не запускают — а значит он ничего не защищает.
  * ОТПРАВКА: фальшивый Bot ЗАПИСЫВАЕТ текст. Проверяем, ЧТО уехало бы человеку, а не факт
    вызова внутренней функции (закон №35): именно текст читает человек, и именно в нём
    случаются дефекты вроде «$0.99 вместо $48K».

ЧЕГО ЗДЕСЬ НЕТ: ожидания живого выброса на рынке. Детектор кормится синтетическим рядом, у
которого известен правильный ответ. Тест, который ждёт настоящего движения, зелен всегда и
не доказывает ничего.
"""
import asyncio
import os
import sys
import tempfile
import time
import types

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ['SENTINEL_LLM_OFF'] = '1'            # пересказ моделью в тестах не зовётся

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'onchain'))

import db                                        # noqa: E402
_TMP = tempfile.mkdtemp(prefix='sentinel_test_')
# ПУТЬ СТАВИМ ПУБЛИЧНОЙ ДВЕРЬЮ `set_path`, А НЕ ВНУТРЕННИМ `_PATHS`. Этот файл уезжает в
# публичную выжимку (`tools/export_nansen_public.py`), а `db.py` там — своя маленькая
# реализация той же двери БЕЗ `_PATHS`. Тест, который лезет во внутренности, работал бы в
# приватном репозитории и падал в публичном первой же строкой — то есть судья увидел бы
# сломанный артефакт вместо доказательства.
for _k in ('onchain', 'main'):
    db.set_path(_k, os.path.join(_TMP, '%s.db' % _k))
# ── ПРОВЕРКА, ЧТО МЫ ПРАВДА В TMP, И ОСТАНОВКА, ЕСЛИ НЕТ ───────────────────────────────────
# Этот файл запускают НА СЕРВЕРЕ, рядом с живым ботом (владелец так и сделал 25.09). Если путь
# базы однажды не подменится - из-за правки db.py, из-за .env, из-за чего угодно, - тест начнёт
# писать в БОЕВУЮ базу и ронять живую службу. Тест, способный навредить проду, опаснее
# отсутствующего, поэтому здесь не «предупреждение», а выход.
for _k in ('onchain', 'main'):
    _p = db.get_path(_k) if hasattr(db, 'get_path') else _TMP
    if _TMP not in str(_p):
        print('ОСТАНОВЛЕНО: база %r это %s, а не временный каталог %s. Тест писал бы в '
              'боевую базу - прогон отменён.' % (_k, _p, _TMP))
        sys.exit(2)

# ── ЗАГЛУШКА `httpx`, ЕСЛИ БИБЛИОТЕКИ НЕТ ──────────────────────────────────────────────────
# Ссылки в карточке строит ОДНА общая дверь `nansen_api.tok_link` (пятая копия тега `a href` в
# проекте запрещена законом №40), а `nansen_api` на импорте тянет httpx. Без заглушки карточка
# молча уезжала бы БЕЗ ссылок везде, где httpx нет - на машине разработки и в публичной выжимке,
# - и проверить «ссылки стали ссылками» было бы нечем. Подменяются только классы-контейнеры
# клиента: ни одного запроса этот тест не делает.
try:
    import httpx                                     # noqa: F401
except Exception:
    _hx = types.ModuleType('httpx')

    class _Cl:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False
    _hx.AsyncClient = _Cl
    _hx.Client = _Cl
    _hx.Timeout = _Cl
    _hx.HTTPError = Exception
    _hx.RequestError = Exception
    sys.modules['httpx'] = _hx

# ── ЗАГЛУШКА `telegram`, ЕСЛИ БИБЛИОТЕКИ НЕТ ───────────────────────────────────────────────
# Клавиатуру экрана собирает `InlineKeyboardMarkup`, и без python-telegram-bot тест упал бы
# ImportError - то есть раскладка кнопок осталась бы непроверенной там, где библиотеки нет: на
# машине разработки и в публичной выжимке. Заглушка подменяет РОВНО два класса-контейнера и
# ничего не эмулирует: проверяем МЫ свою раскладку (какие callback_data и какие подписи), а не
# чужую библиотеку. Там, где библиотека установлена (сервер), берётся настоящая.
try:
    import telegram                                   # noqa: F401
except Exception:
    _tg = types.ModuleType('telegram')

    class _B:
        def __init__(self, text, callback_data=None, url=None, web_app=None):
            self.text, self.callback_data, self.url, self.web_app = text, callback_data, url, web_app

    class _M:
        def __init__(self, rows):
            self.inline_keyboard = [list(r) for r in rows]
    _tg.InlineKeyboardButton = _B
    _tg.InlineKeyboardMarkup = _M
    _tg.WebAppInfo = lambda url=None: url
    _tg.Bot = object
    sys.modules['telegram'] = _tg

from sentinel import cards, config, detector, engine, ignition, outbox, store, ui  # noqa: E402
from sentinel import variational_feed as feed    # noqa: E402

UID = 990001
UID2 = 990002
_OK, _FAIL, _SKIP = 0, 0, 0


def check(name, cond, note=''):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print('  ok  %s' % name)
    else:
        _FAIL += 1
        print('FAIL  %s %s' % (name, note))


def _db_diag():
    """ЗАМЕРЫ БАЗЫ ОДНОЙ СТРОКОЙ: путь, бэкенд, режим журнала, таймаут ожидания. -> str.

    Печатается при ЛЮБОМ падении теста (см. `main`). Один текст «database is locked» покрывает
    несколько разных причин, и без этих четырёх чисел разбор идёт гаданием - на сервере
    владельца это уже стоило круга.
    """
    import db as _d
    out = ['backend=%s' % getattr(_d, 'DB_BACKEND', '?')]
    try:
        c0 = _d.get_conn('onchain')
        # ПУТЬ СПРАШИВАЕМ У ЖИВОГО СОЕДИНЕНИЯ (`PRAGMA database_list`), А НЕ У НАСТРОЙКИ. Разница
        # существенная: настройка говорит, что мы ПРОСИЛИ, а PRAGMA - куда СУБД правда пишет.
        # Ровно этот зазор и надо видеть, когда тест внезапно бьётся о боевую базу. Плюс работает
        # там, где у `db` нет функции чтения пути (публичная выжимка несёт свою реализацию).
        cur0 = c0.execute('PRAGMA database_list')
        rows0 = cur0.fetchall() or []
        try:
            cur0.close()
        except Exception:
            pass
        out.append('path=%s' % (rows0[0][2] if rows0 and len(rows0[0]) > 2 else '?'))
    except Exception as e:
        out.append('path=? (%s)' % str(e)[:60])
    try:
        c = _d.get_conn('onchain')
        for pragma in ('journal_mode', 'busy_timeout'):
            try:
                cur = c.execute('PRAGMA %s' % pragma)
                row = cur.fetchone()
                out.append('%s=%s' % (pragma, (row or ['?'])[0]))
                try:
                    cur.close()
                except Exception:
                    pass
            except Exception as e:
                out.append('%s=недоступен (%s)' % (pragma, str(e)[:40]))
    except Exception as e:
        out.append('соединение не взято: %s' % str(e)[:60])
    out.append('поток=%s' % __import__('threading').current_thread().name)
    return ' · '.join(out)


class FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, chat_id=None, text=None, **kw):
        if self.fail:
            raise RuntimeError('tg down')
        self.sent.append((chat_id, text))
        return type('M', (), {'message_id': 100 + len(self.sent)})()


def attach(bot):
    outbox._BOT = bot
    outbox._BOT_TOKEN = 'test'


# ── ФИКСТУРА ОТВЕТА ПЛОЩАДКИ: форма снята с живого ответа 25.09.2026 (553 инструмента,
#    числа строками, наносекундная дробь в `updated_at`, `size_1m` есть не у всех).
def payload(ticker='BTC', name='Bitcoin', mark='100.0', vol='800000000', oi_l='1000',
            oi_s='900', funding='0.05', spread='1.0', quote_iso=None, size_1m=True):
    q = {'updated_at': quote_iso or '2026-09-25T00:23:32.422937751Z',
         'base': {'bid': str(float(mark) * 0.9995), 'ask': str(float(mark) * 1.0005)},
         'size_1k': {'bid': str(float(mark) * 0.999), 'ask': str(float(mark) * 1.001)},
         'size_100k': {'bid': str(float(mark) * 0.998), 'ask': str(float(mark) * 1.002)}}
    if size_1m:
        q['size_1m'] = {'bid': str(float(mark) * 0.99), 'ask': str(float(mark) * 1.01)}
    return {'total_volume_24h': '3.2e9', 'open_interest': '1.9e9', 'tvl': '2.4e8',
            'num_markets': 1,
            'listings': [{'ticker': ticker, 'name': name, 'mark_price': mark,
                          'volume_24h': vol,
                          'open_interest': {'long_open_interest': oi_l,
                                            'short_open_interest': oi_s},
                          'funding_rate': funding, 'funding_interval_s': 28800,
                          'base_spread_bps': spread, 'quotes': q}]}


def one(**kw):
    rows, _meta = feed.parse(payload(**kw))
    return rows[0]


def series(n, start_ts, mark=100.0, step=900, funding=0.05, spread=1.0):
    """Холодное кольцо: n точек по 15 минут. Форма кортежа — контракт `store.history`."""
    return [(start_ts + i * step, mark, 8e8, 1000.0, 900.0, funding, spread, start_ts + i * step)
            for i in range(n)]


# ══════════════════════════════════════════════════════════════════════════════════════════
def t_parse_is_real_and_names_what_is_missing():
    """РАЗБОР ОТВЕТА: строки провайдера -> числа, наносекунды -> возраст, пропуск -> имя."""
    rows, meta = feed.parse(payload())
    x = rows[0]
    check('PARSE: числа провайдера строками стали числами',
          x.mark == 100.0 and x.volume_24h == 8e8, (x.mark, x.volume_24h))
    check('PARSE: наносекундная дробь не убила возраст котировки',
          x.quote_ts is not None and abs(x.quote_ts - 1790295812.42) < 1,
          'возраст None -> штраф за свежесть не сработал бы НИКОГДА')
    check('PARSE: возраст считается от now, а не от часов провайдера',
          abs(x.quote_age(x.quote_ts + 55) - 55) < 1, x.quote_age(x.quote_ts + 55))
    check('PARSE: мета несёт задержку и объём ответа', 'fetched_at' in meta)
    # ОТСУТСТВИЕ ПОЛЯ - НЕ НОЛЬ. Живая проба: у одного инструмента из 553 нет ни `quotes`,
    # ни `base_spread_bps`; ноль спреда означал бы идеальную книгу, чего не бывает.
    p = payload()
    p['listings'][0].pop('base_spread_bps')
    p['listings'][0].pop('quotes')
    y = feed.parse(p)[0][0]
    check('PARSE: пропущенное поле названо, а не заменено нулём',
          y.spread_bps is None and 'base_spread_bps' in y.missing and 'quotes' in y.missing,
          (y.spread_bps, y.missing))
    check('PARSE: чужая форма ответа - отказ с классом, а не пустой список',
          _raises_shape({'listings': []}), 'пустой список читался бы как «рынок замер»')
    check('PARSE: класс актива по имени провайдера, а не по тикеру',
          feed.asset_class(one(ticker='MRNA', name='Moderna, Inc.')) == 'equity'
          and feed.asset_class(one(ticker='A', name='Vaulta')) == 'unknown',
          'тикер `A` в живом списке - токен Vaulta, а не Agilent')
    check('PARSE: «не акция» НЕ объявляется криптой',
          feed.asset_class(one(ticker='XAU', name='Gold')) == 'unknown')
    check('PARSE: ёмкость на объём считается от середины',
          abs(one().depth_bps('size_100k') - 20.0) < 0.5, one().depth_bps('size_100k'))


def _raises_shape(p):
    try:
        feed.parse(p)
        return False
    except feed.FeedError as e:
        return e.kind == 'shape'


def t_detector_needs_both_percent_and_sigma():
    """ДЕТЕКТОР: процент без сигмы — спам, сигма без процента — шум."""
    now = 1800000000
    ring = series(60, now - 60 * 900)                       # ровный ряд: сигма нулевая
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    evs = detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now, ring=ring)
    kinds = {e['kind'] for e in evs}
    check('DETECT: 4% за 15 минут - это событие', 'move_up' in kinds, kinds)
    # РОВНЫЙ РЯД ФАНДИНГА - НЕ ХВОСТ. Первая редакция считала «доля не больше x» и на
    # постоянном ряде давала 1.0: «ставка в верхнем хвосте» печаталась на КАЖДОМ тике по
    # инструменту, у которого ставка не менялась вовсе.
    check('DETECT: постоянная ставка не объявляется хвостом', 'funding_extreme' not in kinds,
          kinds)
    check('DETECT: сигма, измеренная нулём, не глушит движение целиком', 'move_up' in kinds,
          'на идеально ровном ряде порог в сигмах невычислим - событие обязано остаться')
    check('DETECT: и говорит об этом словами',
          any('сигма измерена нулём' in p
              for e in evs if e['kind'] == 'move_up' for p in e['payload']['penalties']),
          [e['payload']['penalties'] for e in evs if e['kind'] == 'move_up'])
    evs2 = detector.detect(one(mark='100.5', quote_iso=_iso(now)), hot, now=now, ring=ring)
    check('DETECT: 0.5% - не событие', not [e for e in evs2 if e['kind'].startswith('move')])
    # ВЫБОРКА МАЛА -> СОБЫТИЕ ЕСТЬ, НО УВЕРЕННОСТЬ НИЖЕ И ПРИЧИНА НАЗВАНА
    short = series(3, now - 3 * 900)
    ev3 = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                      ring=short) if e['kind'] == 'move_up']
    check('DETECT: на короткой выборке событие остаётся', ev3)
    check('DETECT: и честно называет, что сигмы ещё нет',
          ev3 and any('сигма по' in p for p in ev3[0]['payload']['penalties']),
          ev3[0]['payload']['penalties'] if ev3 else None)
    check('DETECT: уверенность за это наказана', ev3 and ev3[0]['severity'] < 100,
          ev3[0]['severity'] if ev3 else None)
    # ОКНО НЕДОСТУПНО -> МОЛЧАНИЕ, А НЕ «0%»
    ev4 = detector.detect(one(mark='104.0', quote_iso=_iso(now)), [], now=now, ring=ring)
    check('DETECT: без точки в прошлом движение не объявляется',
          not [e for e in ev4 if e['kind'].startswith('move')],
          'отсутствие замера превратилось бы в утверждение о рынке')
    check('DETECT: pct без базы отдаёт None, а не ноль',
          detector.pct(5, 0) is None and detector.pct(5, None) is None)
    # ОБОРОТ - ПОРОГ ВХОДА
    ev5 = detector.detect(one(mark='104.0', vol='1000', quote_iso=_iso(now)), hot, now=now,
                          ring=ring)
    check('DETECT: инструмент без оборота в дозор не идёт вовсе', not ev5, ev5)


def _iso(ts):
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S.000000000Z')


def t_event_key_is_stable_and_step_escalates():
    """КЛЮЧ СОБЫТИЯ: один выброс — один ключ; удвоение движения — НОВЫЙ ключ."""
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    a = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                    ring=ring) if e['kind'] == 'move_up'][0]
    b = [e for e in detector.detect(one(mark='104.4', quote_iso=_iso(now + 30)), hot,
                                    now=now + 30, ring=ring) if e['kind'] == 'move_up'][0]
    check('KEY: тот же выброс через 30с даёт ТОТ ЖЕ ключ', a['key'] == b['key'],
          'иначе одно движение дало бы десятки алертов')
    c = [e for e in detector.detect(one(mark='107.0', quote_iso=_iso(now + 60)), hot,
                                    now=now + 60, ring=ring) if e['kind'] == 'move_up'][0]
    check('KEY: движение удвоилось - это НОВОЕ событие', c['key'] != a['key'],
          'ступень %s' % c['payload']['step'])
    # СТУПЕНЬ СРАВНИВАЕМ С ПРЕДЫДУЩЕЙ, А НЕ С КОНСТАНТОЙ: её величина зависит от порога, а порог
    # правится замером (25.09 он понижен с 3% до 1.2%). Тест на конкретное «2» ломался бы при
    # каждой настройке чувствительности и проверял бы конфиг, а не поведение.
    check('KEY: ступень выросла числом',
          c['payload']['step'] > a['payload']['step'],
          (a['payload']['step'], c['payload']['step']))


def t_oi_funding_and_spread_have_their_own_reasons():
    """ТРИ ОСТАЛЬНЫХ ВИДА: интерес, ставка, спред — каждый ловится своим замером."""
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [(now - 3600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 3600)]
    evs = detector.detect(one(mark='100.0', oi_l='5000', oi_s='900', quote_iso=_iso(now)),
                          hot, now=now, ring=ring)
    check('OI: скачок интереса при стоящей цене — событие',
          'oi_surge' in {e['kind'] for e in evs}, {e['kind'] for e in evs})
    # АБСОЛЮТНЫЙ ПОРОГ РЯДОМ С ПРОЦЕНТНЫМ: +20% к интересу, которого было на копейки, - это
    # копейки. Без этой проверки процент один решал бы, и алерт приходил бы по пустякам.
    small = detector.detect(one(mark='100.0', oi_l='1600', oi_s='900', quote_iso=_iso(now)),
                            hot, now=now, ring=ring)
    check('OI: скачок на $60k событием НЕ считается',
          'oi_surge' not in {e['kind'] for e in small},
          {e['kind'] for e in small})
    # ФАНДИНГ: хвост СВОЕГО распределения (единица провайдером не названа, абсолюта нет)
    ring_f = [(now - (60 - i) * 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, 0) for i in range(60)]
    ring_f = ring_f * 1
    evs2 = detector.detect(one(mark='100.0', funding='9.99', quote_iso=_iso(now)), hot,
                           now=now, ring=ring_f)
    check('FUNDING: порог процентильный, не абсолютный',
          'funding_extreme' in {e['kind'] for e in evs2} or len(ring_f) < 50,
          {e['kind'] for e in evs2})
    # ДИВИДЕНД У АКЦИЙ ВЫГЛЯДИТ КАК ПОЗИЦИОНИРОВАНИЕ - КАРТОЧКА ОБЯЗАНА СКАЗАТЬ ЭТО САМА
    ring_n = [(now - (60 - i) * 900, 100.0, 8e8, 1000.0, 900.0, 0.5, 1.0, 0) for i in range(60)]
    evs3 = [e for e in detector.detect(
        one(ticker='MRNA', name='Moderna, Inc.', mark='100.0', funding='-9.9',
            quote_iso=_iso(now)), hot, now=now, ring=ring_n)
        if e['kind'] == 'funding_extreme']
    check('FUNDING: у акции отрицательная ставка помечена как возможный дивиденд',
          evs3 and any('дивиденд' in p for p in evs3[0]['payload']['penalties']),
          evs3[0]['payload']['penalties'] if evs3 else 'события нет')
    evs4 = [e for e in detector.detect(one(mark='100.0', spread='60.0', quote_iso=_iso(now)),
                                       hot, now=now, ring=ring) if e['kind'] == 'spread_shock']
    check('SPREAD: спред 60 б.п. при медиане 1 - событие', evs4)
    check('SPREAD: и карточка называет это предостережением, а не сигналом',
          evs4 and 'предостережение' in cards.card(evs4[0]).lower(),
          'человек прочитал бы «дёрнулось» как приглашение')
    # ── СЛУЧАЙ XAGS ИЗ ЖИВОГО ЛОГА 25.09. Три алерта подряд: «спред 2.4 б.п. - ×9.5 к медиане
    #    0.3». Арифметика верна, новости нет: это две сотых процента. Вердикт владельца -
    #    «походит на спам», «это же не алерт». Относительный порог измеряет НЕОБЫЧНОСТЬ, а не
    #    ЗНАЧИМОСТЬ, поэтому рядом обязан стоять абсолютный.
    ring_thin = [(now - (60 - i) * 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 0.3, 0)
                 for i in range(60)]
    xags = detector.detect(one(ticker='XAGS', name='Swap on Silver Spot', mark='63.4',
                               spread='2.4', quote_iso=_iso(now)), hot, now=now, ring=ring_thin)
    check('SPREAD: 2.4 б.п. при медиане 0.3 - НЕ событие (случай XAGS, ×9.5)',
          'spread_shock' not in {e['kind'] for e in xags}, {e['kind'] for e in xags})
    check('SPREAD: и порог назван числом в конфиге', config.spread_min_bps() >= 10,
          config.spread_min_bps())


def t_card_leads_with_magnitude_and_admits_limits():
    """КАРТОЧКА: величина в первой строке, HTML, ссылки - ссылками, и она КОРОТКАЯ.

    ПЕРЕПИСАН ПОСЛЕ ЖИВОГО ЧАСА 25.09. Вердикт владельца: «весь текст от алертов без формата»,
    «зачем-то все ссылки без линков внутри», «должно быть красиво, чётко, содержательно, по
    делу». Прежняя карточка занимала 22 строки, повторяла один и тот же дисклеймер из четырёх
    пунктов в каждом алерте и заканчивалась служебной строкой про `/metadata/stats`.
    """
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    ev = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                     ring=ring) if e['kind'] == 'move_up'][0]
    txt = cards.card(ev, bot_un='testbot')
    head = txt.split('\n')[0]
    check('CARD: тикер и величина в ПЕРВОЙ строке', 'BTC' in head and '+4.00%' in head, head)
    check('CARD: величина выделена разметкой', '<b>+4.00%</b>' in head, head)
    check('CARD: карточка короткая (<= 14 строк)', len(txt.split('\n')) <= 14,
          len(txt.split('\n')))
    check('CARD: сказано, во что обойдётся вход на $100k', 'Вход на $100k' in txt)
    check('CARD: возраст котировки числом', 'котировке' in txt)
    check('CARD: уверенность числом', 'Уверенность <b>' in txt)
    check('CARD: дисклеймер ОДНОЙ строкой, а не списком из четырёх пунктов',
          txt.count('•') <= 1 and 'Причину движения дозорный не читает' in txt, txt)
    check('CARD: служебной строки про эндпоинт больше нет',
          '/metadata/stats' not in txt, 'человеку в момент решения это не нужно')
    check('CARD: ссылка на площадку - ССЫЛКОЙ', '<a href="https://omni.variational.io/"' in txt,
          txt[-200:])
    check('CARD: нулевой фандинг в карточке не печатается',
          'funding_rate' not in cards.card(
              [e for e in detector.detect(one(mark='104.0', funding='0', quote_iso=_iso(now)),
                                          hot, now=now, ring=ring)
               if e['kind'] == 'move_up'][0]),
          'строка «funding_rate: 0» в каждом алерте - шум')
    check('CARD: экранирование включено (амперсанд в имени не рвёт разметку)',
          cards.esc('A & B < C') == 'A &amp; B &lt; C', cards.esc('A & B < C'))
    check('CARD: контракты печатаются человеческим числом, а не 1.045e+06',
          cards._num(1045000) == '1.04M', cards._num(1045000))
    check('CARD: деньги None показываются словом, а не $0',
          cards._usd(None) == 'нет данных')


def t_ignition_counts_wallets_not_trades_and_first_poll_is_silent():
    """ЗАЖИГАНИЕ: считаем РАЗНЫЕ адреса; первый опрос только заводит границу."""
    now = 1800000000

    def trade(tx, who, usd=100000, sym='PEPE', addr='0xtok', mcap=2e8, ts=None):
        return {'transaction_hash': tx, 'trader_address': who, 'trader_address_label': 'Fund ' + who[-1],
                'token_bought_symbol': sym, 'token_bought_address': addr, 'chain': 'ethereum',
                'trade_value_usd': usd, 'token_bought_market_cap': mcap,
                'token_bought_age_days': 400,
                'block_timestamp': _iso(ts or (now - 600))}
    many_one = [trade('0x1', '0xaaa1'), trade('0x2', '0xaaa1'), trade('0x3', '0xaaa1')]
    evs, note = ignition.scan(now=now, fetch=lambda: many_one)
    check('IGN: первый опрос НЕ алертит', not evs and 'первый опрос' in note, note)
    evs, note = ignition.scan(now=now + 60, fetch=lambda: many_one)
    check('IGN: три сделки ОДНОГО адреса - не зажигание', not evs, note)
    three = many_one + [trade('0x4', '0xbbb2'), trade('0x5', '0xccc3')]
    evs, note = ignition.scan(now=now + 120, fetch=lambda: three)
    check('IGN: три РАЗНЫХ адреса - зажигание', len(evs) == 1, note)
    ev = evs[0]
    check('IGN: доля от капитализации посчитана',
          ev['payload']['mcap_bps'] and ev['payload']['mcap_bps'] > 0,
          ev['payload']['mcap_bps'])
    check('IGN: ключ события построен на КОНТРАКТЕ, а не на тикере',
          ev['key'] == detector.key('ignition', 'ethereum:0xtok',
                                    detector._window(now + 120),
                                    ev['payload']['step']),
          'однофамильцы с одним тикером склеились бы в одно «зажигание»')
    check('IGN: повтор той же ленты нового события не даёт',
          not ignition.scan(now=now + 180, fetch=lambda: three)[0])
    # СВАП В СТЕЙБЛ - ЭТО ВЫХОД, А НЕ ВХОД
    outs = [trade('0x%d' % i, '0xddd%d' % i, sym='USDC', addr='0xusdc') for i in range(5)]
    evs2, _ = ignition.scan(now=now + 240, fetch=lambda: outs)
    check('IGN: покупка стейбла не считается заходом', not evs2,
          'массовая фиксация прибыли выглядела бы как приток')
    txt = cards.card(ev, bot_un='testbot')
    check('IGN: карточка ведёт числом адресов и суммой',
          '3 умных адреса' in txt and 'капитализации' in txt, txt[:160])
    check('IGN: и называет сеть с контрактом', '0xtok' in txt and 'ethereum' in txt)
    check('IGN: контракт в <code> - тапом копируется', '<code>0xtok</code>' in txt, txt)
    check('IGN: есть ссылка в наши же экраны (deep-link), а не на чужой сайт',
          't.me/testbot?start=tok_0xtok' in txt and 'dexscreener' not in txt, txt[-260:])


def t_delivery_dedupe_cooldown_cap_and_state():
    """ДОСТАВКА: дедупликация в базе, пауза после успеха, потолок числом, состояние честное."""
    now = int(time.time())
    store.sub_add(UID, 'BTC')
    store.settings_set(UID, alerts_on=1, enrich_on=0)
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    ev = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                     ring=ring) if e['kind'] == 'move_up'][0]
    check('DB: событие записалось', store.event_new(ev) is True)
    check('DB: ПОВТОР того же ключа отбит БАЗОЙ, а не памятью процесса',
          store.event_new(ev) is False,
          'память обнуляется рестартом - после деплоя пришёл бы повтор всех событий')
    n, why = outbox.plan(ev)
    check('PLAN: подписчику поставлена доставка', n == 1, (n, why))
    check('PLAN: повторная постановка не удваивает', outbox.plan(ev)[0] == 0)

    bad = FakeBot(fail=True)
    attach(bad)
    ok, err = asyncio.run(outbox.deliver_due())
    check('SEND: отказ Telegram не считается доставкой', ok == 0 and err == 1, (ok, err))
    st = store.delivery_state(ev['key'], UID)
    check('SEND: «доставлено» НЕ поставлено при сбое', st and st['delivered_at'] is None, st)
    check('SEND: причина сбоя записана словами', st and st['last_err'], st)
    _cd = outbox._cd_kind(ev)        # ключ паузы включает ступень - берём фактический
    check('SEND: пауза НЕ съедена сбоем',
          store.cooldown_left(UID, 'BTC', _cd) == 0,
          'иначе человек не получил алерт И не получит следующий')

    good = FakeBot()
    attach(good)
    ok, err = asyncio.run(outbox.deliver_due())
    check('SEND: после ретрая алерт ушёл', ok == 1 and len(good.sent) == 1, (ok, err))
    check('SEND: ушёл ИМЕННО подписчику', good.sent[0][0] == UID, good.sent[0][0])
    check('SEND: в тексте есть величина', '+4.00%' in good.sent[0][1])
    check('SEND: теперь пауза отмечена', store.cooldown_left(UID, 'BTC', _cd) > 0)
    check('SEND: суточный счётчик считает ДОСТАВЛЕННЫЕ', store.sent_today(UID) == 1)

    # ПАУЗА ПО ПАРЕ (ИНСТРУМЕНТ, ВИД): второе такое же событие в очередь не попадает
    ev2 = dict(ev, key=ev['key'] + 'x', ts=now + 10)
    store.event_new(ev2)
    n2, why2 = outbox.plan(ev2)
    check('COOLDOWN: то же движение в паузе не отправляется', n2 == 0, (n2, why2))
    check('COOLDOWN: и причина называет остаток паузы',
          any('пауза' in w for w in why2), why2)

    # ПОТОЛОК ЧИСЛОМ
    store.settings_set(UID, daily_cap=1)
    ev3 = dict(ev, key=ev['key'] + 'y', ts=now + 20,
               payload=dict(ev['payload'], step=9))
    store.event_new(ev3)
    n3, why3 = outbox.plan(ev3)
    check('CAP: упор в потолок отсекает', n3 == 0, (n3, why3))
    check('CAP: и печатается ВЕЛИЧИНОЙ, а не флагом',
          any('потолок 1/1' in w for w in why3), why3)
    store.settings_set(UID, daily_cap=None)


def t_two_subscribers_each_get_only_their_own():
    """ДВА ПОДПИСЧИКА: доставка — свойство ЧЕЛОВЕКА, а не события."""
    now = int(time.time())
    store.sub_add(UID2, 'ETH')
    store.settings_set(UID2, alerts_on=1, enrich_on=0)
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 200.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    ev = [e for e in detector.detect(one(ticker='ETH', name='Ethereum', mark='208.0',
                                         quote_iso=_iso(now)), hot, now=now, ring=ring)
          if e['kind'] == 'move_up'][0]
    store.event_new(ev)
    outbox.plan(ev)
    bot = FakeBot()
    attach(bot)
    asyncio.run(outbox.deliver_due())
    check('ADDR: алерт по ETH ушёл только подписчику ETH',
          [c for c, _t in bot.sent] == [UID2], [c for c, _t in bot.sent])
    check('ADDR: подписчик BTC ничего не получил', UID not in [c for c, _t in bot.sent])


def t_quiet_hours_cross_midnight():
    """ТИХИЕ ЧАСЫ: окно через полночь работает (наивная проверка даёт круглосуточную тишину)."""
    s = {'quiet_from': 22, 'quiet_to': 8}
    mid = 1800000000 - (1800000000 % 86400) + 23 * 3600
    day = 1800000000 - (1800000000 % 86400) + 12 * 3600
    check('QUIET: 23:00 внутри окна 22-8', outbox.quiet_now(s, now=mid) is True)
    check('QUIET: 12:00 вне окна 22-8', outbox.quiet_now(s, now=day) is False)
    check('QUIET: окно не задано - молчания нет', outbox.quiet_now({}) is False)


def t_enrichment_never_blocks_the_numbers():
    """ОБОГАЩЕНИЕ: второе сообщение, только доставленным, провал не трогает первое."""
    now = int(time.time())
    store.settings_set(UID, alerts_on=1, enrich_on=1, daily_cap=None)
    key = 'evtest%d' % now
    store.event_new({'key': key, 'ts': now, 'kind': 'move_up', 'ticker': 'BTC',
                     'severity': 80, 'payload': {'mark': 100.0, 'move_pct': 4.0,
                                                 'penalties': []}})
    store.delivery_plan(key, UID)
    bot = FakeBot()
    attach(bot)
    asyncio.run(outbox.deliver_due())
    check('ENRICH: сводку ждут только доставленные',
          key in store.enrich_pending(limit=10), store.enrich_pending(limit=10))
    check('ENRICH: замок на строке не даёт купить сводку дважды',
          store.enrich_claim(key) is True and store.enrich_claim(key) is False)
    brief = {'lines': ['Покупали за сутки:', '  • Fund A — $48000'],
             'refused': 'X: нет ключа TWITTERAPI_IO_KEY', 'summary': '',
             'cost_line': 'Стоимость сводки: 10 кр'}
    n = asyncio.run(outbox.deliver_enrichment(key, brief))
    check('ENRICH: сводка ушла вторым сообщением', n == 1 and len(bot.sent) == 2, bot.sent)
    txt = bot.sent[1][1]
    check('ENRICH: отказ назван КЛАССОМ, а не «не удалось»', 'нет ключа' in txt, txt)
    check('ENRICH: пересказ модели подписан как пересказ, если он есть',
          'Пересказ моделью' not in txt or 'пересказ данных выше' in txt)
    store.settings_set(UID, enrich_on=0)
    n2 = asyncio.run(outbox.deliver_enrichment(key, brief))
    check('ENRICH: выключенные сводки не шлются, а алерты - шлются', n2 == 0)
    store.settings_set(UID, enrich_on=1)


def t_budget_is_a_quantity_and_stops_spending():
    """БЮДЖЕТ: пока кап числом - он ограничивает; выключенный кап не притворяется исчерпанным.

    ПЕРЕПИСАН 25.09 вместе со сменой смысла нуля. Прежняя редакция утверждала «ноль капа =
    стоп», и это утверждение было НЕВЕРНЫМ по существу: на время хакатона Nansen бесплатен
    (решение владельца), кап выключен, и «выключен» обязано отличаться от «исчерпан» - иначе
    дозорный молча перестаёт ходить в Nansen, а лог показывает «бюджет исчерпан» при нулевом
    расходе. Старый тест на новом поведении покраснел, и это ровно то, зачем он был нужен.
    """
    os.environ['SENTINEL_NANSEN_DAY_CREDITS'] = '500'
    check('BUDGET: остаток - число, когда кап задан числом',
          isinstance(store.budget_left(), int), store.budget_left())
    check('BUDGET: пока не исчерпан - тратить можно', store.budget_block() is None)
    store.spend_add(credits=500)
    check('BUDGET: исчерпан - причина СЛОВАМИ, а не флаг',
          store.budget_block() and 'исчерпан' in store.budget_block(), store.budget_block())
    check('BUDGET: остаток обнулился', store.budget_left() == 0, store.budget_left())
    # ТИК НЕ ХОДИТ В СЕТЬ И ГОВОРИТ ПОЧЕМУ. Сам сетевой вызов здесь не проверяем (httpx может
    # отсутствовать на машине разработки - и тогда «не ходил» подтвердилось бы отказом импорта,
    # то есть по ложной причине). Проверяем ТО, ЧТО РЕШАЕТ: ворота бюджета закрыты.
    note = asyncio.run(engine.ignition_tick())
    check('BUDGET: зажигание при исчерпанном бюджете пропущено с причиной',
          'пропущено' in note and 'исчерпан' in note, note)
    store.spend_add(credits=-500)
    os.environ['SENTINEL_NANSEN_DAY_CREDITS'] = '0'


def t_lease_keeps_one_poller():
    """АРЕНДА: два процесса не опрашивают площадку одновременно."""
    check('LEASE: первый берёт', store.lease('t1', ttl=60, owner='A') is True)
    check('LEASE: второй получает отказ', store.lease('t1', ttl=60, owner='B') is False)
    check('LEASE: владелец продлевает свою', store.lease('t1', ttl=60, owner='A') is True)
    store.lease_release('t1', owner='A')
    check('LEASE: после освобождения берёт другой',
          store.lease('t1', ttl=60, owner='B') is True)
    owner, until = store.lease_owner('t1')
    check('LEASE: владелец и срок видны наружу', owner == 'B' and until > time.time())


def t_rings_and_outcome_are_measured_not_told():
    """ДВА КОЛЬЦА И ИСХОД: холодное живёт в базе, исход мерится нашими же снимками."""
    now = int(time.time())
    x = one(ticker='SOL', name='Solana', mark='150.0')
    n = store.snapshot_put([x], ts=now - 3600)
    check('RING: снимок записался', n == 1)
    hist = store.history('SOL', since_ts=now - 7200)
    check('RING: читается по индексу (PG не даёт доступ по имени)',
          hist and hist[0][1] == 150.0, hist[:1])
    store.snapshot_put([one(ticker='SOL', name='Solana', mark='156.0')], ts=now - 60)
    engine._COLD.pop('SOL', None)
    key = 'outc%d' % now
    store.event_new({'key': key, 'ts': now - 3600, 'kind': 'move_up', 'ticker': 'SOL',
                     'severity': 70, 'payload': {'mark': 150.0, 'penalties': []}})
    due = [k for k, _t, _s in store.outcome_due(60, now=now)]
    check('OUTCOME: событие старше горизонта попало в очередь замера', key in due, due[:3])
    asyncio.run(engine.outcome_tick())
    rows = store.outcomes(kind='move_up', horizon_min=60, since_ts=now - 7200)
    got = [r for r in rows if r[0] == key]
    check('OUTCOME: исход записан и посчитан от НАШИХ снимков',
          got and got[0][1] is not None and abs(got[0][1] - 4.0) < 0.2,
          got[:1])
    check('HITRATE: на малой выборке честно отказывает, а не рисует процент',
          'выборка мала' in engine.hit_rate(kind='move_up', horizon_min=60, min_sample=20),
          engine.hit_rate(kind='move_up', horizon_min=60, min_sample=20))


def t_commands_are_parsed_exactly_and_refuse_with_words():
    """КОМАНДЫ: разбор точный, отказ со словом, «дозор» в теле письма ничего не перехватывает."""
    check('CMD: голое «дозор» - состояние', ui.parse('дозор') == ('status', {}))
    check('CMD: тикер добавляет', ui.parse('дозор btc') == ('add', {'ticker': 'BTC'}))
    check('CMD: «всё» - вся площадка',
          ui.parse('дозор всё') == ('add', {'ticker': store.ALL}))
    check('CMD: убрать', ui.parse('дозор убрать ETH') == ('del', {'ticker': 'ETH'}))
    check('CMD: порог', ui.parse('дозор порог 5,5') == ('minpct', {'pct': 5.5}))
    check('CMD: тихие часы', ui.parse('дозор тихо 22 8') == ('quiet', {'from': 22, 'to': 8}))
    check('CMD: чужая фраза - НЕ наша дверь',
          ui.parse('что там по дозору думаешь') is None,
          'подстрочный матч выхватывал бы слово из тела письма')
    check('CMD: «дозор» с мусором отдаёт помощь, а не молчит',
          ui.parse('дозор абракадабра бывает')[0] == 'help')
    r = ui.route(UID, 'дозор ZZZQQ9')
    check('CMD: подписка на несуществующее отбита СЛОВАМИ',
          r and 'нет инструмента' in r, r)
    st = ui.route(UID, 'дозор')
    check('CMD: состояние ведёт величинами, а не флагами',
          st and 'Сегодня доставлено' in st and 'Пороги сейчас' in st, st)
    check('CMD: в помощи сказано, что дозорный не торгует',
          'НЕ торгует' in ui.HELP or 'НЕ советует' in ui.HELP)


def t_no_import_of_the_trading_contour():
    """ГРАНИЦА: ни один файл дозорного не знает про подписанта и торговые маршруты."""
    import re
    bad = []
    d = os.path.join(BASE, 'sentinel')
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.py'):
            continue
        src = open(os.path.join(d, fn), encoding='utf-8').read()
        # ИЩЕМ ИМПОРТЫ И ВЫЗОВЫ, А НЕ УПОМИНАНИЯ В КОММЕНТАРИЯХ: запрет на слово превратил бы
        # объяснение границы в её нарушение.
        for m in re.finditer(r'^\s*(?:import|from)\s+([\w.]+)', src, re.M):
            mod = m.group(1)
            if 'nansen_signer' in mod or mod.startswith('perp.') or mod == 'trade_session':
                bad.append('%s -> %s' % (fn, mod))
        for call in ('prepare_order', 'execute_order', 'place_order', 'sign_order'):
            if re.search(r'\b%s\s*\(' % call, src):
                bad.append('%s -> %s()' % (fn, call))
    check('ISOLATION: торгового контура в дозорном нет', not bad, bad)
    check('ISOLATION: сцены дозорного есть в закрытом реестре телеметрии',
          _scenes_ok(), 'расход дозорного лёг бы в сводку строкой «? N кр»')


def _scenes_ok():
    import nansen_log as t
    return ({'sentinel_watch', 'sentinel_ignition'} <= set(t.SCENES)
            and 'sentinel' in t.SURFACES)


def t_engine_tick_never_throws_and_always_says_something():
    """ТИК: не бросает ни при какой поломке и ВСЕГДА печатает, что произошло."""
    orig = feed.fetch

    def boom():
        raise feed.FeedError('http', 'HTTP 403', http=403)
    feed.fetch = boom
    note = asyncio.run(engine.ingest_tick())
    feed.fetch = orig
    check('TICK: отказ фида назван классом, а не «не получилось»',
          '403' in note and 'площадка не прочитана' in note, note)

    def kaput():
        raise RuntimeError('что угодно')
    feed.fetch = kaput
    note2 = asyncio.run(engine.ingest_tick())
    feed.fetch = orig
    check('TICK: любая другая поломка тоже не роняет джобу',
          'упал' in note2 or 'не прочитана' in note2, note2)
    check('TICK: строка состояния ведёт величинами',
          'инструментов за час' in outbox.status_line(), outbox.status_line())


def t_reads_close_their_cursors_and_never_lock():
    """КУРСОР ЗАКРЫТ - ЗАПИСЬ ПРОХОДИТ. Это боевой отказ, а не гигиена.

    ЖИВОЙ ПРОГОН ВЛАДЕЛЬЦА НА СЕРВЕРЕ 25.09: 14 отказов `database is locked`, все на записях.
    Причина - `execute('SELECT …').fetchone()`: недочитанный курсор держит read-транзакцию, в
    sqlite это блокирует запись, а в PostgreSQL оставляет соединение «idle in transaction».
    Локально тест был зелёным, то есть «у меня работает» тут не значило ничего.
    """
    uid = 991100
    store.settings(uid)            # fetchone
    store.cooldown_left(uid, 'BTC', 'move_up:1')
    store.sent_today(uid)
    store.event('нет такого ключа')
    store.spend_today()
    store.lease_owner('никого')
    store.cursor_get('нет')
    # ПОСЛЕ ШЕСТИ ЧТЕНИЙ ЗАПИСЬ ОБЯЗАНА ПРОЙТИ. Если курсоры остались открытыми, именно здесь
    # sqlite отдаст «database is locked» - ровно как на сервере.
    ok, why = store.sub_add(uid, 'ZZTEST')
    check('CURSOR: после серии чтений запись проходит', ok, why)
    check('CURSOR: и читается обратно', 'ZZTEST' in store.sub_list(uid))
    store.sub_del(uid, 'ZZTEST')
    src = open(os.path.join(BASE, 'sentinel', 'store.py'), encoding='utf-8').read()
    body = src[src.index('def _shut('):]
    check('CURSOR: голых fetchone/fetchall вне общих дверей нет',
          '.fetchone()' not in body and '.fetchall()' not in body,
          'каждое чтение обязано идти через _one/_all, иначе замок вернётся')


def t_sql_survives_postgres():
    """SQL ПОРТИРУЕМ. Тест на sqlite НЕ ловит PG-отказ - значит ловим текстом запроса.

    ЖИВОЙ ПРОД 25.09: джоба сводок падала КАЖДУЮ минуту с «for SELECT DISTINCT, ORDER BY
    expressions must appear in select list». На стенде и в тестах (sqlite) тот же запрос
    работал, поэтому зелёный прогон ничего не гарантировал. Правило проекта: PG-специфичный
    баг нельзя списывать как «только на тесте», потому что тест как раз зелёный.
    """
    import ast as _ast
    src = open(os.path.join(BASE, 'sentinel', 'store.py'), encoding='utf-8').read()
    # ЗАПРОСЫ БЕРЁМ ЧЕРЕЗ ast, А НЕ РЕГУЛЯРКОЙ ПО ФАЙЛУ. Неявную конкатенацию соседних строк
    # ('SELECT … ' 'FROM …') Python склеивает САМ ещё при разборе, поэтому каждый запрос - это
    # ровно один литерал. Регулярка по файлу склеивала соседние ЗАПРОСЫ между собой и ругалась
    # на несуществующее: проверка, дающая ложную тревогу, умирает первой.
    sql = [n.value for n in _ast.walk(_ast.parse(src))
           if isinstance(n, _ast.Constant) and isinstance(n.value, str)
           and 'SELECT' in n.value.upper()]
    check('PG: детектор нашёл запросы', len(sql) >= 10, len(sql))
    bad = []
    for qtext in sql:
        up = ' '.join(qtext.split()).upper()
        if 'SELECT DISTINCT' not in up or 'ORDER BY' not in up or ' FROM ' not in up:
            continue
        picked = up.split(' FROM ')[0]
        tail = up.split('ORDER BY', 1)[1].split()
        col = tail[0].strip(',').split('.')[-1] if tail else ''
        if col and col not in picked:
            bad.append(up[:140])
    check('PG: DISTINCT не сортируется по невыбранной колонке', not bad, bad)
    check('PG: у сводок ключ и время берутся группировкой',
          'GROUP BY d.event_key' in src,
          'DISTINCT + ORDER BY delivered_at - ровно тот запрос, что падал на проде')
    # ЖИВАЯ ПРОВЕРКА САМОГО ЗАПРОСА (на sqlite он тоже обязан работать и отдавать нужное).
    now = int(time.time())
    key = 'pgq%d' % now
    store.event_new({'key': key, 'ts': now, 'kind': 'move_up', 'ticker': 'BTC',
                     'severity': 50, 'payload': {'mark': 1.0, 'penalties': []}})
    store.delivery_plan(key, UID)
    store.delivery_ok(key, UID, 1)
    check('PG: запрос сводок отдаёт доставленное и необогащённое',
          key in store.enrich_pending(limit=20), store.enrich_pending(limit=20))


def t_free_hackathon_cap_does_not_block():
    """КАП ВЫКЛЮЧЕН - ЗНАЧИТ НЕ ОГРАНИЧИВАЕТ. «Выключен» не равно «исчерпан».

    РЕШЕНИЕ ВЛАДЕЛЬЦА 25.09: «всё, что связано с Нансеном, бесплатно на время хакатона;
    включай на будущее». Механизм остался, дефолт - ноль. Ноль обязан означать РОВНО «потолка
    нет»: в первой редакции `budget_left()` отдавал на нуле ноль остатка, и дозорный молча
    перестал бы ходить в Nansen - выключенный ограничитель выглядел бы как сработавший.
    """
    os.environ['SENTINEL_NANSEN_DAY_CREDITS'] = '0'
    check('FREE: дефолт капа - ноль (бесплатно на время хакатона)',
          config.nansen_day_credits() == 0, config.nansen_day_credits())
    check('FREE: ноль капа НЕ блокирует трату', store.budget_block() is None,
          store.budget_block())
    check('FREE: остаток при выключенном капе - None, а не ноль',
          store.budget_left() is None, store.budget_left())
    store.spend_add(credits=12345)
    check('FREE: расход всё равно измеряется', store.spend_today()[0] >= 12345,
          store.spend_today())
    check('FREE: и строка говорит это словами, а не «12345 из 0»',
          'кап выключен' in store.spend_line(), store.spend_line())
    note = asyncio.run(engine.ignition_tick())
    check('FREE: зажигание при выключенном капе НЕ пропускается по бюджету',
          'кап' not in note or 'исчерпан' not in note, note)
    # ВКЛЮЧЁННЫЙ КАП ПО-ПРЕЖНЕМУ РАБОТАЕТ - иначе «включай на будущее» было бы обещанием без
    # механизма.
    os.environ['SENTINEL_NANSEN_DAY_CREDITS'] = '100'
    check('FREE: включённый кап снова ограничивает',
          store.budget_block() and 'исчерпан' in store.budget_block(), store.budget_block())
    check('FREE: и строка ведёт двумя числами', ' из 100' in store.spend_line(),
          store.spend_line())
    os.environ['SENTINEL_NANSEN_DAY_CREDITS'] = '0'
    store.spend_add(credits=-12345)


def t_menu_has_buttons_for_everything_the_words_can_do():
    """МЕНЮ: включение и пороги кнопкой, состояние подписью, и ни одной кириллицы на en.

    ТРЕБОВАНИЕ ВЛАДЕЛЬЦА ДОСЛОВНО: «пороги должны быть настраиваемые и само включение/
    выключение дозора должно идти через какое-то меню». Тест держит ДВА утверждения: кнопки
    реально меняют настройку (а не просто рисуются) и подпись тумблера говорит СОСТОЯНИЕ.
    """
    uid = 991200
    store.settings_set(uid, alerts_on=1, enrich_on=1, min_pct=None, daily_cap=None,
                       cooldown_min=None, quiet_from=None, quiet_to=None)
    kb = ui.menu_kb(uid, 'ru')
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    for need in ('sen:t:al', 'sen:t:br', 'sen:t:all', 'sen:mp:1', 'sen:mp:-1', 'sen:cd:15',
                 'sen:cap:5', 'sen:q:next', 'sen:rep', 'sen:home'):
        check('MENU: кнопка %s есть' % need, need in data, data)
    txt = ui.menu_text(uid, 'ru')
    check('MENU: подпись тумблера говорит СОСТОЯНИЕ, а не действие',
          any('Алерты: вкл' in b.text for row in kb.inline_keyboard for b in row),
          [b.text for row in kb.inline_keyboard for b in row])
    check('MENU: экран называет общие пороги (их кнопками не крутят)',
          'Общие пороги' in txt, txt)
    check('MENU: и говорит, что Nansen сейчас бесплатен', 'бесплат' in txt.lower(), txt)

    # ── КНОПКИ РЕАЛЬНО МЕНЯЮТ НАСТРОЙКУ (гоняем сам роутер с фальшивым callback) ──
    class Q:
        def __init__(self, uid, data):
            self.data = data
            self.from_user = type('U', (), {'id': uid})()
            self.message = type('M', (), {'chat_id': uid, 'text': 'x'})()
            self.shown = []

        async def answer(self, *a, **kw):
            return True

        async def edit_message_text(self, text, reply_markup=None, **kw):
            self.shown.append(text)
            return True

    class Ctx:
        class bot:
            sent = []

            @staticmethod
            async def send_message(chat_id=None, text=None, **kw):
                Ctx.bot.sent.append((chat_id, text))
                return True

    def tap(data):
        q = Q(uid, data)
        asyncio.run(ui.handle_callback(type('U', (), {'callback_query': q})(), Ctx()))
        return q

    tap('sen:t:al')
    check('MENU: тумблер выключил алерты', store.settings(uid)['alerts_on'] == 0)
    tap('sen:t:al')
    check('MENU: и включил обратно', store.settings(uid)['alerts_on'] == 1)
    tap('sen:t:all')
    check('MENU: «вся площадка» подписала', store.ALL in store.sub_list(uid))
    tap('sen:t:all')
    check('MENU: и отписала', store.ALL not in store.sub_list(uid))
    tap('sen:mp:1')
    check('MENU: порог поднялся на 1%', store.settings(uid)['min_pct'] == 1.0,
          store.settings(uid)['min_pct'])
    tap('sen:mp:-1')
    check('MENU: и вернулся к «как общий», а не в минус',
          store.settings(uid)['min_pct'] is None, store.settings(uid)['min_pct'])
    check('MENU: порог не уходит ниже нуля и не выше 50',
          ui._step_pct(0.5, -1) is None and ui._step_pct(49, 5) == 50.0)
    tap('sen:cd:15')
    check('MENU: пауза стала личной и выросла',
          store.settings(uid)['cooldown_min'] == (config.cooldown_sec() // 60) + 15,
          store.settings(uid)['cooldown_min'])
    check('MENU: личная пауза сильнее общей',
          store.cooldown_for(uid) == store.settings(uid)['cooldown_min'] * 60)
    tap('sen:cd:0')
    check('MENU: сброс паузы возвращает общую',
          store.cooldown_for(uid) == config.cooldown_sec())
    tap('sen:cap:-5')
    check('MENU: потолок опустился', store.cap_for(uid) == config.daily_cap() - 5,
          store.cap_for(uid))
    q = tap('sen:q:next')
    check('MENU: тихие часы идут по лестнице', store.settings(uid)['quiet_from'] == 22,
          store.settings(uid))
    check('MENU: экран перерисовывается НА МЕСТЕ, а не новым сообщением', q.shown, 'нет edit')
    q2 = tap('sen:rep')
    check('MENU: отчёт уходит отдельным сообщением',
          any('Попадания' in (t or '') for _c, t in Ctx.bot.sent), Ctx.bot.sent[-1:])

    # ── ДВА ЯЗЫКА. По меню ходит обходчик e2e и требует, чтобы на en кириллицы не было. ──
    import re as _re
    en = ui.menu_text(uid, 'en') + ' '.join(b.text for row in ui.menu_kb(uid, 'en').inline_keyboard
                                            for b in row)
    check('MENU: на en кириллицы нет', not _re.search(r'[А-Яа-яЁё]', en),
          _re.findall(r'[А-Яа-яЁё]+', en)[:6])
    check('MENU: английская справка тоже без кириллицы',
          not _re.search(r'[А-Яа-яЁё]', ui.HELP_EN.replace('дозор', '')),
          'команды по-русски оставлены нарочно - их набирают словами')


def t_words_and_buttons_share_one_parser():
    """СЛОВА И КНОПКИ - ОДИН РАЗБОР. Разойдись они, половина команд тихо перестала бы работать."""
    uid = 991300
    sent = []

    class Bot:
        @staticmethod
        async def send_message(chat_id=None, text=None, reply_markup=None, **kw):
            sent.append((chat_id, text, reply_markup))
            return True

    check('ROUTE: чужая фраза не перехвачена',
          asyncio.run(ui.route_send(Bot, uid, 'что там по дозору')) is False)
    check('ROUTE: «дозор» отдал экран С КЛАВИАТУРОЙ',
          asyncio.run(ui.route_send(Bot, uid, 'дозор')) is True and sent
          and sent[-1][2] is not None, sent[-1:] if sent else None)
    asyncio.run(ui.route_send(Bot, uid, 'дозор порог 4'))
    check('ROUTE: порог словами лёг в ту же настройку',
          store.settings(uid)['min_pct'] == 4.0, store.settings(uid))
    check('ROUTE: и после правки показан экран',
          sent and sent[-1][2] is not None, sent[-1:])


def t_kinds_and_parts_are_the_subscribers_choice():
    """ЧТО ПРИСЫЛАТЬ И ЧТО ВНУТРИ - ВЫБОР ЧЕЛОВЕКА, И ОТСЕВ СТОИТ НА ДОСТАВКЕ, А НЕ В ДЕТЕКТОРЕ.

    ПРОСЬБА ВЛАДЕЛЬЦА ДОСЛОВНО: «настраивать, что приходят алерты движения плюс нансен движения
    существенные, или просто Нансен сигналы, или просто алерты по объёму»; «в настройках можно
    включить, что в алерте приходит: только карточка наша обычная … и включать ли сразу новости и
    что с нансена инфа».

    ОТСЕВ ИМЕННО НА ДОСТАВКЕ: событие одно на всех и пишется в базу целиком (оно нужно отчёту
    попаданий), а получатели у него разные. Отсей в детекторе - и отчёт считал бы попадания
    только по тем видам, что кто-то включил.
    """
    uid = 991400
    check('KINDS: по умолчанию спред и фандинг ВЫКЛЮЧЕНЫ (они не повод звонить)',
          store.kinds_for(uid) == set(config.DEFAULT_KINDS)
          and 'spread_shock' not in store.kinds_for(uid)
          and 'funding_extreme' not in store.kinds_for(uid), store.kinds_for(uid))
    check('KINDS: движения, интерес и зажигание - включены',
          {'move_up', 'move_down', 'oi_surge', 'ignition'} <= store.kinds_for(uid))
    store.kinds_set(uid, {'ignition'})
    check('KINDS: «только сигналы Нансена» собирается одним набором',
          store.kinds_for(uid) == {'ignition'}, store.kinds_for(uid))

    now = int(time.time())
    store.sub_add(uid, 'BTC')
    store.settings_set(uid, alerts_on=1, enrich_on=0)
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    mv = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                     ring=ring) if e['kind'] == 'move_up'][0]
    store.event_new(mv)
    n, why = outbox.plan(mv)
    check('KINDS: движение выключенному виду НЕ уходит', n == 0, (n, why))
    check('KINDS: и причина названа словами',
          any('выключен в настройках' in w for w in why), why)
    store.kinds_set(uid, set(config.DEFAULT_KINDS))
    mv2 = dict(mv, key=mv['key'] + 'k2')
    store.event_new(mv2)
    check('KINDS: после включения - уходит', outbox.plan(mv2)[0] == 1)

    # ── СОСТАВ АЛЕРТА ──
    check('PARTS: по умолчанию едут ончейн и новости',
          {'nansen', 'news'} <= store.parts_for(uid), store.parts_for(uid))
    store.part_toggle(uid, 'news')
    check('PARTS: новости выключаются', 'news' not in store.parts_for(uid))
    store.part_toggle(uid, 'nansen')
    check('PARTS: ончейн выключается', 'nansen' not in store.parts_for(uid))
    check('PARTS: числа площадки выключить НЕЛЬЗЯ',
          'card' in store.part_toggle(uid, 'card'),
          'алерт без чисел - уведомление «что-то случилось» без ответа «что именно»')
    store.parts_set(uid, {'nansen', 'news'})


def t_news_are_fresh_relevant_and_not_from_nobody():
    """ТВИТТЕР: три отсева, и каждый оплачен живой сводкой 25.09.

    ЗАМЕР ВЛАДЕЛЬЦА. При окне запроса 90 минут в сводку попали твиты возрастом 9 дней, 14 дней и
    175 дней; аккаунты на 8, 16 и 93 подписчика; и японский список форекс-пар в ответ на запрос
    «UKOILP». То есть сломаны были ВСЕ ТРИ измерения сразу: свежесть, вес источника и тема.
    Главный вывод - фильтру провайдера доверять нельзя: `since_minutes` был передан.
    """
    from sentinel import enrichment as en
    try:
        import twitter_api as tw
    except ImportError:
        # ПРОПУСК НАЗЫВАЕТ СЕБЯ, А НЕ ПРИТВОРЯЕТСЯ УСПЕХОМ. Публичная выжимка не несёт слой X
        # (он не про Nansen), и падать там нечем - но и делать вид, что проверка прошла, нельзя:
        # молчаливо «зелёный» пропуск это тот же дефект, что молчаливый отказ.
        global _SKIP
        _SKIP += 1
        print('SKIP  твиттер-фильтры: в этой сборке нет модуля X (в боте проверка идёт)')
        return
    now = 1800000000

    def tweet(mins_ago, followers, text):
        import datetime
        d = datetime.datetime.utcfromtimestamp(now - mins_ago * 60)
        return {'createdAt': d.strftime('%a %b %d %H:%M:%S +0000 %Y'),
                'text': text, 'author': {'userName': 'x', 'followers': followers}}

    fresh = tweet(30, 5000, 'UKOILP looks strong today')
    check('X: свежий и весомый твит проходит', en._fresh_enough(fresh, now, tw)
          and en._relevant(fresh, 'UKOILP', 'Swap on Brent Crude Oil', tw))
    old = tweet(9 * 24 * 60, 8600, 'UKOILP spread chart')
    check('X: твит девятидневной давности НЕ проходит по свежести',
          not en._fresh_enough(old, now, tw),
          'ровно он и стоял в живой сводке при окне 90 минут')
    check('X: твит без разобранного возраста тоже НЕ проходит',
          not en._fresh_enough({'text': 'UKOILP', 'createdAt': 'какая-то чушь'}, now, tw),
          '«разобрать не смогли» не может означать «сойдёт»')
    off = tweet(10, 9000, 'XAGUSDp = silver, US100p = nasdaq, JP225p = nikkei')
    check('X: чужой список тикеров отсеивается по теме',
          not en._relevant(off, 'UKOILP', 'Swap on Brent Crude Oil', tw), 'японский список')
    # ── ЗАПРОС СТРОИТСЯ ИЗ ИМЕНИ, А НЕ ИЗ ТИКЕРА ПЛОЩАДКИ ──
    q = en._q_for('UKOILP', 'Swap on Brent Crude Oil')
    check('X: в запросе есть человеческое имя актива', 'Brent' in q, q)
    check('X: и тикер с решёткой доллара', '$UKOILP' in q, q)
    q2 = en._q_for('MSTR', 'Strategy Inc')
    check('X: юридический хвост из запроса убран',
          'Inc' not in q2 and 'Strategy' in q2, q2)
    check('X: порог веса аккаунта назван числом', config.x_min_followers() >= 500,
          config.x_min_followers())


def t_wallet_sizes_are_read_not_lost():
    """«РАЗМЕР НЕ НАЗВАН» У КАЖДОГО КОШЕЛЬКА - ЭТО БЫЛ НАШ БАГ, А НЕ МОЛЧАНИЕ ПЛОЩАДКИ.

    ЗАМЕР ВЛАДЕЛЬЦА: в живой сводке восемь кошельков подряд и у всех «размер не назван». Мы
    искали объём в `volume_usd`/`value_usd`, а `tgm/who-bought-sold` отдаёт
    `bought_volume_usd`/`sold_volume_usd` - имена стоят в `order_by` НАШЕГО ЖЕ клиента, то есть
    были известны и не использованы. Сводка выглядела собранной и не несла ни одного числа.
    """
    from sentinel import enrichment as en
    rows = [{'address': '0x' + 'ab' * 20, 'address_label': 'Fund A',
             'bought_volume_usd': 48000},
            {'address': '0x' + 'cd' * 20, 'sold_volume_usd': 91000},
            {'address': '0x' + 'ef' * 20}]
    out = en._who_lines(rows, 'Покупали за сутки', bot_un='testbot')
    body = '\n'.join(out)
    check('WHO: bought_volume_usd прочитан', '$48.0k' in body, body)
    check('WHO: sold_volume_usd прочитан', '$91.0k' in body, body)
    check('WHO: где размера правда нет - сказано словами',
          'размер не назван' in body, body)
    # ПРОВЕРЯЕМ ВИДИМЫЙ ТЕКСТ, А НЕ ИСХОДНИК СТРОКИ: адрес обязан быть в АТРИБУТЕ ссылки (по нему
    # открывается экран кошелька) и не обязан быть на экране - человек читает метку, а сорок два
    # символа hex не читает и не сравнивает. Первая редакция проверки смотрела на строку целиком
    # и краснела на своей же ссылке.
    import re as _re2
    seen = _re2.sub(r'<[^>]+>', '', body)
    check('WHO: метка читается вместо сорока двух символов hex',
          'Fund A' in seen and ('0x' + 'ab' * 20) not in seen, seen)
    check('WHO: адрес без метки сокращён', '0xcdcd…cdcd' in body, body)
    check('WHO: кошелёк - ССЫЛКА на свой экран в боте',
          't.me/testbot?start=acc_0x' in body, body)
    check('WHO: и цена одного токена под сумму НЕ берётся',
          'price_usd' not in en._VOL_FIELDS,
          'спутать их значит напечатать $0.99 вместо $48K')


def t_locked_diagnosis_prints_measurements():
    """ЕСЛИ БАЗА ОТКАЖЕТ - ТЕСТ ПЕЧАТАЕТ ЗАМЕРЫ, А НЕ ТОЛЬКО ТЕКСТ ОШИБКИ.

    ПОЧЕМУ ЭТО ОТДЕЛЬНАЯ ПРОВЕРКА. На сервере владельца тест дал 14 отказов `database is
    locked`, и разобрать их по логу было нельзя: один текст ошибки покрывает несколько причин
    (чужой процесс на том же файле, открытая транзакция, WAL, не применённый busy_timeout).
    ГИПОТЕЗА «ВИНОВАТЫ НЕДОЧИТАННЫЕ КУРСОРЫ» БЫЛА ПРОВЕРЕНА ОПЫТОМ И НЕ ПОДТВЕРДИЛАСЬ: в WAL
    чтение и запись идут параллельно, повтор на чистом sqlite замок не даёт. Курсоры всё равно
    закрываются (на PostgreSQL незакрытый курсор оставляет «idle in transaction»), но выдавать
    это за причину было бы ложью - и именно так опровергнутая гипотеза возвращается через день.
    Поэтому здесь не догадка, а ЗАМЕР: следующий отказ приедет с путём, бэкендом, режимом
    журнала и таймаутом, и разбор займёт один круг, а не три.
    """
    diag = _db_diag()
    for word in ('backend=', 'path=', 'journal_mode=', 'busy_timeout='):
        check('DIAG: в замерах есть %s' % word, word in diag, diag)
    check('DIAG: путь ведёт во временный каталог', _TMP in diag, diag)
    check('DIAG: замер снимается с ЖИВОГО соединения, а не из настроек',
          'wal' in diag.lower() or 'delete' in diag.lower() or 'postgres' in diag.lower(),
          diag)


def t_silence_is_explained_by_numbers_not_by_faith():
    """«ВКЛЮЧИЛ, ПОКА НИЧЕГО НЕ ПРИШЛО» ОБЯЗАН ИМЕТЬ ОТВЕТ ЧИСЛОМ.

    ЖИВОЙ СЛУЧАЙ 25.09. Владелец включил дозорного и не получил ни одного алерта о движении.
    Это была ПРАВДА ПРО РЫНОК, а не поломка: замер пяти снимков с шагом 45 секунд показал, что
    за ТРИ МИНУТЫ ни один из 553 инструментов не изменил `mark_price`, а у BTC цена держалась
    две минуты и сдвинулась на 0.016%. Но узнать это человеку было НЕГДЕ - молчание дозорного и
    его смерть выглядят одинаково.

    ЗДЕСЬ ПРОВЕРЯЕТСЯ ИМЕННО РАЗЛИЧИМОСТЬ: экран обязан назвать, сколько инструментов вообще
    сдвинулось, каково сильнейшее движение и как оно соотносится с порогом.
    """
    # ВРЕМЯ БЕРЁМ НАСТОЯЩЕЕ: экран `now_text` спрашивает рынок «сейчас» и своего аргумента
    # времени не имеет - он показывает человеку то, что есть в кольце В ЭТУ МИНУТУ. Синтетическое
    # время из прошлого дало бы пустой срез, и тест проверял бы не экран, а свою фикстуру.
    now = int(time.time())
    engine._HOT.clear()
    # Кольцо из двух точек: один инструмент двинулся на 0.4%, остальные стоят.
    for t, (p0, p1) in (('AAA', (100.0, 100.4)), ('BBB', (50.0, 50.0)), ('CCC', (7.0, 7.0))):
        engine._HOT[t] = [(now - 900, p0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900),
                          (now, p1, 8e8, 1000.0, 900.0, 0.05, 1.0, now)]
    m = engine.market_now(now=now)
    check('NOW: срез не ходит в сеть и считает по кольцу', m['tickers'] == 3, m['tickers'])
    check('NOW: сильнейшее движение измерено', abs(m['best'] - 0.4) < 0.01, m.get('best'))
    check('NOW: сказано, сколько инструментов ВООБЩЕ сдвинулось',
          m['stirred'] == 1 and m['measured'] == 3, (m['stirred'], m['measured']))
    txt = ui.now_text('ru')
    check('NOW: экран называет и движение, и порог',
          '0.40%' in txt and ('%.2f%%' % config.move_pct_15m()) in txt, txt)
    check('NOW: и говорит, что тихо НА РЫНКЕ, а не в дозорном',
          'тихо на рынке' in txt, txt)
    check('NOW: пустое кольцо тоже объяснено словами',
          'Кольцо пустое' in (engine._HOT.clear() or ui.now_text('ru')), ui.now_text('ru'))
    check('NOW: на en кириллицы нет',
          not __import__('re').search(r'[А-Яа-яЁё]', ui.now_text('en')), ui.now_text('en'))


def t_hot_ring_actually_grows():
    """ГОРЯЧЕЕ КОЛЬЦО ОБЯЗАНО РАСТИ. Без второй точки нет доходности - и нет ни одного движения.

    ТИХИЙ БАГ, НАЙДЕННЫЙ ЗАМЕРОМ 25.09: при опросе чаще разрешения кольца последняя точка
    ПЕРЕЗАПИСЫВАЛАСЬ вместе со своим временем, поэтому интервал до неё никогда не накапливался -
    каждый следующий опрос снова оказывался «слишком рано». Кольцо на любом инструменте вечно
    оставалось длиной в ОДНУ точку («в кольце 553 инструментов, 1 точек на инструмент»), а
    значит доходность за 15 и 60 минут была невычислима и событий движения не возникало НИКОГДА.
    Тик при этом исправно печатал «опрошено 553 инстр.».
    """
    engine._HOT.clear()
    x = one(ticker='RING', name='Ring Test', mark='100.0')
    base = 1800000000
    for i in range(6):
        engine._hot_put(x, base + i * 30)        # опрос раз в 30с
    arr = engine._HOT['RING']
    check('RING: шесть опросов дали шесть точек, а не одну', len(arr) == 6, len(arr))
    check('RING: время точек растёт', [r[0] for r in arr] == sorted(r[0] for r in arr))
    engine._hot_put(x, base + 5 * 30)            # тот же миг: наложение тиков
    check('RING: два тика в одну секунду дают одну точку',
          len(engine._HOT['RING']) == 6, len(engine._HOT['RING']))
    old = engine._hot_put(x, base + 200 * 60)    # далеко в будущем - старое выпадает
    check('RING: точки старше глубины выпадают', len(old) < 7, len(old))
    engine._HOT.clear()


def t_volume_is_its_own_signal():
    """ОБЪЁМ - ОТДЕЛЬНЫЙ ВИД СОБЫТИЯ, И НА ЭТОЙ ПЛОЩАДКЕ ОН ВАЖНЕЕ ЦЕНЫ.

    Просьба владельца: «или просто алерты по объёму». Замер подтверждает, что это не каприз:
    марк-цена стоит минутами, а оборот растёт непрерывно - то есть приход денег виден по объёму
    РАНЬШЕ, чем по цене.
    """
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [(now - 3600, 100.0, 1.0e6, 1000.0, 900.0, 0.05, 1.0, now - 3600)]
    evs = detector.detect(one(mark='100.0', vol='2000000', quote_iso=_iso(now)), hot, now=now,
                          ring=ring)
    vs = [e for e in evs if e['kind'] == 'vol_surge']
    check('VOL: оборот вырос вдвое - событие', vs, {e['kind'] for e in evs})
    check('VOL: прирост назван и в процентах, и в деньгах',
          vs and abs(vs[0]['payload']['vol_change_pct'] - 100.0) < 1
          and vs[0]['payload']['vol_change_usd'] == 1.0e6,
          vs[0]['payload'] if vs else None)
    txt = cards.card(vs[0]) if vs else ''
    check('VOL: карточка ведёт оборотом', 'оборот <b>+100.00%</b>' in txt, txt[:140])
    # МАЛЫЙ ПРИРОСТ В ДЕНЬГАХ - НЕ СОБЫТИЕ (тот же закон, что у спреда и интереса)
    small = detector.detect(one(mark='100.0', vol='75000', quote_iso=_iso(now)),
                            [(now - 3600, 100.0, 60000, 1000.0, 900.0, 0.05, 1.0, now - 3600)],
                            now=now, ring=ring)
    check('VOL: +25% к обороту в $60k событием НЕ считается',
          'vol_surge' not in {e['kind'] for e in small}, {e['kind'] for e in small})
    check('VOL: вид включён по умолчанию', 'vol_surge' in config.DEFAULT_KINDS,
          config.DEFAULT_KINDS)


def t_db_failure_speaks_with_measurements():
    """ОТКАЗ БАЗЫ ПЕЧАТАЕТ ЗАМЕРЫ РЯДОМ С СОБОЙ, А НЕ ТОЛЬКО ТЕКСТ ОШИБКИ.

    На сервере владельца `database is locked` пришло ДВАЖДЫ: в тесте и в живой доставке
    («доставка не поставлена: database is locked»). Один этот текст покрывает несколько причин, и
    прошлая догадка (недочитанные курсоры) была проверена опытом и НЕ подтвердилась. Значит
    строка отказа обязана нести замеры - иначе следующий круг снова уйдёт на гадание.
    """
    d = store.diag()
    for word in ('backend=', 'file=', 'journal_mode=', 'busy_timeout=', 'поток='):
        check('DBFAIL: в замерах есть %s' % word, word in d, d)
    check('DBFAIL: файл назван ЖИВЫМ соединением и он временный', _TMP in d, d)
    src = open(os.path.join(BASE, 'sentinel', 'store.py'), encoding='utf-8').read()
    check('DBFAIL: все отказы записи идут через одну дверь с замерами',
          src.count('_say_fail(') >= 4 and 'def _say_fail' in src,
          'замеры в каждом except по месту однажды забудут в одном из десяти')


def main():
    for fn in (t_parse_is_real_and_names_what_is_missing,
               t_detector_needs_both_percent_and_sigma,
               t_event_key_is_stable_and_step_escalates,
               t_oi_funding_and_spread_have_their_own_reasons,
               t_card_leads_with_magnitude_and_admits_limits,
               t_ignition_counts_wallets_not_trades_and_first_poll_is_silent,
               t_delivery_dedupe_cooldown_cap_and_state,
               t_two_subscribers_each_get_only_their_own,
               t_quiet_hours_cross_midnight,
               t_enrichment_never_blocks_the_numbers,
               t_budget_is_a_quantity_and_stops_spending,
               t_lease_keeps_one_poller,
               t_rings_and_outcome_are_measured_not_told,
               t_commands_are_parsed_exactly_and_refuse_with_words,
               t_no_import_of_the_trading_contour,
               t_engine_tick_never_throws_and_always_says_something,
               # ── круг 2 (25.09): боевые отказы с прода Ren + меню и бесплатный Nansen ──
               t_reads_close_their_cursors_and_never_lock,
               t_sql_survives_postgres,
               t_free_hackathon_cap_does_not_block,
               t_menu_has_buttons_for_everything_the_words_can_do,
               t_words_and_buttons_share_one_parser,
               # ── круг 3 (25.09): спам, формат, мусорные новости, настройки состава ──
               t_kinds_and_parts_are_the_subscribers_choice,
               t_news_are_fresh_relevant_and_not_from_nobody,
               t_wallet_sizes_are_read_not_lost,
               t_locked_diagnosis_prints_measurements,
               # ── круг 4 (25.09): почему было тихо, и чем это доказано ──
               t_silence_is_explained_by_numbers_not_by_faith,
               t_hot_ring_actually_grows,
               t_volume_is_its_own_signal,
               t_db_failure_speaks_with_measurements):
        print('\n== %s' % fn.__name__)
        try:
            fn()
        except Exception as e:
            global _FAIL
            _FAIL += 1
            import traceback
            traceback.print_exc()
            print('FAIL  %s упал: %s' % (fn.__name__, e))
            # ЗАМЕРЫ БАЗЫ РЯДОМ С ОТКАЗОМ, А НЕ В ГОЛОВЕ РАЗБИРАЮЩЕГО. `database is locked` без
            # пути, бэкенда и таймаута - это приглашение гадать; с ними разбор идёт по числам.
            print('      замеры базы: %s' % _db_diag())
    print('\n%d PASS / %d FAIL%s' % (_OK, _FAIL,
                                    (' / %d SKIP' % _SKIP) if _SKIP else ''))
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
