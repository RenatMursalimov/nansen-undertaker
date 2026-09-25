# -*- coding: utf-8 -*-
"""sentinel/store.py — состояние дозорного в общей базе бота: кольцо снимков, события,
подписки, доставки, исходы.

ПОЧЕМУ ОБЩАЯ БАЗА, А НЕ СВОЙ ФАЙЛ. Дозорный переезжает в отдельный процесс (см. шапку
пакета), и своя SQLite-ка в тот же момент стала бы вторым источником правды: бот показывал
бы подписки из одного файла, воркер рассылал бы по другому. Прод уже на PostgreSQL, там
«отдельный процесс на той же базе» — штатный режим, а не трюк.

ЧТО ЗДЕСЬ ГЛАВНОЕ: ИДЕНТИЧНОСТЬ СОБЫТИЯ И СОСТОЯНИЕ ДОСТАВКИ — ДВЕ РАЗНЫЕ ТАБЛИЦЫ
Событие случается ОДИН раз (`sentinel_events`, ключ — первичный), доставка случается по
разу НА ЧЕЛОВЕКА (`sentinel_deliveries`). Сложи их в одну таблицу — и «алерт уже был» начнёт
означать «кому-то уже отправляли», то есть второй подписчик не получит ничего. Ровно этот
класс бага (доставка как свойство события) уже ловился в рассыльщиках бота.

«ОТПРАВЛЕНО» СТАВИТСЯ ТОЛЬКО ПОСЛЕ ОТВЕТА ТЕЛЕГРАМА. `delivered_at` заполняет не тот, кто
решил отправить, а тот, кто получил подтверждение (см. `outbox.py`). Иначе первая же
RetryAfter превращается в «доставлено» — и человек не получил, а база уверена, что получил.

ЧИСЛА В КОЛЬЦЕ ЖИВУТ 7 СУТОК И НЕ БОЛЬШЕ. Кольцо нужно двум потребителям: сигме (порог «во
сколько сигм») и отчёту попаданий. Держать больше — значит платить местом за данные, которые
никто не читает; держать меньше — значит считать сигму по выборке, где её нет.
"""

import json
import os
import socket
import time

import db

#: КЛЮЧ БАЗЫ - ONCHAIN, как у всего ончейн-слоя (`perp_watch`, `oc_alerts`): дозорный читает
#: те же тикеры и те же кошельки, и разносить это по двум базам значило бы делать JOIN руками.
DB_KEY = 'onchain'


def _ensure(conn):
    # ── КОЛЬЦО СНИМКОВ. Первичный ключ (тикер, секунда) - защита от двойного тика: два
    #    процесса в момент переезда запишут ОДИН снимок, а не два с разными числами.
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_snapshots (
        ticker TEXT NOT NULL,
        ts INTEGER NOT NULL,
        mark REAL,
        vol24 REAL,
        oi_long REAL,
        oi_short REAL,
        funding REAL,
        spread_bps REAL,
        quote_ts INTEGER,
        PRIMARY KEY (ticker, ts))''')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_sent_snap_ts ON sentinel_snapshots(ts)')
    # ── СОБЫТИЯ. `event_key` - НАШ детерминированный ключ (см. detector.key), а не автоинкремент:
    #    один и тот же выброс, увиденный дважды (перезапуск, наложение тиков), обязан дать ОДНУ
    #    строку. Автоинкремент дал бы две и два алерта.
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_events (
        event_key TEXT PRIMARY KEY,
        ts INTEGER,
        kind TEXT,
        ticker TEXT,
        severity INTEGER,
        payload TEXT,
        created_at INTEGER)''')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_sent_ev_ts ON sentinel_events(ts)')
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_subs (
        user_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,
        created_at INTEGER,
        UNIQUE(user_id, ticker))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_settings (
        user_id INTEGER PRIMARY KEY,
        alerts_on INTEGER DEFAULT 1,
        min_pct REAL,
        quiet_from INTEGER,
        quiet_to INTEGER,
        daily_cap INTEGER,
        enrich_on INTEGER DEFAULT 1)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_deliveries (
        event_key TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        state TEXT,
        attempts INTEGER DEFAULT 0,
        last_err TEXT,
        created_at INTEGER,
        delivered_at INTEGER,
        msg_id INTEGER,
        UNIQUE(event_key, user_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_cooldown (
        user_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,
        kind TEXT NOT NULL,
        last_ts INTEGER,
        UNIQUE(user_id, ticker, kind))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_enrich (
        event_key TEXT PRIMARY KEY,
        state TEXT,
        body TEXT,
        credits INTEGER DEFAULT 0,
        err TEXT,
        ts INTEGER)''')
    # ── ИСХОД. Отчёт попаданий строится ТОЛЬКО по этой таблице: цена в момент алерта и цена
    #    через горизонт, снятые ОДНИМ И ТЕМ ЖЕ фидом. Считать «сработало ли» по памяти
    #    человека или по скриншоту нельзя - это и есть «выборка мала», только без честного
    #    признания.
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_outcome (
        event_key TEXT NOT NULL,
        horizon_min INTEGER NOT NULL,
        price_then REAL,
        price_after REAL,
        ret_pct REAL,
        ts INTEGER,
        UNIQUE(event_key, horizon_min))''')
    # ── КУРСОРЫ ЧУЖИХ ЛЕНТ. Nansen отдаёт трейлинг-окно (24ч у DEX, 7 суток у перпов), а не
    #    «что нового с прошлого раза». Значит границу «нового» ведём МЫ, и ведём в базе:
    #    в памяти она обнулялась бы рестартом, и после каждого деплоя человек получал бы
    #    суточный бэклог как «живые алерты».
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_cursor (
        name TEXT PRIMARY KEY,
        value TEXT,
        updated_at INTEGER)''')
    # ── ХЭШИ УЖЕ УЧТЁННЫХ СДЕЛОК. `transaction_hash` есть в обеих лентах Nansen (ЗАМЕР по
    #    схеме ответа), и он — единственная настоящая идентичность сделки: по времени ключ
    #    строить нельзя, в одну секунду попадает несколько сделок, а округление времени
    #    склеило бы разные сделки в одну.
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_seen_tx (
        tx TEXT PRIMARY KEY,
        ts INTEGER)''')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_sent_seen_ts ON sentinel_seen_tx(ts)')
    # ── АРЕНДА ОПРОСА. Один опрашивающий на площадку: в момент переезда бот и отдельный юнит
    #    живы ОБА, и без аренды они удвоили бы запросы (лимит 10/10с) и записали бы кольцо
    #    вразнобой.
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_lease (
        name TEXT PRIMARY KEY,
        owner TEXT,
        until INTEGER)''')
    # ── РАСХОД КРЕДИТОВ ДОЗОРНЫМ, ОТДЕЛЬНО ОТ ОБЩЕГО. Автономная трата обязана иметь свою
    #    границу: человек, не просивший дозорного, не должен получить отказ на своём экране.
    conn.execute('''CREATE TABLE IF NOT EXISTS sentinel_spend (
        day TEXT PRIMARY KEY,
        credits INTEGER DEFAULT 0,
        events INTEGER DEFAULT 0)''')


def conn():
    return db.ready('sentinel', _ensure, key=DB_KEY)


def _now():
    return int(time.time())


def _today():
    return time.strftime('%Y-%m-%d', time.gmtime())


# ══════════════════════════════════════════════════════════════════════════════════════════
# КОЛЬЦО СНИМКОВ
# ══════════════════════════════════════════════════════════════════════════════════════════
def snapshot_put(listings, ts=None):
    """Записать снимок площадки. -> сколько строк легло.

    ПИШЕМ ВСЁ, ЧТО ОПРОСИЛИ, А НЕ ТОЛЬКО ПОДПИСАННОЕ. Сигма и медиана спреда считаются по
    истории инструмента; если писать только то, на что кто-то подписан, то первый же новый
    подписчик получил бы инструмент без истории — то есть без порога — и увидел бы либо
    молчание, либо мусор. История рынка дешевле, чем объяснение этого поведения.
    """
    ts = int(ts if ts is not None else time.time())
    c = conn()
    n = 0
    for x in listings:
        try:
            c.execute('INSERT OR REPLACE INTO sentinel_snapshots '
                      '(ticker, ts, mark, vol24, oi_long, oi_short, funding, spread_bps, quote_ts)'
                      ' VALUES (?,?,?,?,?,?,?,?,?)',
                      (x.ticker, ts, x.mark, x.volume_24h, x.oi_long, x.oi_short,
                       x.funding_raw, x.spread_bps,
                       int(x.quote_ts) if x.quote_ts else None))
            n += 1
        except Exception as e:
            print('[sentinel] снимок %s не записан: %s' % (x.ticker, str(e)[:120]))
    try:
        c.commit()
    except Exception:
        pass
    return n


def history(ticker, since_ts=None, limit=4000):
    """Снимки инструмента по возрастанию времени. -> [(ts, mark, vol24, oi_long, oi_short,
    funding, spread_bps, quote_ts)].

    ЧИТАЕМ ПО ИНДЕКСУ, А НЕ ПО ИМЕНИ КОЛОНКИ: на PostgreSQL строка курсора не даёт доступа по
    имени так, как `sqlite3.Row`, и код «r['mark']» падал бы ровно на проде (наш случай уже
    был). Порядок полей зафиксирован в докстринге — это и есть контракт.
    """
    since = int(since_ts if since_ts is not None else 0)
    rows = conn().execute(
        'SELECT ts, mark, vol24, oi_long, oi_short, funding, spread_bps, quote_ts '
        'FROM sentinel_snapshots WHERE ticker=? AND ts>=? ORDER BY ts ASC LIMIT ?',
        (ticker, since, int(limit))).fetchall()
    return [tuple(r[i] for i in range(8)) for r in rows]


def prune(days=None):
    """Убрать снимки старше окна. -> сколько удалено (или -1, если СУБД не сказала)."""
    from . import config
    keep = int(days if days is not None else config.ring_days())
    cut = _now() - keep * 86400
    c = conn()
    cur = c.execute('DELETE FROM sentinel_snapshots WHERE ts < ?', (cut,))
    try:
        c.commit()
    except Exception:
        pass
    try:
        return int(cur.rowcount)
    except Exception:
        return -1


def tickers_seen(since_ts=None):
    """Какие инструменты вообще есть в кольце. -> set(тикеров)."""
    since = int(since_ts if since_ts is not None else _now() - 86400)
    rows = conn().execute('SELECT DISTINCT ticker FROM sentinel_snapshots WHERE ts>=?',
                          (since,)).fetchall()
    return {r[0] for r in rows}


# ══════════════════════════════════════════════════════════════════════════════════════════
# СОБЫТИЯ
# ══════════════════════════════════════════════════════════════════════════════════════════
def event_new(ev):
    """Записать событие, ЕСЛИ такого ключа ещё не было. -> True (новое) | False (повтор).

    ВОЗВРАТ - ГЛАВНОЕ В ЭТОЙ ФУНКЦИИ. Дедупликация живёт в БАЗЕ (первичный ключ), а не в
    памяти процесса: память обнуляется рестартом, и после каждого деплоя человек получал бы
    повтор всех событий последнего часа. Проверка «SELECT, потом INSERT» тоже не годится —
    два тика успеют пройти между ними.
    """
    c = conn()
    try:
        c.execute('INSERT INTO sentinel_events '
                  '(event_key, ts, kind, ticker, severity, payload, created_at) '
                  'VALUES (?,?,?,?,?,?,?)',
                  (ev['key'], int(ev.get('ts') or _now()), ev.get('kind'), ev.get('ticker'),
                   int(ev.get('severity') or 0),
                   json.dumps(ev.get('payload') or {}, ensure_ascii=False), _now()))
        c.commit()
        return True
    except Exception as e:
        if _is_dup(e):
            return False
        print('[sentinel] событие %s не записано: %s' % (ev.get('key'), str(e)[:140]))
        return False


def _is_dup(e):
    """Нарушение уникальности -> True. Любая ДРУГАЯ ошибка базы не должна выглядеть как
    «это повтор»: иначе упавшая запись молча превратится в «уже было» и событие исчезнет."""
    s = str(e).lower()
    return ('unique' in s or 'duplicate key' in s or 'уже существует' in s
            or 'already exists' in s)


def event(event_key):
    """-> dict события | None."""
    r = conn().execute('SELECT event_key, ts, kind, ticker, severity, payload '
                       'FROM sentinel_events WHERE event_key=?', (event_key,)).fetchone()
    if not r:
        return None
    try:
        payload = json.loads(r[5] or '{}')
    except Exception:
        payload = {}
    return {'key': r[0], 'ts': r[1], 'kind': r[2], 'ticker': r[3], 'severity': r[4],
            'payload': payload}


def events_since(ts, limit=200):
    rows = conn().execute('SELECT event_key FROM sentinel_events WHERE ts>=? '
                          'ORDER BY ts ASC LIMIT ?', (int(ts), int(limit))).fetchall()
    return [r[0] for r in rows]


# ══════════════════════════════════════════════════════════════════════════════════════════
# ПОДПИСКИ И НАСТРОЙКИ
# ══════════════════════════════════════════════════════════════════════════════════════════
#: '*' - ПОДПИСКА НА ВСЮ ПЛОЩАДКУ. Отдельной таблицей «подписан на всё» не заводим: тогда
#: появились бы два способа быть подписанным, и половина проверок знала бы только про один.
ALL = '*'


def sub_add(uid, ticker):
    """-> (ok, причина). Отказ ВСЕГДА со словом: «ничего не произошло» человек читает как баг."""
    from . import config
    t = (ticker or '').strip().upper()
    if not t:
        return False, 'пустой тикер'
    cur = sub_list(uid)
    if t in cur:
        return False, 'уже в дозоре'
    if t != ALL and len([x for x in cur if x != ALL]) >= config.max_tickers():
        return False, 'больше %d инструментов не держим' % config.max_tickers()
    c = conn()
    c.execute('INSERT INTO sentinel_subs (user_id, ticker, created_at) VALUES (?,?,?)',
              (int(uid), t, _now()))
    c.commit()
    return True, 'в дозоре'


def sub_del(uid, ticker):
    t = (ticker or '').strip().upper()
    c = conn()
    cur = c.execute('DELETE FROM sentinel_subs WHERE user_id=? AND ticker=?', (int(uid), t))
    c.commit()
    try:
        return int(cur.rowcount) > 0
    except Exception:
        return True


def sub_list(uid):
    rows = conn().execute('SELECT ticker FROM sentinel_subs WHERE user_id=? ORDER BY ticker',
                          (int(uid),)).fetchall()
    return [r[0] for r in rows]


def subscribers(ticker):
    """Кому интересен этот инструмент. -> [uid]. Включает подписчиков '*'."""
    rows = conn().execute('SELECT DISTINCT user_id FROM sentinel_subs WHERE ticker=? OR ticker=?',
                          ((ticker or '').upper(), ALL)).fetchall()
    return [int(r[0]) for r in rows]


def watched():
    """Все инструменты под дозором. -> set. `ALL` в наборе означает «вся площадка»."""
    rows = conn().execute('SELECT DISTINCT ticker FROM sentinel_subs').fetchall()
    return {r[0] for r in rows}


_DEF_SETTINGS = {'alerts_on': 1, 'min_pct': None, 'quiet_from': None, 'quiet_to': None,
                 'daily_cap': None, 'enrich_on': 1}


def settings(uid):
    r = conn().execute('SELECT alerts_on, min_pct, quiet_from, quiet_to, daily_cap, enrich_on '
                       'FROM sentinel_settings WHERE user_id=?', (int(uid),)).fetchone()
    if not r:
        return dict(_DEF_SETTINGS)
    return {'alerts_on': int(r[0] or 0), 'min_pct': r[1], 'quiet_from': r[2],
            'quiet_to': r[3], 'daily_cap': r[4],
            'enrich_on': 1 if r[5] is None else int(r[5])}


def settings_set(uid, **kw):
    """Точечная правка настроек. Неизвестные ключи игнорируются со строкой в лог."""
    cur = settings(uid)
    for k, v in kw.items():
        if k not in _DEF_SETTINGS:
            print('[sentinel] настройка %r неизвестна - пропущена' % k)
            continue
        cur[k] = v
    c = conn()
    c.execute('INSERT OR REPLACE INTO sentinel_settings '
              '(user_id, alerts_on, min_pct, quiet_from, quiet_to, daily_cap, enrich_on) '
              'VALUES (?,?,?,?,?,?,?)',
              (int(uid), int(cur['alerts_on'] or 0), cur['min_pct'], cur['quiet_from'],
               cur['quiet_to'], cur['daily_cap'], int(cur['enrich_on'] or 0)))
    c.commit()
    return cur


# ══════════════════════════════════════════════════════════════════════════════════════════
# ПАУЗА И СУТОЧНЫЙ ПОТОЛОК
# ══════════════════════════════════════════════════════════════════════════════════════════
def cooldown_left(uid, ticker, kind, now=None):
    """Сколько секунд ещё молчим по этой паре. -> 0, если можно."""
    from . import config
    now = int(now if now is not None else time.time())
    r = conn().execute('SELECT last_ts FROM sentinel_cooldown '
                       'WHERE user_id=? AND ticker=? AND kind=?',
                       (int(uid), ticker, kind)).fetchone()
    if not r or not r[0]:
        return 0
    left = config.cooldown_sec() - (now - int(r[0]))
    return max(0, int(left))


def cooldown_mark(uid, ticker, kind, now=None):
    """Отметить отправку. ЗОВЁТ ТОЛЬКО ТОТ, КТО УЖЕ ПОЛУЧИЛ ПОДТВЕРЖДЕНИЕ ТЕЛЕГРАМА.

    Иначе сбой отправки съедал бы час тишины: человек не получил алерт И не получит
    следующий. Ровно эту ошибку `perp_watch` исправлял отдельной правкой.
    """
    now = int(now if now is not None else time.time())
    c = conn()
    c.execute('INSERT INTO sentinel_cooldown (user_id, ticker, kind, last_ts) VALUES (?,?,?,?) '
              'ON CONFLICT (user_id, ticker, kind) DO UPDATE SET '
              'last_ts=excluded.last_ts', (int(uid), ticker, kind, now))
    c.commit()


def sent_today(uid, now=None):
    """Сколько алертов человек получил за сутки UTC. Считаем ДОСТАВЛЕННЫЕ, а не задуманные."""
    now = int(now if now is not None else time.time())
    day0 = now - (now % 86400)
    r = conn().execute('SELECT COUNT(*) FROM sentinel_deliveries '
                       'WHERE user_id=? AND delivered_at IS NOT NULL AND delivered_at>=?',
                       (int(uid), day0)).fetchone()
    return int((r or [0])[0] or 0)


def cap_for(uid):
    from . import config
    s = settings(uid)
    return int(s.get('daily_cap') or config.daily_cap())


# ══════════════════════════════════════════════════════════════════════════════════════════
# ДОСТАВКА
# ══════════════════════════════════════════════════════════════════════════════════════════
def delivery_plan(event_key, uid):
    """Поставить доставку в очередь. -> True (поставлена) | False (уже стояла).

    Очередь в БАЗЕ, а не в памяти: сбой отправки (RetryAfter, сеть, блокировка бота) должен
    пережить рестарт, иначе алерт исчезает вместе с процессом и о нём никто не узнает.
    """
    c = conn()
    try:
        c.execute('INSERT INTO sentinel_deliveries (event_key, user_id, state, attempts, '
                  'created_at) VALUES (?,?,?,?,?)',
                  (event_key, int(uid), 'queued', 0, _now()))
        c.commit()
        return True
    except Exception as e:
        if _is_dup(e):
            return False
        print('[sentinel] доставка не поставлена: %s' % str(e)[:140])
        return False


def delivery_due(limit=50):
    """Что ждёт отправки. -> [(event_key, uid, attempts)]."""
    rows = conn().execute("SELECT event_key, user_id, attempts FROM sentinel_deliveries "
                          "WHERE delivered_at IS NULL AND state<>'dead' "
                          "ORDER BY created_at ASC LIMIT ?", (int(limit),)).fetchall()
    return [(r[0], int(r[1]), int(r[2] or 0)) for r in rows]


def delivery_ok(event_key, uid, msg_id=None):
    c = conn()
    c.execute("UPDATE sentinel_deliveries SET state='sent', delivered_at=?, msg_id=?, "
              "last_err=NULL WHERE event_key=? AND user_id=?",
              (_now(), (int(msg_id) if msg_id else None), event_key, int(uid)))
    c.commit()


#: Сколько раз пробуем доставить, прежде чем назвать доставку мёртвой. Мёртвая доставка
#: ОСТАЁТСЯ строкой в базе с причиной: «пропало молча» - худший из исходов.
MAX_ATTEMPTS = int(os.getenv('SENTINEL_MAX_ATTEMPTS') or 5)


def delivery_fail(event_key, uid, err):
    c = conn()
    r = c.execute('SELECT attempts FROM sentinel_deliveries WHERE event_key=? AND user_id=?',
                  (event_key, int(uid))).fetchone()
    n = int((r or [0])[0] or 0) + 1
    state = 'dead' if n >= MAX_ATTEMPTS else 'retry'
    c.execute('UPDATE sentinel_deliveries SET state=?, attempts=?, last_err=? '
              'WHERE event_key=? AND user_id=?',
              (state, n, str(err)[:200], event_key, int(uid)))
    c.commit()
    return state


def delivery_state(event_key, uid):
    r = conn().execute('SELECT state, attempts, last_err, delivered_at FROM sentinel_deliveries '
                       'WHERE event_key=? AND user_id=?', (event_key, int(uid))).fetchone()
    if not r:
        return None
    return {'state': r[0], 'attempts': int(r[1] or 0), 'last_err': r[2], 'delivered_at': r[3]}


def delivered_users(event_key):
    rows = conn().execute('SELECT user_id FROM sentinel_deliveries WHERE event_key=? '
                          'AND delivered_at IS NOT NULL', (event_key,)).fetchall()
    return [int(r[0]) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════════════════
# ОБОГАЩЕНИЕ
# ══════════════════════════════════════════════════════════════════════════════════════════
def enrich_claim(event_key):
    """Занять событие под обогащение. -> True, если заняли мы.

    ЗАЧЕМ ЗАМОК НА СТРОКЕ: обогащение стоит кредитов, и два тика, наложившись, купили бы одну
    и ту же сводку дважды. Признак «уже обогащено» - строка в базе, а не переменная.
    """
    c = conn()
    try:
        c.execute('INSERT INTO sentinel_enrich (event_key, state, ts) VALUES (?,?,?)',
                  (event_key, 'work', _now()))
        c.commit()
        return True
    except Exception as e:
        if _is_dup(e):
            return False
        print('[sentinel] обогащение не занято: %s' % str(e)[:140])
        return False


def enrich_done(event_key, body, credits=0, err=None):
    c = conn()
    c.execute('INSERT OR REPLACE INTO sentinel_enrich '
              '(event_key, state, body, credits, err, ts) VALUES (?,?,?,?,?,?)',
              (event_key, ('done' if body else 'fail'), body or '', int(credits or 0),
               (str(err)[:200] if err else None), _now()))
    c.commit()


def enrich_get(event_key):
    r = conn().execute('SELECT state, body, credits, err FROM sentinel_enrich '
                       'WHERE event_key=?', (event_key,)).fetchone()
    if not r:
        return None
    return {'state': r[0], 'body': r[1], 'credits': int(r[2] or 0), 'err': r[3]}


def enrich_pending(limit=20):
    """События, доставленные хотя бы одному человеку и ещё не обогащённые. -> [event_key].

    ПОРЯДОК ИМЕННО ТАКОЙ: обогащаем ТО, ЧТО УЖЕ УШЛО. Обогащать недоставленное значит платить
    кредитами за сводку к алерту, которого человек не видел.
    """
    rows = conn().execute(
        'SELECT DISTINCT d.event_key FROM sentinel_deliveries d '
        'LEFT JOIN sentinel_enrich e ON e.event_key = d.event_key '
        'WHERE d.delivered_at IS NOT NULL AND e.event_key IS NULL '
        'ORDER BY d.delivered_at DESC LIMIT ?', (int(limit),)).fetchall()
    return [r[0] for r in rows]


# ══════════════════════════════════════════════════════════════════════════════════════════
# ИСХОД И ОТЧЁТ ПОПАДАНИЙ
# ══════════════════════════════════════════════════════════════════════════════════════════
def outcome_put(event_key, horizon_min, price_then, price_after):
    ret = None
    if price_then and price_after is not None:
        ret = (price_after - price_then) / price_then * 100.0
    c = conn()
    c.execute('INSERT OR REPLACE INTO sentinel_outcome '
              '(event_key, horizon_min, price_then, price_after, ret_pct, ts) '
              'VALUES (?,?,?,?,?,?)',
              (event_key, int(horizon_min), price_then, price_after, ret, _now()))
    c.commit()
    return ret


def outcomes(kind=None, horizon_min=60, since_ts=None):
    """Исходы по виду события. -> [(event_key, ret_pct, kind, severity)]."""
    args = [int(horizon_min)]
    sql = ('SELECT o.event_key, o.ret_pct, e.kind, e.severity FROM sentinel_outcome o '
           'JOIN sentinel_events e ON e.event_key=o.event_key '
           'WHERE o.horizon_min=? AND o.ret_pct IS NOT NULL')
    if kind:
        sql += ' AND e.kind=?'
        args.append(kind)
    if since_ts:
        sql += ' AND e.ts>=?'
        args.append(int(since_ts))
    rows = conn().execute(sql, tuple(args)).fetchall()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def outcome_due(horizon_min, now=None):
    """События, у которых горизонт истёк, а исход не записан. -> [(event_key, ticker, ts)]."""
    now = int(now if now is not None else time.time())
    cut = now - int(horizon_min) * 60
    rows = conn().execute(
        'SELECT e.event_key, e.ticker, e.ts FROM sentinel_events e '
        'LEFT JOIN sentinel_outcome o ON o.event_key=e.event_key AND o.horizon_min=? '
        'WHERE e.ts<=? AND o.event_key IS NULL ORDER BY e.ts ASC LIMIT 200',
        (int(horizon_min), cut)).fetchall()
    return [(r[0], r[1], int(r[2] or 0)) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════════════════
# АРЕНДА ОПРОСА И РАСХОД
# ══════════════════════════════════════════════════════════════════════════════════════════
def _me():
    return '%s:%s' % (socket.gethostname()[:30], os.getpid())


def lease(name='variational', ttl=None, owner=None, now=None):
    """Взять/продлить аренду опроса. -> True, если опрашивать можно НАМ.

    ПОЧЕМУ АРЕНДА, А НЕ ФЛАГ «Я ГЛАВНЫЙ». Владелец процесса умирает без предупреждения
    (kill, деплой, OOM), и флаг остался бы поднятым навсегда — опрос замолчал бы совсем. У
    аренды есть срок: умерший владелец теряет её сам, живой продлевает каждым тиком.
    """
    from . import config
    now = int(now if now is not None else time.time())
    ttl = int(ttl or max(30, config.poll_sec() * 3))
    who = owner or _me()
    c = conn()
    r = c.execute('SELECT owner, until FROM sentinel_lease WHERE name=?', (name,)).fetchone()
    if r and r[0] != who and int(r[1] or 0) > now:
        return False
    c.execute('INSERT INTO sentinel_lease (name, owner, until) VALUES (?,?,?) '
              'ON CONFLICT (name) DO UPDATE SET owner=excluded.owner, until=excluded.until',
              (name, who, now + ttl))
    c.commit()
    return True


def lease_owner(name='variational'):
    r = conn().execute('SELECT owner, until FROM sentinel_lease WHERE name=?', (name,)).fetchone()
    return (r[0], int(r[1] or 0)) if r else (None, 0)


def lease_release(name='variational', owner=None):
    who = owner or _me()
    c = conn()
    c.execute('DELETE FROM sentinel_lease WHERE name=? AND owner=?', (name, who))
    c.commit()


def spend_add(credits=0, events=0, day=None):
    d = day or _today()
    c = conn()
    c.execute('INSERT INTO sentinel_spend (day, credits, events) VALUES (?,?,?) '
              'ON CONFLICT (day) DO UPDATE SET '
              'credits = sentinel_spend.credits + excluded.credits, '
              'events = sentinel_spend.events + excluded.events',
              (d, int(credits or 0), int(events or 0)))
    c.commit()


def spend_today(day=None):
    r = conn().execute('SELECT credits, events FROM sentinel_spend WHERE day=?',
                       (day or _today(),)).fetchone()
    return (int((r or [0, 0])[0] or 0), int((r or [0, 0])[1] or 0))


def budget_left():
    """Сколько кредитов дозорному ещё можно сжечь сегодня. -> int (0 = стоп).

    ВЕЛИЧИНА, А НЕ ФЛАГ: «обогащение включено» не отвечает на вопрос «а есть ли на него
    деньги». Строка в карточке будет говорить остаток числом.
    """
    from . import config
    cap = config.nansen_day_credits()
    if cap <= 0:
        return 0
    used, _ = spend_today()
    return max(0, cap - used)


# ══════════════════════════════════════════════════════════════════════════════════════════
# КУРСОРЫ И УЧТЁННЫЕ СДЕЛКИ
# ══════════════════════════════════════════════════════════════════════════════════════════
def cursor_get(name):
    r = conn().execute('SELECT value FROM sentinel_cursor WHERE name=?', (name,)).fetchone()
    return (r[0] if r else None)


def cursor_set(name, value):
    c = conn()
    c.execute('INSERT INTO sentinel_cursor (name, value, updated_at) VALUES (?,?,?) '
              'ON CONFLICT (name) DO UPDATE SET value=excluded.value, '
              'updated_at=excluded.updated_at', (name, str(value), _now()))
    c.commit()


def seen_tx(hashes, ts=None):
    """Отметить сделки учтёнными. -> множество тех, что мы видим ПЕРВЫЙ раз.

    ВОЗВРАТ ИМЕННО ТАКОЙ, ПОТОМУ ЧТО ВОПРОС ИМЕННО ТАКОЙ. Вызывающему нужно «что нового», и
    отдать ему это должна ОДНА операция: сначала «спросить, потом записать» двумя вызовами —
    это гонка между тиками, и одна и та же сделка посчиталась бы дважды.
    """
    ts = int(ts if ts is not None else time.time())
    c = conn()
    fresh = set()
    for h in hashes:
        if not h:
            continue
        try:
            c.execute('INSERT INTO sentinel_seen_tx (tx, ts) VALUES (?,?)', (str(h), ts))
            fresh.add(str(h))
        except Exception as e:
            if not _is_dup(e):
                print('[sentinel] tx %s не записан: %s' % (str(h)[:12], str(e)[:100]))
    c.commit()
    return fresh


def seen_prune(days=3):
    """Хэши старше окна убираем: лента Nansen и так трейлинговая (24ч/7 суток), и держать
    больше значило бы платить местом за проверку, которая уже невозможна."""
    c = conn()
    c.execute('DELETE FROM sentinel_seen_tx WHERE ts < ?', (_now() - int(days) * 86400,))
    c.commit()


#: КЛЮЧ СОБЫТИЯ ЖИВЁТ В `detector`, А ЗДЕСЬ ТОЛЬКО ИМЯ ДЛЯ ЧИТАЮЩИХ ЭТОТ ФАЙЛ. Функция
#: переехала туда, когда живое доказательство (`nansen/proofs/sentinel_live_proof.py`) упало на
#: `DB_BACKEND не задан`: считать ключ события — чистая арифметика, и тянуть за ней базу
#: означало, что путь «разобрать ответ площадки и собрать карточку» невозможен без базы вовсе.
from .detector import digest_key   # noqa: F401,E402  (реэкспорт ради прежних вызывающих)
