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
sys.path.insert(0, os.path.join(BASE, 'tests'))
# ПРОВЕРКИ «ПРИЧИНА ЗАПИСАНА РЯДОМ С КОДОМ» ИДУТ ПО ПРОЗЕ ЯВНО (gt01): иголка живёт в
# комментарии или докстринге намеренно, и сторож обязан говорить, какую половину он читает.
import guard_text as _gt  # noqa: E402

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


def _sub(uid, ticker):
    """Подписка человека, у которого УЖЕ ЕСТЬ настройки (строка в базе).

    С ЭТАПА 4 первая подписка человека без настроек ставит ему пресет «Новичок» (предохранитель
    2/10, потолок 12, сводка раз в 30 мин). Тесты ниже написаны про общие дефолты - то есть про
    человека, который настройки уже трогал; строка настроек создаётся явно, и это читается как
    утверждение, а не как случайность. Сам дефолтный пресет проверяет `t_presets_stage4`.
    """
    if not store.settings_exists(uid):
        store.settings_set(uid)
    return store.sub_add(uid, ticker)


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
    """Телеграм-заглушка. Помнит И отправленное, И ПРАВКИ.

    ПРАВКИ ПОЯВИЛИСЬ ВМЕСТЕ С ПУНКТОМ 2.6: обогащение теперь дополняет уже отправленную карточку
    вместо второго сообщения. Без `edit_message_text` здесь заглушка отвечала бы отказом, тест
    проходил бы по АВАРИЙНОМУ пути (ответ сообщением) и молча проверял бы не то, что работает.
    `edit_fail=True` - наоборот, проверка аварийного пути.
    """

    def __init__(self, fail=False, edit_fail=False):
        self.sent = []
        self.edits = []
        self.fail = fail
        self.edit_fail = edit_fail

    async def send_message(self, chat_id=None, text=None, **kw):
        if self.fail:
            raise RuntimeError('tg down')
        self.sent.append((chat_id, text))
        return type('M', (), {'message_id': 100 + len(self.sent)})()

    async def edit_message_text(self, chat_id=None, message_id=None, text=None, **kw):
        if self.edit_fail:
            raise RuntimeError('message to edit not found')
        self.edits.append((chat_id, message_id, text))
        return type('M', (), {'message_id': message_id})()


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


#: РАЗБРОС ЦЕНЫ В ТЕСТОВОМ КОЛЬЦЕ. ±0.2% на точку, то есть сигма 15-минутных доходностей около
#: 0.4%. Число выбрано так, чтобы порог в сигмах (`z_min`=2.5) требовал примерно 1% хода: это
#: чуть ниже порога движения (1.2%), и оба порога остаются проверяемыми по отдельности.
_WOBBLE = 0.002


def series(n, start_ts, mark=100.0, step=900, funding=0.05, spread=1.0, oi_usd=1.9e6,
           wobble=_WOBBLE):
    """Холодное кольцо: n точек по 15 минут. Форма кортежа — контракт `store.history`.

    ДЕВЯТОЕ ПОЛЕ - `oi_usd`, ОТКРЫТЫЙ ИНТЕРЕС В ДОЛЛАРАХ, и стоит оно ПОСЛЕДНИМ. Детектор читает
    фандинг и спред по индексам 5 и 6; вставь новую величину в середину - и числа остались бы на
    местах, а смысл поехал бы на одну позицию. Здесь это и проверяется тем, что тесты фандинга и
    спреда продолжают работать без правок.

    ═══ ЦЕНА В КОЛЬЦЕ КОЛЕБЛЕТСЯ, И ЭТО НЕ УКРАШЕНИЕ ТЕСТА (ТЗ 2.1) ═══
    Прежний хелпер держал цену ИДЕАЛЬНО РОВНОЙ, то есть сигма ряда равнялась нулю. До 26.09 такой
    ряд всё равно давал событие - со штрафом к уверенности; теперь «нет измеренной сигмы» значит
    «нет события», и ровный ряд честно перестал их порождать. Значит тест, который проверяет
    ДВИЖЕНИЕ, обязан подавать инструмент с ИЗМЕРЕННЫМ разбросом - иначе он проверяет не движение,
    а отсутствие сигмы. Кому нужен именно ровный ряд (проверка нулевой сигмы), передаёт
    `wobble=0` явно, и это читается как утверждение, а не как случайность.
    """
    # ПЕРИОД КОЛЕБАНИЯ НЕ КРАТЕН ЧЕТЫРЁМ, И ЭТО НЕ ПРИДИРКА. Первая редакция чередовала знак
    # через точку (период 2), а часовая сигма собирается по КАЖДОЙ ЧЕТВЁРТОЙ точке (15 минут в
    # часовую корзину) - и брала из каждой корзины одно и то же значение, то есть ряд часовых
    # доходностей оказывался КОНСТАНТОЙ с нулевой сигмой. Тест «часовое движение публикуется»
    # краснел, хотя код был прав: кольцо действительно не имело измеренного часового разброса.
    # Период 7 даёт ненулевую сигму на обоих окнах сразу.
    return [(start_ts + i * step,
             mark * (1.0 + wobble * (((i * 3) % 7) - 3) / 3.0),
             8e8, 1000.0, 900.0, funding, spread, start_ts + i * step, oi_usd)
            for i in range(n)]


def hot1(ts, mark=100.0, vol=8e8, oi_usd=1.9e6):
    """Одна точка ГОРЯЧЕГО кольца в той же форме, что пишет `engine._row`.

    Заведён ради веток открытого интереса: они сравнивают `oi_usd` текущего снимка с точкой часовой
    давности, и точка без девятого поля означает «интерес час назад не измерен» - то есть событие
    не создаётся вовсе. Это правильное поведение (замера нет - нет и события), но тест обязан
    подавать измеренную точку, когда проверяет сам скачок.
    """
    return (ts, mark, vol, 1000.0, 900.0, 0.05, 1.0, ts, oi_usd)


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
    # С ТЗ 2.5 «Gold» с тикером XAU - металл по РЕЕСТРУ ИМЁН площадки; то же имя с чужим тикером
    # по-прежнему не угадывается (у мема «Gold» с тем же правом может быть это имя).
    check('PARSE: «не акция» НЕ объявляется криптой; металл - только по реестру пары',
          feed.asset_class(one(ticker='XAU', name='Gold')) == 'metal'
          and feed.asset_class(one(ticker='GOLDX', name='Gold')) == 'unknown',
          (feed.asset_class(one(ticker='XAU', name='Gold')),
           feed.asset_class(one(ticker='GOLDX', name='Gold'))))
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
    ring = series(60, now - 60 * 900)                       # разброс измерен: сигма около 0.4%
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    evs = detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now, ring=ring)
    kinds = {e['kind'] for e in evs}
    check('DETECT: 4% за 15 минут - это событие', 'move_up' in kinds, kinds)
    # РОВНЫЙ РЯД ФАНДИНГА - НЕ ХВОСТ. Первая редакция считала «доля не больше x» и на
    # постоянном ряде давала 1.0: «ставка в верхнем хвосте» печаталась на КАЖДОМ тике по
    # инструменту, у которого ставка не менялась вовсе.
    check('DETECT: постоянная ставка не объявляется хвостом', 'funding_extreme' not in kinds,
          kinds)
    # ═══ ПЕРЕПИСАНО 26.09 ПО ПУНКТУ 2.1 ТЗ: НЕТ ИЗМЕРЕННОЙ СИГМЫ - НЕТ СОБЫТИЯ ═══
    # ЧТО ПРОВЕРЯЛОСЬ РАНЬШЕ И ПОЧЕМУ ЭТО БЫЛО НЕВЕРНО. Три проверки выше требовали, чтобы на
    # ровном ряде (сигма = 0) и на короткой выборке событие ОСТАВАЛОСЬ со штрафом к уверенности.
    # Замер прода показал цену такого решения: из 167 движений, доставленных владельцу за сутки,
    # у 147 сигма считалась по МЕНЕЕ ЧЕМ 20 точкам, у большинства - по ОДНОЙ, и они звонили;
    # движения по 1.3-1.8% приходили как «необычные». Штраф -25 давал итог 75 при пороге звонка
    # 70, то есть порог проходился ЗА СЧЁТ подмены отсутствующего замера замером похуже.
    # Это закон 41, и теперь он соблюдается: событие не создаётся вовсе.
    flat = series(60, now - 60 * 900, wobble=0)              # ровный ряд: сигма ровно нулевая
    ev_flat = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                          ring=flat) if e['kind'].startswith('move')]
    check('DETECT: сигма, измеренная нулём, события НЕ даёт (было: давала со штрафом)',
          not ev_flat,
          'нулевая сигма означает, что провайдер повторял одно число, а не что рынок стоял')
    evs2 = detector.detect(one(mark='100.5', quote_iso=_iso(now)), hot, now=now, ring=ring)
    check('DETECT: 0.5% - не событие', not [e for e in evs2 if e['kind'].startswith('move')])
    short = series(3, now - 3 * 900)
    ev3 = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                      ring=short) if e['kind'] == 'move_up']
    check('DETECT: на выборке из 3 точек события НЕТ (было: было, со штрафом -25)', not ev3,
          'сигма по трём точкам - случайное число, и «z=40» на ней означает лишь недавний старт')
    # А ВОТ НА СРЕДНЕЙ ВЫБОРКЕ СОБЫТИЕ ЕСТЬ, И ОНО ПЛАТИТ ЗА НЕЁ ЧЕСТНЫМ ШТРАФОМ -10.
    mid = series(25, now - 25 * 900)
    ev_mid = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                         ring=mid) if e['kind'] == 'move_up']
    check('DETECT: 20-49 точек - событие есть', ev_mid, mid[:1])
    check('DETECT: и выборка названа словами, а уверенность ниже сотни',
          ev_mid and any('выборка небольшая' in p for p in ev_mid[0]['payload']['penalties'])
          and ev_mid[0]['severity'] < 100,
          (ev_mid[0]['payload']['penalties'], ev_mid[0]['severity']) if ev_mid else None)
    # ЧАСОВОЕ ОКНО ТЕПЕРЬ ПРОВЕРЯЕТСЯ СВОЕЙ СИГМОЙ, А НЕ ПЯТНАДЦАТИМИНУТНОЙ.
    # Раньше ветка 60 минут не проверяла порог в сигмах ВООБЩЕ, а в карточку печатался `z`,
    # посчитанный по 15-минутному разбросу - то есть «необычность» часового хода завышалась.
    hot60 = [(now - 3600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 3600)]
    # КОЛЬЦО ДЛЯ ЧАСОВОЙ СИГМЫ ОБЯЗАНО БЫТЬ ДЛИННЫМ, И ЭТО ИЗМЕРЕННОЕ СЛЕДСТВИЕ ПРАВИЛА:
    # 20 часовых доходностей набираются за 21 ЧАС наблюдения. Пятнадцатиминутному окну хватает
    # пяти часов, часовому - почти суток. Значит после рестарта часовые движения молчат дольше,
    # и знать это лучше из теста, чем из вопроса «почему час ничего не приходит».
    ring60 = series(90, now - 90 * 900)
    ev60 = [e for e in detector.detect(one(mark='103.0', quote_iso=_iso(now)), hot60, now=now,
                                       ring=ring60) if e['kind'] == 'move_up']
    check('DETECT: часовое движение публикуется и помечено своим окном',
          ev60 and ev60[0]['payload'].get('sigma_window') == '60м',
          ev60[0]['payload'].get('sigma_window') if ev60 else None)
    check('DETECT: и «необычность» в карточке считается по ТОМУ ЖЕ окну',
          ev60 and ev60[0]['payload'].get('z') is not None
          and abs(ev60[0]['payload']['z']) >= config.z_min(),
          ev60[0]['payload'].get('z') if ev60 else None)
    # ОКНО НЕДОСТУПНО -> МОЛЧАНИЕ, А НЕ «0%»
    # С ЭТАПА 5 ЧАС БЕРЁТСЯ И ИЗ ХОЛОДНОГО КОЛЬЦА (ТЗ 5.3), поэтому «точки в прошлом нет»
    # проверяется кольцом, в котором её НЕТ: последние два часа пусты.
    _ring_old = [r for r in ring if r[0] < now - 2 * 3600]
    ev4 = detector.detect(one(mark='104.0', quote_iso=_iso(now)), [], now=now, ring=_ring_old)
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
    # ЧИСЛА ИНТЕРЕСА ЗДЕСЬ - В ДОЛЛАРАХ, И ЭТО НЕ КОСМЕТИКА ТЕСТА. Variational отдаёт
    # `long_open_interest`/`short_open_interest` уже в долларах (замер 26.09), а прежний код
    # домножал их на цену - отсюда 118 невозможных событий из 139 за сутки. Раньше тест подавал
    # «5000 контрактов» и проходил ровно потому, что повторял ошибку кода.
    hot = [hot1(now - 3600)]
    # ОБОРОТ $50M ЗАДАН ЯВНО (ТЗ 2.4): порог в деньгах теперь max($250k, 3% оборота 24ч), и при
    # дефолтном обороте фикстуры ($800M) он был бы $24M - скачок на $4M честно не прошёл бы.
    evs = detector.detect(one(mark='100.0', oi_l='5000000', oi_s='900000', vol='50000000',
                              quote_iso=_iso(now)),
                          hot, now=now, ring=ring)
    check('OI: скачок интереса при стоящей цене — событие',
          'oi_surge' in {e['kind'] for e in evs}, {e['kind'] for e in evs})
    _oi = [e for e in evs if e['kind'] == 'oi_surge'][0]['payload']
    check('OI: прирост назван в ДОЛЛАРАХ и без второго умножения на цену',
          abs(_oi['oi_change_usd'] - 4.0e6) < 1.0, _oi['oi_change_usd'])
    # АБСОЛЮТНЫЙ ПОРОГ РЯДОМ С ПРОЦЕНТНЫМ: +20% к интересу, которого было на копейки, - это
    # копейки. Без этой проверки процент один решал бы, и алерт приходил бы по пустякам.
    # ПРОЦЕНТ ЗДЕСЬ ПРОХОДИТ (+30%), А ДЕНЬГИ НЕТ ($60k) - значит проверяется именно порог в
    # деньгах, а не заодно сработавший процентный.
    hot_small = [hot1(now - 3600, oi_usd=2.0e5)]
    small = detector.detect(one(mark='100.0', oi_l='130000', oi_s='130000', quote_iso=_iso(now)),
                            hot_small, now=now, ring=ring)
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
    # С ЭТАПА 3: уверенность - одним числом в строке заголовка, дисклеймера нет вовсе.
    check('CARD: уверенность числом в заголовке', '· 100/100' in head, head)
    check('CARD: дисклеймера «причину не читает» больше нет (строка не меняет решение)',
          txt.count('•') <= 1 and 'Причину движения дозорный не читает' not in txt, txt)
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
    _sub(UID, 'BTC')
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
    _sub(UID2, 'ETH')
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
    """ОБОГАЩЕНИЕ: ПРАВКА карточки, только доставленным, провал не трогает первое.

    ПЕРЕПИСАН 26.09 ПО ПУНКТУ 2.6 ТЗ. Раньше здесь утверждалось «сводка ушла ВТОРЫМ
    СООБЩЕНИЕМ» - и это было верное описание кода, который давал замеренный на проде результат:
    280 алертов и 279 обогащений за сутки, то есть каждый алерт приходил дважды и половина
    потока была контекстом. Теперь основной путь - правка уже отправленной карточки: она не
    будит телефон и в окно предохранителя не входит. Второе сообщение осталось АВАРИЙНЫМ путём
    (сообщение удалено или слишком старое), и оно в окно входит - проверяется ниже отдельно.
    ТИКЕР У ТЕСТА СВОЙ. С появлением нитей (2.2) общий 'BTC' означал, что событие попадает в
    нить, открытую предыдущим тестом, и не доставляется вовсе: правильное поведение кода ломало
    тест, который про обогащение, а не про нити.
    """
    now = int(time.time())
    store.settings_set(UID, alerts_on=1, enrich_on=1, daily_cap=None)
    key = 'evtest%d' % now
    store.event_new({'key': key, 'ts': now, 'kind': 'move_up', 'ticker': 'ENR',
                     'severity': 80, 'payload': {'mark': 100.0, 'move_pct': 4.0,
                                                 'venue': 'variational', 'step': 1,
                                                 'penalties': []}})
    _sub(UID, 'ENR')
    store.delivery_plan(key, UID)
    bot = FakeBot()
    attach(bot)
    asyncio.run(outbox.deliver_due())
    check('ENRICH: сводку ждут только доставленные',
          key in store.enrich_pending(limit=10), store.enrich_pending(limit=10))
    check('ENRICH: замок на строке не даёт купить сводку дважды',
          store.enrich_claim(key) is True and store.enrich_claim(key) is False)
    brief = {'lines': ['Покупали за 3 ч:', '  • Fund A: $48000'],
             'refused': 'X: нет ключа TWITTERAPI_IO_KEY', 'summary': '',
             'cost_line': 'Стоимость сводки: 10 кр'}
    _was_sent = len(bot.sent)
    # ОКНО СРАВНИВАЕМ ПРИРОСТОМ, А НЕ АБСОЛЮТОМ: в общем прогоне этому же человеку до нас уже
    # приходили алерты других тестов, и проверка «в окне меньше двух» краснела бы от порядка.
    _win_before = store.sent_in_window(UID, 600)
    n = asyncio.run(outbox.deliver_enrichment(key, brief))
    check('ENRICH: контекст пришёл ПРАВКОЙ карточки, а не вторым сообщением',
          n == 1 and len(bot.edits) == 1 and len(bot.sent) == _was_sent,
          (bot.edits, bot.sent[_was_sent:]))
    txt = bot.edits[0][2]
    check('ENRICH: правка несёт И карточку, И контекст (человек не теряет числа)',
          'ENR' in txt and 'Fund A' in txt, txt[:200])
    check('ENRICH: предохранитель правку НЕ считает - телефон она не будила',
          store.sent_in_window(UID, 600) == _win_before,
          (_win_before, store.sent_in_window(UID, 600)))
    # ── АВАРИЙНЫЙ ПУТЬ: правка не удалась -> ответ сообщением, и он в окно ВХОДИТ ─────────
    key2 = 'evtest2%d' % now
    store.event_new({'key': key2, 'ts': now, 'kind': 'ignition', 'ticker': 'ENR',
                     'severity': 85, 'payload': {'mark': 100.0, 'venue': 'variational',
                                                 'symbol': 'ENR', 'penalties': []}})
    store.delivery_plan(key2, UID)
    bot2 = FakeBot(edit_fail=True)
    attach(bot2)
    asyncio.run(outbox.deliver_due())
    _before = len(bot2.sent)
    n3 = asyncio.run(outbox.deliver_enrichment(key2, brief))
    check('ENRICH: отказ правки не теряет контекст - он уезжает ответом',
          n3 == 1 and len(bot2.sent) == _before + 1, (n3, bot2.sent[_before:]))
    txt = bot2.sent[-1][1]
    # С ЭТАПА 3 ОТКАЗ ЧЕЛОВЕКУ НЕ ПЕЧАТАЕТСЯ: он в логе (`enrichment.build`), а в карточке -
    # только то, что меняет решение.
    check('ENRICH: отказ «чего не собрали» в карточку не попадает', 'нет ключа' not in txt
          and 'Чего не собрали' not in txt and 'Стоимость сводки' not in txt, txt)
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
    # ═══ РОЛЬ ВМЕСТО ФЛАГА: КТО ИМЕННО ОПРАШИВАЕТ (ЗАМЕР 26.09) ═══
    # На проде опрос вели ДВА процесса по очереди, раз в TTL+90с вместо 30с, потому что оба
    # читали `SENTINEL_IN_BOT=0` как «опрашивает кто-то другой». Юнит при этом печатал «опрос у
    # отдельного юнита», будучи этим самым юнитом. Проверяем поведение, а не текст переменной.
    _env0 = os.environ.get('SENTINEL_ROLE')
    try:
        os.environ['SENTINEL_ROLE'] = 'poller'
        check('ROLE: юнит с ролью poller считает опрос СВОИМ делом', config.is_poller() is True)
        check('ROLE: роль едет в имени владельца аренды',
              store.lease_role(store._me()) == 'poller', store._me())
        os.environ['SENTINEL_ROLE'] = 'deliver'
        check('ROLE: бот по умолчанию доставщик, а не опрашивающий',
              config.is_poller() is False)
        os.environ.pop('SENTINEL_ROLE', None)
        check('ROLE: переменной нет -> НЕ опрашивающий (забытая строка не даёт второго опроса)',
              config.is_poller() is False)
        os.environ['SENTINEL_ROLE'] = 'polller'
        check('ROLE: опечатка в роли не превращает доставщика в опрашивающего',
              config.is_poller() is False)
        # ВЫТЕСНЕНИЕ: доставщик подхватил опрос, опрашивающий вернулся - и забирает аренду СРАЗУ,
        # не дожидаясь её истечения. Иначе каждый рестарт юнита стоил бы дырки в кольце.
        store.lease_release('t2', owner='deliver@bot:1')
        check('ROLE: доставщик взял опрос, пока опрашивающего не было',
              store.lease('t2', ttl=600, owner='deliver@bot:1') is True)
        check('ROLE: вернувшийся опрашивающий забирает аренду сразу',
              store.lease('t2', ttl=600, owner='poller@unit:2') is True)
        _o, _u = store.lease_owner('t2')
        check('ROLE: и владельцем записан именно он', _o == 'poller@unit:2', _o)
        check('ROLE: доставщик НЕ вытесняет живого опрашивающего (иначе аренда прыгала бы)',
              store.lease('t2', ttl=600, owner='deliver@bot:1') is False)
        check('ROLE: аренда старой формы (без роли) считается доставщиком, а не опрашивающим',
              store.lease_role('host:123') == 'deliver')
        check('SRV: юнит выдаёт себе роль poller в файле службы',
              'SENTINEL_ROLE=poller' in open('deploy/sentinel.service', encoding='utf-8').read())
    finally:
        if _env0 is None:
            os.environ.pop('SENTINEL_ROLE', None)
        else:
            os.environ['SENTINEL_ROLE'] = _env0


def t_rings_and_outcome_are_measured_not_told():
    """ДВА КОЛЬЦА И ИСХОД: холодное живёт в базе, исход мерится нашими же снимками."""
    now = int(time.time())
    x = one(ticker='SOL', name='Solana', mark='150.0')
    n = store.snapshot_put([x], ts=now - 3600)
    check('RING: снимок записался', n == 1)
    hist = store.history('variational', 'SOL', since_ts=now - 7200)
    check('RING: читается по индексу (PG не даёт доступ по имени)',
          hist and hist[0][1] == 150.0, hist[:1])
    # ═══ ДВЕ ПЛОЩАДКИ В ОДНУ СЕКУНДУ - ДВЕ СТРОКИ, А НЕ ОДНА ═══
    # ДО 26.09 ключом кольца была пара (тикер, секунда), и `INSERT OR REPLACE` затирал снимок
    # одной площадки снимком другой. На проде это дало 48 740 строк, в которых смешаны цены трёх
    # площадок, а детектор, читавший кольцо по ключу «площадка:тикер», не находил НИ ОДНОЙ.
    _hl = one(ticker='SOL', name='Solana', mark='151.5')
    _hl.venue = 'hyperliquid'
    store.snapshot_put([_hl], ts=now - 3600)
    _var = store.history('variational', 'SOL', since_ts=now - 7200)
    _hyp = store.history('hyperliquid', 'SOL', since_ts=now - 7200)
    check('RING: снимки двух площадок в одну секунду лежат ОБА и не перетёрлись',
          len(_var) == 1 and len(_hyp) == 1 and _var[0][1] == 150.0 and _hyp[0][1] == 151.5,
          (_var[:1], _hyp[:1]))
    check('RING: история одной площадки не отдаёт строки другой',
          all(abs(r[1] - 151.5) > 0.1 for r in _var), _var[:2])
    store.snapshot_put([one(ticker='SOL', name='Solana', mark='156.0')], ts=now - 60)
    engine._COLD.pop('variational:SOL', None)
    key = 'outc%d' % now
    # ПЛОЩАДКА В PAYLOAD - ЭТО ТО, ЧЕМ ЗАМЕР ИСХОДА НАХОДИТ НУЖНОЕ КОЛЬЦО (см. `engine._mark_at`).
    store.event_new({'key': key, 'ts': now - 3600, 'kind': 'move_up', 'ticker': 'SOL',
                     'severity': 70,
                     'payload': {'mark': 150.0, 'venue': 'variational', 'penalties': []}})
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
    ok, why = _sub(uid, 'ZZTEST')
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
          {'sen:pr:newbie', 'sen:pr:trader', 'sen:pr:quiet'} <= set(main_data), main_data)
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
    _sub(uid, 'BTC')
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
    # ═══ ПЕРЕПИСАНО 26.09 ВМЕСТЕ С ПУНКТОМ 1.4 ТЗ. ЧТО ИМЕННО ИЗМЕНИЛОСЬ И ПОЧЕМУ ═══
    # Прежний тест подавал ОДИН список и требовал, чтобы в нём прочитались И покупки, И продажи -
    # он закреплял правило «бери первое непустое поле объёма». Это правило и было дефектом: у
    # КАЖДОЙ строки ответа `tgm/who-bought-sold` есть оба поля, первым в списке стоял
    # `bought_volume_usd`, и в разделе «Продавали» печаталась сумма ПОКУПОК того же адреса.
    # Живой замер владельца 26.09: Token Millionaire продал на $74 959, купил на $14 773 - в
    # карточке стояло «$14.8k»; чистый продавец с нулевыми покупками печатался как «$0».
    # Поэтому теперь сторона ЗАДАЁТСЯ ВЫЗОВОМ, и тест проверяет именно это: одни и те же строки,
    # прочитанные как покупки и как продажи, дают РАЗНЫЕ суммы.
    rows = [{'address': '0x' + 'ab' * 20, 'address_label': 'Fund A',
             'bought_volume_usd': 48000, 'sold_volume_usd': 0},
            {'address': '0x' + 'cd' * 20, 'bought_volume_usd': 14773,
             'sold_volume_usd': 74959},
            {'address': '0x' + 'ef' * 20}]
    buy = '\n'.join(en._who_lines(rows, 'Покупали за 3 ч', bot_un='testbot', side='BUY'))
    sell = '\n'.join(en._who_lines(rows, 'Продавали за 3 ч', bot_un='testbot', side='SELL'))
    check('WHO: покупки читаются из bought_volume_usd', '$48.0k' in buy, buy)
    check('WHO: продажи читаются из sold_volume_usd', '$75.0k' in sell, sell)
    check('WHO: в продажах НЕ печатается сумма покупок того же адреса (живой дефект 26.09)',
          '$14.8k' not in sell, sell)
    check('WHO: нулевую сторону не печатаем вовсе - «$0» это не измерение, а шум',
          'Fund A' not in sell and '$0' not in sell, sell)
    check('WHO: строка без объёма вообще не печатается',
          ('0xefef' not in buy) and ('0xefef' not in sell), (buy, sell))
    # ПРОВЕРЯЕМ ВИДИМЫЙ ТЕКСТ, А НЕ ИСХОДНИК СТРОКИ: адрес обязан быть в АТРИБУТЕ ссылки (по нему
    # открывается экран кошелька) и не обязан быть на экране - человек читает метку, а сорок два
    # символа hex не читает и не сравнивает. Первая редакция проверки смотрела на строку целиком
    # и краснела на своей же ссылке.
    import re as _re2
    seen = _re2.sub(r'<[^>]+>', '', buy)
    check('WHO: метка читается вместо сорока двух символов hex',
          'Fund A' in seen and ('0x' + 'ab' * 20) not in seen, seen)
    check('WHO: адрес без метки сокращён', '0xcdcd…cdcd' in sell, sell)
    check('WHO: кошелёк - ССЫЛКА на свой экран в боте',
          't.me/testbot?start=acc_0x' in buy, buy)
    check('WHO: и цена одного токена под сумму НЕ берётся',
          'price_usd' not in en._VOL_FIELDS,
          'спутать их значит напечатать $0.99 вместо $48K')
    # ОДИНАКОВЫЕ МЕТКИ РАЗЛИЧАЮТСЯ ХВОСТОМ АДРЕСА: три строки «Token Millionaire» подряд читаются
    # как ОДИН кошелёк, то есть ровно наоборот смыслу сигнала «несколько РАЗНЫХ адресов».
    same = [{'address': '0x' + '11' * 20, 'address_label': 'Token Millionaire',
             'sold_volume_usd': 50000},
            {'address': '0x' + '22' * 20, 'address_label': 'Token Millionaire',
             'sold_volume_usd': 40000}]
    st = '\n'.join(en._who_lines(same, 'Продавали', side='SELL'))
    check('WHO: одинаковые метки различимы хвостом адреса',
          '…1111' in st and '…2222' in st, st)
    # НЕТТО СЧИТАЕТ КОД, А НЕ ЧЕЛОВЕК ГЛАЗАМИ ПО ШЕСТИ СТРОКАМ.
    line, net, turn = en._net_line([rows[0]], [rows[1]], hours=3)
    check('NET: нетто считается кодом и печатается со знаком',
          line and '-' in line and '$27' in line, (line, net))
    check('NET: оборот отдаётся отдельно - по нему решается, платить ли за перп-контекст',
          abs(turn - (48000 + 74959)) < 1, turn)


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
    # ПУСТО И ГОРЯЧЕЕ, И ХОЛОДНОЕ (этап 3: без горячего экран читает базу - см. ниже).
    _rs = store.ring_since
    store.ring_since = lambda *_a, **_k: {}
    try:
        check('NOW: пустое кольцо тоже объяснено словами',
              'Кольцо пустое' in (engine._HOT.clear() or ui.now_text('ru')), ui.now_text('ru'))
    finally:
        store.ring_since = _rs
    # БОТ БЕЗ СВОЕГО ОПРОСА (опрос в юните): горячего кольца нет - срез из холодного в базе.
    _xs = one(ticker='NOWDB', name='Now DB', mark='20.0')
    store.snapshot_put([_xs], ts=now - 30)
    engine._HOT.clear()
    _m = engine.market_now(now=now)
    check('NOW: без горячего кольца срез собирается из базы, а не «кольцо пустое»',
          _m['tickers'] >= 1 and 'Кольцо пустое' not in ui.now_text('ru'), _m['tickers'])
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
    # КОЛЬЦО НА 25 ЧАСОВ (ТЗ 2.4): порог оборота мерится медианой СВОИХ часовых приростов, и она
    # требует `sigma_min_points` часов. На 15-часовом кольце (60 точек) события нет - это
    # проверяется отдельно в `t_vol_and_oi_thresholds_are_measured_2_4`.
    ring = series(100, now - 100 * 900)
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


def t_open_interest_is_dollars_on_every_venue():
    """ОТКРЫТЫЙ ИНТЕРЕС: единицу ставит слой площадки, детектор считает только доллары.

    ═══ ЗАМЕР 26.09: ТРИ ПЛОЩАДКИ - ТРИ ЕДИНИЦЫ В ОДНОМ ПОЛЕ ═══
    Variational отдаёт стороны интереса УЖЕ В ДОЛЛАРАХ, Hyperliquid и Lighter - в базовом активе.
    Детектор умножал на цену ВСЁ и одинаково, и это дало на проде 118 невозможных событий из 139:
    DELL показывал прирост $47.79M при суточном обороте $497k, SOL - $1.04B, Lighter по BTC
    выходил на 13.7 ТРИЛЛИОНА (там умножение случалось дважды).
    Тест идёт по каждой площадке отдельно, потому что общего правила «если число маленькое, это
    контракты» не существует: это была бы догадка о рынке, а не замер.
    """
    # ── VARIATIONAL: числа из живого ответа по DELL (интерес $309 586 при обороте $497k) ──
    _dell = one(ticker='DELL', name='Dell Technologies', mark='142.0',
                oi_l='154793', oi_s='154793', vol='497000')
    check('OIU: Variational - стороны складываются КАК ЕСТЬ, без умножения на цену',
          abs(_dell.oi_usd - 309586.0) < 1.0, _dell.oi_usd)
    check('OIU: и это $310k, а не $174M (как печаталось на проде)',
          _dell.oi_usd < 1e6, _dell.oi_usd)
    # ── HYPERLIQUID: интерес в БАЗОВОМ активе, перевод один раз (BTC 37 639 при цене 84k) ──
    _hl = feed.Listing(ticker='BTC', name='BTC', mark=84000.0, volume_24h=1e9,
                       oi_long=None, oi_short=None, venue='hyperliquid')
    _hl.oi_total_raw = 37639.0
    _hl.oi_usd = _hl.oi_total_raw * _hl.mark
    check('OIU: Hyperliquid - база на цену, получается 3.16 млрд',
          abs(_hl.oi_usd - 3.16e9) / 3.16e9 < 0.01, _hl.oi_usd)
    # ── LIGHTER: та же база, но умножение было ДВАЖДЫ (в слое площадки и ещё в детекторе) ──
    _lg = feed.Listing(ticker='BTC', name='BTC', mark=83900.0, volume_24h=1e9,
                       oi_long=None, oi_short=None, venue='lighter')
    _lg.oi_usd = 1953.5 * _lg.mark
    check('OIU: Lighter - 1953.5 BTC это 164 млн, а не 13.7 триллиона',
          1.5e8 < _lg.oi_usd < 1.8e8, _lg.oi_usd)
    # ── ДЕТЕКТОР НЕ УМНОЖАЕТ НИЧЕГО: та же цифра интереса при РАЗНОЙ цене даёт тот же прирост ──
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [hot1(now - 3600, oi_usd=1.0e6)]
    ev_a = [e for e in detector.detect(
        one(mark='100.0', oi_l='2000000', oi_s='0', vol='20000000', quote_iso=_iso(now)),
        hot, now=now, ring=ring) if e['kind'] == 'oi_surge']
    ev_b = [e for e in detector.detect(
        one(mark='5000.0', oi_l='2000000', oi_s='0', vol='20000000', quote_iso=_iso(now)),
        hot, now=now, ring=ring) if e['kind'] == 'oi_surge']
    check('OIU: прирост интереса НЕ зависит от цены инструмента (цена больше не множитель)',
          ev_a and ev_b and abs(ev_a[0]['payload']['oi_change_usd']
                                - ev_b[0]['payload']['oi_change_usd']) < 1.0,
          [e[0]['payload']['oi_change_usd'] for e in (ev_a, ev_b) if e])
    # ── СТОРОЖ СОГЛАСОВАННОСТИ: прирост больше двух оборотов - молчим, а не «штрафуем» ──
    # Случай DELL с прода: оборот $497k, «прирост» $47.79M. Это не неточность, это разные
    # величины, и событие с таким числом вреднее молчания - человек по нему заходит.
    hot_small = [hot1(now - 3600, vol=497000.0, oi_usd=2.0e5)]
    bad = detector.detect(one(mark='142.0', oi_l='24000000', oi_s='24000000',
                              vol='497000', quote_iso=_iso(now)),
                          hot_small, now=now, ring=ring)
    check('OIU: прирост больше двух суточных оборотов события НЕ даёт',
          'oi_surge' not in {e['kind'] for e in bad}, {e['kind'] for e in bad})
    check('OIU: и поглощение на тех же несогласованных числах тоже молчит',
          'absorption' not in {e['kind'] for e in bad}, {e['kind'] for e in bad})
    # ── КОЛЬЦО ХРАНИТ ДОЛЛАРЫ ОТДЕЛЬНЫМ ПОЛЕМ, И ОНО ПОСЛЕДНЕЕ В КОРТЕЖЕ ──
    _t = int(time.time())
    _x = one(ticker='OIU', name='OIU', mark='10.0', oi_l='700000', oi_s='300000')
    store.snapshot_put([_x], ts=_t)
    _h = store.history('variational', 'OIU', since_ts=_t - 60)
    check('OIU: кольцо вернуло 9 полей, интерес в долларах - последним',
          _h and len(_h[0]) == 9 and abs(_h[0][8] - 1.0e6) < 1.0, _h[:1])
    check('OIU: фандинг и спред остались на своих индексах (сдвига нет)',
          _h and _h[0][5] == 0.05 and _h[0][6] == 1.0, _h[:1])


def t_perp_context_on_real_nansen_shapes():
    """ПЕРП-КОНТЕКСТ И СЕГМЕНТЫ НА НАСТОЯЩИХ ОТВЕТАХ NANSEN (фикстура живой пробы 26.09).

    ЗАЧЕМ ФИКСТУРА, А НЕ ЗАГЛУШКА. Строка «С плечом» в 1b не появилась НИ РАЗУ: код перебирал
    словарь `perp_positioning_data` как список и падал на строке-ключе. Тест на самодельной
    заглушке этого поймать не мог - заглушка была той формы, которую ожидал код, а не той, что
    отдаёт Nansen. Нашёл живой прогон; теперь форма живого ответа закреплена фикстурой.
    """
    import json as _json
    from sentinel import enrichment as en
    import nansen_api as N
    # ПУТЬ ФИКСТУРЫ - ОБА МИРА: в боте `nansen/fixtures/`, в публичной выжимке `fixtures/`.
    _fxp = os.path.join(BASE, 'nansen', 'fixtures', 'sentinel_perp_context.json')
    if not os.path.exists(_fxp):
        _fxp = os.path.join(BASE, 'fixtures', 'sentinel_perp_context.json')
    fx = _json.load(open(_fxp,
                         encoding='utf-8'))
    _pi, _pp = N.perp_positioning, N.perp_positions
    N.perp_positioning = lambda key: (fx['position_intelligence_HYPE'][0] if key == 'HYPE'
                                      else None)
    N.perp_positions = lambda key, n=20: fx['perp_positions_JUP'] if key == 'JUP' else []
    try:
        lines, cr = asyncio.run(en._perp_lines('HYPE', None, None, 100.0, 'hyperliquid'))
        body = '\n'.join(lines)
        check('PCTX: строка «С плечом» собирается из настоящего ответа (дефект 1b)',
              'С плечом' in body and 'смарт-трейдеры лонг' in body, body)
        lines2, _ = asyncio.run(en._perp_lines('JUP', None, None, 0.35, 'variational'))
        body2 = '\n'.join(lines2)
        check('PCTX: ликвидации есть и у события не с Hyperliquid, и площадка названа',
              'Ликвидации' in body2 and '(Hyperliquid)' in body2, body2)
        _ref = sorted(float(r['mark_price']) for r in fx['perp_positions_JUP'])[20]
        check('PCTX: расстояние до ликвидации считается от цены Hyperliquid, а не события',
              en._liq_line(fx['perp_positions_JUP'], _ref) in body2, (body2, _ref))
    finally:
        N.perp_positioning, N.perp_positions = _pi, _pp
    seg = en.segment_text(fx['flow_intelligence_JUP'][0], 25000)
    check('PCTX: сегменты за сутки - одной строкой и только значимые',
          seg and seg.startswith('• за сутки:'), seg)
    check('PCTX: при пороге выше всех чисел строки нет вовсе',
          en.segment_text(fx['flow_intelligence_JUP'][0], 1e12) is None)
    check('PCTX: биржи в строку не идут (их знак читается наоборот)',
          seg is None or 'бирж' not in seg, seg)
    from sentinel import assets
    check('PCTX: HYPE - нативная монета, ончейн по солановскому однофамильцу не зовётся',
          assets.onchain_refusal('HYPE') is not None, assets.onchain_refusal('HYPE'))


def t_ignition_without_mcap_goes_to_digest():
    """ЗАЖИГАНИЕ: звонит только то, что прошло ВСЕ ТРИ порога (решение владельца 26.09).

    Замер ленты: SI - шесть адресов на $43.8k, капитализации нет. Без неё третий порог (доля
    рынка) не проверен, и прежде такое событие звонило со штрафом - то есть непроверенное
    подменялось уверенностью похуже.
    """
    from sentinel import ignition
    now = int(time.time())
    check('IGN: дефолт суммы - $100 000 (p99 полного окна 180 мин: 133 токена, $113k)',
          config.ign_usd() == 100000.0 or os.getenv('SENTINEL_IGN_USD'), config.ign_usd())
    base = {'chain': 'solana', 'address': 'SiMint', 'symbol': 'SI',
            'wallets': {'a', 'b', 'c', 'd', 'e', 'f'}, 'labels': ['Smart Trader'],
            'usd': 143842.0, 'trades': 6, 'age_days': 40.0, 'last_ts': now - 60,
            'usd_by': {}, 'txs': set()}
    ev = ignition.judge(dict(base, mcap=None), now=now)
    check('IGN: без капитализации событие ЕСТЬ (оно посчитано и записано)', ev, ev)
    check('IGN: но помечено «только в сводку» с причиной словами',
          ev and ev['payload'].get('digest_only') == 'капитализация неизвестна, долю проверить нечем',
          ev['payload'] if ev else None)
    uid = UID + 13
    store.settings_set(uid, alerts_on=1, min_sev=0, burst_max=50, daily_cap=200)
    v, why = outbox.mute_reason(uid, ev, now=now)
    check('IGN: и в звонок не идёт ни при какой уверенности - только в сводку',
          v == 'digest' and 'капитализация неизвестна' in why, (v, why))
    ev2 = ignition.judge(dict(base, mcap=3.0e7), now=now)
    check('IGN: с капитализацией и долей 47.9 б.п. - обычное событие, звонит',
          ev2 and not ev2['payload'].get('digest_only')
          and outbox.mute_reason(uid, ev2, now=now)[0] is None,
          (ev2['payload'] if ev2 else None, outbox.mute_reason(uid, ev2, now=now) if ev2 else None))
    ev3 = ignition.judge(dict(base, mcap=4.0e8), now=now)
    check('IGN: доля 3.6 б.п. ниже порога 5 - события нет вовсе (STONK-подобный случай)',
          ev3 is None, ev3)


def t_venue_gap_is_rare_and_not_a_basis():
    """РАСХОЖДЕНИЕ ПЛОЩАДОК (ТЗ 2.3): разовый лаг и структурный базис - не события.

    Замер F7: 613 событий расхождения за сутки - половина всех событий дозора; живучие пары
    (AERO, ZRO, NIL, JUP, LDO) держали 40-74 б.п. часами, US500 - 90 221 б.п. (разные
    инструменты). Живая карточка JUP 26.09: Variational дешевле Hyperliquid часами.
    """
    now = 1800000000

    def _pair(t, lo_mark, hi_mark, vol=2e7, lo_q=None):
        a = feed.Listing(ticker=t, name=t, mark=lo_mark, volume_24h=vol, venue='variational',
                         spread_bps=5.0, quote_ts=lo_q)
        b = feed.Listing(ticker=t, name=t, mark=hi_mark, volume_24h=vol, venue='hyperliquid',
                         spread_bps=5.0)
        return [a, b]
    calm = lambda t, a, b: (4.0, 60)           # обычная пара: базис 4 б.п. за сутки, 60 точек
    basis = lambda t, a, b: (45.0, 60)         # структурный базис, как у JUP
    none_ = lambda t, a, b: (None, 0)          # суточной истории пары нет
    st = {}
    evs = []
    for i in range(3):
        evs.append(detector.cross_venue(_pair('GAPX', 100.0, 102.5, lo_q=now + i * 30),
                                        now=now + i * 30, median_fn=calm, state=st))
    check('GAP: первый и второй тик расхождения - ещё не событие (лаг котировки)',
          not evs[0] and not evs[1], [len(e) for e in evs])
    check('GAP: третий тик подряд - событие', len(evs[2]) == 1, evs[2])
    p = evs[2][0]['payload'] if evs[2] else {}
    check('GAP: в событии названы чистая кромка, тики и суточная медиана пары',
          p.get('net_bps') and p.get('ticks') == 3 and p.get('median_24h_bps') == 4.0, p)
    st2 = {}
    for i in range(4):
        e = detector.cross_venue(_pair('BASX', 100.0, 102.5, lo_q=now + i * 30),
                                 now=now + i * 30, median_fn=basis, state=st2)
    check('GAP: структурный базис пары (медиана 45 б.п.) событием НЕ становится (JUP)',
          not e, e)
    st3 = {}
    for i in range(4):
        e = detector.cross_venue(_pair('NOMX', 100.0, 102.5, lo_q=now + i * 30),
                                 now=now + i * 30, median_fn=none_, state=st3)
    check('GAP: без суточной истории пары события НЕТ (нет базы - нет звонка)', not e, e)
    st4 = {}
    for i in range(4):
        e = detector.cross_venue(_pair('SMLX', 100.0, 101.0, lo_q=now + i * 30),
                                 now=now + i * 30, median_fn=calm, state=st4)
    check('GAP: 100 б.п. ниже порога 150 - не событие', not e, e)
    st5 = {}
    for i in range(4):
        e = detector.cross_venue(_pair('OLDX', 100.0, 102.5, lo_q=now - 300),
                                 now=now + i * 30, median_fn=calm, state=st5)
    check('GAP: при котировке старше минуты расхождение - это устаревшая цена, не событие',
          not e, e)
    st6 = {}
    for i in range(4):
        e = detector.cross_venue(_pair('US500', 100.0, 1000.0, lo_q=now + i * 30),
                                 now=now + i * 30, median_fn=calm, state=st6)
    check('GAP: расхождение больше 2000 б.п. - разные инструменты, и пара запомнена',
          not e and any(r.get('different') for r in st6.values()), st6)
    e = detector.cross_venue(_pair('US500', 100.0, 102.5, lo_q=now + 200), now=now + 200,
                             median_fn=calm, state=st6)
    check('GAP: и в сверку она больше не входит, даже когда цены сблизились', not e, e)
    st7 = {}
    for i in range(3):
        e_small = detector.cross_venue(_pair('CFA', 100.0, 102.2, lo_q=now + i * 30),
                                       now=now + i * 30, median_fn=calm, state=st7)
    st8 = {}
    for i in range(3):
        e_big = detector.cross_venue(_pair('CFB', 100.0, 106.0, lo_q=now + i * 30),
                                     now=now + i * 30, median_fn=calm, state=st8)
    check('GAP: уверенность зависит от кромки (не постоянные 80)',
          e_small and e_big and e_big[0]['severity'] > e_small[0]['severity'],
          (e_small[0]['severity'] if e_small else None, e_big[0]['severity'] if e_big else None))
    check('GAP: по умолчанию вид выключен у новых подписчиков',
          'venue_gap' not in config.DEFAULT_KINDS)
    check('GAP: расхождение есть только в «Потоке», во всех остальных пресетах его нет',
          all(('venue_gap' in p['kinds']) == (k == 'flow') for k, p in store.PRESETS.items()),
          {k: p['kinds'] for k, p in store.PRESETS.items()})


def t_verdict_is_code_and_model_is_behind_a_flag():
    """ИТОГ КОДОМ, МОДЕЛЬ ЗА ФЛАГОМ (ТЗ 2.8). Живая карточка JUP: «Вывод модели» написал про
    «80% bullish настроя в X» - такого числа в данных нет, и текст был обрезан на полуслове."""
    from sentinel import enrichment as en
    _env = os.environ.pop('SENTINEL_LLM_SUMMARY', None)
    try:
        check('VERD: модель по умолчанию ВЫКЛЮЧЕНА', config.llm_summary_on() is False)
        os.environ['SENTINEL_LLM_SUMMARY'] = '1'
        check('VERD: и включается флагом (обратный путь проверен)', config.llm_summary_on())
    finally:
        os.environ.pop('SENTINEL_LLM_SUMMARY', None)
        if _env is not None:
            os.environ['SENTINEL_LLM_SUMMARY'] = _env
    base_hl = {'venue': 'hyperliquid', 'funding_raw': 0.0000125, 'funding_interval_s': 3600}
    up = {'kind': 'move_up', 'ticker': 'JUP', 'payload': dict(base_hl, move_pct=5.0)}
    v = en.verdict_lines(up, {'sm': ('net', 150000.0, 400000.0), 'tweets': []})
    check('VERD: нетто в сторону движения - «подтверждают»', 'подтверждают' in v[0], v)
    v = en.verdict_lines(up, {'sm': ('net', -412000.0, 548000.0), 'tweets': []})
    check('VERD: нетто против движения - «против», со знаком и суммой',
          'против' in v[0] and '-$412' in v[0], v)
    down = {'kind': 'move_down', 'ticker': 'JUP', 'payload': dict(base_hl, move_pct=-5.0)}
    v = en.verdict_lines(down, {'sm': ('net', -90000.0, 200000.0), 'tweets': []})
    check('VERD: у падения продажи смарт-мани ПОДТВЕРЖДАЮТ (знак считается от направления)',
          'подтверждают' in v[0], v)
    v = en.verdict_lines(up, {'sm': ('silent', 1000.0, 4000.0), 'tweets': []})
    check('VERD: мелкий след - «молчат», и размер назван', 'молчат' in v[0] and '$4' in v[0], v)
    vol = {'kind': 'vol_surge', 'ticker': 'JUP', 'payload': dict(base_hl)}
    v = en.verdict_lines(vol, {'sm': ('net', 50000.0, 90000.0), 'tweets': []})
    check('VERD: у вида без направления нет ни «подтверждают», ни «против»',
          'подтверждают' not in v[0] and 'против' not in v[0], v)
    # С ЭТАПА 3 СОСТОЯНИЕ ФАНДИНГА ПЕЧАТАЕТ КАРТОЧКА (`cards.funding_line`), итог его не повторяет.
    check('VERD: фандинг в итоге не повторяется (он в строке карточки)',
          not any('фандинг' in x for x in v), v)
    check('VERD: базовая ставка Hyperliquid - одним словом «базовый», без сырого поля и сторон',
          cards.funding_line(base_hl) == 'Фандинг базовый', cards.funding_line(base_hl))
    hot = {'venue': 'hyperliquid', 'funding_raw': 0.0000945, 'funding_interval_s': 3600}
    _fh = cards.funding_line(hot) or ''
    check('VERD: повышенный фандинг назван числом и стороной',
          'повышен' in _fh and 'платят лонги' in _fh and '0.0000945' not in _fh, _fh)
    lg_eq = {'venue': 'lighter', 'funding_raw': 0.000032, 'funding_interval_s': 28800}
    check('VERD: у акции на Lighter своя база (3.5%), и она тоже «базовый»',
          cards.funding_line(lg_eq) == 'Фандинг базовый', cards.funding_line(lg_eq))
    tw = [{'text': '$JUP is up 60% for the month. Hated rally coming.'},
          {'text': 'Jupiter announces mainnet upgrade for JUP staking'}]
    v = en.verdict_lines(up, {'sm': None, 'tweets': tw})
    check('VERD: причина - только твит со словом новости, мнение причиной не считается',
          any('причина в X' in x and 'mainnet' in x for x in v)
          and not any('Hated rally' in x for x in v), v)
    v = en.verdict_lines(up, {'sm': None, 'tweets': tw[:1]})
    check('VERD: без новостного твита - честное «не найдена»',
          any('причина в X не найдена' in x for x in v), v)
    ign = {'kind': 'ignition', 'ticker': 'STONK', 'payload': {'usd': 156000}}
    v = en.verdict_lines(ign, {'sm': ('source', 156000.0, 5.0), 'tweets': []}, {'nansen'})
    check('VERD: у зажигания смарт-мани - это само событие, строки фандинга нет',
          len(v) == 1 and 'это и есть событие' in v[0], v)
    # ── СТОРОЖ МОДЕЛИ, ЕСЛИ ЕЁ ВКЛЮЧИЛИ ──
    data = 'JUP +5.2% за 15 мин, нетто -$412k'
    check('VERD: число, которого нет в данных, выбрасывает пересказ целиком',
          en.guard_summary('Настрой в X 80% bullish, это подтверждает рост.', data) == '')
    check('VERD: обрезанный на полуслове пересказ выбрасывается',
          en.guard_summary('Движение 5.2% не подтверждается смарт-мани, котор', data) == '')
    check('VERD: честный пересказ с числами из данных проходит',
          en.guard_summary('Рост на 5.2% идёт против продаж смарт-мани.', data) != '')
    card = cards.enrich_card(up, {'lines': ['x'], 'verdict': ['смарт-мани молчат'],
                                  'cost_line': 'Сводка: 10 кр Nansen'})
    check('VERD: в карточке блок «Итог»', '<b>Итог</b>' in card and 'молчат' in card, card)
    check('VERD: строки расхода кредитов у подписчика НЕТ', 'кр Nansen' not in card, card)
    check('VERD: и у владельца её тоже нет (этап 3: расход - на экране дозорного)',
          'кр Nansen' not in cards.enrich_card(up, {'lines': ['x'],
                                                    'cost_line': 'Сводка: 10 кр Nansen'},
                                               owner=True))


def t_x_and_polymarket_lines_are_for_the_reader():
    """X И POLYMARKET В КАРТОЧКЕ - ТОЛЬКО ТО, ЧТО ЧЕЛОВЕК ПРОЧТЁТ И ЧЕМ ВОСПОЛЬЗУЕТСЯ (ТЗ 2.7)."""
    from sentinel import enrichment as en
    check('X: твит на китайском не проходит (живой случай JUP, «暴富三剑客»)',
          en._lang_ok('$AXS $JUP $INJ 暴富三剑客，这三个币，你买一个，这一轮牛市 你就会暴富！') is False)
    check('X: английский проходит', en._lang_ok('$JUP is up more than 60% for the month.'))
    check('X: русский проходит', en._lang_ok('JUP растёт третий день, объём вырос вдвое'))
    check('X: одни тикеры и ссылка - не повод выкинуть твит',
          en._lang_ok('$JUP $SOL https://t.co/abc'))
    check('X: не больше двух твитов', en.X_LIMIT == 2, en.X_LIMIT)
    for m in ('entry:', 'sl:', 'tp:', 'targets:', 'new listing around the corner',
              'community vote', 'vip access', 'launchpad', 'join our official'):
        check('X: спам-метка %r' % m, en._is_spam('Great setup! %s 0.5' % m.upper()))
    t_eq = {'text': 'Dell announced new laptops today'}
    check('X: у акции имя компании релевантностью НЕ считается',
          en._relevant(t_eq, 'DELL', 'Dell Technologies', None, klass='equity') is False)
    check('X: у акции засчитывается кэштег',
          en._relevant({'text': '$DELL beats estimates'}, 'DELL', 'Dell', None, klass='equity'))
    # ── POLYMARKET: отказ поиска - в лог, а не человеку ──
    from sentinel import ignition, predict
    _rp, _rc, _rx = predict.lines, ignition.confirm, en._x_lines

    async def _no_market(*a, **k):
        return [], 'у инструмента нет полного имени, а по тикеру искать нельзя', 0

    async def _no_onchain(*a, **k):
        return {'refused': None, 'address': None}

    async def _no_x(*a, **k):
        return [], None
    predict.lines, ignition.confirm, en._x_lines = _no_market, _no_onchain, _no_x
    try:
        ev = {'kind': 'venue_gap', 'ticker': 'JUPX', 'key': 'pmx',
              'payload': {'venue': 'hyperliquid', 'mark': 0.35, 'name': 'JUPX'}}
        b = asyncio.run(en.build(ev))
    finally:
        predict.lines, ignition.confirm, en._x_lines = _rp, _rc, _rx
    check('PM: «предсказательный рынок не найден» человеку НЕ показывается',
          'предсказательный' not in (b.get('refused') or '')
          and 'Polymarket' not in '\n'.join(b.get('lines') or []), b)


def t_live_defects_after_1b():
    """ЧЕТЫРЕ ДЕФЕКТА, ПОЙМАННЫХ ПЕРВЫМИ ЖИВЫМИ СОБЫТИЯМИ ПОСЛЕ 1b (26.09).

    Живые события были хорошими - зажигание STONK (5 адресов, $156k, 6.7 б.п.), смарт-перп NEAR
    (лонг трёх китов на $689k) - и НИ ОДНО не дошло до владельца.
    """
    from sentinel import clusters, ignition
    import nansen_api as N
    now = int(time.time())
    uid = UID + 11
    store.settings_set(uid, alerts_on=1, venues='hyperliquid', min_sev=0, burst_max=50,
                       daily_cap=200)
    # ── 1. ФИЛЬТР ПЛОЩАДКИ НЕ РЕЖЕТ ЗАЖИГАНИЕ И СМАРТ-ПЕРП ────────────────────────────────
    # У зажигания поля `venue` нет вовсе, и фильтр подставлял 'variational'. У владельца
    # Variational выключена - событие резалось «площадка выключена».
    ign = {'kind': 'ignition', 'ticker': 'STONK', 'severity': 90,
           'payload': {'symbol': 'STONK', 'chain': 'solana', 'penalties': []}}
    v, why = outbox.mute_reason(uid, ign, now=now)
    check('LIVE1: зажигание доходит до того, у кого включена только Hyperliquid',
          v != 'drop' or 'площадка' not in why, (v, why))
    rows = [{'transaction_hash': '0xnp%d' % i, 'token_symbol': 'NEARP', 'side': 'Long',
             'action': 'Add', 'trader_address': '0xw%d' % i, 'value_usd': 230000,
             'trader_address_label': 'HL Perps Whale',
             'block_timestamp': __import__('datetime').datetime.utcfromtimestamp(
                 now - 60).strftime('%Y-%m-%dT%H:%M:%SZ')} for i in range(3)]
    pevs, _ = ignition.scan_perp(now=now, fetch=lambda: rows)
    sp = [e for e in pevs if e['payload'].get('symbol') == 'NEARP']
    check('LIVE1: смарт-перп несёт свою площадку явно', sp and
          sp[0]['payload'].get('venue') == 'hyperliquid', sp[0]['payload'] if sp else None)
    v2, why2 = outbox.mute_reason(uid, sp[0], now=now) if sp else ('drop', 'нет события')
    check('LIVE1: и доходит до того, у кого включена только Hyperliquid',
          v2 != 'drop' or 'площадка' not in why2, (v2, why2))
    store.settings_set(uid, venues='variational')
    v3, why3 = outbox.mute_reason(uid, sp[0], now=now) if sp else (None, '')
    check('LIVE1: а у того, у кого Hyperliquid выключена, смарт-перп режется честно',
          v3 == 'drop' and 'hyperliquid' in why3, (v3, why3))
    # ── 2. НОВЫЙ ВИД НЕ РАВЕН ВЫКЛЮЧЕННОМУ ──────────────────────────────────────────────
    # Набор владельца сохранён до появления смарт-перпа - и вид стоял «✗», хотя он его не трогал.
    old = UID + 12
    store.settings_set(old, alerts_on=1)
    c = store.conn()
    c.execute('UPDATE sentinel_settings SET kinds=?, kinds_seen=NULL WHERE user_id=?',
              ('move_up,move_down,ignition', old))
    c.commit()
    check('LIVE2: у подписчика со старым набором новый вид ВКЛЮЧЁН',
          'sm_perp' in store.kinds_for(old), store.kinds_for(old))
    check('LIVE2: и то, что он выключал сам, осталось выключенным',
          'oi_surge' not in store.kinds_for(old), store.kinds_for(old))
    store.kind_toggle(old, 'sm_perp')
    check('LIVE2: выключил смарт-перп руками - он выключен и не возвращается сам',
          'sm_perp' not in store.kinds_for(old), store.kinds_for(old))
    check('LIVE2: пресеты включают смарт-перп (они ставят набор целиком)',
          all('sm_perp' in p['kinds'] for p in store.PRESETS.values()),
          [p['kinds'] for p in store.PRESETS.values()])
    # ── 3. АДРЕС SOLANA НЕ ПРИВОДИТСЯ К НИЖНЕМУ РЕГИСТРУ ─────────────────────────────────
    # Живой замер: `3uox8K7U…` как есть -> 10 связей, в нижнем регистре -> 422
    # invalid_address_format. base58 чувствителен к регистру; проверка связей по Solana не
    # работала никогда и давала «связи не проверены: badreq».
    sol = '3uox8K7U4NZoZCXKFYm1CpT1TX3etbHDtJNv1ggBSjpK'
    trs = [{'transaction_hash': '0xs%d' % i, 'token_bought_symbol': 'CASE',
            'token_bought_address': 'CaseMint111', 'chain': 'solana', 'trade_value_usd': 1000,
            'trader_address': (sol if i == 0 else 'Bi8CtUDGiGz2Y9ptmTnoAcrvjaJiVak868bwV8Qrbxmi'),
            'block_timestamp': __import__('datetime').datetime.utcfromtimestamp(
                now - 60).strftime('%Y-%m-%dT%H:%M:%SZ')} for i in range(2)]
    g = list(ignition.group(ignition.rows_from_feed(trs), now=now).values())[0]
    top = ignition._top_wallets(g, 6)
    check('LIVE3: адреса для проверки связей уходят в ИСХОДНОМ регистре',
          sol in top, top)
    check('LIVE3: а разные адреса считаются по нормализованному виду (EVM-checksum не двоится)',
          len(g['wallets']) == 2, g['wallets'])
    seen = []
    _real = N.profiler_related_wallets
    N.profiler_related_wallets = lambda a, ch, n=10: (seen.append(a) or [])
    try:
        asyncio.run(clusters.check(top, 'solana', spend=False))
    finally:
        N.profiler_related_wallets = _real
    check('LIVE3: в Nansen уходит адрес как есть, а не в нижнем регистре',
          sol in seen and sol.lower() not in seen, seen)
    # ── 4. ТЕХНИЧЕСКИЕ МЕТКИ ЧЕЛОВЕКУ НЕ ПОКАЗЫВАЕМ ─────────────────────────────────────
    for lb in ('Uses "LEGENDTRADE" HL Referral Code', 'wallet.poor', 'sh4dow.eth*',
               'Funded @abc On Friendtech'):   # короткая ручка: скруббер выжимки берёт 4+
        check('LIVE4: техническая метка скрыта: %s' % lb, N.meaningful_label(lb) == '')
    for lb in ('HL Perps Whale', 'Smart Trader', 'Fund', 'STONK Whale',
               'MILKSHAKE Token Deployer'):
        check('LIVE4: смысловая метка показана: %s' % lb, N.meaningful_label(lb) == lb)
    rows2 = [dict(r, trader_address_label=('Uses "ZXY" HL Referral Code' if i else
                                            'HL Perps Whale'),
                  transaction_hash='0xlb%d' % i, token_symbol='LBL')
             for i, r in enumerate(rows)]
    ev4, _ = ignition.scan_perp(now=now, fetch=lambda: rows2)
    lb4 = [e for e in ev4 if e['payload'].get('symbol') == 'LBL']
    check('LIVE4: в карточку смарт-перпа едут только смысловые метки',
          lb4 and lb4[0]['payload']['labels'] == ['HL Perps Whale'],
          lb4[0]['payload']['labels'] if lb4 else None)
    # ── 5. СОКРАЩЕНИЕ ПОЗИЦИИ - НЕ ВХОД ────────────────────────────────────────────────
    # Замер ленты: 25 из 100 перп-сделок - Reduce. Сторона у них та же («Long»), и прежний код
    # складывал их с входами: фиксацию прибыли по лонгу считал «открыл лонг».
    red = [dict(r, action='Reduce', transaction_hash='0xrd%d' % i, token_symbol='RED')
           for i, r in enumerate(rows)]
    e5, _ = ignition.scan_perp(now=now, fetch=lambda: red)
    check('LIVE5: три сокращения лонга событием «открыли лонг» НЕ становятся',
          not [e for e in e5 if e['payload'].get('symbol') == 'RED'], e5)


def t_sigma60_is_estimated_until_hourly_points_exist():
    """ЧАСОВАЯ СИГМА ОЦЕНИВАЕТСЯ ПО 15-МИНУТНОЙ, ПОКА ЧАСОВЫХ ТОЧЕК МАЛО (решение владельца 26.09).

    Замер: 20 часовых доходностей набираются за 21 час кольца, и без оценки часовые движения
    молчали бы весь день показа. Оценка - тот же ряд, пересчитанный на окно по названной формуле
    (sigma60 = sigma15 * sqrt(4)), поэтому это не подмена сигнала соседним. Но она обязана быть
    ВИДНА: источник едет в payload, карточка помечает число.
    """
    now = 1800000000
    hot60 = [(now - 3600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 3600)]
    # 30 точек по 15 минут: 15-минутных доходностей 29 (хватает), часовых около 6 (не хватает).
    short = series(30, now - 30 * 900)
    s15, n15 = detector.sigma_pct(short)
    s60, n60 = detector.sigma_pct(short, step=detector.W60)
    check('S60: исходные условия теста честные - 15-мин точек хватает, часовых нет',
          n15 >= config.sigma_min_points() and n60 < config.sigma_min_points(), (n15, n60))
    ev = [e for e in detector.detect(one(mark='103.0', quote_iso=_iso(now)), hot60, now=now,
                                     ring=short) if e['kind'] == 'move_up']
    check('S60: часовое движение ЕСТЬ, хотя часовых точек мало', ev, (n15, n60))
    p = ev[0]['payload'] if ev else {}
    check('S60: источник сигмы назван - оценка по 15-мин',
          p.get('sigma_source') == '15m*sqrt4' and p.get('sigma_window') == '60м', p)
    check('S60: и это ровно sigma15 * 2, формула не подменена другой',
          p.get('sigma_pct') and abs(p['sigma_pct'] - s15 * 2.0) < 1e-9,
          (p.get('sigma_pct'), s15))
    txt = cards.card(ev[0]) if ev else ''
    check('S60: карточка помечает число как оценку', 'оценка по 15-мин' in txt, txt[:260])
    check('S60: и по-английски тоже', 'estimated from 15-min' in cards.card(ev[0], lang='en')
          if ev else False)
    # 104 точки: часовых доходностей 25 - оценка больше не участвует.
    long_ = series(104, now - 104 * 900)
    _s60, _n60 = detector.sigma_pct(long_, step=detector.W60)
    ev2 = [e for e in detector.detect(one(mark='103.0', quote_iso=_iso(now)), hot60, now=now,
                                      ring=long_) if e['kind'] == 'move_up']
    p2 = ev2[0]['payload'] if ev2 else {}
    check('S60: при %d часовых точках берётся НАСТОЯЩАЯ часовая сигма' % _n60,
          ev2 and p2.get('sigma_source') == '60m' and abs(p2['sigma_pct'] - _s60) < 1e-9,
          (p2.get('sigma_source'), p2.get('sigma_pct'), _s60))
    check('S60: и пометки об оценке в карточке уже нет',
          ev2 and 'оценка по 15-мин' not in cards.card(ev2[0]))
    # БЕЗ 15-МИНУТНОЙ СИГМЫ ОЦЕНИВАТЬ НЕЧЕГО: события нет, как и было.
    tiny = series(8, now - 8 * 900)
    ev3 = [e for e in detector.detect(one(mark='103.0', quote_iso=_iso(now)), hot60, now=now,
                                      ring=tiny) if e['kind'] == 'move_up']
    check('S60: если и 15-мин точек мало, оценки нет и события нет', not ev3)


def t_fuse_counts_every_message_not_only_alerts():
    """ПРЕДОХРАНИТЕЛЬ СЧИТАЕТ ВСЁ, ЧТО ПРИШЛО НА ТЕЛЕФОН (ТЗ 2.6).

    ═══ ЗАМЕР ПРОДА 26.09 ═══
    Владельцу ушло 586 сообщений за сутки: 280 алертов, 279 обогащений, 27 сводок; в час пик 101
    алерт и 100 обогащений. Предохранитель считал ТОЛЬКО алерты, то есть видел меньше половины
    потока: «не больше 3 за 10 минут» на практике означало семь. Ограничитель, не видящий
    половину того, что ограничивает, не ограничитель.
    """
    uid = UID + 8
    now = int(time.time())
    store.settings_set(uid, alerts_on=1, burst_max=3, burst_win_min=10)
    _b = store.sent_in_window(uid, 600, now)
    store.sent_log(uid, 'alert', 'k1', 1, now=now)
    store.sent_log(uid, 'thread', 'k2', 2, now=now)
    store.sent_log(uid, 'brief', 'k3', 3, now=now)
    store.sent_log(uid, 'digest', None, 4, now=now)
    check('FUSE: в окно попали все четыре вида сообщений, а не только алерт',
          store.sent_in_window(uid, 600, now) - _b == 4,
          store.sent_in_window(uid, 600, now) - _b)
    check('FUSE: за пределами окна они не считаются (окно - это окно)',
          store.sent_in_window(uid, 60, now + 3600) == 0)
    # ПРЕДОХРАНИТЕЛЬ ВИДИТ ЭТО ЧИСЛО И ГОВОРИТ ПРИЧИНУ ВЕЛИЧИНОЙ, А НЕ ФЛАГОМ.
    ev = {'kind': 'move_up', 'ticker': 'FUSE', 'severity': 95,
          'payload': {'venue': 'variational', 'move_pct': 5.0, 'step': 2, 'penalties': []}}
    _sub(uid, 'FUSE')
    verdict, why = outbox.mute_reason(uid, ev, now=now)
    check('FUSE: четыре сообщения при границе 3 - в сводку, и причина числом',
          verdict == 'digest' and 'предохранитель' in why and '4' in why, (verdict, why))
    check('FUSE: неизвестный вид сообщения не проглатывается молча',
          'alert' in store.SENT_KINDS and 'digest' in store.SENT_KINDS, store.SENT_KINDS)


def t_digest_says_one_line_per_ticker():
    """СВОДКА: одна строка на инструмент, и это МАКСИМАЛЬНАЯ величина (ТЗ 2.2).

    Без дедупликации сводка повторяла ровно тот дефект, от которого уходят алерты:
    развивающееся движение по одному инструменту давало десяток строк про один и тот же SAGA, и
    «сводка» становилась тем же потоком, собранным в одно сообщение.
    """
    uid = UID + 9
    now = int(time.time())
    store.settings_set(uid, alerts_on=1, enrich_on=0, quiet_from=None, quiet_to=None)
    for i, mv in enumerate((3.0, 7.5, 4.2)):
        k = 'dg-%d-%d' % (now, i)
        store.event_new({'key': k, 'ts': now, 'kind': 'move_up', 'ticker': 'DGT',
                         'severity': 60 + i,
                         'payload': {'mark': 10.0, 'move_pct': mv, 'venue': 'variational',
                                     'step': 1, 'penalties': []}})
        store.digest_add(uid, k, 60 + i, 'слабое')
    k2 = 'dg-other-%d' % now
    store.event_new({'key': k2, 'ts': now, 'kind': 'move_up', 'ticker': 'OTH',
                     'severity': 65, 'payload': {'mark': 5.0, 'move_pct': 2.0,
                                                 'venue': 'variational', 'step': 1,
                                                 'penalties': []}})
    store.digest_add(uid, k2, 65, 'слабое')
    bot = FakeBot()
    attach(bot)
    people, rows = asyncio.run(outbox.deliver_digest(now=now + 10 * 60))
    # СЧИТАЕМ СВОИ СООБЩЕНИЯ: в общем прогоне сводки накопились и у других тестовых людей, и
    # «получателей ровно один» краснело бы от порядка запуска, а не от дефекта.
    mine = [t for (c, t) in bot.sent if c == uid]
    check('DIGEST: этому человеку ушло РОВНО одно сообщение',
          len(mine) == 1 and people >= 1, (people, rows, len(mine)))
    body = mine[0] if mine else ''
    check('DIGEST: по инструменту ОДНА строка, а не три', body.count('DGT') == 1, body)
    check('DIGEST: и в ней максимальная величина (7.5%, а не 3.0%)',
          '7.5' in body and '3.0' not in body, body)
    check('DIGEST: другой инструмент остался отдельной строкой', 'OTH' in body, body)
    check('DIGEST: свёрнутые события отмечены отправленными и не приедут снова',
          not store.digest_pending(uid), store.digest_pending(uid))


def t_one_move_is_one_thread_not_twelve_alerts():
    """НИТЬ: 12 событий по одному инструменту за 70 минут дают ОДНУ карточку и пару ответов.

    ═══ ЖИВОЙ ЗАМЕР 26.09: SAGA, 12 АЛЕРТОВ ЗА 70 МИНУТ ═══
    Причина была не в пороге, а в КЛЮЧЕ события: в него входит ступень силы (|ход| // порог). При
    часовом пороге 2.5% ход +15% давал ступень 6, +18% - 7, +21% - 8; откат давал новую ступень,
    «вверх» и «вниз» были разными видами, а пауза по инструменту тоже включала ступень - то есть
    каждая новая ступень законно открывала себе окно заново. Механизм работал как написан, и
    «покрутить порог» не изменило бы ничего.
    ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ: первая карточка одна; дальше человек слышит только РОСТ ЧИСЛА, и
    слышит его ОТВЕТОМ на первую карточку; события, которые не превысили взятую ступень, ложатся
    в базу без доставки. Сценарий ТЗ воспроизведён числами того же порядка, что были на проде.
    """
    now = int(time.time())
    uid = UID + 7
    store.settings_set(uid, alerts_on=1, enrich_on=0, daily_cap=200, min_pct=None,
                       burst_max=50, burst_win_min=10, min_sev=0)
    _sub(uid, 'SAGA')
    bot = FakeBot()
    attach(bot)
    # ХОД РАСТЁТ И ОТКАТЫВАЕТ, КАК НА ЖИВОМ РЫНКЕ: 12 событий, ступени 6,6,7,7,8,8,...
    moves = [15.0, 15.4, 18.2, 18.6, 21.1, 21.5, 23.0, 22.8, 21.0, 16.0, 15.5, 15.2]
    for i, mv in enumerate(moves):
        step = int(abs(mv) // 2.5)
        k = 'saga-%d-%d' % (now, i)
        store.event_new({'key': k, 'ts': now + i * 300, 'kind': 'move_up', 'ticker': 'SAGA',
                         'severity': 90,
                         'payload': {'mark': 0.04 + i * 0.001, 'move_pct': mv, 'step': step,
                                     'window': '60м', 'threshold_pct': 2.5,
                                     'venue': 'variational', 'penalties': []}})
        store.delivery_plan(k, uid)
        asyncio.run(outbox.deliver_due())
    mine = [t for (c, t) in bot.sent if c == uid]
    firsts = [t for t in mine if 'Дозорный' in t or 'необычность' in t or 'Оборот' in t
              or 'оборот' in t]
    replies = [t for t in mine if 'усилилось' in t or 'откат' in t]
    check('THREAD: человеку ушла ОДНА полная карточка, а не двенадцать',
          len(mine) - len(replies) == 1, [t[:60] for t in mine])
    check('THREAD: продолжений не больше двух (ТЗ: не больше 2 ответов)',
          len(replies) <= 2, [t[:80] for t in replies])
    check('THREAD: продолжение говорит НОВЫМ числом, а не повторяет старое',
          not replies or any('%' in t for t in replies), replies)
    check('THREAD: и приходит ОТВЕТОМ на первую карточку (нить в интерфейсе)',
          all(len(bot.sent) >= 1 for _ in replies))
    _t = store.thread_get('variational', 'SAGA', uid)
    check('THREAD: нить помнит максимальную ступень и пик', _t and _t['max_step'] >= 6
          and _t['peak_pct'] is not None, _t)
    # ОТКАТ ПОСЛЕ ПИКА - ОТДЕЛЬНАЯ НОВОСТЬ, И ОНА СЧИТАЕТСЯ ОТ ПИКА, А НЕ ОТ НУЛЯ.
    d = outbox._thread_decide(uid, {'kind': 'move_up', 'ticker': 'SAGA',
                                    'payload': {'venue': 'variational', 'step': 9,
                                                'move_pct': 12.0, 'threshold_pct': 2.5,
                                                'window': '60м'}},
                              now=now + 100000)
    check('THREAD: нить старше шести часов начинается заново, а не тянется вечно',
          d['act'] == 'first', d)


def t_feed_is_stored_because_window_is_longer_than_page():
    """ЛЕНТА СМАРТ-МАНИ ХРАНИТСЯ У НАС: окно события длиннее того, что отдаёт один ответ.

    ═══ ЗАМЕР ВЛАДЕЛЬЦА 26.09, КОТОРЫЙ ЭТО ЗАВЁЛ ═══
    Один вызов `smart-money/dex-trades` (100 сделок) покрывает 44 МИНУТЫ, а окно зажигания - 180.
    Пока агрегат собирался по последнему ответу, порог «три разных адреса в одном токене за три
    часа» проверялся по данным за три четверти часа и был НЕДОСТИЖИМ ПРИ ЛЮБОМ ЧИСЛЕ: истории
    между опросами не существовало, а курсор помнил лишь «эту сделку я уже видел».
    Из 35 токенов той ленты два адреса собрали пять токенов, три адреса - ни один; единственным
    токеном с шестью адресами оказался SOL на $6412, то есть мейджор с нулевой долей рынка.
    """
    from sentinel import assets, ignition
    now = int(time.time())

    def _tr(h, sym, addr, who, usd, ts, chain='ethereum', mcap=None):
        return {'transaction_hash': h, 'token_bought_symbol': sym, 'token_bought_address': addr,
                'trader_address': who, 'trade_value_usd': usd, 'chain': chain,
                'block_timestamp': __import__('datetime').datetime.utcfromtimestamp(ts).strftime(
                    '%Y-%m-%dT%H:%M:%SZ'),
                'token_bought_market_cap': mcap, 'trader_address_label': 'Smart Trader'}

    # ДВА АДРЕСА ПРИШЛИ ДАВНО (в прошлой «странице»), ТРЕТИЙ - СЕЙЧАС. Раньше первые два к этому
    # моменту уже уехали из ответа провайдера, и порог не собирался никогда.
    old = [_tr('0xa1', 'MOON', '0xmoon', '0xw1', 60000, now - 9000, mcap=5e7),
           _tr('0xa2', 'MOON', '0xmoon', '0xw2', 60000, now - 8400, mcap=5e7)]
    store.sm_trades_put(ignition.rows_from_feed(old), feed='dex', now=now - 8000)
    # СЧИТАЕМ СВОИ СТРОКИ, А НЕ ВСЮ ТАБЛИЦУ: в общем прогоне до нас в неё пишут другие тесты, и
    # проверка «в таблице ровно две записи» краснела бы от порядка запуска, а не от дефекта.
    _mine = [r for r in store.sm_trades_window(now - 4 * 3600, feed='dex')
             if r.get('token_address') == '0xmoon']
    check('FEED: сделки прошлых опросов лежат в базе', len(_mine) == 2, _mine)
    fresh = [_tr('0xa3', 'MOON', '0xmoon', '0xw3', 60000, now - 120, mcap=5e7)]
    evs, note = ignition.scan(now=now, fetch=lambda: fresh)
    kinds = {e['kind'] for e in evs}
    check('FEED: третий адрес СОБИРАЕТ порог вместе с двумя из базы',
          'ignition' in kinds, (kinds, note))
    _ev = [e for e in evs if e['kind'] == 'ignition'][0]
    check('FEED: в событии три РАЗНЫХ адреса, а не три сделки одного',
          _ev['payload']['wallets'] == 3, _ev['payload']['wallets'])
    # ОКНО СТРОГОЕ: сделка старше окна в агрегат не входит, иначе «за три часа» станет «когда-то».
    g = ignition.group(_mine, now=now + 4 * 3600)
    check('FEED: за пределами окна агрегат пуст (окно не растягивается молча)', not g, g)
    # ЛЕНТА КОРОЧЕ ОКНА - ГОВОРИМ ОБ ЭТОМ СЛОВАМИ. Иначе «событий 0» читается как «рынок тихий»,
    # и через сутки тишины человек идёт искать поломку в пороге (ровно это и было).
    # СВЕРЯЕМ С ФАКТОМ, А НЕ С ОЖИДАНИЕМ: накопленный размах зависит от того, что записали тесты
    # до нас, поэтому проверяется соответствие строки замеру, а не сам замер.
    _span_s, _ = store.sm_trades_span('dex')
    _short = _span_s < int(config.ign_window_min()) * 60
    check('FEED: строка итога честно говорит, хватает ли накопленного на окно',
          ('окно ещё неполное' in note) == _short, (note, _span_s))
    # ── ОТСЕВ МЕЙДЖОРОВ (замер: единственный кандидат ленты был SOL) ──────────────────────
    sol = [_tr('0xb%d' % i, 'SOL', '0xsol', '0xs%d' % i, 200000, now - 300, chain='solana',
               mcap=1.48e9) for i in range(4)]
    store.sm_trades_put(ignition.rows_from_feed(sol), feed='dex', now=now)
    evs2, _n2 = ignition.scan(now=now, fetch=lambda: sol)
    check('FEED: покупка SOL четырьмя умными адресами событием НЕ считается',
          not [e for e in evs2 if e['payload'].get('symbol') == 'SOL'], evs2)
    check('FEED: и причина отсева называется словами, а не булевым флагом',
          'мейджор' in (assets.major_reason('SOL', 1.48e9) or ''),
          assets.major_reason('SOL', 1.48e9))
    check('FEED: гигант по капитализации тоже мимо, даже если имени в реестре нет',
          assets.major_reason('NEWCOIN', 2.5e9) is not None,
          assets.major_reason('NEWCOIN', 2.5e9))
    check('FEED: нативная монета сети названа причиной, а не «ончейн недоступен»',
          'нативная монета' in (assets.major_reason('NEAR') or ''),
          assets.major_reason('NEAR'))
    # ── МЕТКА НОВОГО ТОКЕНА: в ключах срезана, человеку показана ──────────────────────────
    # В ленте прода символ приходит как «🌱 P(DOOM)». Не срежешь - один токен живёт под двумя
    # именами и порог по адресам не собирается никогда; срежешь молча - потеряешь «ноль дней».
    clean, is_new = assets.clean_symbol('🌱 P(DOOM)')
    check('FEED: метка нового токена срезана из символа', clean == 'P(DOOM)', clean)
    check('FEED: и факт новизны не потерян', is_new is True)
    newt = [_tr('0xc%d' % i, '🌱 FRESH', '0xfresh', '0xf%d' % i, 60000, now - 200,
                chain='solana', mcap=3e6) for i in range(3)]
    e3, _n3 = ignition.scan(now=now, fetch=lambda: newt)
    _fresh = [e for e in e3 if e['payload'].get('symbol') == 'FRESH']
    check('FEED: токен с меткой собрался под ОДНИМ именем', _fresh, e3)
    check('FEED: и новизна доехала до карточки', _fresh and _fresh[0]['payload'].get('is_new'),
          _fresh[0]['payload'] if _fresh else None)
    check('FEED: карточка говорит «новый токен» словами',
          'Новый токен' in cards.card(_fresh[0]), cards.card(_fresh[0])[:200])
    # ── УБОРКА: только по сроку и только с условием (стоп-правило живой базы) ─────────────
    store.sm_trades_prune(hours=1, now=now + 7200)
    _s2, _c2 = store.sm_trades_span('dex')
    check('FEED: уборка убрала старое и оставила таблицу живой', _c2 >= 0, (_s2, _c2))


def t_smart_perp_is_a_side_not_a_purchase():
    """СМАРТ-ПЕРП (ТЗ 1.7): два разных адреса открыли ОДНУ сторону по одному инструменту.

    ЗАЧЕМ ВИД, КОТОРОГО НЕ БЫЛО. Зажигание видит покупку токена В СЕТИ, а дозорный смотрит за
    ПЕРПАМИ: смарт-адрес, открывший лонг на Hyperliquid, в DEX-ленте не появляется вовсе. То
    есть самый близкий к нашему домену сигнал умных денег не читался ни одним видом.
    СТОРОНА - ЧАСТЬ КЛЮЧА: «двое зашли в лонг» и «один купил, другой продал» это разные новости,
    и без стороны они слиплись бы в одну.
    """
    from sentinel import ignition
    now = int(time.time())

    def _pt(h, sym, side, who, usd, ts, price=None):
        return {'transaction_hash': h, 'token_symbol': sym, 'side': side,
                'trader_address': who, 'value_usd': usd, 'price_usd': price,
                'trader_address_label': 'Smart Trader',
                'block_timestamp': __import__('datetime').datetime.utcfromtimestamp(ts).strftime(
                    '%Y-%m-%dT%H:%M:%SZ')}

    rows = [_pt('0xp1', 'HYPE', 'long', '0xq1', 150000, now - 600, 41.5),
            _pt('0xp2', 'HYPE', 'long', '0xq2', 150000, now - 300, 41.8)]
    evs, note = ignition.scan_perp(now=now, fetch=lambda: rows)
    check('PERP: два адреса в одну сторону на $300k - событие',
          [e for e in evs if e['kind'] == 'sm_perp'], (evs, note))
    ev = [e for e in evs if e['kind'] == 'sm_perp'][0]
    check('PERP: сторона названа', ev['payload']['side'] == 'long', ev['payload'])
    check('PERP: и сумма сложена по обоим адресам',
          abs(ev['payload']['usd'] - 300000) < 1, ev['payload']['usd'])
    txt = cards.card(ev)
    check('PERP: карточка ведёт СТОРОНОЙ и суммой', 'лонг' in txt and '$300' in txt, txt[:220])
    check('PERP: дисклеймера «не рекомендация» в карточке нет (этап 3, он в справке)',
          'не рекомендация' not in txt, txt)
    # ПРОТИВОПОЛОЖНЫЕ СТОРОНЫ НЕ СКЛАДЫВАЮТСЯ: это не согласованность, а обычный рынок.
    mixed = [_pt('0xp3', 'FART', 'long', '0xr1', 200000, now - 300),
             _pt('0xp4', 'FART', 'short', '0xr2', 200000, now - 200)]
    e2, _ = ignition.scan_perp(now=now, fetch=lambda: mixed)
    check('PERP: лонг и шорт разных адресов событием НЕ становятся',
          not [e for e in e2 if e['payload'].get('symbol') == 'FART'], e2)
    # ОДИН АДРЕС, РЕЗАВШИЙ ВХОД НА ЧАСТИ - ЭТО ОДИН ЧЕЛОВЕК (тот же закон, что у зажигания).
    one = [_pt('0xp5', 'WIF', 'long', '0xsame', 200000, now - 300),
           _pt('0xp6', 'WIF', 'long', '0xsame', 200000, now - 200)]
    e3, _ = ignition.scan_perp(now=now, fetch=lambda: one)
    check('PERP: один адрес двумя сделками порог НЕ собирает',
          not [e for e in e3 if e['payload'].get('symbol') == 'WIF'], e3)
    check('PERP: вид включён по умолчанию', 'sm_perp' in config.DEFAULT_KINDS,
          config.DEFAULT_KINDS)
    check('PERP: вид есть в реестре видов детектора', 'sm_perp' in detector.KINDS)


def t_liquidation_clusters_and_outcomes_by_kind():
    """КЛАСТЕРЫ ЛИКВИДАЦИЙ (1.6в) И ИСХОД ПО ВИДУ (1.9) - оба считает КОД, а не модель."""
    from sentinel import enrichment as en
    # ── КОРЗИНЫ ПО 1% ЦЕНЫ: значение имеет СКОПЛЕНИЕ, а не одинокая позиция ──────────────
    rows = [{'liquidation_price': 0.0350, 'position_value_usd': 600000},
            {'liquidation_price': 0.0351, 'position_value_usd': 500000},
            {'liquidation_price': 0.0450, 'position_value_usd': 600000},
            {'liquidation_price': 0.0300, 'position_value_usd': 3000}]
    line = en._liq_line(rows, 0.0418)
    check('LIQ: названы обе стороны и расстояние в процентах',
          line and 'лонгов' in line and 'шортов' in line and '%' in line, line)
    check('LIQ: скопление сложено в один уровень ($1.1M, а не две строки)',
          line and '$1.1' in line, line)
    check('LIQ: одинокая позиция на $3k уровнем НЕ называется',
          line and '0.03' not in line.split('лонгов')[1][:14], line)
    check('LIQ: без цены не выдумываем ничего', en._liq_line(rows, 0) is None)
    # ── ИСХОД ПО ВИДУ: три класса видов - три разных ответа ──────────────────────────────
    # Прежний отчёт считал «продолжением» рост для move_up, ignition и oi_surge: move_down не
    # оценивался вовсе, а скачок интереса считался лонговым, хотя интерес растёт и на входе в
    # шорт. По этой цифре человек решает, верить ли дозору.
    down = [('k%d' % i, -2.0, 'move_down') for i in range(10)]
    txt = engine._rate_text(down, 'move_down', 7, 60)
    check('RATE: падение после move_down считается ПОПАДАНИЕМ',
          '100%' in txt, txt)
    up_wrong = [('k%d' % i, -2.0, 'move_up') for i in range(10)]
    check('RATE: падение после move_up попаданием НЕ считается',
          '0%' in engine._rate_text(up_wrong, 'move_up', 7, 60),
          engine._rate_text(up_wrong, 'move_up', 7, 60))
    oi = [('o%d' % i, (1.5 if i % 2 else 0.2), 'oi_surge') for i in range(10)]
    t_oi = engine._rate_text(oi, 'oi_surge', 7, 60)
    check('RATE: у вида без направления процент попаданий НЕ печатается',
          'направление НЕ утверждалось' in t_oi, t_oi)
    check('RATE: вместо него - медиана хода и доля ходов больше процента',
          'медиана' in t_oi and 'больше 1%' in t_oi, t_oi)
    # С ФИНАЛЬНОГО ЗАХОДА ИСХОД РАСХОЖДЕНИЯ - ИЗМЕНЕНИЕ САМОЙ КРОМКИ В ПРОЦЕНТАХ (outcome_tick):
    # -50 и ниже значит «сошлась вдвое». 7 из 10 сошлись, 3 - нет.
    gap = [('g%d' % i, (-80.0 if i < 7 else 10.0), 'venue_gap') for i in range(10)]
    _gt = engine._rate_text(gap, 'venue_gap', 7, 60)
    check('RATE: у расхождения исход - сошлась ли кромка, числом', 'сошлась вдвое и больше у 7 (70%)'
          in _gt, _gt)


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
    _sub(uid, 'BTC')
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
    # С ЭТАПА 4 «тестовый» пресет называется «Поток» (старое имя - алиас для старых кнопок).
    nm, why2 = store.preset_apply(uid, 'test')
    s = store.settings(uid)
    check('PRESET: «поток» применился и назвал себя словами (старое имя - алиас)',
          nm == 'flow' and 'Поток' in why2 and 'потолок в сутки 120' in why2, (nm, why2))
    check('PRESET: пауза опущена', s['cooldown_min'] == 10, s['cooldown_min'])
    check('PRESET: потолок поднят', store.cap_for(uid) == 120, store.cap_for(uid))
    check('PRESET: личный порог снят (ловим всё, что даёт общий)',
          s['min_pct'] is None, s['min_pct'])
    # ТЗ 4.1: «Поток» - ВСЕ виды, включая расхождение, спред и фандинг (инструмент проверки).
    check('PRESET: в «Поток» входят все виды, включая спред, фандинг и расхождение',
          {'spread_shock', 'funding_extreme', 'venue_gap'} <= store.kinds_for(uid),
          store.kinds_for(uid))
    store.preset_apply(uid, 'quiet')
    check('PRESET: «тихий» ставит порог 5% и паузу три часа (ТЗ 4.1)',
          store.settings(uid)['min_pct'] == 5.0 and store.settings(uid)['cooldown_min'] == 180
          and store.cap_for(uid) == 6, store.settings(uid))
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
    # С ЭТАПА 3 ТИКЕР - ССЫЛКА В ТЕКСТЕ, А НЕ РЯД КНОПОК (та же дверь, что у `sen:card`).
    _nt = ui.now_text('ru', 'testbot')
    check('CROSS: тикер в срезе рынка - ссылка на карточку инструмента',
          '?start=sen_variational_AAA' in _nt, _nt)
    check('CROSS: рядов кнопок-тикеров под срезом нет, возврат в дозор есть',
          data == ['sen:home'], data)
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
    # ── ПОГЛОЩЕНИЕ: интерес растёт, цена стоит. С ТЗ 2.4 - СТРОКА КАРТОЧКИ СКАЧКА ИНТЕРЕСА ──
    ring = series(60, now - 60 * 900)
    hot2 = [hot1(now - 3600)]
    ab = detector.detect(one(mark='100.2', oi_l='4000000', oi_s='900000', vol='50000000',
                             quote_iso=_iso(now)),
                         hot2, now=now, ring=ring)
    kinds = [e['kind'] for e in ab]
    # ═══ НЕ ДВЕ КАРТОЧКИ НА ОДИН СКАЧОК (ТЗ 2.4) ═══
    # Прежде этот замер давал `oi_surge` И `absorption` - два сообщения про один факт.
    check('ABSORB: скачок интереса при стоящей цене - ОДНО событие, а не два',
          kinds.count('oi_surge') == 1 and 'absorption' not in kinds, kinds)
    a0 = [e for e in ab if e['kind'] == 'oi_surge'][0]
    check('ABSORB: признак поглощения лежит в payload скачка',
          a0['payload'].get('absorption') is True, a0['payload'].get('absorption'))
    txt2 = cards.card(a0)
    check('ABSORB: карточка скачка называет поглощение строкой, с ценой за час числом',
          'Поглощение' in txt2 and 'цена за час' in txt2, txt2)
    check('ABSORB: и честно признаёт, что направления здесь нет',
          'Подтверждения направления здесь нет' in txt2, txt2)
    check('ABSORB: строка сводки тоже говорит «цена стоит»',
          'цена стоит' in cards.digest_line(a0), cards.digest_line(a0))
    _en2 = cards.card(a0, lang='en')
    check('ABSORB: EN-строка поглощения без кириллицы (закон 20)',
          'Absorption' in _en2 and 'no confirmation of direction' in _en2, _en2)
    # ЦЕНА УШЛА - ЭТО УЖЕ НЕ ПОГЛОЩЕНИЕ, А ДВИЖЕНИЕ
    moved = detector.detect(one(mark='104.0', oi_l='4000000', oi_s='900000', vol='50000000',
                                quote_iso=_iso(now)),
                            hot2, now=now, ring=ring)
    _mo = [e for e in moved if e['kind'] == 'oi_surge']
    check('ABSORB: при ушедшей цене поглощением это не называется',
          _mo and not _mo[0]['payload'].get('absorption')
          and 'Поглощение' not in cards.card(_mo[0]),
          [e['kind'] for e in moved])
    check('ABSORB: толпа по умолчанию включена, поглощения в наборе видов больше нет',
          'crowded' in config.DEFAULT_KINDS and 'absorption' not in config.DEFAULT_KINDS
          and 'absorption' not in detector.KINDS, (config.DEFAULT_KINDS, detector.KINDS))


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
    _sub(uid, 'LOCKTEST')
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
    # С ЭТАПА 3 БАЗОВАЯ СТАВКА - ОДНИМ СЛОВОМ: 10.95% годовых - устройство площадки, не сигнал.
    check('FUND: базовая ставка Variational - «Фандинг базовый»', _known == 'Фандинг базовый',
          _known)
    check('FUND: без «платят лонги» и без сырого 0.1095 / 8ч',
          'платят' not in _known and '0.1095' not in _known, _known)
    _neg = cards.funding_line({'venue': 'variational', 'funding_raw': -0.0821,
                              'funding_interval_s': 14400})
    check('FUND: отрицательная ставка читается как «платят шорты»', 'платят шорты' in _neg, _neg)
    _unknown = cards.funding_line({'venue': '__чужая__', 'funding_raw': 0.05,
                                   'funding_interval_s': 3600})
    check('FUND: без замера единицы строки нет вовсе - выдуманных процентов тоже',
          _unknown is None, _unknown)
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
    _sub(uid, 'BTC')
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
          all(_gt.in_prose_of(src, _w, allow_negated=True)
              for _w in ('date_range', 'YYYY-MM-DD', 'list of chain names')))
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
    _sub(uid, store.ALL)
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
    # ── ЭКРАН НАЗЫВАЕТ РОЛЬ ОПРАШИВАЮЩЕГО (ЗАМЕР 26.09) ──────────────────────────────────
    # «Юнит опрашивает» и «бот подхватил вместо юнита» - РАЗНЫЕ новости: вторая означает, что
    # отдельный юнит не работает, и смотреть надо его лог. До 26.09 узнать это из чата было
    # нечем: владелец аренды был безымянным «хост:pid».
    _lease('poller@unit:7', now + 300)
    check('FIX: роль опрашивающего названа словами - отдельный юнит',
          'Опрашивает' in ui.fix_polling(uid, now=now)
          and 'отдельный юнит' in ui.fix_polling(uid, now=now),
          ui.fix_polling(uid, now=now))
    _lease('deliver@bot:9', now + 300)
    check('FIX: подхват ботом назван прямо, а не спрятан',
          'подхватил вместо юнита' in ui.fix_polling(uid, now=now),
          ui.fix_polling(uid, now=now))
    # ЭКРАН ДВУЯЗЫЧЕН (закон 20): по экранам ходит обходчик и требует отсутствия кириллицы на en.
    _en = ui.fix_polling(uid, now=now, lang='en')
    check('FIX: на английском экране нет кириллицы',
          not __import__('re').search(r'[А-Яа-яЁё]', _en), _en)
    check('FIX: и на английском он тоже ведёт замерами и ролью',
          'Snapshots in 5 min' in _en and 'Polling by' in _en, _en)
    # ДЛИННЫХ ТИРЕ В ТЕКСТАХ БОТА НЕТ (закон 9) - проверяем оба языка.
    check('FIX: длинных тире в экране нет ни на одном языке',
          '—' not in ui.fix_polling(uid, now=now) and '—' not in _en)
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
    _sub(uid, 'BTC')
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
    _sub(uid, store.ALL)
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
    _bm = store.burst_for(uid)[0]
    check('BURST: ушло не больше границы пресета (%d), а не десять' % _bm, got <= _bm, got)
    check('BURST: и при этом ушло хоть что-то - молчать предохранитель не должен', got > 0, got)
    pend = store.digest_pending(uid)
    check('BURST: остальное НЕ ПОТЕРЯНО, а лежит в сводке',
          len(pend) >= 10 - _bm - 1, len(pend))
    check('BURST: у каждой отложенной строки есть ПРИЧИНА отсрочки',
          all(r[2] for r in pend), pend[:3])
    check('BURST: причина называется величиной, а не словом «лимит»',
          any('предохранитель' in (r[2] or '') for r in pend), [r[2] for r in pend[:3]])
    # ГРАНИЦА ПОВЕРХ ЛЮБЫХ НАСТРОЕК: человек выкрутил всё, что мог, и всё равно не залит.
    check('BURST: пресет «поток» предохранитель НЕ СНЯЛ (5 из 10 по ТЗ, не 10)',
          got <= _bm < 10,
          'иначе ошибка в пресете снова заливала бы человека до невозможности нажать кнопку')


def t_weak_events_do_not_ring():
    """СЛАБОЕ СОБЫТИЕ НЕ ЗВОНИТ, А ИДЁТ В СВОДКУ. Уверенность — величина, а не украшение."""
    now = int(time.time())
    uid = 777003
    _sub(uid, 'BTC')
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
    _sub(uid, store.ALL)
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
    # СЧИТАЕМ ИМЕННО ЭТОГО ЧЕЛОВЕКА: с этапа 4 период сводки личный, и у соседей по прогону
    # (пресет «Тихий» - 60 мин) их сводка законно уезжает именно на этом шаге.
    _mine0 = len([c for c, _t in bot.sent if c == uid])
    asyncio.run(outbox.deliver_digest(now=now + 99999))
    check('DIG: повторно та же сводка не уедет',
          len([c for c, _t in bot.sent if c == uid]) == _mine0)
    kb = cards.digest_kb([{'ev': store.event(k), 'why': ''} for k, _s in keys])
    flat = [b for row in (kb.inline_keyboard if kb else []) for b in row]
    # С ЭТАПА 3 РЯДА КНОПОК-ТИКЕРОВ НЕТ: тикер в строке сводки - сам ссылка на карточку.
    check('DIG: под сводкой ОДНА кнопка «Дозорный», тикеров-кнопок нет',
          [b.callback_data for b in flat] == ['sen:home'], [b.callback_data for b in flat])
    _dl = cards.digest_line(store.event(keys[0][0]), bot_un='testbot')
    check('DIG: тикер в строке сводки - ссылка на карточку инструмента',
          '?start=sen_variational_DG' in _dl, _dl)
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
    _sub(uid, 'ETH')
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
    _sub(uid, 'BTC')
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
    check('LAB: и живой замер записан рядом с кодом',
          all(_gt.in_prose_of(src, _w, allow_negated=True) for _w in ('date_range', '422')))
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


def t_vol_and_oi_thresholds_are_measured_2_4():
    """ТЗ 2.4: ОБОРОТ МЕРИТСЯ СВОИМ ОБЫЧНЫМ ЧАСОМ, ИНТЕРЕС - ОБОРОТОМ, ОБРАТНАЯ НОГА НЕ ЗВОНИТ.

    Каждый порог проверяется ПО ОТДЕЛЬНОСТИ: сценарий, где два других порога пройдены, а
    проверяемый - нет. Иначе тест был бы зелёным у кода, где сработал соседний порог.
    """
    import os as _os
    now = 1800000000

    def _ring(hours, vols=None, ois=None):
        """Кольцо на `hours` часов по 15 минут; оборот и интерес - функции номера точки."""
        n = hours * 4
        base = series(n, now - n * 900)
        return [(r[0], r[1], (vols(i) if vols else r[2]), r[3], r[4], r[5], r[6], r[7],
                 (ois(i) if ois else r[8])) for i, r in enumerate(base)]

    def _vol(ring, v_now, v_then, lst_kw=None):
        hot = [(now - 3600, 100.0, v_then, 1000.0, 900.0, 0.05, 1.0, now - 3600, 1.9e6)]
        return [e for e in detector.detect(one(mark='100.0', vol=str(v_now), quote_iso=_iso(now),
                                               **(lst_kw or {})),
                                           hot, now=now, ring=ring)
                if e['kind'] == 'vol_surge']

    # ── ОБОРОТ: нет медианы (15 часов кольца) - нет события, и молчание названо в лог ──
    import io as _io
    import contextlib as _cl
    detector._SURGE_SAID.clear()
    _buf = _io.StringIO()
    with _cl.redirect_stdout(_buf):
        _no_med = _vol(series(60, now - 60 * 900), 3.0e6, 1.0e6)
    check('VOL24: без медианы часовых приростов события нет (закон 41)', not _no_med, _no_med)
    check('VOL24: и молчание названо числом часов в логе',
          'медианы часовых приростов нет' in _buf.getvalue() and 'нужно' in _buf.getvalue(),
          _buf.getvalue()[-200:])
    # ── МЕДИАНА: обычный час этого инструмента $600k -> порог 3 x = $1.8M ──
    # Оборот 24ч растёт на $600k каждый час (поквартально +150k), значит |изменение| часа $600k.
    _busy = _ring(26, vols=lambda i: 1.0e7 + 150000.0 * i)
    _below = _vol(_busy, 2.2e7 + 1.5e6, 2.2e7)
    check('VOL24: +$1.5M при обычном часе $600k НЕ событие (нужно 3 x медиана = $1.8M)',
          not _below, [e['payload'].get('vol_threshold_usd') for e in _below])
    _above = _vol(_busy, 2.2e7 + 2.0e6, 2.2e7)
    check('VOL24: +$2.0M при том же обычном часе - событие',
          len(_above) == 1, _above)
    _pa = _above[0]['payload'] if _above else {}
    check('VOL24: сработавший порог назван: медиана часа',
          'медиана' in (_pa.get('vol_threshold_src') or '')
          and abs((_pa.get('vol_median_usd') or 0) - 6.0e5) < 1.0
          and abs((_pa.get('vol_threshold_usd') or 0) - 1.8e6) < 1.0, _pa)
    _txt = cards.card(_above[0]) if _above else ''
    check('VOL24: карточка печатает порог и обычный час числом',
          'Порог' in _txt and 'обычный час' in _txt, _txt)
    # ── 5% ОБОРОТА: у крупного инструмента +$1.5M - его обычное дыхание ──
    _flat = _ring(26)                                  # оборот стоит: медиана 0
    _big_no = _vol(_flat, 4.0e7, 4.0e7 - 1.5e6)
    check('VOL24: +$1.5M при обороте $40M НЕ событие (5% = $2M)',
          not _big_no, [e['payload'] for e in _big_no])
    _big_yes = _vol(_flat, 4.0e7, 4.0e7 - 2.5e6)
    check('VOL24: +$2.5M при обороте $40M - событие, порог назван долей оборота',
          len(_big_yes) == 1 and 'оборота' in _big_yes[0]['payload']['vol_threshold_src'],
          [e['payload'].get('vol_threshold_src') for e in _big_yes])
    # ── НИЖНЯЯ ГРАНИЦА: медиана 0, 5% = копейки - решает $500k ──
    _tiny = _vol(_flat, 1.0e6 + 4.0e5, 1.0e6)
    check('VOL24: +$400k у тонкого инструмента НЕ событие (нижняя граница $500k)', not _tiny,
          _tiny)
    # ── СНЯТЫЙ КЛЮЧ ГОВОРИТ О СЕБЕ ──
    _old = _os.environ.get('SENTINEL_VOL_PCT')
    _os.environ['SENTINEL_VOL_PCT'] = '40'
    try:
        _lines = config.retired_env_lines()
    finally:
        if _old is None:
            _os.environ.pop('SENTINEL_VOL_PCT', None)
        else:
            _os.environ['SENTINEL_VOL_PCT'] = _old
    check('VOL24: SENTINEL_VOL_PCT в .env называет себя снятым, а не молча игнорируется',
          any('SENTINEL_VOL_PCT' in _l and 'больше не читается' in _l for _l in _lines), _lines)
    check('VOL24: у конфига нет мёртвой ручки vol_pct/absorb_oi_pct',
          not hasattr(config, 'vol_pct') and not hasattr(config, 'absorb_oi_pct'))

    # ── ИНТЕРЕС: max($250k, 3% оборота 24ч) ───────────────────────────────────────────────
    ring = series(60, now - 60 * 900)
    _hot = [hot1(now - 3600, oi_usd=1.0e7)]

    def _oi(oi_now, vol, ring_=ring, hot_=_hot):
        return [e for e in detector.detect(
            one(mark='100.0', oi_l=str(oi_now), oi_s='0', vol=str(vol), quote_iso=_iso(now)),
            hot_, now=now, ring=ring_) if e['kind'] == 'oi_surge']

    # +$4M (+40%) при обороте $200M: 3% = $6M
    check('OI24: +$4M (+40%) при обороте $200M НЕ событие (3% оборота = $6M)',
          not _oi(1.4e7, 2.0e8), 'порог в деньгах от оборота не применён')
    _ok = _oi(1.8e7, 2.0e8)
    check('OI24: +$8M (+80%) при том же обороте - событие, порог назван долей оборота',
          _ok and 'оборота' in _ok[0]['payload']['oi_threshold_src']
          and abs(_ok[0]['payload']['oi_threshold_usd'] - 6.0e6) < 1.0,
          [e['payload'].get('oi_threshold_src') for e in _ok])
    # процент по-прежнему обязателен: +$3M это +15% к $20M
    _hot20 = [hot1(now - 3600, oi_usd=2.0e7)]
    check('OI24: +15% к интересу НЕ событие, даже если деньги прошли (процент обязателен)',
          not _oi(2.3e7, 5.0e7, hot_=_hot20), 'процентный порог потерян')
    _txt_oi = cards.card(_ok[0]) if _ok else ''
    check('OI24: карточка печатает порог прироста', 'Порог прироста' in _txt_oi, _txt_oi)

    # ── ОБРАТНАЯ НОГА: интерес $10M -> $20M -> назад к $10.5M за три часа ─────────────────
    # Кольцо: до now-2ч интерес $10M, дальше $20M. Час назад (горячая точка) - $20M.
    # Оборот $100M: 3% = $3M, так что порог в деньгах проходят все сценарии ниже.
    _rt_ring = _ring(26, ois=lambda i: (1.0e7 if (now - 26 * 3600 + i * 900) < now - 7200
                                        else 2.0e7))
    _hot_top = [hot1(now - 3600, oi_usd=2.0e7)]
    _back = _oi(1.05e7, 1.0e8, ring_=_rt_ring, hot_=_hot_top)
    check('ROUND: возврат интереса к старту прошлого скачка - событие с round_trip=1',
          _back and _back[0]['payload']['round_trip'] == 1
          and abs(_back[0]['payload']['round_trip_from_oi'] - 1.0e7) < 1.0,
          [e['payload'].get('round_trip') for e in _back])
    # возврат лишь на треть - это не обратная нога (допуск 20% ОТ СКАЧКА, а не от уровня)
    _part = _oi(1.5e7, 1.0e8, ring_=_rt_ring, hot_=_hot_top)
    check('ROUND: возврат на половину скачка - НЕ обратная нога',
          _part and _part[0]['payload']['round_trip'] == 0,
          [e['payload'].get('round_trip') for e in _part])
    # первая нога: до неё интерес стоял на СТАРОМ уровне - не обратная
    _first_ring = _ring(26, ois=lambda i: 1.0e7)
    _first = _oi(2.0e7, 1.0e8, ring_=_first_ring, hot_=[hot1(now - 3600, oi_usd=1.0e7)])
    check('ROUND: первая нога скачка обратной не считается',
          _first and _first[0]['payload']['round_trip'] == 0,
          [e['payload'].get('round_trip') for e in _first])
    # за пределами окна (старт был 5 часов назад) - уже не обратная нога
    _old_ring = _ring(26, ois=lambda i: (1.0e7 if (now - 26 * 3600 + i * 900) < now - 5 * 3600
                                         else 2.0e7))
    _late = _oi(1.05e7, 1.0e8, ring_=_old_ring, hot_=_hot_top)
    check('ROUND: старт прошлого скачка старше 3 часов - обычное событие',
          _late and _late[0]['payload']['round_trip'] == 0,
          [e['payload'].get('round_trip') for e in _late])
    # НЕ ЗВОНИТ И НЕ ИДЁТ В СВОДКУ: mute_reason режет по полю, с причиной словами
    uid = 7702401
    store.settings_set(uid, alerts_on=1, kinds='oi_surge', venues='variational')
    if _back:
        _v, _why = outbox.mute_reason(uid, _back[0])
        check('ROUND: обратная нога не звонит и не идёт в сводку - drop с причиной',
              _v == 'drop' and 'обратная нога' in _why, (_v, _why))
    if _part:
        _v2, _w2 = outbox.mute_reason(uid, _part[0])
        check('ROUND: а неполный возврат доставляется как обычно',
              _v2 != 'drop', (_v2, _w2))
    # ОТЧЁТ ПОПАДАНИЙ ЕЁ НЕ СЧИТАЕТ: никому не звонила - доверие к дозору не мерит
    _k1, _k2 = 'rt-test-%d-a' % now, 'rt-test-%d-b' % now
    store.event_new({'key': _k1, 'ts': now, 'kind': 'oi_surge', 'ticker': 'RTT',
                     'severity': 90, 'payload': {'round_trip': 1}})
    store.event_new({'key': _k2, 'ts': now, 'kind': 'oi_surge', 'ticker': 'RTT',
                     'severity': 90, 'payload': {'round_trip': 0}})
    store.outcome_put(_k1, 60, 100.0, 103.0)
    store.outcome_put(_k2, 60, 100.0, 101.0)
    _keys = {r[0] for r in store.outcomes(kind='oi_surge', horizon_min=60, since_ts=now - 1)}
    check('ROUND: отчёт попаданий не считает обратную ногу, обычный скачок считает',
          _k1 not in _keys and _k2 in _keys, _keys)

    # ── СНЯТЫЙ ВИД: «поглощение» вычитается из сохранённого набора и не стоит в меню ──
    store.settings_set(uid, kinds='oi_surge,absorption')
    check('KIND24: сохранённое «absorption» не читается как включённый вид',
          'absorption' not in store.kinds_for(uid), store.kinds_for(uid))
    # ОБА ВИДА ЭКРАНА (основной и «Ещё»): виды событий могут лежать в любом из них.
    _cbs = []
    for _adv in (False, True):
        if _adv:
            ui._ADV[uid] = True
        else:
            ui._ADV.pop(uid, None)
        _cbs += [b.callback_data for r in ui.menu_kb(uid, 'ru').inline_keyboard for b in r]
    ui._ADV.pop(uid, None)
    check('KIND24: тумблера «Поглощение» в настройках больше нет, смарт-перп на месте',
          'sen:k:absorb' not in _cbs and 'sen:k:smperp' in _cbs, _cbs)


def t_asset_class_on_live_names_and_nyse_session_2_5():
    """ТЗ 2.5: КЛАСС АКТИВА ПО ЖИВЫМ ИМЕНАМ VARIATIONAL, АКЦИЯ ВНЕ СЕССИИ NYSE - ТОЛЬКО СВОДКА.

    Имена взяты из ОДНОГО живого ответа `/metadata/stats` 26.09 (553 листинга, фикстура
    `tests/fixtures/variational_names_20260926.json`), а не придуманы: правило, проверенное на
    выдуманных именах, проверяет фантазию автора теста.
    """
    import json as _json
    import types as _types
    import sys as _sys
    from sentinel import assets as _as
    _fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures',
                       'variational_names_20260926.json')
    live = {t: n for t, n in _json.load(open(_fx, encoding='utf-8'))['listings']}
    check('CLS: фикстура - весь живой ответ, а не выборка', len(live) == 553, len(live))

    def _k(t, n=None):
        return feed.asset_class(_types.SimpleNamespace(ticker=t, name=live[t] if n is None else n))

    # ── 40 ЖИВЫХ ИМЁН С ПРОВЕРЕННЫМ РУКАМИ КЛАССОМ. Первые шесть акций до 2.5 были 'unknown'. ──
    expect = {
        'CRWV': 'equity', 'ARM': 'equity', 'NBIS': 'equity', 'NVO': 'equity', 'NOK': 'equity',
        'CRCL': 'equity', 'BNC': 'equity', 'QNTX': 'equity', 'SHAZ': 'equity', 'ALAB': 'equity',
        'MRNA': 'equity', 'NVDA': 'equity', 'DELL': 'equity', 'CSCO': 'equity', 'RIVN': 'equity',
        'UBER': 'equity', 'BABA': 'equity', 'JPM': 'equity', 'TSM': 'equity',
        'QQQ': 'fund', 'US500': 'fund', 'IWM': 'fund', 'UVXY': 'fund', 'KSTR': 'fund',
        'XAU': 'metal', 'XAG': 'metal', 'XAUS': 'metal', 'XAGS': 'metal', 'COPPER': 'metal',
        'XPT': 'metal', 'XPD': 'metal',
        'CL': 'commodity', 'BZ': 'commodity', 'NATGAS': 'commodity', 'UKOILP': 'commodity',
        'USOILP': 'commodity',
        'US500S': 'index', 'US100S': 'index', 'TWIS': 'index',
        # ТОКЕНЫ, ПОХОЖИЕ НА ДРУГОЕ: до 2.5 первые два были «фондами» и теряли ончейн
        'TWT': 'unknown', 'GIGGLE': 'unknown', 'PAXG': 'unknown', 'XAUT': 'unknown',
        'AGLD': 'unknown', 'GAS': 'unknown', 'A': 'unknown', 'US': 'unknown', 'SPX': 'unknown',
        'CVX': 'unknown', 'ONG': 'unknown', 'BTC': 'unknown',
    }
    _missing = [t for t in expect if t not in live]
    check('CLS: все проверяемые имена - из живого ответа', not _missing, _missing)
    _bad = [(t, live.get(t), _k(t), want) for t, want in expect.items()
            if t in live and _k(t) != want]
    check('CLS: %d живых имён получают свой класс' % len(expect), not _bad, _bad)
    # ── ИНВАРИАНТ НА ВСЁМ ОТВЕТЕ: имя с признаком токена не становится акцией/сырьём ──
    import re as _re
    _crypto = _re.compile(r'(?i)\b(token|protocol|network|coin|dao|finance|fan|meme|chain)\b')
    _leak = [(t, n, _k(t)) for t, n in live.items() if _crypto.search(n) and _k(t) != 'unknown']
    check('CLS: ни один токен из 553 не записан в акции, фонды или сырьё', not _leak, _leak)
    # ── РЕЕСТР ИМЁН ЖИВОЙ: каждая пара в нём есть в ответе площадки (мёртвая строка хуже) ──
    _dead = [k for k in feed.NAMED_CLASS if live.get(k[0], '').lower() != k[1]]
    check('CLS: каждая пара реестра сырья/металлов/индексов есть в живом ответе', not _dead, _dead)
    check('CLS: то же имя с чужим тикером не угадывается', _k('GOLDX', 'Gold') == 'unknown')
    # ── ОНЧЕЙН ДЛЯ СЫРЬЯ/МЕТАЛЛА/ИНДЕКСА НЕ ЗОВЁТСЯ (у «Gold» нашёлся бы PAX Gold) ──
    _r = _as.onchain_refusal('XAU', 'metal')
    check('CLS: металл - отказ от ончейна словами', _r and 'металл' in _r, _r)
    _r_en = _as.onchain_refusal('CL', 'commodity', lang='en')
    check('CLS: EN-отказ без кириллицы', _r_en and not _re.search('[а-яё]', _r_en.lower()), _r_en)
    check('CLS: токен PAX Gold ончейн не теряет', _as.onchain_refusal('PAXG', _k('PAXG')) is None)
    from sentinel import enrichment as _en
    _tw = {'text': 'gold just broke out, silver next'}
    check('CLS: у металла твит засчитывается только кэштегом',
          not _en._relevant(_tw, 'XAU', 'Gold', None, klass='metal')
          and _en._relevant({'text': 'watching $XAU here'}, 'XAU', 'Gold', None, klass='metal'),
          'слово «gold» в тексте засчитывалось бы новостью про перп')

    # ── СЕССИЯ NYSE ─────────────────────────────────────────────────────────────────────
    FRI_OPEN, FRI_EARLY, SAT = 1790348400, 1790341200, 1790434800       # 25.09 15:00, 13:00; 26.09
    DEC_14, DEC_2030 = 1796133600, 1796157000                            # 01.12 (зимнее время)
    FRI_1959, FRI_2000 = 1790366340, 1790366400
    check('NYSE: пятница 15:00 UTC (11:00 NY) - открыта', _as.nyse_open(FRI_OPEN)[0])
    check('NYSE: пятница 13:00 UTC (09:00 NY) - закрыта', not _as.nyse_open(FRI_EARLY)[0])
    check('NYSE: 19:59 открыта, 20:00 закрыта (граница закрытия)',
          _as.nyse_open(FRI_1959)[0] and not _as.nyse_open(FRI_2000)[0])
    check('NYSE: суббота - закрыта весь день', not _as.nyse_open(SAT)[0])
    check('NYSE: зимой 14:00 UTC это 09:00 NY - закрыта, 20:30 UTC - открыта',
          not _as.nyse_open(DEC_14)[0] and _as.nyse_open(DEC_2030)[0],
          'фиксированное окно UTC звонило бы по закрытой бирже с ноября')
    # без базы часовых поясов - окно ТЗ, и источник назван
    _zi = _sys.modules.get('zoneinfo')
    _sys.modules['zoneinfo'] = _types.ModuleType('zoneinfo')         # ZoneInfo нет -> ImportError
    try:
        _ok, _src = _as.nyse_open(FRI_OPEN)
        _ok2, _ = _as.nyse_open(FRI_EARLY)
    finally:
        if _zi is None:
            _sys.modules.pop('zoneinfo', None)
        else:
            _sys.modules['zoneinfo'] = _zi
    check('NYSE: без tzdata - окно ТЗ 13:30-20:00 UTC, и источник назван',
          _ok and not _ok2 and 'UTC' in _src, (_ok, _ok2, _src))

    # ── ДЕТЕКТОР: акция вне сессии -> все её события только в сводку, с причиной ──
    def _move(tick, name, now):
        ring = series(60, now - 60 * 900)
        hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
        return [e for e in detector.detect(one(ticker=tick, name=name, mark='104.0',
                                               quote_iso=_iso(now)),
                                           hot, now=now, ring=ring)
                if e['kind'] == 'move_up']
    _sat = _move('DELL', live['DELL'], SAT)
    _open = _move('DELL', live['DELL'], FRI_OPEN)
    _btc = _move('BTC', 'Bitcoin', SAT)
    _xau = _move('XAU', 'Gold', SAT)
    check('SESSION: движение акции в субботу - только в сводку, причина словами',
          _sat and _sat[0]['payload'].get('digest_only') == 'биржа закрыта, перп на тонкой книге'
          and _sat[0]['payload'].get('session') == 'closed',
          _sat[0]['payload'].get('digest_only') if _sat else 'события нет')
    check('SESSION: то же движение в сессию звонит как обычно',
          _open and not _open[0]['payload'].get('digest_only'),
          _open[0]['payload'].get('digest_only') if _open else 'события нет')
    check('SESSION: крипта и металл в субботу сессией не режутся',
          _btc and not _btc[0]['payload'].get('digest_only')
          and _xau and not _xau[0]['payload'].get('digest_only'),
          ([e['payload'].get('digest_only') for e in _btc],
           [e['payload'].get('digest_only') for e in _xau]))
    uid = 7702502
    store.settings_set(uid, alerts_on=1, kinds='move_up,move_down', venues='variational',
                       min_sev=0)
    if _sat:
        _v, _why = outbox.mute_reason(uid, _sat[0], now=SAT)
        check('SESSION: доставка кладёт её в сводку с той же причиной',
              _v == 'digest' and 'биржа закрыта' in _why, (_v, _why))
        check('SESSION: строка сводки несёт пометку у своего тикера',
              'биржа закрыта' in cards.digest_line(_sat[0]), cards.digest_line(_sat[0]))


#: Реестр запрещённых служебных строк живёт в `cards.SERVICE_FORBIDDEN` (одна копия, закон 40).
SERVICE_FORBIDDEN = cards.SERVICE_FORBIDDEN


def _stage3_events(now):
    """Событие каждого вида, какое реально бывает, с живыми полями. -> [ev]."""
    evs = []
    for kind, mark in (('move_up', '104.0'), ('move_down', '96.0')):
        e = _ev_for(ticker='BTC', mark=mark, now=now, kind=kind)
        if e:
            evs.append(e)
    base = {'venue': 'hyperliquid', 'mark': 12.3, 'volume_24h': 4.0e7, 'oi_usd': 4.27e6,
            'oi_skew': 0.55, 'funding_raw': 0.0000125, 'funding_interval_s': 3600,
            'spread_bps': None, 'penalties': ['котировка старше минуты'], 'asset_class': 'unknown'}
    evs.append({'kind': 'oi_surge', 'ticker': 'DASH', 'severity': 90,
                'payload': dict(base, oi_change_pct=25.4, oi_change_usd=1.16e6,
                                oi_threshold_usd=1.2e6, oi_threshold_src='3% оборота 24ч',
                                absorption=True, ret60_pct=0.1)})
    evs.append({'kind': 'vol_surge', 'ticker': 'ACE', 'severity': 70,
                'payload': dict(base, venue='variational', name='Fusionist',
                                funding_raw=0.1095, funding_interval_s=28800,
                                vol_change_pct=180.0, vol_change_usd=2.0e6,
                                vol_threshold_usd=1.8e6, vol_threshold_src='3 x медиана часа',
                                vol_median_usd=6.0e5, vol_median_points=24, ret60_pct=5.73)})
    evs.append({'kind': 'venue_gap', 'ticker': 'ARB', 'severity': 72,
                'payload': {'venue': 'hyperliquid', 'gap_bps': 180.0, 'cheap_venue': 'variational',
                            'cheap_mark': 0.4, 'rich_venue': 'hyperliquid', 'rich_mark': 0.4072,
                            'cost_bps': 20.0, 'net_bps': 160.0, 'median_24h_bps': 8.0,
                            'volume_24h': 9.0e6, 'penalties': []}})
    evs.append({'kind': 'ignition', 'ticker': 'STONK', 'severity': 90,
                'payload': {'usd': 352500.0, 'wallets': 8, 'mcap': None, 'mcap_bps': None,
                            'chain': 'solana', 'address': 'StonkMint111', 'window_min': 180,
                            'digest_only': 'капитализация неизвестна, долю проверить нечем',
                            'penalties': []}})
    evs.append({'kind': 'sm_perp', 'ticker': 'NEAR', 'severity': 90,
                'payload': {'venue': 'hyperliquid', 'side': 'long', 'wallets': 3, 'usd': 689000.0,
                            'price': 2.41, 'labels': ['HL Perps Whale'], 'penalties': []}})
    return evs


def t_stage3_cards_are_links_without_service_lines():
    """ЭТАП 3: ТИКЕР ССЫЛКОЙ, СЛУЖЕБКИ НЕТ, НИТЬ ОДНА НА ИНСТРУМЕНТ, СТАРОЕ НЕ ДОЕЗЖАЕТ.

    Живые карточки и сводка владельца после деплоя #940 (скриншот 26.09): «Чего не собрали:
    предсказательный рынок», «Вывод модели», «Сводка: 0 кр Nansen · сожжено 2944», ряд
    кнопок-тикеров под сводкой, две карточки оборота ACE за две минуты, расхождения 43-95 б.п.
    при пороге 150, твит про «fusionist claim» из политфилософии в X по ACE.
    """
    from sentinel import assets as _as, enrichment as en
    now = int(time.time())
    evs = _stage3_events(now)
    # ── ЗАКОН: ни одна запрещённая подстрока в карточке, сводке, строке нити и обогащении ──
    brief = {'lines': ['<b>С плечом</b>', '• смарт-мани лонг $1.2M / шорт $0.4M'],
             'verdict': ['смарт-мани <b>молчат</b>: след за 3 ч пустой'],
             'refused': 'предсказательный рынок: рынка про Fusionist на Polymarket не нашлось',
             'summary': 'Вывод модели здесь быть не должен.',
             'cost_line': 'Сводка: 0 кр Nansen · кредитов сожжено сегодня 2944'}
    texts = []
    for e in evs:
        texts.append(('card', e['kind'], cards.card(e, bot_un='testbot')))
        texts.append(('digest', e['kind'], cards.digest_line(e, bot_un='testbot')))
        texts.append(('enrich', e['kind'], cards.enrich_card(e, brief, bot_un='testbot',
                                                             owner=True)))
    texts.append(('digest_card', '-', cards.digest_card([{'ev': e, 'why': 'x'} for e in evs],
                                                        extra=3, bot_un='testbot')))
    _bad = [(w, k, f) for w, k, t in texts for f in SERVICE_FORBIDDEN if f in t]
    check('ЗАКОН: в карточке, сводке и обогащении нет ни одной служебной строки',
          not _bad, _bad[:6])
    # ── ТИКЕР - ССЫЛКА НА КАРТОЧКУ ИНСТРУМЕНТА ВЕЗДЕ ──
    _no_link = [(w, k) for w, k, t in texts if w in ('card', 'digest')
                and '?start=sen_' not in t]
    check('LINK: тикер ссылкой в заголовке каждой карточки и в каждой строке сводки',
          not _no_link, _no_link)
    _en = cards.enrich_card(evs[0], brief, bot_un='testbot', standalone=True)
    check('LINK: и в обогащении, пришедшем отдельным сообщением',
          '?start=sen_variational_BTC' in _en, _en[:120])
    check('LINK: sen_<площадка>_<ТИКЕР> туда и обратно, двоеточие HL-тикера - дефисом',
          cards.parse_sen_start(cards.sen_start('hyperliquid', 'xyz:TSLA'))
          == ('hyperliquid', 'XYZ:TSLA')
          and cards.parse_sen_start(cards.sen_start('variational', 'OPN_OPINION'))
          == ('variational', 'OPN_OPINION'),
          cards.sen_start('hyperliquid', 'xyz:TSLA'))
    check('LINK: тикер с недопустимыми для /start знаками ссылкой не становится',
          cards.sen_start('variational', 'A B') is None
          and '<a ' not in cards.tick_link('A B', 'variational', 'testbot'))
    check('LINK: без имени бота ссылки нет (тест-бот не уводит в прод)',
          '<a ' not in cards.tick_link('BTC', 'variational', None))
    check('LINK: под сводкой одна кнопка «Дозорный»',
          [b.callback_data for r in cards.digest_kb([]).inline_keyboard for b in r]
          == ['sen:home'])
    # ── МАРКЕР КЛАССА ──
    # МАРКЕРЫ ПО ТЗ 3.2: 🪙 токен с контрактом, 🐸 мем, 📊 акция/фонд, 📈 индекс, 🛢 сырьё, 🥇 металл;
    # неизвестное - без маркера (неверный маркер хуже отсутствия).
    marks = {k: cards.tick_link('X', 'variational', None, k).split('<')[0] for k in
             ('equity', 'fund', 'index', 'commodity', 'metal', 'token', 'meme', 'unknown')}
    check('MARK: у каждого класса маркер ТЗ, у неизвестного - никакого',
          marks == {'equity': '📊', 'fund': '📊', 'index': '📈', 'commodity': '🛢', 'metal': '🥇',
                    'token': '🪙', 'meme': '🐸', 'unknown': ''}, marks)
    _ign = [t for w, k, t in texts if w == 'card' and k == 'ignition'][0]
    check('MARK: зажигание без капитализации - токен 🪙, и ссылка на паспорт в первой карточке',
          '🪙' in _ign.split('\n')[0] and 'start=tok_StonkMint111' in _ign, _ign)
    _meme = dict(evs[-2], payload=dict(evs[-2]['payload'], mcap=3.0e7))
    check('MARK: зажигание с капитализацией меньше $100M - мем 🐸',
          '🐸' in cards.card(_meme).split('\n')[0], cards.card(_meme).split('\n')[0])
    # ── УВЕРЕННОСТЬ ОДНИМ ЧИСЛОМ В ЗАГОЛОВКЕ; ПРИЧИНЫ - ТОЛЬКО КОГДА ИХ БОЛЬШЕ ОДНОЙ ──
    _oi = cards.card(evs[2], bot_un='testbot')
    check('CONF: уверенность в строке заголовка', '· 90/100' in _oi.split('\n')[0], _oi)
    check('CONF: одна причина штрафа не печатается', 'котировка старше минуты' not in _oi, _oi)
    _two = dict(evs[2], payload=dict(evs[2]['payload'], penalties=['a-причина', 'b-причина']))
    check('CONF: две и больше - печатаются одной строкой',
          'a-причина; b-причина' in cards.card(_two), cards.card(_two))
    # ── ФАНДИНГ БАЗОВЫЙ, ОИ С ЕДИНИЦЕЙ ──
    _ace = cards.card(evs[3], bot_un='testbot')
    check('FUND3: базовая ставка Variational - «Фандинг базовый»', 'Фандинг базовый' in _ace
          and 'платят лонги' not in _ace, _ace)
    check('OI3: интерес с единицей - «ОИ $4.27M»', 'ОИ $4.27M' in _oi, _oi)
    # ── ОБОГАЩЕНИЕ: нечего добавить - блока нет; модель - только при флаге ──
    check('ENR3: пустая сводка не печатается вовсе', cards.enrich_card(evs[0], {}) == '')
    _old = os.environ.get('SENTINEL_LLM_SUMMARY')
    os.environ['SENTINEL_LLM_SUMMARY'] = '1'
    try:
        _on = cards.enrich_card(evs[0], brief)
    finally:
        if _old is None:
            os.environ.pop('SENTINEL_LLM_SUMMARY', None)
        else:
            os.environ['SENTINEL_LLM_SUMMARY'] = _old
    check('ENR3: при включённом флаге пересказ модели виден (обратный путь флага)',
          'Вывод модели' in _on, _on)

    # ── X: ИМЯ-СЛОВО И ТИКЕР-СЛОВО - ТОЛЬКО КЭШТЕГОМ ──
    _tw = {'text': 'The fusionist claim is that liberty and virtue are compatible. Ace point.'}
    check('X3: «fusionist claim» из политфилософии не засчитан новостью про ACE',
          en._relevant(_tw, 'ACE', 'Fusionist', None) is False)
    check('X3: тикер больше не ищется подстрокой («ace» в «place»)',
          en._relevant({'text': 'Great place to be'}, 'ACE', 'Fusionist', None) is False)
    check('X3: кэштег $ACE засчитан', en._relevant({'text': '$ACE breaking out'}, 'ACE',
                                                    'Fusionist', None))
    check('X3: кэштег с границей - $ACEX это другой тикер',
          en._relevant({'text': '$ACEX moon'}, 'ACE', 'Fusionist', None) is False)
    check('X3: заглавный тикер-не-слово засчитан (JUP)',
          en._relevant({'text': 'JUP staking is live'}, 'JUP', 'Jupiter', None))
    check('X3: заглавный тикер-словарное-слово (GAS) без кэштега не засчитан',
          en._relevant({'text': 'GAS prices are up'}, 'GAS', 'Gas', None) is False)
    check('X3: многословное имя целой фразой засчитано',
          en._relevant({'text': 'Ethereum Name Service ships v2'}, 'ENS',
                       'Ethereum Name Service', None))

    # ── ОДНА НИТЬ НА ИНСТРУМЕНТ: ДВА ВСПЛЕСКА ОБОРОТА ACE ЗА ДВЕ МИНУТЫ ──
    uid = 7703301
    store.settings_set(uid, alerts_on=1, kinds='vol_surge,move_up,move_down', min_sev=0)
    v1 = dict(evs[3], payload=dict(evs[3]['payload'], step=1))
    d1 = outbox._thread_decide(uid, v1, now=now, bot_un='testbot')
    check('THR3: первый всплеск оборота - полная карточка', d1['act'] == 'first', d1)
    store.thread_open('variational', 'ACE', uid, 'ace1', 501, 1, None, now=now,
                      family='vol_surge')
    v2 = dict(evs[3], payload=dict(evs[3]['payload'], step=1))
    d2 = outbox._thread_decide(uid, v2, now=now + 120, bot_un='testbot')
    check('THR3: второй всплеск той же ступени через 2 мин - в базу, не человеку',
          d2['act'] == 'skip', d2)
    v3 = dict(evs[3], payload=dict(evs[3]['payload'], step=2))
    d3 = outbox._thread_decide(uid, v3, now=now + 150, bot_un='testbot')
    check('THR3: ступень выше - одна строка ОТВЕТОМ на первую карточку, тикер ссылкой',
          d3['act'] == 'reply' and d3['reply_to'] == 501 and '?start=sen_variational_ACE'
          in (d3['text'] or ''), d3)
    for i in range(2):
        store.thread_bump('variational', 'ACE', uid, 2 + i, None, now=now + 200 + i,
                          family='vol_surge')
    v4 = dict(evs[3], payload=dict(evs[3]['payload'], step=9))
    check('THR3: потолок ответов по виду - дальше только в базу',
          outbox._thread_decide(uid, v4, now=now + 300)['act'] == 'skip')
    mv = dict(_ev_for(ticker='ACE', mark='104.0', now=now), ticker='ACE')
    mv['payload'] = dict(mv['payload'], venue='variational')
    d5 = outbox._thread_decide(uid, mv, now=now + 310, bot_un='testbot')
    check('THR3: движение цены в нити оборота - своя строка ответом, а не вторая карточка',
          d5['act'] == 'reply' and d5['reply_to'] == 501, d5)

    # ── СТАРЫЕ ПРАВИЛА НЕ ДОЕЗЖАЮТ: ни алертом, ни строкой сводки ──
    check('RULES: событие без штампа версии - прежние правила',
          outbox.rules_reason({'kind': 'move_up', 'payload': {}}) != '')
    check('RULES: со штампом текущей версии - годное',
          outbox.rules_reason({'kind': 'move_up', 'payload': {'rules': config.RULES_VERSION}})
          == '')
    check('RULES: расхождение 90 б.п. с новым штампом всё равно не доезжает (порог 150)',
          'ниже порога' in outbox.rules_reason({'kind': 'venue_gap', 'payload': {
              'rules': config.RULES_VERSION, 'gap_bps': 90.0, 'median_24h_bps': 5.0}}))
    ud = 7703302
    _sub(ud, store.ALL)
    store.settings_set(ud, alerts_on=1, enrich_on=0, quiet_from=None, quiet_to=None,
                       kinds='venue_gap,move_up', venues='variational,hyperliquid')
    _old_ev = {'key': 'oldgap%d' % now, 'ts': now, 'kind': 'venue_gap', 'ticker': 'ZRO',
               'severity': 80, 'payload': {'venue': 'hyperliquid', 'gap_bps': 87.0,
                                           'rules': 2}}
    _new_ev = dict(_ev_for(ticker='DGN', mark='104.0', now=now), key='newmv%d' % now)
    store.event_new(_old_ev)
    store.event_new(_new_ev)
    check('RULES: event_new ставит штамп версии', (store.event(_new_ev['key'])['payload']
                                                   .get('rules')) == config.RULES_VERSION)
    store.digest_add(ud, _old_ev['key'], 80, 'предохранитель')
    store.digest_add(ud, _new_ev['key'], 90, 'предохранитель')
    bot = FakeBot()
    attach(bot)
    asyncio.run(outbox.deliver_digest(now=now + config.digest_sec() + 5))
    mine = [t for c, t in bot.sent if c == ud]
    check('RULES: сводка уехала, в ней свежее событие и нет расхождения по прежним правилам',
          mine and 'DGN' in mine[0] and 'ZRO' not in mine[0], mine)
    store.sub_del(ud, store.ALL)          # не оставлять подписчика соседним тестам доставки

    # ── СЕССИЯ: SKHY - по часам KRX ──
    import datetime as _dt
    TUE_03 = int(_dt.datetime(2026, 9, 29, 3, 0, tzinfo=_dt.timezone.utc).timestamp())
    TUE_15 = int(_dt.datetime(2026, 9, 29, 15, 0, tzinfo=_dt.timezone.utc).timestamp())
    check('KRX: SKHY во вторник 03:00 UTC - корейская биржа открыта',
          _as.session_note('equity', TUE_03, ticker='SKHY') is None)
    check('KRX: SKHY во вторник 15:00 UTC - закрыта, хотя NYSE открыта',
          _as.session_note('equity', TUE_15, ticker='SKHY') is not None
          and _as.session_note('equity', TUE_15, ticker='NVDA') is None)
    check('KRX: NVDA в 03:00 UTC - NYSE закрыта', _as.session_note('equity', TUE_03,
                                                                    ticker='NVDA') is not None)

    # ── КЛАСС HL/LIGHTER - ИЗ VARIATIONAL ПО ТИКЕРУ ──
    _rows = [one(ticker='TSLA', name='Tesla, Inc.'), one(ticker='XAU', name='Gold')]
    _as.book_update(_rows)
    _hl = feed.Listing(ticker='TSLA', name='TSLA', mark=250.0, volume_24h=1e8, oi_long=None,
                       oi_short=None, venue='lighter')
    _sm = feed.Listing(ticker='SAMSUNG', name='SAMSUNG', mark=1.0, volume_24h=1e8, oi_long=None,
                       oi_short=None, venue='lighter')
    check('CLS3: Lighter TSLA получает класс Variational (акция)',
          feed.asset_class(_hl) == 'equity', feed.asset_class(_hl))
    check('CLS3: тикера нет у Variational - unknown, Азию не угадываем',
          feed.asset_class(_sm) == 'unknown', feed.asset_class(_sm))
    _as._BOOK['map'], _as._BOOK['loaded_at'] = {}, 0
    check('CLS3: справочник лежит в базе - процесс без опроса (бот) видит его тоже',
          _as.book_class('XAU') == 'metal', _as.book_class('XAU'))

    # ── КАРТОЧКА ИНСТРУМЕНТА ПО ССЫЛКЕ - ИЗ БАЗЫ, КОГДА ГОРЯЧЕГО КОЛЬЦА НЕТ (бот) ──
    engine._HOT.clear()
    _x = one(ticker='LNK3', name='Link Three', mark='10.0', oi_l='700000', oi_s='300000')
    store.snapshot_put([_x], ts=now - 60)
    _c = asyncio.run(ui.card_link('LNK3', 'variational', 'ru'))
    check('CARD3: карточка по ссылке собирается из холодного кольца в базе',
          'Цена <b>10.0000</b>' in _c and 'ОИ $1.00M' in _c, _c)

    class _B:
        def __init__(self):
            self.sent = []

        async def send_message(self, **k):
            self.sent.append(k)
    _b = _B()
    ok = asyncio.run(ui.open_start(_b, 7703303, 'sen_variational_LNK3', 'ru'))
    check('CARD3: /start sen_... открывает ту же карточку, что кнопка sen:card',
          ok and _b.sent and 'LNK3' in _b.sent[0]['text']
          and _b.sent[0].get('parse_mode') == 'HTML', _b.sent)
    check('CARD3: чужой /start не наш',
          asyncio.run(ui.open_start(_b, 7703303, 'tok_0xabc', 'ru')) is False)

    # ── КОД НА ДИСКЕ НОВЕЕ ПРОЦЕССА ──
    check('STALE: свежий процесс - пусто', engine.code_stale() == [], engine.code_stale())
    _ia = engine._IMPORTED_AT
    engine._IMPORTED_AT = 0
    try:
        _st = engine.code_stale()
    finally:
        engine._IMPORTED_AT = _ia
    check('STALE: диск новее процесса - названы файлы', 'cards.py' in _st, _st)


def t_presets_stage4():
    """ЭТАП 4: ПРЕСЕТЫ НОВИЧОК / ТРЕЙДЕР / ТИХИЙ / ПОТОК С ЧИСЛАМИ ИЗ ТЗ 4.1.

    Каждое число сверяется с ТЗ, а не с кодом: тест, списанный с кода, зелен у любой опечатки.
    """
    import re
    now = int(time.time())
    P = store.PRESETS
    check('PR4: четыре пресета ТЗ', set(P) == {'newbie', 'trader', 'quiet', 'flow'}, set(P))
    nb = P['newbie']
    check('PR4: Новичок - move_up, move_down, ignition, sm_perp; 3%; 2/10; 12; 120 мин; 30 мин',
          set(nb['kinds'].split(',')) == {'move_up', 'move_down', 'ignition', 'sm_perp'}
          and nb['min_pct'] == 3.0 and nb['burst_max'] == 2 and nb['burst_win_min'] == 10
          and nb['daily_cap'] == 12 and nb['cooldown_min'] == 120 and nb['digest_min'] == 30
          and set(nb['parts'].split(',')) == {'card', 'nansen', 'news'}, nb)
    tr = P['trader']
    check('PR4: Трейдер - + oi_surge, vol_surge, crowded; 2%; 3/10; 25; 60; 10',
          set(tr['kinds'].split(',')) == set(nb['kinds'].split(',')) | {'oi_surge', 'vol_surge',
                                                                         'crowded'}
          and tr['min_pct'] == 2.0 and tr['burst_max'] == 3 and tr['daily_cap'] == 25
          and tr['cooldown_min'] == 60 and tr['digest_min'] == 10, tr)
    qu = P['quiet']
    check('PR4: Тихий - те же виды, что у Новичка; 5%; 6; 180; 60',
          set(qu['kinds'].split(',')) == set(nb['kinds'].split(',')) and qu['min_pct'] == 5.0
          and qu['daily_cap'] == 6 and qu['cooldown_min'] == 180 and qu['digest_min'] == 60, qu)
    fl = P['flow']
    check('PR4: Поток - все виды, включая расхождение, спред и фандинг; 120; 5/10',
          set(fl['kinds'].split(',')) == set(detector.KINDS) and fl['daily_cap'] == 120
          and fl['burst_max'] == 5 and fl['burst_win_min'] == 10, (fl['kinds'], detector.KINDS))
    check('PR4: расхождение выключено во всех пресетах, кроме Потока',
          all(('venue_gap' in p['kinds']) == (k == 'flow') for k, p in P.items()))
    # ── ПЕРВАЯ ПОДПИСКА - НОВИЧОК; ТОТ, КТО НАСТРОЙКИ ТРОГАЛ, ОСТАЁТСЯ СО СВОИМИ ──
    fresh, veteran = 7704401, 7704402
    ok, why = store.sub_add(fresh, 'BTC')
    check('PR4: первая подписка без настроек ставит Новичка и говорит об этом',
          ok and 'Новичок' in why and store.cap_for(fresh) == 12
          and store.digest_sec_for(fresh) == 1800
          and store.kinds_for(fresh) == {'move_up', 'move_down', 'ignition', 'sm_perp'},
          (why, store.cap_for(fresh), store.kinds_for(fresh)))
    store.settings_set(veteran, kinds='move_up,move_down,vol_surge,venue_gap', daily_cap=40)
    _before = (store.kinds_for(veteran), store.cap_for(veteran))
    ok2, why2 = store.sub_add(veteran, 'ETH')
    check('PR4: у того, кто настройки трогал (владелец), набор видов НЕ тронут',
          ok2 and 'Новичок' not in why2 and (store.kinds_for(veteran), store.cap_for(veteran))
          == _before, (why2, store.kinds_for(veteran)))
    ok3, why3 = store.sub_add(fresh, 'ETH')
    check('PR4: вторая подписка пресет не переставляет', 'Новичок' not in why3, why3)
    # ── ПРЕДПРОСМОТР: ЧТО ИЗМЕНИТСЯ, ЧИСЛАМИ, ДО ПРИМЕНЕНИЯ ──
    rows = store.preset_preview(veteran, 'trader')
    _f = {r[0]: (r[3], r[4]) for r in rows}
    check('PR4: предпросмотр называет было -> станет по меняющимся полям',
          _f.get('daily_cap') == (40, 25) and _f.get('min_pct', (None, None))[1] == 2.0
          and 'kinds' in _f, _f)
    check('PR4: предпросмотр ничего не применил', store.cap_for(veteran) == 40)
    txt = ui.preset_preview_text(veteran, 'trader', 'ru')
    check('PR4: текст предпросмотра - «было -> станет» с числами',
          'Трейдер' in txt and '40 -> <b>25</b>' in txt, txt)
    check('PR4: EN-предпросмотр без кириллицы',
          not re.search('[А-Яа-яЁё]', ui.preset_preview_text(veteran, 'trader', 'en')),
          ui.preset_preview_text(veteran, 'trader', 'en'))
    kb = ui.preset_preview_kb(veteran, 'trader', 'ru')
    check('PR4: под предпросмотром «Применить» (sen:pa:trader) и «Не менять»',
          [b.callback_data for r in kb.inline_keyboard for b in r] == ['sen:pa:trader',
                                                                       'sen:home'])
    store.preset_apply(veteran, 'trader')
    check('PR4: после применения предпросмотр того же пресета пуст',
          store.preset_preview(veteran, 'trader') == [], store.preset_preview(veteran, 'trader'))
    check('PR4: личный период сводки Трейдера - 10 мин', store.digest_sec_for(veteran) == 600)
    # ── ПОТОК: ТОЛЬКО ВЛАДЕЛЬЦУ И ТЕСТИРОВЩИКАМ ──
    _adm, _fl = os.environ.get('ADMIN_IDS'), os.environ.get('SENTINEL_FLOW_UIDS')
    os.environ['ADMIN_IDS'], os.environ['SENTINEL_FLOW_UIDS'] = '111', '222'
    try:
        check('PR4: Поток доступен владельцу и тестировщику, остальным нет',
              store.preset_allowed(111, 'flow') and store.preset_allowed(222, 'flow')
              and not store.preset_allowed(fresh, 'flow')
              and store.preset_allowed(fresh, 'trader'))
        _d = [b.callback_data for r in ui.menu_kb(fresh, 'ru').inline_keyboard for b in r]
        _o = [b.callback_data for r in ui.menu_kb(111, 'ru').inline_keyboard for b in r]
        check('PR4: кнопка Потока не рисуется подписчику и рисуется владельцу',
              'sen:pr:flow' not in _d and 'sen:pr:flow' in _o, (_d, _o))
        check('PR4: старая кнопка «поток» (sen:pr:test) - тот же запрет',
              not store.preset_allowed(fresh, 'test'))
    finally:
        for _k, _v in (('ADMIN_IDS', _adm), ('SENTINEL_FLOW_UIDS', _fl)):
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v
    # ── ПОРОГ ДВИЖЕНИЯ «ТОЛЬКО 📈📉» И ПОДСКАЗКА ──
    ui._ADV[veteran] = True
    _lbl = [b.text for r in ui.menu_kb(veteran, 'ru').inline_keyboard for b in r]
    ui._ADV.pop(veteran, None)
    check('PR4: кнопка порога называется «Порог движения (только 📈📉)»',
          any(t.startswith('Порог движения (только 📈📉)') for t in _lbl), _lbl)
    check('PR4: подсказка группы говорит, что интерес и оборот порогом не фильтруются',
          'не фильтруются' in ui._t('h_power', 'ru') and 'not filtered' in ui._t('h_power', 'en'))
    # ── ЭКРАН: ЧЕТЫРЕ ЧИСЛА СУТОК ──
    d = store.day_totals(veteran)
    check('PR4: итог суток - события, доставлено, в сводках, кредиты',
          set(d) == {'events', 'delivered', 'digested', 'credits'}, d)
    mt = ui.menu_text(veteran, 'ru')
    check('PR4: экран дозорного печатает «событий N, доставлено M, в сводках K, кредитов L»',
          re.search(r'За сутки: событий \d+, доставлено \d+, в сводках \d+, кредитов Nansen \d+',
                    mt), mt)
    store.sent_log(veteran, 'alert', 'x1', 1)
    store.sent_log(veteran, 'service', None, 2)
    check('PR4: «доставлено» считает алерты человека, а не служебные сообщения',
          store.day_totals(veteran)['delivered'] == d['delivered'] + 1)


def t_contract_cache_gap_outcome_and_card_gap_line():
    """ХВОСТЫ ТЗ: кэш контракта (3.2), исход расхождения по кромке, расхождение в карточке (2.3)."""
    now = int(time.time())
    # ── КЭШ КОНТРАКТА: первая карточка уже со ссылкой на паспорт ──
    store.contract_put('variational', 'CCH', 'solana', 'CchMint111', now=now)
    ev = dict(_ev_for(ticker='CCH', mark='104.0', now=now))
    got = outbox.with_contract(ev)
    _c = cards.card(got, bot_un='testbot')
    check('CC: контракт из кэша - в первой карточке паспорт и маркер 🪙',
          'start=tok_CchMint111' in _c and '🪙' in _c.split('\n')[0], _c)
    check('CC: событие в базе при этом не меняется (копия)',
          not (ev.get('payload') or {}).get('address'))
    check('CC: кэшу больше суток - не используется',
          store.contract_get('variational', 'CCH', now=now + 86401) is None)
    eq = dict(ev, payload=dict(ev['payload'], asset_class='equity'))
    check('CC: акции контракт не подставляется никогда',
          not outbox.with_contract(eq)['payload'].get('address'))
    # ── ИСХОД РАСХОЖДЕНИЯ ПО КРОМКЕ ──
    t0 = now - 7200
    for v, mark in (('variational', 100.0), ('hyperliquid', 100.1)):
        x = one(ticker='GPO', name='GPO', mark=str(mark))
        x.venue = v
        store.snapshot_put([x], ts=t0 + 3600)
    engine._COLD.clear()
    key = 'gpo%d' % now
    store.event_new({'key': key, 'ts': t0, 'kind': 'venue_gap', 'ticker': 'GPO', 'severity': 80,
                     'payload': {'venue': 'hyperliquid', 'gap_bps': 180.0, 'mark': 101.8,
                                 'cheap_venue': 'variational', 'rich_venue': 'hyperliquid'}})
    asyncio.run(engine.outcome_tick())
    _o = [r for r in store.outcomes(kind='venue_gap', horizon_min=60, since_ts=t0 - 1)
          if r[0] == key]
    check('GO: исход расхождения записан как изменение кромки (180 -> 10 б.п. = -94%)',
          _o and _o[0][1] is not None and -96 < _o[0][1] < -93, _o)
    # ── РАСХОЖДЕНИЕ СТРОКОЙ КАРТОЧКИ ИНСТРУМЕНТА ──
    engine._HOT.clear()
    _saved = os.environ.get('SENTINEL_VENUES')
    os.environ['SENTINEL_VENUES'] = 'variational,hyperliquid'
    try:
        for v, mark in (('variational', 50.0), ('hyperliquid', 50.25)):
            x = one(ticker='GCL', name='GCL', mark=str(mark))
            x.venue = v
            store.snapshot_put([x], ts=now - 30)
        txt = asyncio.run(ui.card_link('GCL', 'variational', 'ru'))
    finally:
        os.environ['SENTINEL_VENUES'] = _saved or 'variational'
    check('GL: в карточке инструмента - цена другой площадки и расхождение в б.п.',
          'Hyperliquid 50.2500: дороже на 50 б.п.' in txt, txt)


def t_poller_watchdog_and_one_message_per_incident():
    """ЭТАП 5: СТОРОЖ ПРОЦЕССА, ТАЙМАУТЫ, ОДНО СООБЩЕНИЕ НА ИНЦИДЕНТ, ЧАС ПОСЛЕ РЕСТАРТА."""
    now = 1800000000
    # ── 5.1 СТОРОЖ: снимка нет дольше 3 x poll_sec - процесс умирает, чтобы юнит поднял его ──
    hb = {'fetch_ok': now - 30, 'elsewhere': 0}
    check('WD: свежий снимок - жить', engine.watchdog_verdict(now, now - 999, hb, 30) is None)
    hb2 = {'fetch_ok': now - 91, 'elsewhere': 0}
    _v = engine.watchdog_verdict(now, now - 999, hb2, 30)
    check('WD: 91 с без снимка при опросе 30 с - умереть, причина числом',
          _v and '91' in _v and '90' in _v, _v)
    check('WD: первые 3 x poll_sec после старта - льгота (снимка ещё не было)',
          engine.watchdog_verdict(now, now - 60, {'fetch_ok': 0, 'elsewhere': 0}, 30) is None)
    check('WD: аренда у другого живого процесса - молчание законно, не умирать',
          engine.watchdog_verdict(now, now - 999, {'fetch_ok': 0, 'elsewhere': now - 10}, 30)
          is None)
    import inspect
    from sentinel import main as _mn
    _src = inspect.getsource(_mn)
    check('WD: сторож - отдельный поток и os._exit с ненулевым кодом (не sys.exit из потока)',
          'threading.Thread' in _src and 'os._exit(WATCHDOG_EXIT_CODE)' in _src
          and _mn.WATCHDOG_EXIT_CODE != 0)
    # ── ТАЙМАУТ НА ПЛОЩАДКУ: зависшая площадка отдаёт отказ, остальные читаются ──
    import asyncio as _aio

    async def _hang():
        await _aio.sleep(3600)

    async def _fast():
        return [one(ticker='WDOK')], {'latency_ms': 1}
    _saved = {k: dict(v) for k, v in venues.VENUES.items()}
    _to = venues.VENUE_TIMEOUT_S
    venues.VENUES['variational']['fetch'] = _fast
    venues.VENUES['hyperliquid']['fetch'] = _hang
    venues.VENUE_TIMEOUT_S = 1
    try:
        _t0 = time.time()
        rows, notes = asyncio.run(venues.fetch_all(['variational', 'hyperliquid']))
        _dt = time.time() - _t0
    finally:
        for k, v in _saved.items():
            venues.VENUES[k] = v
        venues.VENUE_TIMEOUT_S = _to
    check('TO: зависшая площадка - отказ «timeout» за секунду, а не вечный тик',
          _dt < 5 and getattr(notes.get('hyperliquid'), 'kind', '') == 'timeout', (_dt, notes))
    check('TO: и соседняя площадка при этом прочитана', rows and rows[0].ticker == 'WDOK')
    # ── 5.2 ОДНО СООБЩЕНИЕ НА ИНЦИДЕНТ И ОДНО ПРИ ВОЗВРАТЕ ──
    sent = []

    async def _cap(text, label):
        sent.append((label, text))
    _orig = engine._say_owners
    engine._say_owners = _cap
    store.cursor_set(engine.INCIDENT_CURSOR, '')
    try:
        store.cursor_set(engine.POLL_OK_CURSOR, str(now - 60))
        asyncio.run(engine.poll_watch(now=now))
        check('INC: минута без снимка - не инцидент (сторож лечит рестартом)', not sent, sent)
        store.cursor_set(engine.POLL_OK_CURSOR, str(now - 400))
        for i in range(5):
            asyncio.run(engine.poll_watch(now=now + i * 30))
        check('INC: потеря опроса - ОДНО сообщение, сколько бы тиков ни прошло',
              [l for l, _t in sent] == ['sentinel:poll_lost'], sent)
        check('INC: сообщение называет, сколько минут нет снимка',
              sent and 'Последний снимок 6 мин' in sent[0][1], sent[:1])
        store.cursor_set(engine.POLL_OK_CURSOR, str(now + 900))
        asyncio.run(engine.poll_watch(now=now + 930))
        asyncio.run(engine.poll_watch(now=now + 960))
        check('INC: возврат - одно «опрос вернулся, кольцо было пустым N минут»',
              [l for l, _t in sent] == ['sentinel:poll_lost', 'sentinel:poll_back']
              and 'кольцо было пустым 21 мин' in sent[-1][1], sent)
        check('INC: второй процесс не отправит то же самое (сравнить-и-записать в базе)',
              store.cursor_cas(engine.INCIDENT_CURSOR, 'нечто', 'x') is False
              and store.cursor_cas(engine.INCIDENT_CURSOR, '', 'x') is True
              and store.cursor_cas(engine.INCIDENT_CURSOR, '', 'y') is False)
    finally:
        engine._say_owners = _orig
        store.cursor_set(engine.INCIDENT_CURSOR, '')
        store.cursor_set(engine.POLL_OK_CURSOR, '')
    # ── 5.3 ПОСЛЕ РЕСТАРТА ЧАС ИЗ ХОЛОДНОГО КОЛЬЦА, С ПОМЕТКОЙ ──
    ring = series(100, now - 100 * 900)
    hot_fresh = [(now - 600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 600, 1.9e6)]
    evs = detector.detect(one(mark='103.0', quote_iso=_iso(now)), hot_fresh, now=now, ring=ring)
    mv = [e for e in evs if e['kind'] == 'move_up']
    check('R53: после рестарта (горячему кольцу 10 мин) часовое движение есть - из холодного',
          mv and mv[0]['payload'].get('p60_src') == 'cold15'
          and mv[0]['payload'].get('window') == '60м',
          [(e['kind'], e['payload'].get('p60_src')) for e in evs])
    _c = cards.card(mv[0]) if mv else ''
    check('R53: карточка помечает «после рестарта, точность часового окна 15 мин»',
          'после рестарта, точность часового окна 15 мин' in _c, _c)
    full = [(now - 3600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 3600, 1.9e6)]
    ev_h = [e for e in detector.detect(one(mark='103.0', quote_iso=_iso(now)), full, now=now,
                                       ring=ring) if e['kind'] == 'move_up']
    check('R53: с полным горячим кольцом пометки нет',
          ev_h and ev_h[0]['payload'].get('p60_src') == 'hot'
          and 'после рестарта' not in cards.card(ev_h[0]))


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
               t_open_interest_is_dollars_on_every_venue,
               t_perp_context_on_real_nansen_shapes,
               t_ignition_without_mcap_goes_to_digest,
               t_venue_gap_is_rare_and_not_a_basis,
               t_verdict_is_code_and_model_is_behind_a_flag,
               t_x_and_polymarket_lines_are_for_the_reader,
               t_live_defects_after_1b,
               t_sigma60_is_estimated_until_hourly_points_exist,
               t_vol_and_oi_thresholds_are_measured_2_4,
               t_asset_class_on_live_names_and_nyse_session_2_5,
               t_stage3_cards_are_links_without_service_lines,
               t_presets_stage4,
               t_contract_cache_gap_outcome_and_card_gap_line,
               t_poller_watchdog_and_one_message_per_incident,
               t_fuse_counts_every_message_not_only_alerts,
               t_digest_says_one_line_per_ticker,
               t_one_move_is_one_thread_not_twelve_alerts,
               t_feed_is_stored_because_window_is_longer_than_page,
               t_smart_perp_is_a_side_not_a_purchase,
               t_liquidation_clusters_and_outcomes_by_kind,
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
