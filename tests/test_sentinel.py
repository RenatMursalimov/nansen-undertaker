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

# ══════════════════════════════════════════════════════════════════════════════════════════
# ПОРОГИ ДОЗОРНОГО ОТВЯЗЫВАЕМ ОТ МАШИНЫ. НЕ ПЕДАНТИЗМ - ЖИВОЙ ОТКАЗ 26.09
#
# `db.py` НА ИМПОРТЕ ЗОВЁТ `env_load.load()`, и на сервере это подтягивает боевой `.env`
# (у владельца 108 ключей). Все пороги дозорного читаются ИЗ ОКРУЖЕНИЯ на каждом вызове -
# значит боевые значения переопределяли их прямо в тесте. Живой прогон владельца дал 16
# отказов там, где в разработке 426 PASS, и причина была не в коде, а в том, что у теста
# НЕ БЫЛО СВОИХ ПОРОГОВ.
#
# ОСОБЕННО ЗЛО ЗДЕСЬ `SENTINEL_DELIVER=0` - аварийный рубильник отправки, который я САМ велел
# владельцу поставить в `.env`, чтобы погасить поток. То есть выполнение моей же инструкции
# ломало проверки: тест «после ретрая алерт ушёл» не мог пройти, потому что отправка выключена
# на уровне машины. Проверка, зависящая от чужой настройки, не проверяет ничего.
#
# ЧИСТИМ ВСЁ `SENTINEL_*` И СТАВИМ СВОЁ. Список НЕ перечисляем по именам: ключей уже за
# тридцать, и забытый в списке однажды вернёт этот же баг. Удаляем по префиксу, затем ставим
# ровно то, что тесту нужно осознанно.
for _ek in [k for k in list(os.environ) if k.startswith('SENTINEL_')]:
    os.environ.pop(_ek, None)
os.environ['SENTINEL_LLM_OFF'] = '1'            # пересказ моделью в тестах не зовётся
os.environ['SENTINEL_VENUES'] = 'variational'   # фикстуры сняты с одной площадки
# ДЕФОЛТЫ ПРЕДОХРАНИТЕЛЯ И ПОРОГА ЗВОНКА СТАВИМ ЯВНО, А НЕ НАДЕЕМСЯ НА КОД: значения из
# `config` могут поменяться по живому замеру (и уже менялись трижды), а ожидания тестов
# записаны числами. Пусть расхождение ловится здесь, а не «загадочным» отказом ниже.
os.environ['SENTINEL_DELIVER'] = '1'
os.environ['SENTINEL_BURST_MAX'] = '3'
os.environ['SENTINEL_BURST_WINDOW_SEC'] = '600'
os.environ['SENTINEL_MIN_SEVERITY'] = '75'
os.environ['SENTINEL_DIGEST_SEC'] = '600'
os.environ['SENTINEL_NANSEN_DAY_CREDITS'] = '0'

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

# ── ТИК В ОДНОМ ПОТОКЕ: УБИРАЕМ ИЗ ТЕСТА ТО, ЧЕГО НЕТ НА ПРОДЕ ─────────────────────────────
# ЗАМЕР С СЕРВЕРА ВЛАДЕЛЬЦА НАЗВАЛ ПРИЧИНУ САМ: `backend=sqlite · file=/tmp/… · journal_mode=wal
# · busy_timeout=60000 · поток=MainThread`. Файл правильный (временный), таймаут ожидания
# минута - и при этом `database is locked` приходит мгновенно. Так выглядит НЕ нехватка
# терпения, а гонка двух соединений одного процесса: часть тика уходит в `asyncio.to_thread`,
# пул потоков открывает ВТОРОЕ соединение к тому же файлу, и sqlite отказывает сразу.
# ПРОД ЭТОГО КЛАССА ОТКАЗА НЕ ЗНАЕТ: там PostgreSQL, где параллельные соединения - штатный
# режим (`backend=postgres` в той же строке замеров это и показывает). То есть падал не
# дозорный, а sqlite под тестовой многопоточностью.
# ПОЭТОМУ ЗДЕСЬ НЕ «ПОЧИНКА», А ЧЕСТНОЕ СУЖЕНИЕ: тик выполняется в одном потоке, и тест
# проверяет ЛОГИКУ дозорного, а не поведение sqlite при гонке. Подмена объявлена вслух
# ровно затем, чтобы никто не принял её за исправление настоящей проблемы.
_real_to_thread = asyncio.to_thread


async def _same_thread(fn, *a, **kw):
    return fn(*a, **kw)


asyncio.to_thread = _same_thread

from sentinel import cards, clusters, config, detector, engine, ignition  # noqa: E402
from sentinel import lab, outbox, store, ui                     # noqa: E402
from sentinel import variational_feed as feed    # noqa: E402
from sentinel import venues                      # noqa: E402

# ТОЛЬКО VARIATIONAL В ТЕСТАХ: вторая площадка - живая сеть, а тесты сети не требуют.
# Список площадок сужаем ЯВНО, а не через окружение: окружение на машине разработчика
# может быть любым, и тест не имеет права зависеть от него.
venues.DEFAULT_VENUES = ('variational',)

UID = 990001
UID2 = 990002
_OK, _FAIL, _SKIP = 0, 0, 0
#: ИМЕНА УПАВШИХ ПРОВЕРОК. Без списка в конце человек читает «11 FAIL» и идёт
#: перелистывать тысячу строк вывода - а прислать одну строку итога дешевле для всех.
_FAILED = []


def check(name, cond, note=''):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print('  ok  %s' % name)
    else:
        _FAIL += 1
        _FAILED.append(name)
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
    # ССЫЛКА ТЕПЕРЬ ВЕДЁТ НА САМ ИНСТРУМЕНТ, А НЕ НА КОРЕНЬ: путь измерен браузером 25.09
    # (`/perpetual/<TICKER>`), и проверка обновлена вместе с поведением - тест на корень
    # краснел бы именно потому, что стало лучше.
    check('CARD: ссылка ведёт на инструмент площадки',
          '<a href="https://omni.variational.io/perpetual/BTC"' in txt, txt[-200:])
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
    # КОМАНДА «ДОЗОР» ВЕДЁТ В ТОТ ЖЕ ЭКРАН, ЧТО И КНОПКА. Раньше `route` отдавал `status_text`,
    # а человек получал `menu_text` - два источника правды на один экран, и тест охранял текст,
    # которого никто не видел. Проверяем ВЕЛИЧИНЫ, а не конкретную строку конкретной функции.
    check('CMD: состояние ведёт величинами, а не флагами',
          st and 'Сегодня доставлено' in st and 'Предохранитель' in st, st)
    check('CMD: и это ТОТ ЖЕ текст, что уходит с клавиатурой',
          st == ui.menu_text(UID, 'ru'),
          'иначе тест проверяет один экран, а человек читает другой')
    # ПОЛНЫЙ РАЗРЕЗ (общие пороги) ОСТАЛСЯ ДОСТУПЕН - в развёрнутом виде и без клавиатуры.
    check('CMD: общие пороги видны в развёрнутом виде',
          'Общие пороги' in (ui.menu_text(UID, 'ru') if ui._ADV.get(UID) else
                             (ui._ADV.__setitem__(UID, True) or ui.menu_text(UID, 'ru'))),
          'их кнопками не крутят, но знать по чему работает дозор человек должен')
    ui._ADV.pop(UID, None)
    check('CMD: и в бесклавиатурной сводке тоже',
          'Пороги сейчас' in ui.status_text(UID), ui.status_text(UID))
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
    orig = venues.VENUES['variational']['fetch']

    async def boom():
        raise feed.FeedError('http', 'HTTP 403', http=403)
    venues.VENUES['variational']['fetch'] = boom
    note = asyncio.run(engine.ingest_tick())
    venues.VENUES['variational']['fetch'] = orig
    check('TICK: отказ фида назван классом, а не «не получилось»',
          '403' in note and 'не прочитана' in note, note)

    async def kaput():
        raise RuntimeError('что угодно')
    venues.VENUES['variational']['fetch'] = kaput
    note2 = asyncio.run(engine.ingest_tick())
    venues.VENUES['variational']['fetch'] = orig
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
    # ═══ ДОСТИЖИМОСТЬ ПРОВЕРЯЕМ НА ОБЪЕДИНЕНИИ ДВУХ ЭКРАНОВ, А НЕ НА ОДНОМ ═══
    # Круг 10 разделил клавиатуру: частое сразу, редкое под «Ещё» (замечание владельца - экран
    # дорос до двадцати рядов). Требование «всё, что умеют слова, доступно кнопками» от этого
    # не изменилось - изменилось ЧИСЛО ТАПОВ до кнопки. Поэтому проверяем, что каждая кнопка
    # достижима ХОТЯ БЫ В ОДНОМ из двух видов, и отдельно - что редкие лежат именно под «Ещё».
    ui._ADV.pop(uid, None)
    kb = ui.menu_kb(uid, 'ru')
    main_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    ui._ADV[uid] = True
    kb_adv = ui.menu_kb(uid, 'ru')
    data = main_data + [b.callback_data for row in kb_adv.inline_keyboard for b in row]
    for need in ('sen:t:al', 'sen:t:br', 'sen:t:all', 'sen:mp:1', 'sen:mp:-1', 'sen:cd:15',
                 'sen:cap:5', 'sen:q:next', 'sen:rep', 'sen:home', 'sen:adv:x',
                 'sen:bm:1', 'sen:bw:5', 'sen:sv:5'):
        check('MENU: кнопка %s достижима' % need, need in data, data)
    # ── ОСНОВНОЙ ЭКРАН КОРОТКИЙ, И ЭТО ИЗМЕРИМО ──────────────────────────────────────────
    check('MENU: основной экран не больше 7 рядов', len(kb.inline_keyboard) <= 7,
          'было 20 - экран, на котором всё одинаково важно, не помогает решать')
    check('MENU: главный тумблер стоит ПЕРВЫМ и один в ряду',
          len(kb.inline_keyboard[0]) == 1
          and kb.inline_keyboard[0][0].callback_data == 'sen:t:al',
          [b.text for b in kb.inline_keyboard[0]])
    check('MENU: пресеты на основном экране (самый частый способ настроить)',
          'sen:pr:normal' in main_data, main_data)
    for _rare in ('sen:bm:1', 'sen:bw:5', 'sen:sv:5', 'sen:cd:15', 'sen:q:next'):
        check('MENU: редкая настройка %s спрятана под «Ещё»' % _rare,
              _rare not in main_data and _rare in data, _rare)
    # ── ГРУППЫ ПОДПИСАНЫ, И ЗАГОЛОВОК НЕ МОЛЧИТ ──────────────────────────────────────────
    _hints = [b.callback_data for row in kb_adv.inline_keyboard for b in row
              if (b.callback_data or '').startswith('sen:hint:')]
    check('MENU: продвинутое разбито на подписанные группы', len(_hints) >= 4, _hints)
    for _h in _hints:
        _key = 'h_%s' % _h.split(':')[-1]
        check('MENU: заголовок %s отвечает подсказкой, а не молчит' % _h,
              ui._t(_key, 'ru') != _key and len(ui._t(_key, 'ru')) > 20, ui._t(_key, 'ru'))
    txt = ui.menu_text(uid, 'ru')
    check('MENU: подпись тумблера говорит СОСТОЯНИЕ, а не действие',
          any('Алерты: вкл' in b.text for row in kb.inline_keyboard for b in row),
          [b.text for row in kb.inline_keyboard for b in row])
    # СЛУЖЕБНЫЕ СТРОКИ - В РАЗВЁРНУТОМ ВИДЕ (их читают один раз, а место занимают всегда).
    check('MENU: экран называет общие пороги (их кнопками не крутят)',
          'Общие пороги' in txt, txt)
    check('MENU: и говорит, что Nansen сейчас бесплатен', 'бесплат' in txt.lower(), txt)
    ui._ADV.pop(uid, None)
    _short = ui.menu_text(uid, 'ru')
    check('MENU: в свёрнутом виде текст короче', len(_short) < len(txt), (len(_short), len(txt)))
    check('MENU: но состояние в нём есть (что под дозором, сколько дошло)',
          'Под дозором' in _short and 'доставлено' in _short, _short)

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
    arr = engine._HOT[venues.key('variational', 'RING')]
    check('RING: шесть опросов дали шесть точек, а не одну', len(arr) == 6, len(arr))
    check('RING: время точек растёт', [r[0] for r in arr] == sorted(r[0] for r in arr))
    engine._hot_put(x, base + 5 * 30)            # тот же миг: наложение тиков
    check('RING: два тика в одну секунду дают одну точку',
          len(engine._HOT[venues.key('variational', 'RING')]) == 6,
          len(engine._HOT[venues.key('variational', 'RING')]))
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


def t_venues_are_data_not_branches():
    """ПЛОЩАДКИ - ДАННЫЕ. Добавление площадки не правит ни детектор, ни кольца, ни меню.

    Просьба владельца: «разные площадки бы потестил и включил бы в настройки (Variational уже
    работает, дальше бы HL, Lighter - у них все есть уже готовые движки у нас)». Ключевое -
    «готовые движки»: транспорт Hyperliquid в проекте уже написан и используется бордом риска,
    поэтому второй клиент к той же ручке был бы дублем транспорта (закон №40).
    """
    check('VENUE: реестр знает три площадки',
          {'variational', 'hyperliquid', 'lighter'} <= set(venues.VENUES), list(venues.VENUES))
    # ═══ МЕХАНИЗМ «ВЫКЛЮЧЕНО С ПРИЧИНОЙ» ПРОВЕРЯЕМ СИНТЕТИЧЕСКОЙ ПЛОЩАДКОЙ ═══
    # Раньше эти три проверки стояли на Lighter, и в круге 9 они ПОКРАСНЕЛИ - потому что
    # Lighter включили по замеру (публичный REST отдаёт 235 рынков одним GET). Правильный ответ
    # тут не «вычеркнуть проверку»: механизм нужен по-прежнему, следующая площадка опять придёт
    # выключенной. Поэтому правило проверяется НА ПРАВИЛЕ, а не на чьём-то текущем состоянии -
    # иначе тест умирает от каждой хорошей новости и его начинают править не читая.
    venues.VENUES['__probe__'] = {'title': 'Probe', 'fetch': None,
                                  'why_off': 'у площадки нет публичного списка рынков',
                                  'why_off_en': 'the venue has no public market list',
                                  'url': 'https://example.invalid/'}
    try:
        check('VENUE: у выключенной названа ПРИЧИНА, а её нет молча',
              venues.why_off('__probe__') and 'нет публичного' in venues.why_off('__probe__'),
              venues.why_off('__probe__'))
        check('VENUE: причина есть и по-английски (по экрану ходит обходчик)',
              venues.why_off('__probe__', 'en')
              and not __import__('re').search(r'[А-Яа-яЁё]', venues.why_off('__probe__', 'en')),
              venues.why_off('__probe__', 'en'))
        check('VENUE: выключенная площадка в live() не попадает',
              '__probe__' not in venues.live(), venues.live())
        check('VENUE: и без измеренного пути ссылка на инструмент - None, а не корень',
              venues.market_url('__probe__', 'BTC') is None,
              'подсунуть непроверенный путь хуже, чем дать ссылку на площадку целиком')
    finally:
        venues.VENUES.pop('__probe__', None)
    # ── А ВСЕ ТРИ НАСТОЯЩИЕ ПЛОЩАДКИ ОБЯЗАНЫ БЫТЬ ЖИВЫМИ И БЕЗ ПРИЧИНЫ ВЫКЛЮЧЕНИЯ ──
    for _v in ('variational', 'hyperliquid', 'lighter'):
        check('VENUE: %s включена и причины выключения у неё нет' % _v,
              (venues.VENUES[_v].get('fetch') is not None
               and venues.why_off(_v) is None), venues.why_off(_v))
    check('VENUE: Lighter умеет отдать список рынков (долг закрыт замером)',
          callable(venues.VENUES['lighter'].get('fetch')))
    check('VENUE: и путь к её инструменту измерен браузером',
          venues.market_url('lighter', 'btc') == 'https://app.lighter.xyz/trade/BTC',
          venues.market_url('lighter', 'btc'))
    check('VENUE: единица фандинга Lighter - 8 часов, выведена сверкой с Hyperliquid',
          venues.LG_FUNDING_INTERVAL_S == 8 * 3600, venues.LG_FUNDING_INTERVAL_S)
    # ── ИДЕНТИЧНОСТЬ ПАРНАЯ: «BTC» на двух площадках - разные инструменты ──
    k1, k2 = venues.key('variational', 'btc'), venues.key('hyperliquid', 'BTC')
    check('VENUE: ключ кольца включает площадку', k1 != k2 and k1 == 'variational:BTC', (k1, k2))
    check('VENUE: ключ разбирается обратно',
          venues.split(k2) == ('hyperliquid', 'BTC'), venues.split(k2))
    check('VENUE: старый ключ без площадки читается как Variational',
          venues.split('BTC') == ('variational', 'BTC'), venues.split('BTC'))
    # ── ПЕРЕХОДНИК HYPERLIQUID НА ЗАПИСАННОМ ОТВЕТЕ ДВИЖКА (сети не требует) ──
    import sentinel.venues as V
    orig = V._oc_perps

    class FakeOC:
        @staticmethod
        async def hl_universe():
            return {'BTC': {'mark': 84797.0, 'vol24': 3.49e9, 'oi_usd': 3.4e9,
                            'oi_base': 39982.7, 'funding': 1.25e-05, 'spread_bps': 0.21,
                            'chg24': 1.7},
                    'DEAD': {'mark': None, 'vol24': 0}}
    V._oc_perps = lambda: FakeOC
    try:
        rows, meta = asyncio.run(V.hl_fetch())
    finally:
        V._oc_perps = orig
    check('VENUE: переходник HL отдал строку', len(rows) == 1 and rows[0].ticker == 'BTC',
          [r.ticker for r in rows])
    x = rows[0]
    check('VENUE: площадка проставлена в инструменте', x.venue == 'hyperliquid', x.venue)
    check('VENUE: инструмент без цены отброшен, а не записан нулём',
          all(r.ticker != 'DEAD' for r in rows))
    check('VENUE: открытый интерес лёг в одиночное поле, а не в лонги',
          x.oi_long is None and x.oi_total == 39982.7, (x.oi_long, x.oi_total))
    check('VENUE: отсутствие разбивки сторон НАЗВАНО, а не нарисовано',
          'oi_long/oi_short' in x.missing, x.missing)
    check('VENUE: интервал фандинга у HL - час', x.funding_interval_s == 3600,
          x.funding_interval_s)
    check('VENUE: пустой ответ движка - ОТКАЗ, а не «рынок замер»', _hl_empty_is_refusal(V),
          'пустота стала бы утверждением о рынке')
    # ── КАРТОЧКА НАЗЫВАЕТ ПЛОЩАДКУ И ВЕДЁТ ИМЕННО НА НЕЁ ──
    ev = {'kind': 'move_up', 'ticker': 'BTC', 'ts': int(time.time()), 'severity': 90,
          'payload': {'venue': 'hyperliquid', 'mark': 84797.0, 'move_pct': 2.1,
                      'volume_24h': 3.49e9, 'penalties': []}}
    txt = cards.card(ev)
    check('VENUE: карточка называет площадку', 'Hyperliquid' in txt, txt[:160])
    check('VENUE: и ссылка ведёт на неё, а не на Variational',
          'app.hyperliquid.xyz' in txt and 'omni.variational' not in txt, txt[-200:])


def _hl_empty_is_refusal(V):
    orig = V._oc_perps

    class Empty:
        @staticmethod
        async def hl_universe():
            return {}
    V._oc_perps = lambda: Empty
    try:
        asyncio.run(V.hl_fetch())
        return False
    except feed.FeedError:
        return True
    finally:
        V._oc_perps = orig


def t_venue_filter_and_presets_are_personal():
    """ПЛОЩАДКА И ПРЕСЕТ - ЛИЧНЫЕ НАСТРОЙКИ. Отсев по площадке стоит на доставке."""
    uid = 991500
    store.settings_set(uid, alerts_on=1, enrich_on=0, venues=None, kinds=None)
    store.sub_add(uid, 'BTC')
    check('VF: по умолчанию слушаем все живые площадки',
          store.venues_for(uid) == set(venues.live()), store.venues_for(uid))
    now = int(time.time())
    ev = {'kind': 'move_up', 'ticker': 'BTC', 'ts': now, 'severity': 80,
          'key': 'vf%d' % now,
          'payload': {'venue': 'hyperliquid', 'mark': 1.0, 'move_pct': 2.0, 'penalties': []}}
    store.event_new(ev)
    store.venues_set(uid, {'variational'})
    n, why = outbox.plan(ev)
    check('VF: алерт чужой площадки НЕ уходит', n == 0, (n, why))
    check('VF: и причина названа словами',
          any('площадка hyperliquid выключена' in w for w in why), why)
    store.venue_toggle(uid, 'hyperliquid')
    ev2 = dict(ev, key=ev['key'] + 'b')
    store.event_new(ev2)
    check('VF: после включения - уходит', outbox.plan(ev2)[0] == 1)
    # ── ПРЕСЕТЫ: ОТВЕТ НА «КАКИЕ НАСТРОЙКИ ВЫСТАВИТЬ, ЧТОБЫ ПОБОЛЬШЕ АЛЕРТОВ» ──
    nm, why2 = store.preset_apply(uid, 'test')
    s = store.settings(uid)
    check('PRESET: «поток» применился и назвал себя словами',
          nm == 'test' and 'пауза 10 минут' in why2, (nm, why2))
    check('PRESET: пауза опущена', s['cooldown_min'] == 10, s['cooldown_min'])
    check('PRESET: потолок поднят', store.cap_for(uid) == 120, store.cap_for(uid))
    check('PRESET: личный порог снят (ловим всё, что даёт общий)',
          s['min_pct'] is None, s['min_pct'])
    check('PRESET: спред и фандинг в поток НЕ включены (они не повод звонить)',
          'spread_shock' not in store.kinds_for(uid)
          and 'funding_extreme' not in store.kinds_for(uid), store.kinds_for(uid))
    store.preset_apply(uid, 'quiet')
    check('PRESET: «тихий» ставит порог и длинную паузу',
          store.settings(uid)['min_pct'] == 3.0 and store.settings(uid)['cooldown_min'] == 180,
          store.settings(uid))
    check('PRESET: чужое имя - отказ со словом',
          store.preset_apply(uid, 'нет такого')[0] is None)
    check('PRESET: пресет НЕ трогает общие пороги детектора',
          config.move_pct_15m() == 1.2, config.move_pct_15m())


def t_screens_are_sent_as_html():
    """ЭКРАНЫ УХОДЯТ С РАЗМЕТКОЙ. Иначе человек читает теги глазами.

    ЖИВОЙ СЛУЧАЙ 25.09: экран «Что сейчас» пришёл владельцу буквально как
    `<b>Что сейчас на площадке</b>`. Карточки алертов ходят через `outbox`, где parse_mode задан,
    а экраны меню отправлялись другой дверью - без него. Одна дверь знала про разметку, вторая
    нет, и разошлись они молча.
    """
    seen = []

    class Ctx:
        class bot:
            @staticmethod
            async def send_message(chat_id=None, text=None, **kw):
                seen.append(kw)
                return True

    class Q:
        data = 'sen:now'
        from_user = type('U', (), {'id': 991600})()
        message = type('M', (), {'chat_id': 991600, 'text': 'x'})()
        edits = []

        async def answer(self, *a, **kw):
            return True

        async def edit_message_text(self, text, reply_markup=None, **kw):
            Q.edits.append(kw)
            return True

    q = Q()
    asyncio.run(ui.handle_callback(type('U', (), {'callback_query': q})(), Ctx()))
    check('HTML: экран отправлен с parse_mode=HTML',
          seen and seen[0].get('parse_mode') == 'HTML', seen[:1])
    check('HTML: превью ссылок выключено',
          seen and seen[0].get('disable_web_page_preview') is True, seen[:1])
    asyncio.run(ui.handle_callback(
        type('U', (), {'callback_query': type('Q2', (Q,), {'data': 'sen:t:al'})()})(), Ctx()))
    check('HTML: и перерисовка экрана тоже с разметкой',
          Q.edits and Q.edits[-1].get('parse_mode') == 'HTML', Q.edits[-1:])
    sent = []

    class Bot:
        @staticmethod
        async def send_message(chat_id=None, text=None, reply_markup=None, **kw):
            sent.append(kw)
            return True
    asyncio.run(ui.route_send(Bot, 991600, 'дозор'))
    check('HTML: ответ на команду словами - тоже HTML',
          sent and sent[0].get('parse_mode') == 'HTML', sent[:1])


def t_every_screen_leads_further():
    """СКВОЗНОЙ ПЕРЕХОД: из любого экрана можно попасть в карточку токена.

    ТРЕБОВАНИЕ ВЛАДЕЛЬЦА ДВАЖДЫ: «в что сейчас приходят тикер без ссылок на карточки токенов или
    контрактов (мемов), не забывай, у нас все сценарии сквозные, чтобы сразу на карточку попасть и
    если что в избранное закинуть». Экран-тупик заставляет человека набирать тикер руками в другом
    окне - то есть мы отдаём ему работу, которую умеем сделать сами.
    """
    engine._HOT.clear()
    now = int(time.time())
    for t, (p0, p1) in (('AAA', (100.0, 102.0)), ('BBB', (5.0, 5.05))):
        engine._HOT[venues.key('variational', t)] = [
            (now - 900, p0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900),
            (now, p1, 9e8, 1000.0, 900.0, 0.05, 1.0, now)]
    kb = ui.now_kb('ru')
    data = [b.callback_data for row in (kb.inline_keyboard if kb else []) for b in row]
    check('CROSS: под срезом рынка есть кнопки тикеров',
          any(d.startswith('sen:card:') for d in data), data)
    check('CROSS: кнопка несёт И площадку, И тикер',
          'sen:card:variational:AAA' in data, data)
    check('CROSS: кнопка возврата в дозор тоже есть', 'sen:home' in data, data)
    check('CROSS: цена для сопоставления берётся из кольца, а не запросом',
          engine.last_mark('AAA') == 102.0, engine.last_mark('AAA'))
    check('CROSS: тикера, которого мы не видели, в кольце нет',
          engine.last_mark('НЕТТАКОГО') is None)
    # ── ОТКАЗ СОПОСТАВЛЕНИЯ НАЗЫВАЕТ ПРИЧИНУ, А НЕ МОЛЧИТ ──
    txt = asyncio.run(ui.card_link('НЕТТАКОГО', 'variational', 'ru'))
    check('CROSS: без цены в кольце - отказ со словами',
          'цены нет в кольце' in txt, txt)
    check('CROSS: и на en он тоже есть',
          'Could not open' in asyncio.run(ui.card_link('НЕТТАКОГО', 'variational', 'en')))
    engine._HOT.clear()


def t_tweets_are_readable_and_not_spam():
    """ТВИТЫ: спам и копипаста не попадают, а то, что попало, ЧИТАЕМО.

    ЖИВАЯ СВОДКА 25.09 пришла с тремя дефектами разом: сигнальный канал («TP1/TP2/STOP LOSS,
    Leverage: Cross 25x - 50x»), накрутка голосов («Less than 100 votes are needed to list $XPL»)
    и ТРИ ОДИНАКОВЫХ поста от трёх разных аккаунтов («I made $80,000 by following his trades»).
    Дедупликация по автору их не ловит - авторы разные; по ссылке тоже - ссылки разные.
    """
    from sentinel import enrichment as en
    check('TW: сигнальный канал отсеян',
          en._is_spam('$XPL/USDT BUY (LONG) Leverage: Cross 25x TP1: 0.1165 STOP LOSS: 0.1070'))
    check('TW: накрутка голосов отсеяна',
          en._is_spam('Less than 100 votes are needed to list $XPL on the Moonshot Leaderboard'))
    check('TW: «я заработал $80,000» отсеяно',
          en._is_spam('$ARCC $W $FTI . I made $80,000 by following his trades'))
    check('TW: обычная новость НЕ отсеяна',
          not en._is_spam('Plasma unlock today: $160M worth of tokens unlocked'))
    # ── КОПИПАСТА: РАЗНЫЕ ССЫЛКИ И РЕГИСТР, ОДИН ОТПЕЧАТОК ──
    a = en._norm('$ARCC $W $FTI . I made $80,000 https://t.co/aaa')
    b = en._norm('$arcc $w $fti . i made $80,000  https://t.co/bbb')
    check('TW: копипаста с разными ссылками даёт ОДИН отпечаток', a == b, (a, b))
    check('TW: разные тексты дают разные отпечатки',
          en._norm('XPL whale bought the dip') != a)

    # ── ФОРМАТ: АВТОР ССЫЛКОЙ, ТЕКСТ ЦИТАТОЙ ──
    # ПРОВЕРКИ АНТИСПАМА ВЫШЕ РАБОТАЮТ ВЕЗДЕ (это чистые функции), а формат строки требует разбора
    # возраста из чужого модуля. В публичной выжимке слоя X нет - он не про Nansen, - поэтому здесь
    # честный пропуск с именем, а не молчаливо зелёная проверка.
    try:
        import twitter_api as tw
    except ImportError:
        global _SKIP
        _SKIP += 1
        print('SKIP  формат строки твита: в этой сборке нет модуля X (в боте проверка идёт)')
        return
    import datetime
    d = datetime.datetime.utcfromtimestamp(time.time() - 300)
    t = {'createdAt': d.strftime('%a %b %d %H:%M:%S +0000 %Y'),
         'text': 'Plasma unlock today: $160M worth of tokens unlocked and this is not a one-off',
         'id': '123', 'author': {'userName': 'someone', 'followers': 8600}}
    line = en._tweet_line(t, tw, time.time())
    check('TW: автор - ССЫЛКА на твит', '<a href="https://x.com/someone/status/123">' in line, line)
    check('TW: текст идёт ЦИТАТОЙ (Telegram рисует отступ)',
          '<blockquote>' in line and '</blockquote>' in line, line)
    check('TW: вес аккаунта и возраст в одной строке с автором',
          '8.6k' in line and '5м' in line, line)
    check('TW: возраст больше часа печатается часами',
          '2ч' in en._tweet_line(dict(t, createdAt=datetime.datetime.utcfromtimestamp(
              time.time() - 7300).strftime('%a %b %d %H:%M:%S +0000 %Y')), tw, time.time()),
          'иначе «123м» человек переводит в часы в голове')


def t_venue_gaps_do_not_pay_for_missing_fields():
    """ЧТО ПЛОЩАДКА НЕ ОТДАЁТ - НЕ ДЕФЕКТ СОБЫТИЯ.

    ЖИВОЙ ПРОГОН 25.09: карточки с Hyperliquid шли с уверенностью 40/100 и тремя штрафами, которые
    все про одно - у этой площадки таких полей нет ВООБЩЕ («возраст котировки не назван»,
    «котировки на $100k нет», «провайдер не дал: quotes»). Мы наказывали событие за свойство
    источника, и сильное движение на самой ликвидной площадке выглядело сомнительным.
    """
    now = int(time.time())
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, None, None, 1.25e-05, 0.21, None)]
    hl = feed.Listing(ticker='ZEC', name='ZEC', mark=102.0, volume_24h=5.4e8,
                      oi_long=None, oi_short=None, oi_total_raw=1.2e6,
                      funding_raw=1.25e-05, funding_interval_s=3600, spread_bps=0.21,
                      quote_ts=None, quotes={}, missing=('oi_long/oi_short', 'quotes'),
                      venue='hyperliquid')
    evs = [e for e in detector.detect(hl, hot, now=now, ring=ring) if e['kind'] == 'move_up']
    check('HLPEN: движение на HL поймано', evs, 'событие не создалось')
    pen = evs[0]['payload']['penalties'] if evs else []
    body = ' | '.join(pen)
    check('HLPEN: три жалобы на отсутствие полей стали ОДНОЙ строкой',
          sum(1 for x in pen if 'не отдаёт' in x) == 1, pen)
    check('HLPEN: и в ней названа площадка и поля',
          'Hyperliquid не отдаёт' in body and 'ёмкость на $100k' in body, body)
    check('HLPEN: за отсутствие полей уверенность НЕ снижена',
          evs[0]['severity'] >= 70, (evs[0]['severity'], pen))
    check('HLPEN: строка-пояснение печатается без «(-0)»', '(-0)' not in body, body)
    txt = cards.card(evs[0])
    check('HLPEN: карточка вместо «котировки нет» печ──ет спред на размер',
          'Спред на размер: 0.2 б.п.' in txt, txt)
    check('HLPEN: и не жалуется на возраст, которого у площадки нет',
          'возраст не назван' not in txt, txt)


def t_crowd_and_absorption_describe_not_predict():
    """ТОЛПА И ПОГЛОЩЕНИЕ: два вида из роудмапа, и оба НЕ предсказывают направление."""
    now = int(time.time())
    # ── ТЕСНАЯ ТОЛПА: перекос И дорогая ставка ──
    ring_f = [(now - (60 - i) * 900, 100.0, 8e8, 1000.0, 900.0, 0.01 * (i % 7), 1.0, 0)
              for i in range(60)]
    hot = [(now - 3600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 3600)]
    x = one(mark='100.0', oi_l='9600', oi_s='400', funding='9.9', quote_iso=_iso(now))
    evs = detector.detect(x, hot, now=now, ring=ring_f)
    cr = [e for e in evs if e['kind'] == 'crowded']
    check('CROWD: 96% в лонгах при верхней ставке - событие', cr, {e['kind'] for e in evs})
    check('CROWD: сторона и доля названы числом',
          cr and cr[0]['payload']['crowd_side'] == 'лонги'
          and abs(cr[0]['payload']['crowd_pct'] - 96.0) < 1, cr[0]['payload'] if cr else None)
    txt = cards.card(cr[0]) if cr else ''
    check('CROWD: карточка говорит «конструкция», а не «пойдёт вниз»',
          'каскад ликвидаций идёт против толпы' in txt and 'Направление дозорный не предсказывает'
          in txt, txt)
    # ПЕРЕКОС БЕЗ ПЛАТЫ - НЕ СОБЫТИЕ (иначе алерт на устройство рынка)
    calm = detector.detect(one(mark='100.0', oi_l='9600', oi_s='400', funding='0.0',
                               quote_iso=_iso(now)), hot, now=now, ring=ring_f)
    check('CROWD: перекос без дорогой ставки событием НЕ считается',
          'crowded' not in {e['kind'] for e in calm}, {e['kind'] for e in calm})
    # ── ПОГЛОЩЕНИЕ: интерес растёт, цена стоит ──
    ring = series(60, now - 60 * 900)
    hot2 = [(now - 3600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 3600)]
    ab = detector.detect(one(mark='100.2', oi_l='4000', oi_s='900', quote_iso=_iso(now)),
                         hot2, now=now, ring=ring)
    kinds = {e['kind'] for e in ab}
    check('ABSORB: интерес +150% при стоящей цене - событие', 'absorption' in kinds, kinds)
    a0 = [e for e in ab if e['kind'] == 'absorption'][0]
    txt2 = cards.card(a0)
    check('ABSORB: карточка ведёт интересом и говорит «цена стоит»',
          'а цена стоит' in txt2, txt2[:140])
    check('ABSORB: и честно признаёт, что направления здесь нет',
          'Подтверждения направления здесь нет' in txt2, txt2)
    # ЦЕНА УШЛА - ЭТО УЖЕ НЕ ПОГЛОЩЕНИЕ, А ДВИЖЕНИЕ
    moved = detector.detect(one(mark='104.0', oi_l='4000', oi_s='900', quote_iso=_iso(now)),
                            hot2, now=now, ring=ring)
    check('ABSORB: при ушедшей цене поглощением это не называется',
          'absorption' not in {e['kind'] for e in moved}, {e['kind'] for e in moved})
    check('ABSORB: оба вида включены по умолчанию',
          {'crowded', 'absorption'} <= set(config.DEFAULT_KINDS), config.DEFAULT_KINDS)


def t_write_after_many_reads():
    """ЗАПИСЬ ПОСЛЕ ДЕСЯТКА ЧТЕНИЙ ОБЯЗАНА ПРОЙТИ. Порядок взят с живого отказа владельца.

    ЧТО ПОКАЗАЛИ ЗАМЕРЫ НА ЕГО СЕРВЕРЕ: `event_new` (запись) прошёл, следующий `delivery_plan`
    (запись) упал `database is locked` - а между ними `outbox.plan` делает десяток SELECT.
    Файл правильный, WAL включён, ожидание минута: так выглядит незавершённое ЧТЕНИЕ, а не
    нехватка терпения. Прошлый круг закрывал курсоры и считал вопрос решённым - отказ вернулся,
    потому что закрыть курсор и завершить транзакцию не одно и то же, а момент, когда sqlite3
    отпускает неявную транзакцию, вдобавок зависит от версии Python (3.12+ у владельца против
    3.9 в разработке). Поэтому тест воспроизводит ПОРЯДОК ОБРАЩЕНИЙ, а не версию.
    """
    uid = 991700
    now = int(time.time())
    store.sub_add(uid, 'LOCKTEST')
    store.settings_set(uid, alerts_on=1, enrich_on=0)
    ev = {'kind': 'move_up', 'ticker': 'LOCKTEST', 'ts': now, 'severity': 80,
          'key': 'lock%d' % now,
          'payload': {'venue': 'variational', 'mark': 1.0, 'move_pct': 5.0, 'penalties': []}}
    check('LOCK: первая запись прошла', store.event_new(ev) is True)
    for _fn in (lambda: store.subscribers('LOCKTEST'), lambda: store.settings(uid),
                lambda: store.kinds_for(uid), lambda: store.venues_for(uid),
                lambda: store.cooldown_left(uid, 'LOCKTEST', 'move_up:1'),
                lambda: store.cap_for(uid), lambda: store.sent_today(uid),
                lambda: store.event(ev['key']), lambda: store.events_by_kind(now - 86400),
                lambda: store.spend_today()):
        _fn()
    check('LOCK: запись после десяти чтений прошла',
          store.delivery_plan(ev['key'], uid) is True,
          'ровно этот переход падал на сервере: %s' % store.diag())
    check('LOCK: замеры называют состояние транзакции',
          'in_transaction=' in store.diag(), store.diag())
    check('LOCK: после чтения транзакция НЕ висит',
          str(getattr(store.conn(), 'in_transaction', False)) in ('False', '?'), store.diag())
    src = open(os.path.join(BASE, 'sentinel', 'store.py'), encoding='utf-8').read()
    check('LOCK: обе двери чтения завершают транзакцию',
          src.count('_end_read(c)') >= 2 and 'def _end_read' in src,
          'закрыть курсор и закрыть транзакцию - не одно и то же')
    store.sub_del(uid, 'LOCKTEST')


def t_link_leads_to_the_instrument():
    """ССЫЛКА ВЕДЁТ НА САМ ИНСТРУМЕНТ. Формат ИЗМЕРЕН браузером, а не угадан.

    ТРИ КРУГА В СПЕКЕ СТОЯЛО «формат не измерен»: `/trade/<T>` и `/markets/<T>` отвечают 403, а
    query-параметр даёт 200 так же, как корень. Вывод был верен по факту и ленив по методу: у
    одностраничного приложения путь видно из САМОГО приложения. Запуск браузера 25.09 показал,
    что корень с `?market=ENA` сам перебрасывает на `/perpetual/BTC`, заголовок страницы -
    «BTC PERP | Variational Omni»; дальше пять тикеров разных классов (BTC, ENA, MSTR, XAU,
    US500) дали 200 каждый. Урок: «403 на двух путях» не равно «прямой ссылки нет».
    """
    check('LINK: путь к инструменту Variational измерен',
          venues.market_url('variational', 'ena')
          == 'https://omni.variational.io/perpetual/ENA',
          venues.market_url('variational', 'ena'))
    check('LINK: у Hyperliquid свой путь',
          venues.market_url('hyperliquid', 'BTC')
          == 'https://app.hyperliquid.xyz/trade/BTC',
          venues.market_url('hyperliquid', 'BTC'))
    check('LINK: у Lighter свой путь (измерен браузером 26.09: заголовок назвал инструмент)',
          venues.market_url('lighter', 'BTC') == 'https://app.lighter.xyz/trade/BTC',
          venues.market_url('lighter', 'BTC'))
    check('LINK: у НЕИЗМЕРЕННОЙ площадки пути нет - None, а не корень',
          venues.market_url('нет-такой-площадки', 'BTC') is None,
          'подсунуть непроверенный путь хуже, чем дать ссылку на площадку целиком')
    check('LINK: пустой тикер ссылки не даёт',
          venues.market_url('variational', '') is None)
    ev = {'kind': 'move_up', 'ticker': 'ENA', 'ts': int(time.time()), 'severity': 85,
          'payload': {'venue': 'variational', 'mark': 0.23, 'move_pct': 3.1,
                      'volume_24h': 7.3e6, 'penalties': []}}
    txt = cards.card(ev)
    check('LINK: карточка ведёт на инструмент, а не на главную',
          '/perpetual/ENA' in txt, txt[-220:])
    check('LINK: и подпись ссылки называет инструмент',
          'Variational · ENA' in txt, txt[-220:])
    hl = dict(ev, payload=dict(ev['payload'], venue='hyperliquid'))
    check('LINK: у события с другой площадки - её путь',
          'app.hyperliquid.xyz/trade/ENA' in cards.card(hl), cards.card(hl)[-200:])


def t_funding_unit_is_measured_not_guessed():
    """ЕДИНИЦА ФАНДИНГА: долг верификации №1 закрыт ЗАМЕРОМ, и это видно в числах.

    ═══ ЧЕМ ИЗМЕРЕНО (tools/sentinel_funding_unit.py, воспроизводится одной командой) ═══
    Калибровка метода на известном ответе: строки `exchange=hyperliquid` в ленте Lighter против
    нашего чтения HL дали ×8.0000 на 95 из 95 пар. Затем суд: медиана Variational к HL = 2190.00
    при 93 парах. И проверка, которую подгонка не пройдёт: гипотеза «годовая ставка» предсказывает
    для 4-часовых 2190, для 8-часовых 1095 - получено 2190.00 (мимо в 1.0000) и 1046.03 (мимо в
    1.047). Одна константа обе группы объяснить не может.

    ГЛАВНАЯ ПРОВЕРКА ЗДЕСЬ - ПОСЛЕДНЯЯ: три площадки с РАЗНЫМИ сырыми числами и РАЗНЫМИ
    интервалами обязаны дать ОДИН И ТОТ ЖЕ годовой процент, потому что это один и тот же рынок в
    трёх записях. Если приведение врёт хоть в одной, числа разъедутся.
    """
    # ЗНАЕМ ЛИ МЫ ЕДИНИЦУ - СВОЙСТВО ПЛОЩАДКИ, И ОНО НАЗЫВАЕТ ИСТОЧНИК ЗНАНИЯ.
    for _v in ('variational', 'hyperliquid', 'lighter'):
        check('FUND: у %s единица заявлена с источником' % _v,
              _v in venues.FUNDING_UNIT and venues.funding_unit_note(_v),
              venues.FUNDING_UNIT.get(_v))
        check('FUND: и источник есть по-английски (строка идёт на экран)',
              venues.funding_unit_note(_v, 'en')
              and not __import__('re').search(r'[А-Яа-яЁё]',
                                             venues.funding_unit_note(_v, 'en')),
              venues.funding_unit_note(_v, 'en'))
    # VARIATIONAL - ГОДОВАЯ ДОЛЯ: интервал в пересчёте НЕ участвует вовсе.
    check('FUND: 0.1095 у Variational это 10.95% годовых',
          abs(venues.funding_apr_pct('variational', 0.1095, 28800) - 10.95) < 0.01,
          venues.funding_apr_pct('variational', 0.1095, 28800))
    check('FUND: и интервал на годовую долю НЕ влияет (умножив, завысили бы в тысячу раз)',
          venues.funding_apr_pct('variational', 0.1095, 28800)
          == venues.funding_apr_pct('variational', 0.1095, 14400))
    # HYPERLIQUID - ДОЛЯ ЗА ЧАС, LIGHTER - ЗА ВОСЕМЬ.
    check('FUND: у Hyperliquid доля за час приводится к году',
          abs(venues.funding_apr_pct('hyperliquid', 0.0000125, 3600) - 10.95) < 0.01,
          venues.funding_apr_pct('hyperliquid', 0.0000125, 3600))
    check('FUND: у Lighter доля за 8 часов приводится к году',
          abs(venues.funding_apr_pct('lighter', 0.0001, 28800) - 10.95) < 0.01,
          venues.funding_apr_pct('lighter', 0.0001, 28800))
    # ═══ ТРИ ЗАПИСИ ОДНОГО РЫНКА СХОДЯТСЯ В ОДНО ЧИСЛО ═══
    _three = (venues.funding_apr_pct('variational', 0.1095, 28800),
              venues.funding_apr_pct('hyperliquid', 0.0000125, 3600),
              venues.funding_apr_pct('lighter', 0.0001, 28800))
    check('FUND: разные сырые числа трёх площадок дают ОДИН годовой процент',
          max(_three) - min(_three) < 0.01, _three)
    # НЕИЗМЕРЕННАЯ ПЛОЩАДКА -> None, А НЕ НОЛЬ.
    check('FUND: у неизмеренной площадки ответ None, а не 0% годовых',
          venues.funding_apr_pct('__чужая__', 0.05, 3600) is None,
          'ноль читался бы как «фандинга нет», то есть как утверждение о рынке')
    # КАРТОЧКА: ГОДОВЫЕ ТАМ, ГДЕ ИЗМЕРЕНО; ИМЯ ПОЛЯ ТАМ, ГДЕ НЕТ.
    _known = cards.funding_line({'venue': 'variational', 'funding_raw': 0.1095,
                                 'funding_interval_s': 28800})
    check('FUND: карточка ведёт годовыми процентами', '10.95% годовых' in _known, _known)
    check('FUND: и говорит, КТО платит', 'платят лонги' in _known, _known)
    check('FUND: сырое поле остаётся рядом - иначе нас нечем проверить',
          '0.1095' in _known, _known)
    _neg = cards.funding_line({'venue': 'variational', 'funding_raw': -0.0821,
                              'funding_interval_s': 14400})
    check('FUND: отрицательная ставка читается как «платят шорты»', 'платят шорты' in _neg, _neg)
    _unknown = cards.funding_line({'venue': '__чужая__', 'funding_raw': 0.05,
                                   'funding_interval_s': 3600})
    check('FUND: без замера карточка честно печатает ИМЯ ПОЛЯ, а не выдуманные проценты',
          'funding_rate' in _unknown and 'годовых' not in _unknown, _unknown)
    # ПОРОГ, КОТОРЫЙ ДЕВЯТЬ КРУГОВ БЫЛ МЁРТВЫМ, ТЕПЕРЬ ЧИТАЕТСЯ.
    import inspect
    _src = inspect.getsource(detector.detect)
    check('FUND: абсолютный порог в годовых применяется в детекторе',
          'config.funding_apr_pct()' in _src,
          'порог был объявлен девять кругов назад и НИ ОДНИМ читателем не читался')
    check('FUND: и при неизвестной единице порог не применяется, а штрафует уверенность',
          'не измерена' in _src, _src[:100])


def t_clusters_count_people_not_addresses():
    """КЛАСТЕРЫ (роудмап 3.6): три адреса могут быть ОДНИМ человеком. Штраф, а не новое событие.

    Зажигание считает РАЗНЫЕ адреса, а не сделки, — это было первым честным решением модуля. Но
    адрес тоже не равен человеку: пять кошельков, заведённых с одного, это ОДИН участник, и «5
    умных адресов купили» завышает силу сигнала во столько раз, сколько кошельков он себе нарезал.

    ПОЧЕМУ ШТРАФ, А НЕ ОТМЕНА: связь адресов не доказывает умысла (биржи, фонды, боты разносят
    позиции по адресам штатно). Отменив событие, мы выбросили бы настоящие покупки.
    """
    A, B, C, D = '0xaaa1', '0xbbb2', '0xccc3', '0xddd4'
    # ── РАЗБОР ОТВЕТА: ЧИСТАЯ ФУНКЦИЯ НА ФИКСТУРЕ ─────────────────────────────────────────
    # Форма строки снята с `nansen_api.profiler_related_wallets` (поля address/label/relation).
    rows = {A: [{'address': B, 'relation': 'funded_by'},
                {'address': '0xEXCHANGE', 'relation': 'counterparty'}],
            B: [{'address': A, 'relation': 'funded'}],
            C: [{'address': '0xROUTER', 'relation': 'counterparty'}]}
    links = clusters.link_map(rows)
    check('CLU: связь внутри набора найдена', links[A] == {B} and links[B] == {A}, links)
    check('CLU: чужие адреса из графа НЕ считаются связью',
          '0xexchange' not in links and '0xrouter' not in links,
          'у любого живого адреса десятки связанных - это шум чужого графа, а не наш вопрос')
    check('CLU: адрес без связей внутри набора остаётся сам за себя', links[C] == set(), links)
    # СИММЕТРИЯ: площадка может назвать B в ответе про A и не назвать A в ответе про B.
    one_way = clusters.link_map({A: [{'address': B}], B: []})
    check('CLU: связь симметрична, даже если названа с одной стороны',
          one_way[A] == {B} and one_way[B] == {A}, one_way)
    # ── ГРУППЫ, А НЕ ПАРЫ: A-B и B-C это ОДИН участник ────────────────────────────────────
    chain3 = clusters.link_map({A: [{'address': B}], B: [{'address': C}], C: []})
    comps = clusters.components(chain3)
    check('CLU: A-B-C склеиваются в ОДНУ группу, а не в две связи',
          len(comps) == 1 and len(comps[0]) == 3, comps)
    # ── ПЕРЕСЧЁТ УЧАСТНИКОВ ───────────────────────────────────────────────────────────────
    v = clusters.verdict(clusters.link_map(rows), wallets_total=4, checked=3)
    check('CLU: из 4 адресов независимых участников 3', v['independent'] == 3, v)
    check('CLU: непроверенные адреса НЕ занижаются - про них мы ничего не знаем',
          v['wallets'] == 4 and v['checked'] == 3, v)
    v1 = clusters.verdict({}, wallets_total=1, checked=0)
    check('CLU: один адрес не с чем связывать - это не отказ', v1['independent'] == 1, v1)
    # ── ШТРАФ РАСТЁТ С ДОЛЕЙ СЛИПШИХСЯ ────────────────────────────────────────────────────
    small = clusters.penalty(clusters.verdict(clusters.link_map({A: [{'address': B}], B: []}),
                                              wallets_total=12, checked=3))
    big = clusters.penalty(clusters.verdict(chain3, wallets_total=3, checked=3))
    check('CLU: «2 из 12 связаны» штрафуется мягче, чем «3 из 3»',
          small and big and small[1] < big[1], (small, big))
    check('CLU: текст штрафа называет ЧИСЛА, а не «подозрительно»',
          'независимых участников' in small[0], small)
    check('CLU: где связей нет - штрафа нет вовсе',
          clusters.penalty(clusters.verdict({C: set()}, 3, 3)) is None)
    # ── НЕ СМОГЛИ ПРОВЕРИТЬ ≠ СВЯЗЕЙ НЕТ ──────────────────────────────────────────────────
    ref = clusters.penalty(clusters.verdict({}, 5, 0, refused='кап исчерпан'))
    check('CLU: «связи не проверены» - отдельная строка, а не молчание', ref and 'не проверены'
          in ref[0], ref)
    check('CLU: и штраф за НАШУ неудачу маленький, сигнал в ней не виноват',
          ref[1] <= 10, ref)
    # ── ЖИВОЙ ПУТЬ: ШТРАФ ЛОЖИТСЯ В СОБЫТИЕ ДО ОТПРАВКИ ───────────────────────────────────
    ev = {'kind': 'ignition', 'ticker': 'PEPE', 'ts': int(time.time()), 'severity': 90,
          'key': 'clu-1',
          'payload': {'symbol': 'PEPE', 'chain': 'ethereum', 'address': '0xtok',
                      'wallets': 4, 'usd': 200000.0, 'penalties': [],
                      'wallet_addrs': [A, B, C, D]}}
    _real = clusters.check

    async def _fake(addresses, chain, **kw):
        return clusters.verdict(clusters.link_map(rows), len(addresses), 3)
    clusters.check = _fake
    try:
        hit = asyncio.run(engine._cluster_mark(ev))
    finally:
        clusters.check = _real
    check('CLU: связи найдены и отмечены', hit is True)
    check('CLU: уверенность ПЕРЕСЧИТАНА вниз', ev['severity'] < 90, ev['severity'])
    check('CLU: причина попала в штрафы события',
          any('независимых участников' in str(x) for x in ev['payload']['penalties']),
          ev['payload']['penalties'])
    check('CLU: число участников легло в payload', ev['payload']['independent'] == 3,
          ev['payload'].get('independent'))
    # ── КАРТОЧКА ВЕДЁТ УЧАСТНИКАМИ, А НЕ АДРЕСАМИ ─────────────────────────────────────────
    txt = cards.card(ev)
    check('CLU: заголовок называет независимых участников',
          '3</b> независимых участника' in txt, txt.split('\n')[0])
    check('CLU: а число адресов ушло в скобки, но не пропало', 'адресов 4' in txt,
          txt.split('\n')[0])
    ev2 = dict(ev, severity=90,
               payload=dict(ev['payload'], independent=4, wallets=4, penalties=[]))
    check('CLU: где связей нет - заголовок прежний, про адреса',
          'умных адреса купили' in cards.card(ev2), cards.card(ev2).split('\n')[0])
    # ── ЧИСТАЯ ФУНКЦИЯ `judge` ОСТАЛАСЬ ЧИСТОЙ ────────────────────────────────────────────
    # ПРОВЕРЯЕМ ПОВЕДЕНИЕМ, А НЕ ПОИСКОМ СЛОВА В ИСХОДНИКЕ. Первая редакция искала подстроку
    # 'clusters' в тексте `judge` и ПОКРАСНЕЛА на комментарии, который всего лишь ссылается на
    # модуль. Это ровно то, что запрещает сторож `gt01` в e2e: тест не имеет права быть ни
    # зелёным из-за комментария, ни красным из-за него. Поэтому подменяем саму дверь в сеть и
    # смотрим, полезет ли судья наружу.
    import nansen_api as _napi
    _saved = _napi.profiler_related_wallets

    def _boom(*a, **kw):
        raise AssertionError('judge полез в сеть - он обязан остаться чистой функцией')
    _napi.profiler_related_wallets = _boom
    try:
        _agg = {'chain': 'ethereum', 'address': '0xtok', 'symbol': 'PEPE',
                'wallets': {A, B, C, D}, 'labels': ['Smart'], 'usd': 400000.0, 'trades': 7,
                'mcap': 5e7, 'age_days': 300.0, 'last_ts': int(time.time()),
                'usd_by': {A: 100.0, B: 300000.0, C: 200.0, D: 50.0}}
        _judged = ignition.judge(_agg)
        check('CLU: judge вынес событие, НЕ обратившись к сети', _judged is not None)
        check('CLU: и положил адреса для проверки связей отдельным полем',
              (_judged['payload'].get('wallet_addrs') or [])[0] == B,
              _judged['payload'].get('wallet_addrs'))
    finally:
        _napi.profiler_related_wallets = _saved
    # ── АДРЕСА ДЛЯ ПРОВЕРКИ БЕРУТСЯ ПО ОБЪЁМУ, А НЕ ПО ПОРЯДКУ ────────────────────────────
    agg = {'wallets': {A, B, C}, 'usd_by': {A: 10.0, B: 900.0, C: 50.0}}
    check('CLU: первым проверяем САМОГО КРУПНОГО покупателя',
          ignition._top_wallets(agg, 2) == [B, C], ignition._top_wallets(agg, 2))
    check('CLU: порядок устойчив при равных объёмах (иначе ответы гуляют между запусками)',
          ignition._top_wallets({'wallets': {A, B}, 'usd_by': {A: 5.0, B: 5.0}}, 2) == [A, B])


def t_one_connection_per_thread_not_per_call():
    """ОДНО СОЕДИНЕНИЕ НА ПОТОК. Настоящая причина `database is locked`, пережившая два круга.

    ═══ ЖИВОЙ ПРОГОН ВЛАДЕЛЬЦА 26.09 НА ПРОДЕ (Python 3.12) ═══
    `delivery_plan` падает `database is locked` при `in_transaction=False`, включённом WAL,
    ожидании 60 секунд, ОДНОМ потоке и tmp-файле, к которому никто больше не обращался. То есть
    пишущее соединение чистое, а лок держит кто-то ещё в этом же процессе.

    ЗАМЕР НАШЁЛ КОГО (перепись объектов `sqlite3.Connection` через `gc`): `db.get_conn` создаёт
    НОВОЕ соединение на каждый вызов, кэша там нет, а `_one`/`_all` зовут `conn()` каждый раз.
    Одна серия чтений в `outbox.plan` подняла число живых соединений с 3 до 15, и каждое держало
    свой read-lock в WAL.

    ПОЧЕМУ ДВА ПРЕДЫДУЩИХ КРУГА ЛЕЧИЛИ НЕ ТО: круг 2 закрывал курсоры, круг 7 добавил rollback -
    оба верные и оба лечили ОДНО соединение, пока их плодилось по одному на вызов.

    ПОЧЕМУ ЭТОТ ТЕСТ ЛОВИТ ПРИЧИНУ, А НЕ СИМПТОМ: `locked` воспроизводится не на всякой версии
    Python и не на всякой машине (в разработке 3.9 - там сборка мусора убирала соединения
    раньше). А вот «сколько соединений мы наплодили» - число, и оно одинаково везде.
    """
    import gc
    import inspect
    import sqlite3
    c1, c2 = store.conn(), store.conn()
    check('CONN: conn() отдаёт ОДИН И ТОТ ЖЕ объект', c1 is c2,
          'иначе каждое чтение открывает свою дверь и оставляет её приоткрытой')
    # ═══ И ТОЛЬКО ПОД SQLITE. ПОД POSTGRES КЭШ УБИЛ БЫ ПРОД ═══
    # Под PG `db.get_conn` берёт соединение ИЗ ПУЛА (`pool.getconn`), и закэшировав его навсегда,
    # мы бы никогда его не вернули - пул исчерпался бы и бот встал. Прод владельца именно на PG,
    # а этот тест идёт под sqlite: без этой проверки правка дошла бы до прода НЕПРОВЕРЕННОЙ
    # стороной. Проверяем наличие ветки в коде двери - поведенчески её здесь не вызвать (PG в
    # этом окружении нет), и честнее сказать это прямо, чем изобразить проверку.
    _src = inspect.getsource(store.conn)
    check('CONN: под postgres кэша НЕТ - соединение возвращается в пул',
          "== 'postgres'" in _src and 'return db.ready' in _src,
          'кэш соединения из пула исчерпал бы пул и остановил бота')
    before = len([o for o in gc.get_objects() if isinstance(o, sqlite3.Connection)])
    uid = 778001
    store.sub_add(uid, 'BTC')
    store.settings_set(uid, alerts_on=1)
    # РОВНО ТА СЕРИЯ ЧТЕНИЙ, ЧТО ДЕЛАЕТ `outbox.plan` ПЕРЕД ЗАПИСЬЮ.
    for _ in range(3):
        store.subscribers('BTC')
        store.settings(uid)
        store.kinds_for(uid)
        store.venues_for(uid)
        store.min_sev_for(uid)
        store.burst_for(uid)
        store.sent_in_window(uid, 600)
        store.cooldown_left(uid, 'BTC', 'move_up:1')
        store.cap_for(uid)
        store.sent_today(uid)
        store.nansen_cap()
    after = len([o for o in gc.get_objects() if isinstance(o, sqlite3.Connection)])
    check('CONN: 33 чтения НЕ наплодили соединений', after <= before,
          'было %d, стало %d - на проде так выросло с 3 до 15, и запись упёрлась в чужой лок'
          % (before, after))
    # И ЗАПИСЬ ПОСЛЕ ЭТОЙ СЕРИИ ПРОХОДИТ - то, что падало у владельца.
    ev = dict(_ev_for(now=int(time.time())), key='conn-1')
    store.event_new(ev)
    check('CONN: запись после серии чтений проходит', store.delivery_plan('conn-1', uid) is True,
          'ровно этот вызов падал `database is locked` на проде')
    check('CONN: и транзакция за собой не осталась',
          getattr(store.conn(), 'in_transaction', False) is False)


def t_thresholds_do_not_depend_on_the_machine():
    """ПОРОГИ ТЕСТА - СВОИ, А НЕ С МАШИНЫ. Живой отказ 26.09: 16 FAIL на проде при 426 PASS тут.

    `db.py` на импорте зовёт `env_load.load()`, и на сервере это подтягивает боевой `.env` (108
    ключей). Все пороги дозорного читаются из окружения на каждом вызове - значит боевые
    значения переопределяли их прямо в тесте.

    ОСОБЕННО ЗЛО: `SENTINEL_DELIVER=0` - аварийный рубильник, который я САМ велел владельцу
    поставить, чтобы погасить поток. Выполнение моей же инструкции ломало проверки.
    """
    for _k in ('SENTINEL_DELIVER', 'SENTINEL_BURST_MAX', 'SENTINEL_MIN_SEVERITY',
               'SENTINEL_BURST_WINDOW_SEC', 'SENTINEL_DIGEST_SEC'):
        check('ENV: %s зафиксирован тестом, а не взят с машины' % _k,
              os.environ.get(_k) is not None, _k)
    check('ENV: отправка в тесте включена', config.deliver_on() is True,
          'иначе половина проверок доставки охраняла бы пустоту')
    check('ENV: предохранитель тестовый (3 за 600с)',
          (config.burst_max(), config.burst_window_sec()) == (3, 600),
          (config.burst_max(), config.burst_window_sec()))
    check('ENV: порог звонка тестовый (75)', config.min_severity() == 75,
          config.min_severity())
    # ЭТАЛОН ИЗОЛЯЦИИ: ни одного унаследованного ключа дозорного не осталось.
    _known = {'SENTINEL_DELIVER', 'SENTINEL_BURST_MAX', 'SENTINEL_BURST_WINDOW_SEC',
              'SENTINEL_MIN_SEVERITY', 'SENTINEL_DIGEST_SEC', 'SENTINEL_LLM_OFF',
              'SENTINEL_VENUES', 'SENTINEL_NANSEN_DAY_CREDITS'}
    _extra = sorted(k for k in os.environ if k.startswith('SENTINEL_') and k not in _known)
    check('ENV: чужих SENTINEL_* из .env машины не осталось', not _extra,
          'найдены: %s - они переопределят пороги и отказ будет выглядеть загадочным' % _extra)


def t_lab_body_matches_the_venue_schema():
    """ТЕЛО ЛАБОРАТОРИИ: три поля, и каждое имя СКАЗАЛА САМА ПЛОЩАДКА живым отказом.

    Ручки нет в нашей описи 59 маршрутов, поэтому схему снимали живыми вызовами владельца - три
    круга подряд, и каждый назвал следующую ошибку:
      1) «Required field 'body -> date_range' is missing» -> поле не `date`, а `date_range`;
      2) «Date format not allowed … use YYYY-MM-DD … Time components are not supported» ->
         своя функция окна, без ISO-времени;
      3) «Required field 'body -> chains' is missing. Must be a list of chain names» ->
         поле `chains` и это СПИСОК, а не строка `chain`, как у всех остальных ручек.
    """
    import inspect
    src = inspect.getsource(lab.holdings)
    check('LAB: chains списком', "'chains': [" in src, src[:200])
    check('LAB: одиночного chain в теле больше нет', "'chain':" not in src)
    check('LAB: date_range на месте', "'date_range'" in src)
    check('LAB: и все три замера записаны рядом с кодом',
          'date_range' in src and 'YYYY-MM-DD' in src and 'list of chain names' in src)
    r = lab._days_range(30)
    check('LAB: дата без времени', 'T' not in r['from'] and 'Z' not in r['to'], r)
    # ── РЕМОНТ ПОНИМАЕТ ПОДСКАЗКУ ПРО СПИСОК (дословный текст с прода) ───────────────────
    import nansen_api as _n
    ERR = ("Required field 'body -> chains' is missing. Must be a list of chain names, "
           'e.g., ["ethereum", "solana"]')
    nb, why = _n._apply_hint({'chain': 'ethereum', 'token_address': '0xabc'}, ERR)
    check('LAB: ремонт СОБРАЛ chains из chain', nb and nb.get('chains') == ['ethereum'],
          (nb, why))
    check('LAB: и убрал старое поле, а не оставил рядом', nb and 'chain' not in nb,
          'иначе следующий круг ответил бы «поле chain не распознано»')
    check('LAB: причина правки называет оба поля', 'chains' in why and 'chain' in why, why)
    _nb2, _why2 = _n._apply_hint({'token_address': '0xabc'}, ERR)
    check('LAB: собрать нечего -> отказ ПОДСКАЗЫВАЕТ, что дописать',
          _nb2 is None and '_SINGULAR_OF' in _why2, _why2)


def t_repair_must_not_change_the_question():
    """РЕМОНТ СХЕМЫ НЕ ИМЕЕТ ПРАВА МОЛЧА СМЕНИТЬ ВОПРОС.

    ═══ ЖИВОЙ ПРОГОН ВЛАДЕЛЬЦА 26.09: САМАЯ ТИХАЯ ФОРМА ЛЖИ ═══
    Площадка ответила «Field 'token_address' is not recognized», ремонт поле убрал, запрос
    прошёл - и функция вернула «строк: 1, отказ: None», то есть УСПЕХ. Но в этой строке лежал
    топ-100 holdings умных денег ПО ВСЕЙ СЕТИ, а спрашивали про ОДИН токен.

    Формально всё верно: код 200, данные настоящие, отказа нет. Фактически ответ не на наш
    вопрос, и никто об этом не сказал. Это «признак наличия не равен признаку пользы» в самом
    злом виде - потому что здесь нет ни ошибки, ни пустоты, которые можно заметить.

    ЧЕТВЁРТАЯ СХЕМА ЭТОЙ РУЧКИ, СНЯТАЯ ЖИВЬЁМ: `date_range` -> формат даты -> `chains` списком
    -> `token_address` не принимается вовсе.
    """
    import nansen_api as _n
    # АДРЕС СИНТЕТИЧЕСКИЙ, А НЕ ЖИВОЙ. Первая редакция взяла настоящий токен из прогона
    # владельца, и скруббер публичной выжимки это поймал: чужие адреса в код не уезжают. Для
    # фикстуры это ничего не меняет - проверяется МЕХАНИКА поиска по адресу (регистр, место в
    # списке, «его тут нет»), а не конкретный токен.
    SEND = '0xCcCc000000000000000000000000000000000003'
    # ── ФИКСТУРА - ФОРМА И ЧИСЛА ИЗ ЖИВОГО ОТВЕТА, а не придуманные ──────────────────────
    live = [{'data': [
        {'token_address': '0xaaaa000000000000000000000000000000000001',
         'token_symbol': 'STRCX', 'value_usd': 1967958.67, 'holders_count': 2,
         'token_age_days': 316},
        {'token_address': '0xbbbb000000000000000000000000000000000002',
         'token_symbol': 'FP', 'value_usd': 1803664.95, 'holders_count': 28,
         'token_age_days': 356},
        {'token_address': '0xcccc000000000000000000000000000000000003',
         'token_symbol': 'SEND', 'value_usd': 104982.61, 'holders_count': 11,
         'token_age_days': 15},
    ], 'pagination': {'page': 1, 'per_page': 100, 'is_last_page': False}}]
    check('ASK: вложенный `data` распаковывается', len(lab._flatten(live)) == 3,
          len(lab._flatten(live)))
    rows, refused = lab._pick(live, SEND, 'ethereum')
    check('ASK: вернулась ОДНА строка - наш токен, а не срез по сети', len(rows) == 1, len(rows))
    check('ASK: и это правда он', rows[0]['token_symbol'] == 'SEND', rows[0])
    check('ASK: регистр адреса не помешал (запрос EIP-55, ответ в нижнем)',
          rows[0]['token_address'] != SEND, 'иначе живой вызов молча не нашёл бы токен')
    check('ASK: место в списке названо числом - в нём и смысл',
          rows[0]['rank'] == 3 and rows[0]['of'] == 3, rows[0].get('rank'))
    # ── «ЕГО НЕТ В СРЕЗЕ» - ЭТО ОТВЕТ, А НЕ ПУСТОТА ──────────────────────────────────────
    _rows2, _why2 = lab._pick(live, '0x3333000000000000000000000000000000000033', 'ethereum')
    check('ASK: отсутствие токена названо ОТВЕТОМ, а не отказом',
          not _rows2 and 'не держат' in _why2, _why2)
    check('ASK: и в ответе есть число - сколько позиций мы просмотрели',
          '3 позиц' in _why2, _why2)
    # ── ТОКЕН НЕ НАЗВАН -> ОТДАЁМ СРЕЗ ЦЕЛИКОМ (его и просили) ───────────────────────────
    _rows3, _why3 = lab._pick(live, None, 'ethereum')
    check('ASK: без токена отдаём срез целиком', len(_rows3) == 3 and _why3 is None, _why3)
    # ── РЕМОНТ ПРЕДУПРЕЖДАЕТ, ЧТО СУЗИЛ ВОПРОС ──────────────────────────────────────────
    ERR = "Field 'token_address' is not recognized. Please check the API documentation."
    nb, why = _n._apply_hint({'chains': ['ethereum'], 'token_address': SEND}, ERR)
    check('ASK: поле убрано (иначе запрос не пройдёт вовсе)',
          nb is not None and 'token_address' not in nb, nb)
    check('ASK: но ремонт СКАЗАЛ, что ответ придёт шире запроса',
          'сужало' in (why or ''), why)
    # ── И СУЖАЮЩЕЕ ПОЛЕ НЕ ПОДСТАВЛЯЕТСЯ ДЕФОЛТОМ ───────────────────────────────────────
    _nb4, _why4 = _n._apply_hint({'chains': ['ethereum']},
                                 "Required field 'body -> date_range' is missing")
    check('ASK: сужающее поле дефолтом НЕ подставляется',
          _nb4 is None and 'СУЖАЕТ' in _why4,
          'окно «за 7 дней» вместо спрошенного - ответ на другой вопрос')
    check('ASK: реестр сужающих полей заведён явно',
          'token_address' in _n._NARROWING and 'date_range' in _n._NARROWING,
          '«похоже на фильтр» здесь не годится - список пополняется руками')


def t_silence_names_the_cap_and_the_dead_poller():
    """ПРИЧИНА ТИШИНЫ НАЗЫВАЕТСЯ ПРИЧИНОЙ, А НЕ СТОИТ ЧИСЛОМ В СТОРОНКЕ.

    ═══ ЖИВОЙ ЭКРАН ВЛАДЕЛЬЦА 25.09 ═══
    «Сегодня доставлено: 147 из 25 · инструментов за час 0 · события за сутки 1002 · опрос ЕСТЬ
    (аренда истекла)». Алертов не было полчаса, и человек искал причину в настройках - хотя обе
    причины уже стояли на экране и ни одна не была названа причиной:

    1. ПОТОЛОК ПЕРЕБРАН В ШЕСТЬ РАЗ. Он крутил пресеты: «поток» поднимает потолок до 120,
       «рабочий» опускает до 25, а доставленное за сутки никуда не девается. Всё новое уходило
       в сводку - и это ПРАВИЛЬНО, но число стояло отдельной строкой состояния, без вывода.
    2. «ОПРОС ЕСТЬ» ПРИ ИСТЁКШЕЙ АРЕНДЕ - ЭТО ЛОЖЬ. Строка в базе есть, процесс мёртв. Флаг
       «владелец записан» измеряет ПРИСУТСТВИЕ ЗАПИСИ, а не живой опрос: третий случай того же
       закона в проекте (enabled-лидеры при мёртвом пуле, systemd active при неторгующем
       движке, redeemable при нулевом payout).
    """
    now = int(time.time())
    uid = 660002
    store.sub_add(uid, store.ALL)
    store.settings_set(uid, alerts_on=1, daily_cap=25)
    c = store.conn()
    for i in range(147):
        c.execute('INSERT INTO sentinel_deliveries (event_key, user_id, state, attempts, '
                  'created_at, delivered_at) VALUES (?,?,?,?,?,?)',
                  ('cap-%d' % i, uid, 'sent', 0, now - 60, now - 60))
    c.commit()
    check('WHY: суточный потолок перебран - это факт, а не настройка',
          store.sent_today(uid) >= store.cap_for(uid),
          (store.sent_today(uid), store.cap_for(uid)))
    _why = ui.silence_reasons(uid, 'ru')
    check('WHY: исчерпанный потолок НАЗВАН причиной тишины',
          any('потолок исчерпан' in w for w in _why), _why)
    check('WHY: и назван ЧИСЛАМИ - сколько и из сколька',
          any('147 из 25' in w for w in _why), _why)
    check('WHY: и сказано, что события не пропали, а поедут сводкой',
          any('СВОДКОЙ' in w for w in _why), _why)
    # ── МЁРТВЫЙ ОПРОС: ВЛАДЕЛЕЦ ЗАПИСАН, АРЕНДА ИСТЕКЛА 40 МИНУТ НАЗАД ───────────────────
    c.execute('INSERT OR REPLACE INTO sentinel_lease (name, owner, until) VALUES (?,?,?)',
              ('variational', 'host:12345', now - 2400))
    c.commit()
    line = outbox.status_line()
    check('WHY: строка состояния БОЛЬШЕ НЕ ГОВОРИТ «опрос есть» при мёртвом опросе',
          'НИКТО НЕ ВЕДЁТ' in line, line)
    check('WHY: и называет, СКОЛЬКО минут назад он умер', '40 мин назад' in line, line)
    _why2 = ui.silence_reasons(uid, 'ru')
    check('WHY: мёртвый опрос назван причиной тишины',
          any('НИКТО НЕ ОПРАШИВАЕТ' in w for w in _why2), _why2)
    check('WHY: и сказано, что настройки тут не виноваты',
          any('не ваши настройки' in w for w in _why2), _why2)
    # ── ЖИВАЯ АРЕНДА -> ЭТОЙ ПРИЧИНЫ НЕТ (иначе сторож кричал бы всегда) ────────────────
    c.execute('INSERT OR REPLACE INTO sentinel_lease (name, owner, until) VALUES (?,?,?)',
              ('variational', 'host:12345', now + 600))
    c.commit()
    check('WHY: при живом опросе про опрос не жалуемся',
          not any('НИКТО НЕ ОПРАШИВАЕТ' in w for w in ui.silence_reasons(uid, 'ru')),
          'сторож, который кричит всегда, перестают читать')
    check('WHY: и строка состояния говорит «идёт»', 'идёт' in outbox.status_line(),
          outbox.status_line())
    # ── ОБА ОБЪЯСНЕНИЯ ЕСТЬ И ПО-АНГЛИЙСКИ (по экрану ходит обходчик e2e) ───────────────
    for _k in ('s_cap', 's_nopoll'):
        _en = ui._t(_k, 'en')
        check('WHY: %s есть по-английски без кириллицы' % _k,
              _en != _k and not __import__('re').search(r'[А-Яа-яЁё]', _en), _en)


def t_bot_takes_over_a_dead_poller():
    """СМЕРТЬ ОТДЕЛЬНОГО ЮНИТА БОЛЬШЕ НЕ ЗНАЧИТ ТИШИНУ НАВСЕГДА.

    ═══ ЖИВОЙ СЛУЧАЙ 25-26.09 ═══
    Юнит `sentinel` работал СЕМЬ ЧАСОВ со статусом `active` и перестал писать снимки: кольцо
    пустое, «инструментов за час 0». Бот в это время видел `SENTINEL_IN_BOT=0`, честно выходил
    из тика со словами «опрос у отдельного юнита» и НЕ ДЕЛАЛ НИЧЕГО. Алертов не было полчаса, и
    вылечить это из интерфейса было нельзя.

    Выключатель `SENTINEL_IN_BOT` защищает от ДВОЙНОГО опроса - это его работа. Но «не
    опрашивать, потому что опрашивает другой» верно только пока другой ЖИВ, а живость у нас уже
    измеряется арендой. Читая выключатель и игнорируя аренду, мы превратили страховку в
    единственную точку отказа.

    И КНОПКА «ПОЧИНИТЬ ОПРОС» (просьба владельца) НЕ ЗОВЁТ systemctl: `systemctl` по нажатию в
    чате - это выполнение команд с правами root из мессенджера. Она отдаёт зависшую аренду, а
    опрос подхватывает живой процесс.
    """
    # ВРЕМЯ БЕРЁМ СВОЁ, НА СУТКИ ВПЕРЁД. Иначе в окно «снимки за 5 минут» попадают снимки,
    # насыпанные СОСЕДНИМИ тестами, и кнопка честно отвечает «опрос идёт» - то есть проверка
    # падает не из-за кода, а из-за чужих данных. Часы аргументом - правило этого пакета.
    now = int(time.time()) + 86400
    uid = 670002
    c = store.conn()

    def _lease(owner, until):
        c.execute('INSERT OR REPLACE INTO sentinel_lease (name, owner, until) VALUES (?,?,?)',
                  ('variational', owner, until))
        c.commit()

    # ── ЖИВАЯ АРЕНДА -> НЕ ЛЕЗЕМ (иначе двойной опрос, от которого выключатель и защищает) ──
    _lease('host:1', now + 300)
    check('OVER: при живой аренде бот опрос НЕ забирает',
          engine._poller_dead(now) is False, 'иначе площадку опрашивали бы двое')
    # ── ТОЛЬКО ЧТО ПРОСРОЧИЛАСЬ -> ДАЁМ ШАНС ПРОДЛИТЬ (сеть могла мигнуть) ────────────────
    _lease('host:1', now - 5)
    check('OVER: сразу после просрочки не вырываем - даём продлить',
          engine._poller_dead(now) is False,
          'один пропущенный тик это заминка, а не смерть')
    # ── ПРОСРОЧЕНА ДАВНО -> БЕРЁМ НА СЕБЯ ────────────────────────────────────────────────
    _lease('host:1', now - 2400)
    check('OVER: мёртвый опрашивающий -> бот берёт опрос на себя',
          engine._poller_dead(now) is True,
          'смерть юнита означала тишину НАВСЕГДА - это и случилось живьём')
    _lease(None, 0)
    check('OVER: аренду не брал никто -> тоже берём',
          engine._poller_dead(now) is True)
    # ── КНОПКА: ЧЕТЫРЕ СОСТОЯНИЯ, И КАЖДОЕ ОТВЕЧАЕТ ПО ДЕЛУ ──────────────────────────────
    _lease('host:1', now - 2400)
    t1 = ui.fix_polling(uid, now=now)
    check('FIX: зависшую аренду кнопка ОТДАЁТ', store.lease_owner('variational')[0] is None,
          store.lease_owner('variational'))
    check('FIX: и говорит, что опрос подхватится сам', 'подхватит опрос' in t1, t1)
    check('FIX: ведёт ЗАМЕРАМИ - снимки за 5 минут и за час',
          'Снимков за 5 минут' in t1, t1)
    # ПРОЦЕСС ЖИВ, НО НЕ РАБОТАЕТ - самый коварный случай: кнопка честно говорит, что бессильна.
    _lease('host:1', now + 300)
    t2 = ui.fix_polling(uid, now=now)
    check('FIX: «аренда жива, а снимков нет» названо прямо',
          'НЕ РАБОТАЕТ' in t2, t2)
    check('FIX: и сказано, где искать причину (лог юнита, НЕ journalctl)',
          'sentinel.log' in t2 and 'journalctl' in t2, t2)
    # СНИМКИ ЕСТЬ -> НЕ ПУГАЕМ, А ПЕРЕВОДИМ ВНИМАНИЕ НА НАСТРОЙКИ.
    rows, _m = feed.parse(payload())
    store.snapshot_put(rows, ts=now - 60)
    t3 = ui.fix_polling(uid, now=now)
    check('FIX: при живом опросе кнопка это подтверждает числом',
          'Опрос идёт' in t3 and 'за 5 минут: <b>1' in t3, t3)
    # ── ЖУРНАЛ ДОСТАВОК КНОПКА НЕ ПОДДЕЛЫВАЕТ ────────────────────────────────────────────
    # Владелец спрашивал, не сбросит ли кнопка «147 из 25». НЕ СБРОСИТ: это журнал того, что
    # человеку присылали, а не счётчик состояния. Подделав его, мы потеряли бы ответ на
    # «что мне приходило» - потолок для этого поднимается отдельной кнопкой.
    store.settings_set(uid, daily_cap=25)
    for i in range(5):
        c.execute('INSERT INTO sentinel_deliveries (event_key, user_id, state, attempts, '
                  'created_at, delivered_at) VALUES (?,?,?,?,?,?)',
                  ('ovr-%d' % i, uid, 'sent', 0, now - 60, now - 60))
    c.commit()
    _before = store.sent_today(uid)
    ui.fix_polling(uid, now=now)
    check('FIX: суточный счётчик доставок кнопка НЕ трогает',
          store.sent_today(uid) == _before, (_before, store.sent_today(uid)))
    # ── И КНОПКА НЕ ЗОВЁТ systemctl НИ ОДНИМ СПОСОБОМ ────────────────────────────────────
    # ПОВЕДЕНЧЕСКАЯ ПРОВЕРКА, А НЕ ПОИСК СЛОВА: сторож `gt01` запрещает быть красным или
    # зелёным из-за комментария, а слово «systemctl» в тексте для человека стоять ОБЯЗАНО.
    import subprocess as _sp
    _real = _sp.run

    def _boom(*a, **kw):
        raise AssertionError('кнопка полезла выполнять команды в системе')
    _sp.run = _boom
    try:
        ui.fix_polling(uid, now=now)
        check('FIX: кнопка НЕ выполняет системных команд', True)
    finally:
        _sp.run = _real


def _pure_only(predict):
    """Замки моста, проверяемые БЕЗ слоя Polymarket. -> None.

    ЗАЧЕМ ОТДЕЛЬНО: без `poly_read` недоступен только ЖИВОЙ поиск рынка, а сами правила
    сопоставления - чистые функции, и именно они держат границу «не угадывать». Пропустить их
    вместе с сетевой частью значило бы оставить главное без охраны там, где охранять как раз
    можно.
    """
    for _bad in ('A', 'US', 'Gold', 'ETF', ''):
        check('PM: имя %r к сопоставлению не допускается' % _bad,
              predict.ambiguous(_bad) is not None, predict.ambiguous(_bad))
    check('PM: «Bitcoin Conference» отсекается третьим замком (рынок не про цену)',
          predict.confirms('Will the Bitcoin Conference sell out?', 'c', 'Bitcoin',
                           'крипто') is False)
    check('PM: ценовой рынок подтверждается',
          predict.confirms('What price will Bitcoin hit in September?', 'btc-price', 'Bitcoin',
                           'крипто') is True)
    check('PM: чужой актив в заголовке не проходит',
          predict.confirms('What price will Bitcoin hit?', 'b', 'Solana', 'крипто') is False)


def t_prediction_bridge_refuses_to_guess():
    """СВЯЗКА С POLYMARKET (роудмап 3.7): три замка против ложного сопоставления.

    ═══ ГЛАВНАЯ ОПАСНОСТЬ ЗДЕСЬ СМЫСЛОВАЯ, А НЕ ТЕХНИЧЕСКАЯ ═══
    Роудмап предупреждает прямым текстом, и предупреждение оплачено: связку «тикер → внешний
    объект» брать можно только из проверенного сопоставления, потому что вывод по совпадению
    тикера уже стоил проекту трёх экранов. На Variational это не теория: тикер `A` — токен
    Vaulta, `US` — токен Talus. Поиск по «A» вернёт что угодно.

    ЗАМЕР 26.09 НА 13 ЖИВЫХ ИНСТРУМЕНТАХ: нашлось 4 (BTC, ETH, SOL, XRP — все верные, оборот
    $0.6M-$14M), промолчал на 9. Ложных сопоставлений НОЛЬ: Vaulta, Talus, XAGS, FWDI, US500,
    MSTR, MRNA, Gold — все отказались с причиной.
    """
    from sentinel import predict
    try:
        import poly_read as _pr_check                      # noqa: F401
    except ImportError:
        # ПРОПУСК НАЗЫВАЕТ СЕБЯ. Публичная выжимка НАРОЧНО не несёт слой Polymarket: он не про
        # Nansen, и тащить его туда значило бы расширить выжимку тем, чего судья не просил.
        # Но и притворяться, что проверка прошла, нельзя - молчаливо зелёный пропуск это тот же
        # дефект, что молчаливый отказ. Чистые функции моста ниже проверяются и без него.
        global _SKIP
        _SKIP += 1
        print('SKIP  связка Polymarket: в этой сборке нет слоя poly_read (в боте проверка идёт)')
        _pure_only(predict)
        return
    # ── ЗАМОК 1: КОРОТКИЕ И ОБЩИЕ ИМЕНА НЕ СОПОСТАВЛЯЮТСЯ НИКОГДА ─────────────────────────
    for _bad in ('A', 'US', 'Gold', 'ETF', ''):
        check('PM: имя %r к сопоставлению не допускается' % _bad,
              predict.ambiguous(_bad) is not None, predict.ambiguous(_bad))
    check('PM: и причина называется словами, а не «не найдено»',
          'слишком' in (predict.ambiguous('US') or ''), predict.ambiguous('US'))
    for _ok in ('Bitcoin', 'Ethereum', 'Solana'):
        check('PM: имя %s сопоставлять можно' % _ok, predict.ambiguous(_ok) is None)
    # ── ЗАМОК 2+3: ОБРАТНАЯ ПРОВЕРКА НА ФИКСТУРАХ НАСТОЯЩИХ ЗАГОЛОВКОВ ────────────────────
    # Заголовки взяты из живого ответа gamma-api 26.09, а не придуманы.
    _fx = [('Bitcoin above ___ on September 25?', 'bitcoin-above', 'Bitcoin', 'крипто', True),
           ('What price will Ethereum hit in September?', 'eth-price', 'Ethereum', 'крипто', True),
           ('Solana Up or Down - October 5', 'solana-up-down', 'Solana', 'крипто', True),
           ('Will Ethereum flip Bitcoin?', 'eth-flip-btc', 'Ethereum', 'крипто', True),
           # НЕ ПРО ЦЕНУ - отсекается третьим замком. Именно этот случай нашла живая проба:
           # имя есть, категория 'крипто' есть, а рынок про конференцию.
           ('Will the Bitcoin Conference sell out?', 'btc-conf', 'Bitcoin', 'крипто', False),
           ('Bitcoin ETF approved in 2027?', 'btc-etf', 'Bitcoin', 'крипто', False),
           # ЧУЖОЙ АКТИВ и ЧУЖАЯ КАТЕГОРИЯ.
           ('Lakers vs Celtics', 'lakers', 'Bitcoin', 'спорт', False),
           ('What price will Bitcoin hit?', 'btc-price', 'Solana', 'крипто', False)]
    for _t, _s, _n, _c, _want in _fx:
        check('PM: «%s» + имя %s -> %s' % (_t[:38], _n, _want),
              predict.confirms(_t, _s, _n, _c) is _want,
              predict.confirms(_t, _s, _n, _c))
    check('PM: без категории проверка НЕ усиливается сама собой',
          predict.confirms('Will the Bitcoin Conference sell out?', 'c', 'Bitcoin', None) is False,
          'третий замок (про цену) работает и без категории')
    # ── РАСКЛАД КОШЕЛЬКОВ: ВЕДЁМ ДЕНЬГАМИ, А НЕ ЧИСЛОМ АДРЕСОВ ───────────────────────────
    # Форма `holders` взята у готовой двери `nansen_api.pm_reputation` (схема снята пробой 20.09).
    rep = {'holders': [{'addr': '0x1', 'side': 'Yes', 'usd': 50000.0, 'wr': 71.0},
                       {'addr': '0x2', 'side': 'No', 'usd': 9000.0, 'wr': 22.0},
                       {'addr': '0x3', 'side': 'No', 'usd': 8000.0, 'wr': 31.0},
                       {'addr': '0x4', 'side': 'Yes', 'usd': 4000.0, 'wr': None}],
           'no_history': 1}
    sp = predict.sharp_split(rep)
    check('PM: сильные кошельки собраны по стороне и деньгам',
          sp['strong'] == {'Yes': 50000.0}, sp['strong'])
    check('PM: слабые - отдельно', sp['weak'] == {'No': 17000.0}, sp['weak'])
    check('PM: кошелёк БЕЗ истории не причислен ни к сильным, ни к слабым',
          sp['unknown_usd'] == 4000.0 and sp['no_history'] == 1, sp)
    check('PM: сторона перевеса названа', sp['strong_side'] == 'Yes', sp['strong_side'])
    check('PM: пустой ответ даёт None, а не выдуманный расклад',
          predict.sharp_split({'holders': []}) is None)
    # ── МОСТ НЕ ХОДИТ В СЕТЬ, КОГДА ИМЯ ЗАПРЕЩЕНО ────────────────────────────────────────
    # ПОВЕДЕНЧЕСКАЯ ПРОВЕРКА: подменяем чужую дверь на бросающую. Замок обязан сработать ДО
    # запроса - иначе каждый инструмент с мусорным именем стоил бы нам запроса.
    import poly_read as _pr
    _saved = _pr.find_event

    async def _boom(*a, **kw):
        raise AssertionError('мост пошёл в сеть с запрещённым именем')
    _pr.find_event = _boom
    try:
        mk, why = asyncio.run(predict.market_for('A', 'Vaulta'))
        check('PM: имя из стоп-списка не даёт сопоставления', mk is None)
        mk2, why2 = asyncio.run(predict.market_for('US', 'US'))
        check('PM: и запроса в сеть при этом НЕ было', mk2 is None and why2, why2)
    finally:
        _pr.find_event = _saved
    # ── ПОРОГ ОБОРОТА: РЫНОК БЕЗ ДЕНЕГ - НЕ МНЕНИЕ ТОЛПЫ ─────────────────────────────────
    async def _thin(*a, **kw):
        return {'title': 'What price will Bitcoin hit in September?',
                'slug': 'btc-price-sep', 'volume': 100.0}
    _pr.find_event = _thin
    try:
        mk3, why3 = asyncio.run(predict.market_for('BTC', 'Bitcoin'))
        check('PM: рынок с оборотом $100 отвергнут', mk3 is None, mk3)
        check('PM: и причина называет ОБА числа - оборот и порог',
              why3 and '100' in why3 and str(int(predict.MIN_VOLUME_USD)) in why3, why3)
    finally:
        _pr.find_event = _saved


def _ev_for(ticker='BTC', mark='104.0', now=None, kind='move_up'):
    """Живое событие нужного вида через НАСТОЯЩИЙ детектор. -> ev."""
    now = int(now if now is not None else time.time())
    ring = series(60, now - 60 * 900, mark=100.0)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    got = [e for e in detector.detect(one(ticker=ticker, mark=mark, quote_iso=_iso(now)),
                                      hot, now=now, ring=ring) if e['kind'] == kind]
    return got[0] if got else None


def t_the_switch_actually_switches_off():
    """ВЫКЛЮЧАТЕЛЬ ВЫКЛЮЧАЕТ, И ВЫКЛЮЧАЕТ СЕЙЧАС.

    ═══ ЖИВОЙ ИНЦИДЕНТ 25.09, СЛОВА ВЛАДЕЛЬЦА ═══
    «Я сейчас отключил алерты в Дозорном, всё равно всё шлёт мне сигналы… какой-то спам идёт и
    идёт». Причина была не в пресетах: все семь проверок стояли ТОЛЬКО в `plan` (постановка в
    очередь), а `deliver_due` читал очередь и настроек не смотрел ВООБЩЕ. Выключатель управлял
    правом ВСТАТЬ в очередь, а не правом ПРИЙТИ на телефон.

    ЭТОТ ТЕСТ ПАДАЕТ НА СТАРОМ КОДЕ - в этом его смысл. Он ставит доставку в очередь ПРИ
    ВКЛЮЧЁННЫХ алертах, затем выключает их и проверяет, что на телефон не ушло НИЧЕГО.
    """
    now = int(time.time())
    uid = 777001
    store.sub_add(uid, 'BTC')
    store.settings_set(uid, alerts_on=1, enrich_on=0, daily_cap=None, cooldown_min=None,
                       min_pct=None, quiet_from=None, quiet_to=None)
    ev = _ev_for(now=now)
    ev = dict(ev, key='off-1')
    store.event_new(ev)
    outbox.plan(ev)
    # ПРОВЕРЯЕМ СВОЮ СТРОКУ, А НЕ ОБЩЕЕ ЧИСЛО: на BTC к этому моменту подписаны и другие тесты,
    # и счёт «поставлено всего» проверял бы соседей, а не выключатель.
    check('OFF: при включённых алертах доставка встала в очередь',
          any(x[0] == 'off-1' and x[1] == uid for x in store.delivery_due(limit=99)),
          store.delivery_due(limit=99))

    # ЧЕЛОВЕК ВЫКЛЮЧАЕТ АЛЕРТЫ УЖЕ ПОСЛЕ ТОГО, КАК СТРОКА ЛЕГЛА В ОЧЕРЕДЬ.
    store.settings_set(uid, alerts_on=0)
    bot = FakeBot()
    attach(bot)
    asyncio.run(outbox.deliver_due(limit=99))
    check('OFF: после выключения НИ ОДНО сообщение не ушло',
          not [c for c, _t in bot.sent if c == uid],
          'ровно этот дефект владелец видел живьём: «отключил, всё равно шлёт»')
    st = store.delivery_state(ev['key'], uid)
    check('OFF: доставка ОТМЕНЕНА, а не оставлена в очереди',
          st and st['state'] == 'off' and st['delivered_at'] is None, st)
    check('OFF: и причина отмены записана словами',
          st and 'выключены' in (st['last_err'] or ''), st)

    # ОТМЕНА, А НЕ ПРОПУСК: на следующем тике строка не возвращается.
    asyncio.run(outbox.deliver_due(limit=99))
    check('OFF: на следующем тике строка не всплывает снова',
          not [c for c, _t in bot.sent if c == uid], bot.sent)

    # ВЫКЛЮЧЕНИЕ ЧИСТИТ ОЧЕРЕДЬ НЕМЕДЛЕННО И НАЗЫВАЕТ ЧИСЛО.
    store.settings_set(uid, alerts_on=1)
    ev2 = dict(_ev_for(mark='106.0', now=now + 5), key='off-2')
    store.event_new(ev2)
    outbox.plan(ev2)
    ans = ui.route(uid, 'дозор алерты выкл')
    check('OFF: команда словами гасит очередь и говорит СКОЛЬКО',
          ans and 'Отменено в очереди' in ans, ans)
    check('OFF: в очереди человека больше нечего отправлять',
          not [x for x in store.delivery_due(limit=50) if x[1] == uid],
          store.delivery_due(limit=50))

    # ТУМБЛЕР И КОМАНДА ДЕЛАЮТ ОДНО И ТО ЖЕ.
    store.settings_set(uid, alerts_on=1)
    ev3 = dict(_ev_for(mark='108.0', now=now + 10), key='off-3')
    store.event_new(ev3)
    outbox.plan(ev3)
    q = _Q(uid, 'sen:t:al')
    asyncio.run(ui.handle_callback(type('U', (), {'callback_query': q})(), _Ctx()))
    check('OFF: тумблер правда выключил настройку', store.settings(uid)['alerts_on'] == 0)
    check('OFF: ТУМБЛЕР тоже гасит очередь, а не только настройку',
          not [x for x in store.delivery_due(limit=99) if x[1] == uid],
          'иначе «выключил кнопкой, а шлёт» - тот же баг через другую дверь')
    # СВОДКА ВЫКЛЮЧЕННОМУ НЕ ЕДЕТ: иначе поток вернулся бы сводкой того же потока.
    store.digest_add(uid, 'off-3', 90, 'предохранитель')
    before = len([c for c, _t in bot.sent if c == uid])
    asyncio.run(outbox.deliver_digest(now=now + 99999))
    check('OFF: сводка выключенному не едет тоже',
          len([c for c, _t in bot.sent if c == uid]) == before,
          'иначе выключатель оставил бы лазейку: поток вернулся бы сводкой')


def t_burst_guard_is_a_boundary_not_a_setting():
    """ПРЕДОХРАНИТЕЛЬ ТЕМПА: три сообщения за окно, остальное — сводкой. ПРЕСЕТ ЕГО НЕ СНИМАЕТ.

    ЗАМЕР ВЛАДЕЛЬЦА: «за минут больше 70 сообщений», «даже нажать ничего нельзя», «все подряд
    тикеры - это бред». И ключевое: «даже если юзер ошибся или я с выбором пресетов, все подряд
    не нужно кидать».

    ПОЧЕМУ ПАУЗА И ПОТОЛОК, КОТОРЫЕ УЖЕ БЫЛИ, ЭТОГО НЕ ЛОВИЛИ: оба считались ПО ИНСТРУМЕНТУ, а
    инструментов 787 - то есть у бота было 787 независимых законных разрешений заговорить.
    Здесь счёт идёт НА ЧЕЛОВЕКА, поэтому число инструментов роли не играет.
    """
    now = int(time.time())
    uid = 777002
    store.sub_add(uid, store.ALL)
    # ПРЕСЕТ «ПОТОК» - САМЫЕ РАЗРЕШАЮЩИЕ НАСТРОЙКИ, КАКИЕ ЧЕЛОВЕК МОЖЕТ ВЫБРАТЬ.
    store.preset_apply(uid, 'test')
    store.settings_set(uid, enrich_on=0, quiet_from=None, quiet_to=None)
    check('BURST: пресет «поток» правда снял паузу и поднял потолок',
          store.cap_for(uid) == 120 and int(store.settings(uid)['cooldown_min']) == 10)

    bot = FakeBot()
    attach(bot)
    # ДЕСЯТЬ РАЗНЫХ ИНСТРУМЕНТОВ - то есть ни одна пауза по инструменту не мешает.
    for i in range(10):
        e = _ev_for(ticker='TK%d' % i, mark='104.0', now=now + i)
        store.event_new(e)
        outbox.plan(e)
        asyncio.run(outbox.deliver_due())
    got = len([c for c, _t in bot.sent if c == uid])
    check('BURST: ушло не больше границы (%d), а не десять' % config.burst_max(),
          got <= config.burst_max(), got)
    check('BURST: и при этом ушло хоть что-то - молчать предохранитель не должен', got > 0, got)
    pend = store.digest_pending(uid)
    check('BURST: остальное НЕ ПОТЕРЯНО, а лежит в сводке',
          len(pend) >= 10 - config.burst_max() - 1, len(pend))
    check('BURST: у каждой отложенной строки есть ПРИЧИНА отсрочки',
          all(r[2] for r in pend), pend[:3])
    check('BURST: причина называется величиной, а не словом «лимит»',
          any('предохранитель' in (r[2] or '') for r in pend), [r[2] for r in pend[:3]])
    # ГРАНИЦА ПОВЕРХ ЛЮБЫХ НАСТРОЕК: человек выкрутил всё, что мог, и всё равно не залит.
    check('BURST: пресет «поток» предохранитель НЕ СНЯЛ',
          got <= config.burst_max(),
          'иначе ошибка в пресете снова заливала бы человека до невозможности нажать кнопку')


def t_weak_events_do_not_ring():
    """СЛАБОЕ СОБЫТИЕ НЕ ЗВОНИТ, А ИДЁТ В СВОДКУ. Уверенность — величина, а не украшение."""
    now = int(time.time())
    uid = 777003
    store.sub_add(uid, 'BTC')
    store.settings_set(uid, alerts_on=1, enrich_on=0, daily_cap=None, cooldown_min=None,
                       min_pct=None, quiet_from=None, quiet_to=None)
    ev = _ev_for(now=now)
    weak = dict(ev, key='sev-weak', severity=40)
    store.event_new(weak)
    n, why = outbox.plan(weak)
    check('SEV: событие на 40/100 нашему подписчику не звонит',
          not any(x[0] == 'sev-weak' and x[1] == uid for x in store.delivery_due(limit=99)),
          (n, why))
    check('SEV: причина называет ОБА числа - его и порог',
          any('40/100' in w and str(config.min_severity()) in w for w in why), why)
    check('SEV: и оно легло в сводку, а не пропало',
          any(r[0] == 'sev-weak' for r in store.digest_pending(uid)))
    strong = dict(ev, key='sev-strong', severity=90)
    store.event_new(strong)
    outbox.plan(strong)
    check('SEV: событие на 90/100 звонит как раньше',
          any(x[0] == 'sev-strong' and x[1] == uid for x in store.delivery_due(limit=99)))


def t_digest_is_one_message_sorted_by_strength():
    """СВОДКА: одно сообщение, сильное сверху, кнопки на карточки, остаток назван числом."""
    now = int(time.time())
    uid = 777004
    store.sub_add(uid, store.ALL)
    store.settings_set(uid, alerts_on=1, enrich_on=0, quiet_from=None, quiet_to=None)
    keys = []
    for i, sev in enumerate((55, 95, 70, 88)):
        e = _ev_for(ticker='DG%d' % i, mark='104.0', now=now + i)
        e = dict(e, key='dg%d' % i, severity=sev)
        store.event_new(e)
        store.digest_add(uid, e['key'], sev, 'предохранитель: 5 сообщений за 10 мин (граница 3)')
        keys.append((e['key'], sev))
    pend = store.digest_pending(uid)
    check('DIG: порядок ПО СИЛЕ, а не по времени',
          [r[1] for r in pend] == sorted([r[1] for r in pend], reverse=True),
          [r[1] for r in pend])
    check('DIG: сильнейшее сверху', pend[0][1] == 95, pend[0])

    bot = FakeBot()
    attach(bot)
    # ОКНО ВЫДЕРЖКИ: строки только что созданы, и сводка ждать умеет. Время передаём
    # аргументом - тест, который спал бы десять минут, не запускают.
    check('DIG: свежие строки сводкой сразу НЕ уезжают',
          not [c for c, _t in bot.sent if c == uid],
          'иначе сводка уезжала бы по одной строке - тот же поток под другим именем')
    asyncio.run(outbox.deliver_digest(now=now))
    check('DIG: до конца выдержки сводки нет',
          not [c for c, _t in bot.sent if c == uid], bot.sent)
    asyncio.run(outbox.deliver_digest(now=now + config.digest_sec() + 1))
    # ОДНО СООБЩЕНИЕ НА ЧЕЛОВЕКА - главное свойство сводки. Считаем ИМЕННО наши: к этому моменту
    # свои накопления есть и у других подписчиков из предыдущих проверок.
    mine = [t for c, t in bot.sent if c == uid]
    check('DIG: сводка ушла ОДНИМ сообщением', len(mine) == 1,
          [c for c, _t in bot.sent])
    txt = mine[0]
    check('DIG: в сводке есть все четыре инструмента',
          all(('DG%d' % i) in txt for i in range(4)), txt[:300])
    check('DIG: и у каждого ВЕЛИЧИНА, а не только тикер', txt.count('%') >= 4, txt[:300])
    check('DIG: сказано, почему списком, а не звонком', 'Не звонили' in txt, txt[:200])
    check('DIG: сводка размечена HTML', '<b>' in txt)
    check('DIG: строки отмечены отправленными', not store.digest_pending(uid),
          store.digest_pending(uid))
    check('DIG: повторно та же сводка не уедет',
          asyncio.run(outbox.deliver_digest(now=now + 99999))[0] == 0)
    kb = cards.digest_kb([{'ev': store.event(k), 'why': ''} for k, _s in keys])
    flat = [b for row in (kb.inline_keyboard if kb else []) for b in row]
    check('DIG: под сводкой кнопки-тикеры (сквозной сценарий)',
          any('DG0' in (b.text or '') for b in flat), [b.text for b in flat])
    check('DIG: кнопка ведёт в карточку инструмента, а не в никуда',
          any((b.callback_data or '').startswith('sen:card:') for b in flat),
          [b.callback_data for b in flat])
    # ОСТАТОК НАЗЫВАЕТСЯ ЧИСЛОМ
    many = [{'ev': store.event(k), 'why': 'x'} for k, _s in keys]
    card_txt = cards.digest_card(many, extra=34)
    check('DIG: хвост назван числом, а не съеден', 'ещё 34' in card_txt, card_txt[-200:])


def t_queue_is_taken_by_one_process_only():
    """ЗАХВАТ ОЧЕРЕДИ: два процесса читают одну базу и НЕ отправляют одно и то же дважды.

    ВТОРАЯ ПРИЧИНА ПОТОКА, НАЙДЕННАЯ ПО КОДУ. Читателей у очереди два - джоба бота
    (`sentinel_deliver_only`, 30с) и отдельный юнит `sentinel.main` (свой `deliver_tick`, 30с).
    Аренда `store.lease` держит ОПРОС площадки, а доставку не держал никто: оба брали одни и те
    же строки и оба звали Telegram. До 50 сообщений за полминуты и каждый алерт ДВАЖДЫ - это
    ровно арифметика владельца «больше 70 за минуты».
    """
    now = int(time.time())
    uid = 777005
    store.sub_add(uid, 'ETH')
    store.settings_set(uid, alerts_on=1, enrich_on=0, daily_cap=None, cooldown_min=None,
                       min_pct=None, quiet_from=None, quiet_to=None)
    ev = _ev_for(ticker='ETH', mark='104.0', now=now)
    store.event_new(ev)
    outbox.plan(ev)
    check('CLAIM: первый процесс строку взял', store.delivery_claim(ev['key'], uid) is True)
    check('CLAIM: второй процесс ту же строку НЕ получил',
          store.delivery_claim(ev['key'], uid) is False,
          'без захвата оба процесса отправили бы один алерт дважды')
    check('CLAIM: взятая строка из очереди пропала',
          not [x for x in store.delivery_due(limit=50)
               if x[0] == ev['key'] and x[1] == uid])
    # СИРОТА: процесс умер между захватом и отправкой - строка обязана вернуться.
    n = store.delivery_unstick(older_sec=0)
    check('CLAIM: застрявшая в работе строка возвращается в очередь', n >= 1, n)
    check('CLAIM: и снова доступна для отправки',
          any(x[0] == ev['key'] and x[1] == uid for x in store.delivery_due(limit=50)),
          'иначе захват создал бы новый способ потерять алерт МОЛЧА')


def t_emergency_switch_stops_everything():
    """АВАРИЙНЫЙ РУБИЛЬНИК: `SENTINEL_DELIVER=0` глушит отправку целиком и говорит об этом."""
    now = int(time.time())
    uid = 777006
    store.sub_add(uid, 'BTC')
    store.settings_set(uid, alerts_on=1, enrich_on=0, daily_cap=None, cooldown_min=None,
                       min_pct=None, quiet_from=None, quiet_to=None)
    ev = _ev_for(mark='109.0', now=now)
    ev = dict(ev, key='emg1')
    store.event_new(ev)
    outbox.plan(ev)
    bot = FakeBot()
    attach(bot)
    # ЗАПОМИНАЕМ И ВОССТАНАВЛИВАЕМ, А НЕ УДАЛЯЕМ. Первая редакция в `finally` делала `pop`, то
    # есть оставляла окружение НЕ ТАКИМ, каким взяла: ключ исчезал, и следующий тест работал уже
    # на значении из кода вместо тестового. Поймал это сторож изоляции порогов - ровно за тем он
    # и написан. Уборка, меняющая состояние, хуже отсутствующей.
    _prev_deliver = os.environ.get('SENTINEL_DELIVER')
    os.environ['SENTINEL_DELIVER'] = '0'
    try:
        check('STOP: рубильник выключен -> отправки нет', config.deliver_on() is False)
        ok, bad = asyncio.run(outbox.deliver_due())
        check('STOP: ни одного сообщения не ушло',
              ok == 0 and not [c for c, _t in bot.sent if c == uid], (ok, bad, bot.sent))
        check('STOP: сводка тоже молчит',
              asyncio.run(outbox.deliver_digest(now=now + 99999))[0] == 0)
        scr = ui.status_text(uid)
        check('STOP: экран ОБЪЯВЛЯЕТ, что отправка выключена на сервере',
              'SENTINEL_DELIVER' in scr,
              'иначе человек крутит свои настройки, а причина лежит в .env')
        check('STOP: очередь НЕ потеряна - строка ждёт',
              any(x[0] == 'emg1' for x in store.delivery_due(limit=50)),
              'рубильник глушит отправку, а не выбрасывает события')
    finally:
        if _prev_deliver is None:
            os.environ.pop('SENTINEL_DELIVER', None)
        else:
            os.environ['SENTINEL_DELIVER'] = _prev_deliver
    check('STOP: рубильник вернули - отправка снова разрешена', config.deliver_on() is True)
    ok2, _ = asyncio.run(outbox.deliver_due())
    check('STOP: и отложенное рубильником уехало', ok2 >= 1, ok2)


def t_guard_is_visible_on_the_screen():
    """ПРЕДОХРАНИТЕЛЬ ВИДЕН ЧЕЛОВЕКУ. Молчащее правило неотличимо от поломки."""
    uid = 777007
    store.settings_set(uid, alerts_on=1)
    scr = ui.status_text(uid)
    check('SCR: экран называет границу числом',
          str(config.burst_max()) in scr and 'Предохранитель' in scr, scr[:400])
    check('SCR: и говорит, куда девается остальное', 'сводкой' in scr, scr[:400])
    check('SCR: и сколько уже потрачено из окна', 'уже' in scr, scr[:400])


def t_lab_field_name_came_from_the_venue():
    """ЛАБОРАТОРИЯ: имя поля снято ЖИВЫМ ВЫЗОВОМ, а не угадано.

    Первая редакция послала `date` и получила от площадки дословно: «Required field
    'body -> date_range' is missing» (http 422, missing_field). Ручки нет в нашей описи 59
    маршрутов - значит схему называет САМА площадка, и это измерение, а не догадка.
    """
    import inspect
    src = inspect.getsource(lab.holdings)
    check('LAB: в теле запроса стоит date_range', "'date_range'" in src, src[:200])
    check('LAB: старого имени поля больше нет', "'date':" not in src)
    check('LAB: и живой замер записан рядом с кодом', 'date_range' in src and '422' in src)
    calls, credits, line = lab.plan(['0xabc'], 30)
    check('LAB: план расхода печатается ДО траты', 'План:' in line and str(credits) in line)
    rows, refused = lab.holdings('ethereum', '0xabc', days=30)
    check('LAB: сухой прогон ничего не тратит и говорит об этом',
          rows == [] and 'сухой прогон' in (refused or ''), refused)


class _Q:
    """Минимальный callback-запрос: нам нужны только uid, data и факт правки экрана."""
    def __init__(self, uid, data):
        self.data = data
        self.from_user = type('U', (), {'id': uid})()
        self.message = type('M', (), {'chat_id': uid, 'text': 'x'})()
        self.edited = []

    async def answer(self, *a, **kw):
        return True

    async def edit_message_text(self, text=None, reply_markup=None, **kw):
        self.edited.append(text)
        return True


class _Ctx:
    class bot:
        sent = []

        @staticmethod
        async def send_message(chat_id=None, text=None, **kw):
            _Ctx.bot.sent.append((chat_id, text))
            return True


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
               t_db_failure_speaks_with_measurements,
               # ── круг 5 (25.09): площадки как данные, пресеты, HTML на экранах ──
               t_venues_are_data_not_branches,
               t_venue_filter_and_presets_are_personal,
               t_screens_are_sent_as_html,
               # ── круг 6 (25.09): сквозные переходы, читаемые твиты, толпа, поглощение ──
               t_every_screen_leads_further,
               t_tweets_are_readable_and_not_spam,
               t_venue_gaps_do_not_pay_for_missing_fields,
               t_crowd_and_absorption_describe_not_predict,
               # ── круг 7 (25.09): запись после чтений, прямая ссылка на инструмент ──
               t_write_after_many_reads,
               t_link_leads_to_the_instrument,
               # ── круг 8 (25.09): ВЫКЛЮЧАТЕЛЬ НЕ ВЫКЛЮЧАЛ + поток 70 сообщений за минуты ──
               #    Оба дефекта пойманы владельцем на живом боте. Первый - срочный: настройки
               #    проверялись только при постановке в очередь. Второй - архитектурный: пауза
               #    и потолок считались по инструменту, а инструментов 787.
               t_the_switch_actually_switches_off,
               t_burst_guard_is_a_boundary_not_a_setting,
               t_weak_events_do_not_ring,
               t_digest_is_one_message_sorted_by_strength,
               t_queue_is_taken_by_one_process_only,
               t_emergency_switch_stops_everything,
               t_guard_is_visible_on_the_screen,
               t_lab_field_name_came_from_the_venue,
               # ── круг 9 (26.09): настройки кнопками, третья площадка, единица фандинга ──
               t_funding_unit_is_measured_not_guessed,
               t_clusters_count_people_not_addresses,
               t_prediction_bridge_refuses_to_guess,
               # ── круг 9, разбор живого прогона на проде: корень `database is
               #    locked`, зависимость теста от .env машины, третья схема тела ──
               t_one_connection_per_thread_not_per_call,
               t_thresholds_do_not_depend_on_the_machine,
               t_lab_body_matches_the_venue_schema,
               # ── круг 10: экран разделён на основное и «Ещё»; ремонт схемы не
               #    имеет права молча сменить ВОПРОС ──
               t_repair_must_not_change_the_question,
               t_silence_names_the_cap_and_the_dead_poller,
               t_bot_takes_over_a_dead_poller):
        print('\n== %s' % fn.__name__)
        try:
            fn()
        except Exception as e:
            global _FAIL
            _FAIL += 1
            import traceback
            traceback.print_exc()
            _FAILED.append(fn.__name__ + ' (исключение)')
            print('FAIL  %s упал: %s' % (fn.__name__, e))
            # ЗАМЕРЫ БАЗЫ РЯДОМ С ОТКАЗОМ, А НЕ В ГОЛОВЕ РАЗБИРАЮЩЕГО. `database is locked` без
            # пути, бэкенда и таймаута - это приглашение гадать; с ними разбор идёт по числам.
            print('      замеры базы: %s' % _db_diag())
    print('\n%d PASS / %d FAIL%s' % (_OK, _FAIL,
                                    (' / %d SKIP' % _SKIP) if _SKIP else ''))
    if _FAILED:
        print('УПАЛИ (%d):' % len(_FAILED))
        for _n in _FAILED:
            print('  · %s' % _n)
        print('Пришли этот список - по нему причина видна без перелистывания вывода.')
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
