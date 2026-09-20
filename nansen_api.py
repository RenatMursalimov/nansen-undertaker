"""
nansen_api.py — интеграция с Nansen (on-chain smart money данные) для Гробовщика.

Два способа:
- Agent (fast/expert): вопрос на естественном языке -> ответ на основе on-chain данных (SSE-стрим).
- Smart Money endpoints: структурированные данные (netflow, holdings, dex-trades и т.д.).

ВАЖНО ПРО ДЕНЬГИ: agent/fast стоит 200 кредитов, а agent/expert - 750
(docs.nansen.ai/api/overview, снято 14.09.2026). Expert включается СЛОВАМИ человека
(«глубок», «детальн», «подробно разбери» - см. _EXPERT_TRIGGERS), то есть почти случайно, и
стоит он как четыре обычных вопроса. Кэшируем агрессивно, не дёргаем на каждый чих.
"""
import os
import json
import re
import time
import threading
import httpx

try:
    import env_load
    env_load.load()
except Exception:
    pass

# ТЕЛЕМЕТРИЯ ЖИВЁТ В ГОРЛОВИНАХ ЭТОГО ФАЙЛА, а не у двадцати вызывающих: врезка «по местам»
# уже была (`cost_tracker.track('nansen')` в ОДНОЙ точке из ~20), и поэтому все наши цифры
# расхода были занижены систематически. Новая точка вызова попадает в учёт САМА.
# Клиент обязан работать и без телеметрии, поэтому импорт под try, а заглушка молчалива.
try:
    import nansen_log as _tele
except Exception as _tele_err:                                   # pragma: no cover
    print('[nansen] телеметрия не поднялась: %s' % _tele_err)

    class _TeleStub(object):
        import contextlib as _c

        @_c.contextmanager
        def scene(self, name, uid=None):
            yield {}

        def clear(self):
            return {}

        def note(self, *a, **kw):
            return None

        def note_age(self, *a, **kw):
            return None

        def outcome(self):
            return None

        def age(self):
            return None

        def cache_only(self):
            return False

        def flight_begin(self):
            return (None, 1)

        def flight_end(self, *a, **kw):
            return None

        def record(self, *a, **kw):
            return None

        def sig_of(self, *a, **kw):
            return ''

        def credits_read(self):
            return {'remaining': None, 'used': None, 'ts': 0}

        def credits_write(self, *a, **kw):
            return None

    _tele = _TeleStub()

_BASE = "https://api.nansen.ai/api/v1"
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nansen_cache.json')
_CACHE_TTL = 1800  # 30 мин кэш на одинаковые запросы
# Reputation-screen делает пять независимых address-summary параллельно. Без lock два потока
# читали один старый JSON и последний save стирал записи остальных — кэш-хит зависел от гонки.
_CACHE_LOCK = threading.RLock()


def _key():
    return os.getenv('NANSEN_API_KEY') or os.getenv('NANSEN_KEY')


def _headers():
    return {"Content-Type": "application/json", "apikey": _key()}


# ── кэш ──────────────────────────────────────────────────────────────────────
def _load_cache():
    try:
        with open(_CACHE, encoding='utf-8') as f:
            return json.loads(f.read().strip() or '{}')
    except Exception:
        return {}


def _save_cache(d):
    try:
        with open(_CACHE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        print(f"[nansen] cache save: {e}")


def _cache_get(ckey, ttl=None):
    """Получить запись, соблюдая TTL конкретной записи, а не один глобальный.

    `ttl` вызывающего имеет приоритет; иначе используем TTL, сохранённый при записи; старые
    записи без поля мигрируют на обычные 30 минут. Это важно для истории: свеча прошлого дня
    не меняется, и обещанные 30 дней не должны превращаться в два часа после любой новой
    записи кэша.
    """
    with _CACHE_LOCK:
        d = _load_cache()
        row = d.get(ckey)
    effective = ttl or ((row or {}).get('ttl')) or _CACHE_TTL
    if row and time.time() - row.get('ts', 0) < effective:
        _tele.note_age(time.time() - row.get('ts', 0))
        return row.get('value')
    return None


def _cache_put(ckey, value, ttl=None):
    """Записать значение с его собственным TTL и чистить каждую запись по её TTL."""
    with _CACHE_LOCK:
        d = _load_cache()
        d[ckey] = {'ts': time.time(), 'ttl': int(ttl or _CACHE_TTL), 'value': value}
        now = time.time()
        # Раньше всё старше `_CACHE_TTL*4` (2 часа) удалялось безотносительно к своему TTL.
        # История обещала 6–720 часов, но следующая запись стирала её через два.
        d = {k: v for k, v in d.items()
             if now - float((v or {}).get('ts') or 0) <
             float((v or {}).get('ttl') or _CACHE_TTL)}
        _save_cache(d)


# ── Agent (SSE) ──────────────────────────────────────────────────────────────
def ask_agent(question, expert=False, use_cache=True, timeout=120, continue_conv=False):
    """Задаёт вопрос Nansen-агенту, собирает SSE-стрим в готовый текст.
    Возвращает (text, tools_used) или (None, error_str).

    continue_conv=True - продолжить последний разговор (`conversation_id` из события
    `finish`), чтобы агент помнил токен и сеть из предыдущего вопроса. Кэш при продолжении
    ОБХОДИТСЯ: тот же текст уточнения в другом разговоре означает другой ответ, и склеить их
    по ключу вопроса значило бы отдать человеку ответ про чужой токен."""
    if not _key():
        return None, "нет NANSEN_API_KEY"
    # Ключ по ХЭШУ ПОЛНОГО вопроса, а не по первым 120 символам. Обрезка склеивала запросы,
    # различающиеся только хвостом: например «…потоки по LIT. Отвечай ПО-РУССКИ» и та же
    # строка с «Answer in English» давали ОДИН ключ, и язык ответа зависел от того, кто
    # нажал кнопку первым. Префикс оставлен читаемым, чтобы кэш можно было смотреть глазами.
    import hashlib as _hl
    _qn = (question or "").strip()
    ckey = "agent:%s:%s:%s" % ('exp' if expert else 'fast', _qn.lower()[:60],
                               _hl.sha1(_qn.encode('utf-8')).hexdigest()[:10])
    _ep = 'agent/%s' % ('expert' if expert else 'fast')
    _conv = last_conversation() if continue_conv else None
    if _conv:
        use_cache = False          # продолжение разговора не кэшируется, см. докстринг
    if use_cache:
        cached = _cache_get(ckey)
        if cached is not None:
            _cache_hit(_ep, cached)
            return cached, ['cache']
    if not _key():
        _tele.note('nokey')
        return None, "нет NANSEN_API_KEY"
    url = f"{_BASE}/agent/{'expert' if expert else 'fast'}"
    text_parts = []
    tools = []
    # САМЫЙ ДОРОГОЙ ПУТЬ (~200 кредитов) ДО СЕГОДНЯ НЕ УЧИТЫВАЛСЯ ВООБЩЕ: `_note_credits`
    # звался только из `_post`/`_post_beta`, а сюда не заходил. Значит остаток, который бот
    # показывал владельцу, был систематически завышен, а в зачёт участнику самый дорогой его
    # вопрос давал ноль.
    _t0 = time.time()
    _fb = _tele.flight_begin() or (None, 1, 0)
    _rem_before, _parallel = _fb[0], _fb[1]
    _overlap_start = _fb[2] if len(_fb) > 2 else 0
    _http = 0
    try:
        _payload = {"text": question}
        if _conv:
            _payload["conversation_id"] = _conv
        with httpx.stream("POST", url, headers=_headers(),
                          json=_payload, timeout=timeout) as r:
            _http = r.status_code
            _note_credits(r.headers)
            if r.status_code != 200:
                body = r.read().decode('utf-8', 'ignore')[:200]
                _tele.note(_classify(r.status_code), r.status_code)
                _agent_tele(_ep, _t0, _http, False, False, _rem_before, _parallel,
                            _overlap_start, question)
                print("[nansen] %s HTTP %s: %s" % (_ep, r.status_code, body))
                return None, f"HTTP {r.status_code}: {body}"
            _tele.note_age(0)
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except Exception:
                    continue
                t = ev.get("type")
                if t == "delta":
                    text_parts.append(ev.get("text", ""))
                elif t == "tool_call":
                    nm = ev.get("name")
                    if nm and nm not in tools:
                        tools.append(nm)
                elif t == "finish":
                    # СОБЫТИЕ `finish` МЫ ДО СИХ ПОР ВЫБРАСЫВАЛИ, А В НЁМ ЛЕЖИТ
                    # `conversation_id` - ключ к продолжению разговора
                    # (docs.nansen.ai/api/agent). Без него КАЖДЫЙ уточняющий вопрос человека
                    # начинал новый разговор с нуля: агент не помнил ни токена, ни сети, и
                    # человек пересказывал контекст заново - за те же 200 кредитов.
                    # Особенно глупо это выглядело в Хабе, где бот САМ просит уточнить тикер.
                    _cid = ev.get("conversation_id")
                    if _cid:
                        _remember_conversation(_cid)
                elif t == "error":
                    _tele.note('http', _http)
                    _agent_tele(_ep, _t0, _http, False, False, _rem_before, _parallel,
                            _overlap_start, question)
                    return None, f"agent error: {ev.get('error')}"
        text = "".join(text_parts).strip()
        _tele.note('ok' if text else 'empty')
        _agent_tele(_ep, _t0, _http, bool(text), not text, _rem_before, _parallel,
                    _overlap_start, question)
        if not text and 'askUserQuestion' in str(tools):
            return None, "нужен уточняющий вопрос (агент не понял тикер/сеть)"
        if text and use_cache:
            _cache_put(ckey, text)
        return (text or None), tools
    except Exception as e:
        _tele.note('timeout' if isinstance(e, httpx.TimeoutException) else 'http', _http)
        _agent_tele(_ep, _t0, _http, False, False, _rem_before, _parallel,
                            _overlap_start, question)
        print("[nansen] %s: %s" % (_ep, e))
        return None, f"exception: {e}"


def _agent_tele(ep, t0, http, ok, empty, rem_before, parallel, overlap_start, question):
    """Строка телеметрии для Agent. Отдельной функцией, потому что у `ask_agent` три выхода
    (ошибка HTTP, событие error, обычный конец), и врезка «по местам» уже один раз стоила
    нам всего учёта: пропущенный выход = потерянные 200 кредитов в отчёте."""
    _rem = _CREDITS.get('remaining')
    _rem = _rem if isinstance(_rem, int) else None
    overlap_end = _tele.flight_end(_rem)
    _tele.record(ep, ms=int((time.time() - t0) * 1000), http=http, ok=ok, empty=empty,
                 cache=False, rem=_rem, used=_CREDITS.get('used'),
                 rem_before=rem_before, parallel=parallel,
                 overlap=(overlap_end != overlap_start),
                 sig=_tele.sig_of(ep, {'text': question}))


#: ПОСЛЕДНИЙ РАЗГОВОР С АГЕНТОМ — ПО КЛЮЧУ ЧЕЛОВЕКА И ТОЛЬКО В ПАМЯТИ ПРОЦЕССА.
#:
#: Раньше слот был ОДИН на процесс. Последовательность «A спросил → B спросил → A уточнил»
#: продолжала разговор B и могла отдать A ответ про чужой токен/контекст. Это не просто UX:
#: cross-user context mix-up — утечка смысла чужого вопроса. Хранить на диске не нужно и
#: нельзя; uid уже есть в коробке телеметрии, а через 10 минут запись протухает.
_LAST_CONV = {}                 # key(uid) -> {'id': str, 'ts': float}
_CONV_TTL = 600                # 10 минут: уточняют сразу, а не через час


def _conversation_key():
    """Ключ текущего человека из коробки сцены. -> str | None.

    Без uid продолжение ОТКЛЮЧЕНО: глобальный fallback снова склеил бы двух людей. Фоновые
    вызовы и CLI начинают новый разговор — это безопаснее, чем продолжить чужой.
    """
    try:
        uid = (_tele.box() or {}).get('uid')
    except Exception:
        uid = None
    return ('u:%s' % uid) if uid not in (None, '') else None


def _remember_conversation(conversation_id):
    """Запомнить id для текущего uid в памяти процесса. Ничего не пишет на диск."""
    key = _conversation_key()
    if key and conversation_id:
        _LAST_CONV[key] = {'id': str(conversation_id), 'ts': time.time()}
        # Чистим протухшее при записи: словарь не растёт за каждым пользователем навсегда.
        now = time.time()
        for k, row in list(_LAST_CONV.items()):
            if now - float((row or {}).get('ts') or 0) > _CONV_TTL:
                _LAST_CONV.pop(k, None)


def last_conversation(max_age=None):
    """id последнего разговора ТЕКУЩЕГО человека, если ещё свеж. -> str | None."""
    key = _conversation_key()
    row = _LAST_CONV.get(key) if key else None
    if not row or not row.get('id'):
        return None
    if time.time() - float(row.get('ts') or 0) > (max_age or _CONV_TTL):
        _LAST_CONV.pop(key, None)
        return None
    return row['id']


# ── Smart Money (структурированные) ──────────────────────────────────────────
def smart_money_netflow(chains=None, timeframe="24h", only_smart_money=True, per_page=20, direction="DESC"):
    """Топ токенов по чистому притоку smart money. Возвращает список dict или None.

    САМЫЙ ЧАСТЫЙ ПУТЬ (дайджест, твиты, тренды, меню, паспорт), и он тоже не звал
    `_note_credits`. Теперь ходит через ту же горловину `_http_post`, что и остальные:
    остаток, телеметрия и класс отказа считаются в одном месте на всех."""
    if not _key():
        _tele.note('nokey')
        return None
    chains = chains or ["ethereum", "solana", "base"]
    ckey = f"netflow:{','.join(chains)}:{timeframe}:{direction}:{per_page}"
    cached = _cache_get(ckey)
    if cached is not None:
        _cache_hit("token-screener", cached)
        return cached
    body = {
        "chains": chains, "timeframe": timeframe,
        "filters": {"only_smart_money": only_smart_money},
        "order_by": [{"field": "netflow", "direction": direction}],
        "pagination": {"page": 1, "per_page": per_page},
    }
    data, http = _http_post(_BASE, "token-screener", body, 60, "")
    if http != 200 or data is None:
        return None
    rows = data if isinstance(data, list) else data.get("data") or data.get("result") or []
    _cache_put(ckey, rows)
    return rows


# Остаток кредитов приходит В ЗАГОЛОВКАХ ЛЮБОГО ответа, поэтому отдельный запрос за ним
# не нужен. Раньше credits_left() дёргал agent/fast со словом «hi» — то есть проверка
# баланса стоила ~200 кредитов и сама же его уменьшала.
_CREDITS = {'remaining': None, 'used': None, 'ts': 0}
_CREDITS_LOCK = threading.RLock()


def _note_credits(hdr):
    """Запомнить остаток кредитов из заголовков ответа. Бесплатно.

    ОСТАТОК ПЕРЕЖИВАЕТ РЕСТАРТ. Раньше он жил только в памяти процесса: рестарт бота терял
    знание об остатке, и до первого структурного запроса `credits_left()` не знал ничего, а
    владельцу в отчёте не показывалось вообще ничего."""
    try:
        low = dict((k.lower(), v) for k, v in dict(hdr).items())
    except Exception:
        return
    rem = low.get('x-nansen-credits-remaining')
    if rem is None:
        return
    with _CREDITS_LOCK:
        try:
            _CREDITS['remaining'] = int(float(rem))
        except (TypeError, ValueError):
            _CREDITS['remaining'] = rem
        used = low.get('x-nansen-credits-used')
        if used is not None:
            try:
                _CREDITS['used'] = int(float(used))
            except (TypeError, ValueError):
                _CREDITS['used'] = used
        _CREDITS['ts'] = time.time()
        # Один snapshot под lock: параллельные responses не смешивают remaining одного с
        # used другого и не пишут полусобранный JSON.
        _tele.credits_write(_CREDITS['remaining'], _CREDITS['used'])


def credits_left(force=False):
    """Остаток кредитов. -> int | str | None. По умолчанию БЕСПЛАТНО, из заголовков
    последнего ответа. force=True — сделать самый дешёвый реальный запрос, если мы ещё
    ни одного ответа не видели."""
    if _CREDITS['remaining'] is not None:
        return _CREDITS['remaining']
    # ХОЛОДНЫЙ СТАРТ: читаем то, что запомнили ДО рестарта, и говорим, насколько оно старое
    # (звать площадку ради этого не надо — заголовок приезжает с любым ответом).
    _saved = _tele.credits_read() or {}
    if _saved.get('remaining') is not None:
        _CREDITS['remaining'] = _saved.get('remaining')
        _CREDITS['used'] = _saved.get('used')
        _CREDITS['ts'] = _saved.get('ts') or 0
        return _CREDITS['remaining']
    if not force or not _key():
        return None
    try:
        r = httpx.post("%s/smart-money/netflow" % _BASE, headers=_headers(),
                       json={"chains": ["ethereum"], "filters": {"include_stablecoins": False},
                             "pagination": {"page": 1, "per_page": 1},
                             "order_by": [{"field": "net_flow_24h_usd", "direction": "DESC"}]},
                       timeout=30)
        _note_credits(r.headers)
    except Exception:
        return None
    return _CREDITS['remaining']


# ═══════════════════════════════════════════════════════════════════════════
# ИСТОЧНИК НАЗЫВАЕТСЯ, И ОТКАЗ НАЗЫВАЕТ ПРИЧИНУ (ТЗ B, пункты B0 и B1)
#
# B0. РАНЬШЕ ИСТОЧНИК ПРЯТАЛСЯ НАМЕРЕННО: три места в промптах требовали «не упоминай слово
# Nansen, подай как свою блокчейн-разведку». Для Nansen это правило снято УЗКО - именно для
# него и только для него: запрет называть прочих поставщиков (медиасервер, распознавание
# речи, аналитику, модели) остаётся как был, он живёт своей строкой в общем промпте.
#
# B1. ЧЕТЫРЕ СОСТОЯНИЯ РАЗНЫМИ СЛОВАМИ. «Данных нет» и «мы не смогли спросить» - разные
# миры, и человек обязан их различать. Отсутствие метки это отсутствие метки, а не
# безопасность: ни один текст ниже не имеет права читаться как «адрес чистый».
# ═══════════════════════════════════════════════════════════════════════════

#: правило для промптов, которым модель пересказывает данные Nansen. ОДНА СТРОКА НА ВСЕ ТРИ
#: МЕСТА (дайджест RU, дайджест EN, Хаб): копия разошлась бы на первой правке, и источник
#: снова исчез бы в одном из них молча.
SOURCE_RULE = {
    'ru': ('ИСТОЧНИК НАЗЫВАЙ ЯВНО: эти данные дал Nansen, и в тексте обязана быть фраза '
           '«по данным Nansen». Никаких ДРУГИХ поставщиков данных, моделей, сервисов и '
           'нашей технической кухни не упоминай вовсе - только Nansen.'),
    'en': ('NAME THE SOURCE EXPLICITLY: this data comes from Nansen, and the text must '
           'contain the words "data by Nansen". Do not name any OTHER data provider, model '
           'or internal service - only Nansen.'),
}

_SRC_MARK = '📡'          # признак того, что подпись источника уже стоит (идемпотентность)


def freshness(lang='ru', age_sec=None):
    """Словами: насколько свежи данные. -> str.

    Возраст берётся ИЗ ФАКТА - времени сетевого ответа или возраста записи кэша
    (`nansen_log.note_age`), а не из головы. Не замерен - так и сказано: выдуманная свежесть
    хуже её отсутствия (закон №22)."""
    if age_sec is None:
        age_sec = _tele.age()
    if age_sec is None:
        return 'свежесть не замерена' if lang != 'en' else 'freshness not measured'
    try:
        age_sec = float(age_sec)
    except (TypeError, ValueError):
        return 'свежесть не замерена' if lang != 'en' else 'freshness not measured'
    if age_sec < 60:
        return 'данные только что' if lang != 'en' else 'data just now'
    mins = int(age_sec // 60)
    if mins < 60:
        return ('данные на %d мин назад' % mins) if lang != 'en' else ('data %d min old' % mins)
    hrs = mins // 60
    return ('данные на %d ч назад' % hrs) if lang != 'en' else ('data %d h old' % hrs)


def source_note(lang='ru', age_sec=None):
    """Подпись под ответом: источник плюс свежесть. -> str."""
    if lang == 'en':
        return '%s Source: Nansen, %s' % (_SRC_MARK, freshness('en', age_sec))
    return '%s Источник: Nansen, %s' % (_SRC_MARK, freshness('ru', age_sec))


def with_source(text, lang='ru', age_sec=None):
    """Дописать подпись источника к готовому блоку. Идемпотентно. -> str | None.

    Стоит В ФОРМАТТЕРАХ, а не у двадцати вызывающих: подпись, которую надо не забыть
    приписать, однажды забудут - и ровно в том месте, где данные Nansen видны сильнее всего."""
    if not text:
        return text
    if _SRC_MARK in text:
        return text
    return '%s\n\n<i>%s</i>' % (text, source_note(lang, age_sec))


def ensure_attribution(text, lang='ru', age_sec=None):
    """ВЫХОДНОЙ РУБЕЖ для текстов, которые пересказывает модель. -> str.

    Правило в промпте необходимо, но недостаточно: модель может его проигнорировать, и
    проверять надо РЕЗУЛЬТАТ, а не факт того, что мы попросили (закон №52). Если имени
    Nansen в ответе нет - подпись приезжает кодом, и это видно в логе."""
    if not text:
        return text
    if _SRC_MARK in text:
        return text
    if 'nansen' not in str(text).lower():
        print('[nansen] атрибуция: модель не назвала источник, подпись дописана кодом')
    return '%s\n\n%s' % (text, source_note(lang, age_sec))


#: ЧТО ИМЕННО НЕ НАЙДЕНО - слот, а не общая фраза: «меток по этому адресу» и «данных по
#: этому токену» лечатся по-разному, и склеивать их значит уводить человека от причины.
#: Подставляется в РОДИТЕЛЬНОМ падеже («меток по этому адресу»), потому что во всех шести
#: шаблонах слот стоит после отрицания - иначе тексты пришлось бы согласовывать по одному.
_REFUSAL = {
    'nokey': {
        'ru': ('🔌 Nansen: ключ не задан (NANSEN_API_KEY), поэтому {what} мы не запрашивали '
               'вовсе. Это наша настройка, а не результат проверки.'),
        'en': ('🔌 Nansen: the API key is not set, so we never asked for {what}. This is our '
               'configuration, not a verdict.')},
    'nocredits': {
        'ru': ('💳 Кредиты Nansen кончились (402): {what} мы НЕ получили. Это отказ оплаты, '
               'а не результат проверки. Владелец пополняет баланс, и запрос повторится.'),
        'en': ('💳 Nansen credits are exhausted (402): we did NOT get {what}. This is a '
               'billing refusal, not a verdict. Retry after the balance is topped up.')},
    'ratelimit': {
        'ru': ('⏳ Nansen придержал нас по частоте запросов (429): {what} мы НЕ получили. '
               'Повтори через минуту - пока мы ничего не знаем.'),
        'en': ('⏳ Nansen rate-limited us (429): we did NOT get {what}. Retry in a minute - '
               'so far we know nothing.')},
    'timeout': {
        'ru': ('⌛ Nansen не ответил вовремя (таймаут): {what} мы НЕ получили. Это наш отказ, '
               'а не результат проверки.'),
        'en': ('⌛ Nansen did not answer in time (timeout): we did NOT get {what}. This is our '
               'failure, not a verdict.')},
    'http': {
        'ru': ('⚠️ Nansen ответил ошибкой: {what} мы НЕ получили. Это отказ площадки, а не '
               'результат проверки; код ответа в логе бота.'),
        'en': ('⚠️ Nansen replied with an error: we did NOT get {what}. This is a provider '
               'failure, not a verdict; the status code is in the bot log.')},
    'badreq': {
        'ru': ('🛠 Nansen НЕ ПРИНЯЛ наш запрос (400/422): {what} мы не получили, и виноват '
               'запрос, а не площадка и не этот адрес. Это наш баг, он в логе бота с телом '
               'запроса; данных по адресу это не говорит НИЧЕГО.'),
        'en': ('🛠 Nansen REJECTED our request (400/422): we did not get {what}, and the '
               'request is at fault - not the provider and not this address. This is our bug, '
               'logged with the request body; it says NOTHING about the address.')},
    'empty': {
        'ru': ('🔍 Nansen ответил, но {what} у него нет. Это НЕ значит «чисто»: отсутствие '
               'метки - это отсутствие метки, а не безопасность. У свежих адресов и '
               'листингов покрытие появляется не сразу.'),
        'en': ('🔍 Nansen answered, but has no {what}. This does NOT mean "clean": a missing '
               'label is a missing label, not safety. Fresh addresses and listings get '
               'covered later.')},
    # ═══ ВОСЬМОЙ КЛАСС, И ОН ПОЯВИЛСЯ ИЗ ЖИВОЙ ПРОБЫ 19.09 ═══
    # Площадка ответила 422, но сказала не «схема не та», а СОДЕРЖАТЕЛЬНОЕ: «токен на base -
    # стейблкоин, эндпоинт потоков стейблкоины не поддерживает». Это ни одно из семи прежних
    # состояний: запрос верный (значит не badreq), данные существуют (значит не empty), и
    # площадка работает (значит не http). Это ГРАНИЦА ПОКРЫТИЯ, названная самой площадкой.
    #
    # Сваливать её в badreq было бы вдвойне неверно: человек читал бы «наш баг, смотри лог»
    # там, где чинить нечего, а мы бы неделю искали ошибку в теле запроса, которой нет.
    # А сваливать в empty - тот самый запрет: «потоков нет» прочиталось бы как свойство
    # токена, хотя на деле эндпоинт просто не про эти токены.
    'unsupported': {
        'ru': ('🚧 У Nansen нет {what} для этого актива: эндпоинт его не покрывает (так и '
               'ответил). Это не пустота и не наша ошибка - это граница покрытия. Причина '
               'из ответа площадки в логе бота.'),
        'en': ('🚧 Nansen does not cover {what} for this asset: the endpoint said so itself. '
               'This is neither emptiness nor our bug - it is a coverage boundary. The '
               "provider's own reason is in the bot log.")},
}

#: во что подставляется {what} по умолчанию (родительный падеж)
_WHAT = {'ru': 'данных', 'en': 'the data'}


def refusal(reason, lang='ru', what=None):
    """Отказ ЧЕЛОВЕКУ, называющий причину. -> str.

    reason: 'nokey' | 'nocredits' | 'ratelimit' | 'timeout' | 'badreq' | 'http' | 'empty' |
    'unsupported' | None.
    None означает «вызовов не было вовсе» - и это тоже наш отказ, а не пустота у Nansen."""
    lang = 'en' if lang == 'en' else 'ru'
    if reason is None:
        return ('⚠️ До Nansen дело не дошло: запрос не ушёл. Это наш отказ, данных нет.'
                if lang == 'ru' else
                '⚠️ We never reached Nansen: the request did not go out. This is our failure.')
    row = _REFUSAL.get(reason) or _REFUSAL['http']
    return row[lang].replace('{what}', what or _WHAT[lang])


#: как называются части, из которых собран блок - для строки «что не приехало»
_EP_HUMAN = {
    'profiler/address/labels': ('метки', 'labels'),
    'profiler/address/premium-labels': ('премиум-метки', 'premium labels'),
    'profiler/address/pnl-summary': ('PnL и winrate', 'PnL and winrate'),
    'profiler/address/related-wallets': ('связанные кошельки', 'related wallets'),
    'profiler/address/counterparties': ('контрагенты', 'counterparties'),
    'profiler/address/current-balance': ('портфель', 'portfolio'),
    'tgm/flow-intelligence': ('потоки по сегментам', 'segment flows'),
    'tgm/indicators': ('Nansen Score', 'Nansen Score'),
    'tgm/holders': ('метки топ-холдеров', 'top holder labels'),
    'tgm/pnl-leaderboard': ('топ по PnL', 'top PnL'),
    'tgm/who-bought-sold': ('сделки', 'trades'),
    'tgm/token-information': ('справка по токену', 'token information'),
}


def missing_note(lang='ru', total=None):
    """Строка «что не приехало» для ЧАСТИЧНОГО блока. -> str | '' (если приехало всё).

    ЗАЧЕМ ЭТО ОТДЕЛЬНАЯ СТРОКА, А НЕ ОТКАЗ. Блок из трёх-четырёх запросов, где часть упала,
    возвращается НЕПУСТЫМ и потому проходит как успех - reason='ok', отказ не показывается.
    Это тот же сторож пустоты, что и исчезающий блок Nansen в карточке токена, только в
    более коварной форме: экран выглядит целым, и человек читает отсутствие меток как их
    отсутствие у адреса, а не как наш непрошедший запрос."""
    f = _tele.fails()
    if not f:
        return ''
    seen, parts, codes = set(), [], set()
    for ep, code, _cls in f:
        nm = _EP_HUMAN.get(str(ep).strip('/'))
        nm = (nm[1] if lang == 'en' else nm[0]) if nm else str(ep).strip('/')
        if nm not in seen:
            seen.add(nm)
            parts.append(nm)
        if code:
            codes.add(code)
    _tail = (' (код %s)' % ', '.join(str(c) for c in sorted(codes))) if codes else ''
    _all = (' из %s' % total) if total else ''
    if lang == 'en':
        return ('⚠️ <i>NOT delivered%s: %s%s. This is our failed request, not a property of '
                'the address.</i>' % (_all, ', '.join(parts), _tail))
    return ('⚠️ <i>НЕ приехало%s: %s%s. Это наш непрошедший запрос, а не свойство адреса.</i>'
            % (_all, ', '.join(parts), _tail))


def fail_reason(default='empty'):
    """Причина последнего отказа из коробки вызова. -> str.

    Собирается в горловинах (`_http_post`, `ask_agent`), поэтому одинаково работает и для
    структурных запросов, и для агента, и для блока из четырёх вызовов.

    'ok' ОТСЮДА НЕ ВЫХОДИТ, И ЭТО НЕ КОСМЕТИКА. Зовут эту функцию ровно тогда, когда
    показывать человеку НЕЧЕГО. Ответ 200 с непонятной нам формой (схема сменилась, поле
    переехало) дал бы `outcome()=='ok'` - и человек получил бы текст «всё в порядке» вместо
    отказа, то есть тот же сторож пустоты с другой стороны. Площадка ответила, а того, что
    мы просили, в ответе нет - это `empty`, и так и говорим."""
    o = _tele.outcome()
    return default if o in (None, 'ok') else o


def data_age():
    """Возраст данных текущего ответа в секундах или None. -> float | None."""
    return _tele.age()


# ── детектор Nansen-запроса в чате ────────────────────────────────────────────
_NANSEN_TRIGGERS = [
    'smart money', 'умные деньги', 'умных денег', 'nansen', 'нансен',
    'что набирают', 'что накапливают', 'что покупают', 'что заносят', 'кто заносит',
    'on-chain', 'ончейн', 'он-чейн', 'netflow', 'нетфлоу', 'приток', 'оттоки', 'притоки',
    'киты покупают', 'китов', 'китовы', 'умные кошельки', 'смарт мани', 'смартмани',
    'что копят', 'кто накапливает', 'фонды покупают', 'куда течёт', 'куда течет',
]
_EXPERT_TRIGGERS = ['глубок', 'подробно разбери', 'детальн', 'expert', 'экспертн', 'глубже копни']


def wants_nansen(text):
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in _NANSEN_TRIGGERS)


def is_expert_request(text):
    t = (text or '').lower()
    return any(k in t for k in _EXPERT_TRIGGERS)


def build_nansen_question(text):
    """Готовит вопрос для агента из сообщения юзера (чистит обращения к боту)."""
    import re
    t = re.sub(r'(гроб\w*|undertaker|@\w+)[,\s]*', '', text, flags=re.IGNORECASE)
    return t.strip(' ,.:!?') or text.strip()


def with_lang(q, lang='ru'):
    """Дописать к вопросу требование языка ответа. -> str.

    Агент Nansen — внешняя модель, и по умолчанию она отвечает по-английски, даже когда
    у человека русский интерфейс. Просим явно. Инструкция идёт В ТЕКСТ ВОПРОСА сознательно:
    ключ кэша ask_agent строится из вопроса, поэтому русский и английский ответы попадают
    в РАЗНЫЕ записи кэша. Отдельным параметром они бы склеились в одну, и язык ответа стал
    бы делом того, кто нажал кнопку первым.
    """
    q = (q or "").strip()
    if (lang or 'ru') == 'ru':
        return q + ". Отвечай ПО-РУССКИ, целиком, включая заголовки и пояснения."
    return q + ". Answer in English."


def enrich_question(q):
    """Дообогащает вопрос для Nansen-агента, чтобы он не переспрашивал:
    добавляет крипто-контекст, если вопрос короткий/про тикер."""
    ql = q.lower()
    hints = []
    # если есть заглавный тикер 2-6 букв - помечаем как токен
    import re
    tickers = re.findall(r'\b[A-Z]{2,6}\b', q)
    if tickers and 'token' not in ql and 'токен' not in ql:
        hints.append(f"({', '.join(tickers)} are crypto tokens)")
    if 'smart money' not in ql and ('делает' in ql or 'по ' in ql or 'что с' in ql):
        hints.append("Focus on smart money on-chain activity: netflows, holdings, recent trades")
    extra = " ".join(hints)
    return (q + ". " + extra + " Answer directly using available on-chain data; if a token is ambiguous, pick the most traded one and state which.").strip()



# ═══════════════════════════════════════════════════════════════════════════
# СТРУКТУРНЫЙ СЛОЙ Nansen API v1 (дёшево: 1-25 кредитов против 200-750 у Agent).
# Все эндпоинты — POST JSON, заголовок apikey. Парсим ЗАЩИТНО: любой сбой -> None/[],
# карточки от этого не падают. Схемы сверены с docs.nansen.ai (окт-2025).
# ВАЖНО про premium_labels: True = премиум-метки (Smart Money/Fund) = 150 кредитов/вызов
# и платный план. По умолчанию False (free-tier метки, обычная цена).
# ═══════════════════════════════════════════════════════════════════════════
import datetime as _dt

# Слуги сетей у Nansen обычно совпадают с нашими (ethereum/solana/base/arbitrum/…).
# Если для какой-то сети слуг отличается — добавить сюда (проверить живым ключом).
_NANSEN_CHAIN = {}


def _nc(chain):
    return _NANSEN_CHAIN.get((chain or "").lower(), (chain or "").lower())


def _date_range(days=7):
    to = _dt.datetime.utcnow()
    frm = to - _dt.timedelta(days=days)
    return {"from": frm.strftime("%Y-%m-%dT00:00:00Z"),
            "to": to.strftime("%Y-%m-%dT23:59:59Z")}


def _post(path, body, ckey=None, timeout=60):
    """Общий POST к Nansen. -> распарсенный JSON (dict) или None. Кэш по ckey.

    Возврат остался прежним (JSON | None), потому что его читают двадцать мест. НО ПРИЧИНА
    ОТКАЗА БОЛЬШЕ НЕ ТЕРЯЕТСЯ: она уезжает в коробку вызова (`nansen_log`), и верхний слой
    берёт её `nansen_log.outcome()`. Раньше `None` от 402, 429, 500 и «данных правда нет»
    были неразличимы, `_rows(None)` давал `[]`, и пустота выглядела как чистота."""
    if not _key():
        _tele.note('nokey')
        return None
    if ckey:
        c = _cache_get(ckey)
        if c is not None:
            _cache_hit(path, c)
            return c
    j, http = _http_post(_BASE, path, body, timeout, "")
    if j is not None and ckey:
        _cache_put(ckey, j)
    return j


# ═══════════════════════════════════════════════════════════════════════════════
# РЕМОНТ ЗАПРОСА ПО СЛОВАМ ПЛОЩАДКИ (а не по нашей четвёртой догадке)
#
# ЗАЧЕМ ЭТО ВООБЩЕ. У части эндпоинтов схема тела живым ключом НЕ СНЯТА: она написана по
# образцу соседей. Живой прогон 15.09: «перп позиции BTC» -> 422 на `tgm/perp-positions`.
# Обычный путь починки - угадать имя поля, попросить Ren прогнать, посмотреть, повторить.
# Три круга по живому прогону на каждый эндпоинт.
#
# ПРИ ЭТОМ NANSEN САМ ГОВОРИТ, ЧТО НЕ ТАК, и говорит машиночитаемо (снято 14.09):
#   {"error":"Unknown field","message":"Field 'side' is not recognized"}
#   {"error":"Missing field","message":"Required field 'body -> date' is missing"}
#   {"error":"Invalid value","message":"Invalid value 'buy' for body -> buy_or_sell.
#                                       Did you mean 'BUY'?"}
# Это инструкция, а не жалоба. Ниже она исполняется: неизвестное поле убираем, названное
# значение подставляем, отсутствующее обязательное - ТОЛЬКО из списка тех, что мы правда
# умеем построить (окно даты, страница). Чего не умеем - НЕ ВЫДУМЫВАЕМ: круг кончается,
# причина уходит человеку словами.
#
# ГРАНИЦЫ, ЧТОБЫ ЭТО НЕ СТАЛО МАШИНОЙ ДОГАДОК:
#  * потолок кругов (`_FIX_ROUNDS`) - иначе на кривом эндпоинте это молотит кредиты;
#  * ремонт зовут ТОЛЬКО функции с неснятой схемой, остальные ходят прежним `_post`;
#  * каждая правка печатается в лог с именем поля и итоговым телом - чтобы схему можно
#    было ПРИШПИЛИТЬ в коде и ремонт выключить. Ремонт - это лечение симптома, а
#    снятая схема - причины; лог превращает первое во второе за один круг.
# ═══════════════════════════════════════════════════════════════════════════════
_FIX_ROUNDS = 3
#: обязательные поля, которые мы умеем построить САМИ, ничего не выдумывая
_FIX_DEFAULTS = {
    'date': lambda: _date_range(7),
    'pagination': lambda: {'page': 1, 'per_page': 20},
    'order_by': lambda: [],
}
_RE_UNKNOWN = re.compile(r"Field '([^']+)' is not recognized", re.I)
_RE_MISSING = re.compile(r"Required field '([^']+)' is missing", re.I)
_RE_SUGGEST = re.compile(r"Invalid value '([^']*)' for ([^.]+)\.\s*Did you mean '([^']*)'", re.I)
#: последний текст ошибки площадки: нужен ремонту и диагностике (тело уже в логе)
_LAST_ERR = {'path': None, 'text': ''}


def last_error():
    """Текст последней ошибки площадки. -> dict {'path','text'}. Для проб и отчётов."""
    return dict(_LAST_ERR)


def _field_tail(spec):
    """'body -> pagination -> page' -> 'page'. Площадка называет путь, нам нужно имя."""
    return str(spec).replace('`', '').split('->')[-1].strip().strip("'\"")


def _apply_hint(body, text):
    """Одна правка тела по тексту ошибки. -> (новое тело, что сделали) | (None, причина).

    Тело НЕ мутируем: копия, иначе кэш-ключ и повтор запроса поехали бы вместе с ним.
    """
    b = dict(body or {})
    m = _RE_UNKNOWN.search(text or '')
    if m:
        k = _field_tail(m.group(1))
        if k in b:
            b.pop(k, None)
            return b, 'убрал поле %r (площадка его не знает)' % k
        return None, 'площадка не знает поле %r, но его нет и в теле' % k
    m = _RE_MISSING.search(text or '')
    if m:
        k = _field_tail(m.group(1))
        mk = _FIX_DEFAULTS.get(k)
        if mk is None:
            return None, 'нужно обязательное поле %r, а построить его нам нечем' % k
        b[k] = mk()
        return b, 'подставил обязательное поле %r' % k
    m = _RE_SUGGEST.search(text or '')
    if m:
        bad, spec, good = m.group(1), _field_tail(m.group(2)), m.group(3)
        for k, v in list(b.items()):
            if k == spec or (isinstance(v, str) and v == bad):
                b[k] = good
                return b, 'значение %r -> %r в поле %r' % (bad, good, k)
        b[spec] = good
        return b, 'поставил %r=%r по подсказке площадки' % (spec, good)
    return None, 'в тексте ошибки нет исполнимой инструкции'


#: ЧТО ЗАПОМНИЛИ О СХЕМАХ. Не тело целиком, а РАЗНИЦА ФОРМЫ: какие поля площадка не знает
#: и какие требует. Тело нельзя: в нём аргументы («token»: «BTC»), и запомнив его, мы
#: спрашивали бы BTC на запрос про ETH. Имена полей - не чьи-то данные, в файле нет ни
#: адреса, ни ключа.
SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nansen_schema.json')
_SCHEMA = None


def _schema_load():
    global _SCHEMA
    if _SCHEMA is None:
        try:
            with open(SCHEMA_FILE, encoding='utf-8') as fh:
                _SCHEMA = json.load(fh) or {}
        except (OSError, ValueError):
            _SCHEMA = {}
    return _SCHEMA


def _schema_apply(path, body):
    """Наложить ВЫУЧЕННУЮ разницу формы на тело. -> тело (копия)."""
    memo = _schema_load().get(path) or {}
    b = dict(body or {})
    for k in memo.get('drop') or []:
        b.pop(k, None)
    for k in memo.get('add') or []:
        if k not in b and k in _FIX_DEFAULTS:
            b[k] = _FIX_DEFAULTS[k]()
    return b


def _schema_learn(path, before, after):
    """Запомнить разницу формы после удачного ремонта. Тихо: сбой записи не рушит ответ."""
    drop = sorted(k for k in before if k not in after)
    add = sorted(k for k in after if k not in before and k in _FIX_DEFAULTS)
    if not drop and not add:
        return
    memo = _schema_load()
    cur = memo.get(path) or {}
    if cur.get('drop') == drop and cur.get('add') == add:
        return
    memo[path] = {'drop': drop, 'add': add, 'learned': int(time.time())}
    try:
        with open(SCHEMA_FILE, 'w', encoding='utf-8') as fh:
            json.dump(memo, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError as e:
        print('[nansen] схему %s запомнить не удалось: %s' % (path, e))


def _post_fix(path, body, ckey=None, timeout=60):
    """POST к эндпоинту с НЕСНЯТОЙ схемой: при 400/422 правим тело по словам площадки.
    -> распарсенный JSON | None. Кэш и телеметрия - те же, что у `_post`."""
    if not _key():
        _tele.note('nokey')
        return None
    if ckey:
        c = _cache_get(ckey)
        if c is not None:
            _cache_hit(path, c)
            return c
    # ВЫУЧЕННОЕ ПРИМЕНЯЕМ ДО ПЕРВОЙ ПОПЫТКИ. Иначе каждый рестарт бота начинал бы ремонт
    # заново: три отвергнутых запроса на каждый эндпоинт с неснятой схемой, и человек
    # ждёт лишние секунды ровно за то, что уже один раз выяснили.
    # СРАВНИВАЕМ С ИСХОДНЫМ ТЕЛОМ, А НЕ С УЖЕ ПОПРАВЛЕННЫМ: иначе вторая выученная правка
    # затирала бы первую (в памятке осталась бы только последняя разница, и ремонт начинался
    # бы заново с середины пути).
    _b0 = dict(body or {})
    b = _schema_apply(path, body)
    for rnd in range(_FIX_ROUNDS + 1):
        j, http = _http_post(_BASE, path, b, timeout, "")
        if http == 200:
            if rnd:
                # СХЕМА СНЯТА ЖИВЬЁМ - ЭТО САМАЯ ЦЕННАЯ СТРОКА В ЛОГЕ. По ней тело
                # пришпиливается в код, и ремонт на этом эндпоинте больше не нужен.
                print('[nansen] %s: СХЕМА СНЯТА за %d правк(и). Рабочее тело: %s'
                      % (path, rnd, json.dumps(b, ensure_ascii=False)[:400]))
                _schema_learn(path, _b0, b)
            if j is not None and ckey:
                _cache_put(ckey, j)
            return j
        if _classify(http) != 'badreq' or rnd >= _FIX_ROUNDS:
            return None
        nb, why = _apply_hint(b, _LAST_ERR.get('text') or '')
        # ГРАНИЦА ПОКРЫТИЯ РЕМОНТУ НЕ ПОДЛЕЖИТ. Проверка выше пропускает сюда только
        # 'badreq', так что этот случай уже отсечён классификатором - но проверка стоит
        # рядом с ремонтом нарочно: правило «чинить можно только схему» должно быть видно
        # там, где чинят, а не только там, где классифицируют.
        if nb is None:
            print('[nansen] %s: ремонт остановлен - %s' % (path, why))
            return None
        print('[nansen] %s: правка %d - %s' % (path, rnd + 1, why))
        b = nb
    return None


#: ФРАЗЫ, КОТОРЫМИ ПЛОЩАДКА ГОВОРИТ «ЭТОГО Я НЕ УМЕЮ» вместо «ты прислал не то».
#: Снято с живого ответа 19.09: `{"code":"invalid_field_value","message":"Token 0x… on base is
#: a stablecoin. The TGM flows endpoint does not support stablecoins."}`.
#: Ведём по ФРАЗЕ, а не по коду `invalid_field_value`: тем же кодом площадка отвечает и на
#: настоящую ошибку значения (её чинит ремонт тела), а различает их именно текст.
_UNSUPPORTED_MARKS = ('does not support', 'not supported', 'unsupported')


def _classify(status, text=''):
    """HTTP-код (+ текст ответа) -> класс отказа. Состояния разводятся ИМЕННО ЗДЕСЬ, один раз.

    `text` понадобился, когда выяснилось, что ОДНИМ кодом 422 площадка отвечает на две
    совершенно разные вещи: «схема тела не та» (наш баг, чинится ремонтом) и «этот актив
    эндпоинт не покрывает» (граница покрытия, чинить нечего). Без текста они неразличимы, и
    человек читал бы «наш баг, смотри лог» там, где в логе искать нечего.
    """
    if status == 402:
        return 'nocredits'          # кредиты кончились
    if status == 429:
        return 'ratelimit'          # придержали по частоте
    if status in (400, 422) and any(m in str(text).lower() for m in _UNSUPPORTED_MARKS):
        return 'unsupported'        # площадка сказала: этого актива у эндпоинта нет вовсе
    if status in (400, 422):
        # НАШ ЗАПРОС НЕ ПРИНЯТ, И ЭТО НЕ ОТКАЗ ПЛОЩАДКИ. 422 адресован НАМ: схема тела не
        # та, поле переехало, значение невалидно. Живой прогон 14.09 дал ровно это - два из
        # трёх запросов профиля кошелька вернули 422, - и текст «Nansen ответил ошибкой»
        # сваливал вину на площадку, увода от единственного места, где это чинится: у нас.
        return 'badreq'
    return 'http'                   # прочая ошибка площадки


def _is_empty(j):
    """«Ответ пришёл и он пустой» — отдельный вопрос от «ответа не было».

    Нельзя мерить это `_rows()`: у `tgm/indicators` полезная нагрузка лежит НЕ в `data`, и
    `_rows` на здоровом ответе вернул бы [], то есть здоровый ответ был бы объявлен пустым."""
    if j is None:
        return True
    if isinstance(j, list):
        return not j
    if isinstance(j, dict):
        for k in ('data', 'result'):
            if k in j:
                return not j.get(k)
        return not j
    return not j


def _cache_hit(path, j):
    """Попадание в кэш: сетевого запроса не было, кредитов НОЛЬ. Строка в телеметрию всё
    равно идёт — иначе не посчитать, сколько кэш снял."""
    empty = _is_empty(j)
    _tele.note('empty' if empty else 'ok')
    _tele.record(path, ms=0, http=200, ok=True, empty=empty, cache=True)


def _log_body(body):
    """Тело запроса для bot.log без адресов кошельков. Схема остаётся видна.

    Лог тела нужен для ремонта 400/422, но profiler-запросы несут адрес человека. Публичная
    телеметрия его не хранит, а bot.log раньше хранил полностью — privacy claim была только
    наполовину правдой. Контракты токенов (`token_address`) и market_id оставляем: это
    публичные сущности и без них диагностика сети/рынка теряет смысл.
    """
    private_keys = {'address', 'wallet_address', 'user_address', 'owner_address',
                    'to_wallet_address', 'from_address'}

    def walk(v, key=''):
        if key in private_keys and isinstance(v, str):
            return (v[:6] + '…' + v[-4:]) if len(v) > 12 else '<redacted>'
        if isinstance(v, dict):
            return {k: walk(x, str(k)) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        return v
    try:
        return json.dumps(walk(body), ensure_ascii=False)[:400]
    except Exception:
        return '<unprintable body>'


def _http_post(base, path, body, timeout, tag):
    """ГОРЛОВИНА: один сетевой POST, одна строка телеметрии, один класс отказа.
    -> (JSON | None, http-код). `http=0` означает исключение (таймаут, сеть)."""
    t0 = time.time()
    _fb = _tele.flight_begin() or (None, 1, 0)
    rem_before, parallel = _fb[0], _fb[1]
    overlap_start = _fb[2] if len(_fb) > 2 else 0
    http, j, _cls = 0, None, None
    try:
        r = httpx.post("%s/%s" % (base, path), headers=_headers(), json=body, timeout=timeout)
        http = r.status_code
        _note_credits(r.headers)
        if http != 200:
            _cls = _classify(http, r.text)
            # ТЕКСТ ОШИБКИ СОХРАНЯЕМ, А НЕ ТОЛЬКО ПЕЧАТАЕМ. Он машиночитаемый и содержит
            # ровно то, что надо поправить в теле («Field 'side' is not recognized»).
            # Печать в лог помогает ЧЕЛОВЕКУ через сутки, `_post_fix` чинит СЕЙЧАС - и без
            # этой строки чинить ему нечем.
            _LAST_ERR.update({'path': path, 'text': r.text[:600]})
            # ТЕЛО ЗАПРОСА В ЛОГ, КОГДА ВИНОВАТ ЗАПРОС. При 400/422 отвечать нечем, кроме
            # «мы отправили не то», и без самого тела это неисправимо: схема у части
            # эндпоинтов живым ключом не снята, и догадка стоит ещё один круг. Ключа в теле
            # нет (он в заголовке), адресов кошельков людей тоже - только контракт/аргументы.
            if _cls == 'badreq':
                print("[nansen%s] %s HTTP %s ОТВЕРГ НАШ ЗАПРОС: %s | тело: %s"
                      % (tag, path, http, r.text[:220], _log_body(body)))
            else:
                print("[nansen%s] %s HTTP %s: %s" % (tag, path, http, r.text[:180]))
            _tele.note(_cls, http, path)
        else:
            j = r.json()
            _tele.note_age(0)
    except Exception as e:
        print("[nansen%s] %s: %s" % (tag, path, e))
        _tele.note('timeout' if isinstance(e, httpx.TimeoutException) else 'http', 0, path)
    empty = False
    if http == 200:
        empty = _is_empty(j)
        # ПУСТОЙ ОТВЕТ 200 - ТОЖЕ ПОВОД ПОКАЗАТЬ ТЕЛО. «Данных нет» и «мы спросили не то»
        # выглядят одинаково: площадка возвращает 200 с пустым массивом в обоих случаях.
        # Живой прогон 14.09: «кто входил» по USDC на Base (один из самых торгуемых токенов
        # вообще) ответил пусто четыре раза из четырёх - на таком токене это почти наверняка
        # не отсутствие сделок, а неверная схема запроса, и без тела в логе это не отличить.
        if empty:
            print("[nansen%s] %s 200 ПУСТО | тело запроса: %s"
                  % (tag, path, _log_body(body)))
        _tele.note('empty' if empty else 'ok', http, path)
    _rem = _CREDITS.get('remaining')
    _rem = _rem if isinstance(_rem, int) else None
    overlap_end = _tele.flight_end(_rem)
    # КЛАСС ОТКАЗА ЕДЕТ В СТРОКУ ТЕЛЕМЕТРИИ ГОТОВЫМ. Пересчитать его там нельзя: 'unsupported'
    # отличается от 'bad_request' только ТЕКСТОМ ответа, а в `record` доезжает лишь код. Без
    # этого граница покрытия легла бы в сводку как «наш кривой запрос», и месячная строка
    # смешала бы то, что чиним мы, с тем, чего у площадки нет вовсе.
    _tele.record(path, ms=int((time.time() - t0) * 1000), http=http, ok=(http == 200),
                 empty=empty, cache=False, rem=_rem,
                 used=_CREDITS.get('used'), rem_before=rem_before, parallel=parallel,
                 overlap=(overlap_end != overlap_start),
                 sig=_tele.sig_of(path, body), cls=_cls)
    return j, http


def _rows(j):
    """Достаёт список из ответа (поле data|result|список верхнего уровня)."""
    if j is None:
        return []
    if isinstance(j, list):
        return j
    return j.get("data") or j.get("result") or []


# ── Token God Mode ───────────────────────────────────────────────────────────
def tgm_flow_intelligence(chain, token_address, timeframe="1d"):
    """Потоки токена по сегментам холдеров (Smart Money / киты / биржи / публ.фигуры /
    top-PnL / свежие кошельки): net/avg/count. -> dict первой строки или None. ~1-5 кр."""
    j = _post("tgm/flow-intelligence",
              {"chain": _nc(chain), "token_address": token_address, "timeframe": timeframe},
              ckey=f"flowintel:{chain}:{token_address}:{timeframe}")
    rows = _rows(j)
    return rows[0] if rows else None


def tgm_holders(chain, token_address, label_type="all_holders", per_page=20,
                premium_labels=False, include_labels=None):
    """Топ-холдеры с МЕТКАМИ (address_label: Smart Money/Fund/Exchange/…), долей и $.
    label_type: all_holders|smart_money|whale|exchange|public_figure. -> [dict]. ~5 кр
    (150 если premium_labels=True)."""
    body = {"chain": _nc(chain), "token_address": token_address,
            "label_type": label_type, "aggregate_by_entity": False,
            "pagination": {"page": 1, "per_page": per_page},
            "premium_labels": bool(premium_labels),
            "order_by": [{"field": "value_usd", "direction": "DESC"}]}
    if include_labels:
        body["filters"] = {"include_smart_money_labels": include_labels}
    return _rows(_post("tgm/holders", body,
                       ckey=f"tgmhold:{chain}:{token_address}:{label_type}:{per_page}:{int(premium_labels)}"))


def tgm_pnl_leaderboard(chain, token_address, per_page=10, days=30, premium_labels=False):
    """Топ-трейдеры токена по PnL (realized/unrealized, ROI, число сделок). -> [dict]. ~5 кр."""
    body = {"chain": _nc(chain), "token_address": token_address,
            "date": _date_range(days),
            "pagination": {"page": 1, "per_page": per_page},
            "premium_labels": bool(premium_labels),
            "order_by": [{"field": "pnl_usd_realised", "direction": "DESC"}]}
    return _rows(_post("tgm/pnl-leaderboard", body,
                       ckey=f"tgmpnl:{chain}:{token_address}:{per_page}:{days}"))


def tgm_who_bought_sold(chain, token_address, buy_or_sell="BUY", per_page=10, days=1):
    """Кто нетто покупал/продавал токен за период (адрес, метка, объёмы $). -> [dict]. ~1 кр."""
    body = {"chain": _nc(chain), "token_address": token_address,
            "buy_or_sell": buy_or_sell, "date": _date_range(days),
            "pagination": {"page": 1, "per_page": per_page},
            "order_by": [{"field": "%s_volume_usd" % ("bought" if buy_or_sell == "BUY" else "sold"),
                          "direction": "DESC"}]}
    return _rows(_post("tgm/who-bought-sold", body,
                       ckey=f"tgmwbs:{chain}:{token_address}:{buy_or_sell}:{per_page}:{days}"))


def tgm_token_information(chain, token_address, timeframe="1d"):
    """Метаданные + спот-метрики токена (mcap/fdv/supply/vol/buyers/sellers/holders/liq).
    -> dict или None. ~1 кр."""
    j = _post("tgm/token-information",
              {"chain": _nc(chain), "token_address": token_address, "timeframe": timeframe},
              ckey=f"tgminfo:{chain}:{token_address}:{timeframe}")
    if not j:
        return None
    # ФОРМУ ОТВЕТА НЕ УГАДЫВАЕМ. Прежняя редакция брала ТОЛЬКО `dict['data']` и на любом
    # другом виде отдавала None - то есть здоровый ответ выглядел как «данных нет». Схема
    # этого эндпоинта живым ключом не снята, поэтому принимаем и словарь с `data`, и голый
    # список строк, и одиночный словарь метрик.
    if isinstance(j, dict):
        return j.get("data") if j.get("data") is not None else (j or None)
    if isinstance(j, list):
        return j or None
    return None


def tgm_indicators(chain, token_address):
    """Nansen Score: risk_indicators (btc-reflexivity/liquidity/concentration/supply-inflation)
    + reward_indicators (tvl/momentum/fees/cex-flows/funding). score+percentile. -> dict|None. ~25 кр."""
    j = _post("tgm/indicators",
              {"chain": _nc(chain), "token_address": token_address},
              ckey=f"tgmind:{chain}:{token_address}")
    return j if isinstance(j, dict) and (j.get("risk_indicators") or j.get("reward_indicators")) else None


# ── Smart Money ──────────────────────────────────────────────────────────────
def smart_money_holdings(chains=None, per_page=20, min_value_usd=1000,
                         only_new_days=None, direction="DESC", order_field="value_usd"):
    """Агрегированные холдинги smart money по токенам (что копят). -> [dict]. ~1-5 кр."""
    chains = chains or ["ethereum", "solana", "base"]
    filters = {"value_usd": {"min": min_value_usd}, "include_stablecoins": False}
    if only_new_days:
        filters["token_age_days"] = {"max": only_new_days}
    body = {"chains": chains, "filters": filters,
            "pagination": {"page": 1, "per_page": per_page},
            "order_by": [{"field": order_field, "direction": direction}]}
    return _rows(_post("smart-money/holdings", body,
                       ckey=f"smhold:{','.join(chains)}:{per_page}:{order_field}:{direction}:{only_new_days}"))


# ── Profiler (кошельки) ──────────────────────────────────────────────────────
def profiler_labels(address, chain="ethereum", premium=False):
    """Метки адреса (ENS/поведенческие/DeFi/CEX; premium=True -> +Smart Money/Fund/публ.фигуры).
    -> [dict {label, category, kind}]. Дёшево."""
    path = "profiler/address/premium-labels" if premium else "profiler/address/labels"
    return _rows(_post(path,
                       {"address": address, "chain": _nc(chain),
                        "pagination": {"page": 1, "per_page": 100}},
                       ckey=f"lbl:{'p' if premium else 'c'}:{chain}:{address}"))


def profiler_pnl_summary(address, chain="ethereum", days=30):
    """Сводка PnL кошелька: realized_pnl_usd, realized_pnl_percent, win_rate, число сделок,
    топ-5 токенов. -> dict или None. Дёшево.

    `date` ОБЯЗАТЕЛЕН, и это установлено пробой на живом ключе (14.09), а не документацией:
    без него площадка отвечает 422 «Required field 'body -> date' is missing». Мы звали без
    него, поэтому PnL и winrate НИКОГДА не приезжали в профиль кошелька - экран показывал
    метки и связанные кошельки и выглядел целым. Отсюда же два 422 в сводке за 14.09."""
    j = _post("profiler/address/pnl-summary",
              {"address": address, "chain": _nc(chain), "date": _date_range(days)},
              ckey=f"pnlsum:{chain}:{address}:{days}")
    return j if isinstance(j, dict) else None


def profiler_related_wallets(address, chain="ethereum", per_page=10):
    """Связанные кошельки (funding/взаимодействия): address, label, relation, tx, ts.
    Ключ для детекта бандл/инсайдер/сибил. -> [dict]. Дёшево."""
    return _rows(_post("profiler/address/related-wallets",
                       {"address": address, "chain": _nc(chain),
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "order", "direction": "ASC"}]},
                       ckey=f"rel:{chain}:{address}:{per_page}"))


def profiler_counterparties(address, chain="ethereum", per_page=10, days=30):
    """Топ-контрагенты кошелька (с кем чаще всего торгует; объёмы in/out). -> [dict]."""
    return _rows(_post("profiler/address/counterparties",
                       {"address": address, "chain": _nc(chain),
                        "date": _date_range(days), "group_by": "wallet",
                        "source_input": "Combined",
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "total_volume_usd", "direction": "DESC"}]},
                       ckey=f"cp:{chain}:{address}:{per_page}:{days}"))


def profiler_current_balance(address, chain="ethereum", per_page=15):
    """Текущий портфель кошелька (токены, кол-во, $). -> [dict]."""
    return _rows(_post("profiler/address/current-balance",
                       {"address": address, "chain": _nc(chain), "hide_spam_token": True,
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "value_usd", "direction": "DESC"}]},
                       ckey=f"bal:{chain}:{address}:{per_page}"))


# ── Hyperliquid / перпы ──────────────────────────────────────────────────────
def perp_leaderboard(per_page=10, days=7, min_account_value=10000, premium_labels=False):
    """Топ прибыльных перп-трейдеров (HL): trader_address, label, total_pnl, roi, account_value.
    -> [dict]. ~5 кр (150 если premium)."""
    body = {"date": {"from": _date_range(days)["from"][:10], "to": _date_range(days)["to"][:10]},
            "pagination": {"page": 1, "per_page": per_page},
            "filters": {"account_value": {"min": min_account_value}},
            "premium_labels": bool(premium_labels),
            "order_by": [{"field": "total_pnl", "direction": "DESC"}]}
    return _rows(_post("perp-leaderboard", body,
                       ckey=f"perplb:{per_page}:{days}:{min_account_value}"))


# ═══ ФОРМАТТЕРЫ для карточек Гробовщика (готовые строки/блоки, HTML) ═══════════
def _usd(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "?"
    a = abs(x)
    if a >= 1e9:
        return f"{x/1e9:.2f}B"
    if a >= 1e6:
        return f"{x/1e6:.2f}M"
    if a >= 1e3:
        return f"{x/1e3:.1f}K"
    return f"{x:.0f}"


def flow_intelligence_line(chain, token_address):
    """Строка для карточки токена: нетто-потоки 24ч по сегментам. -> str | None."""
    f = tgm_flow_intelligence(chain, token_address, "1d")
    if not f:
        return None
    parts = []
    seg = [("smart_trader", "🧠SM"), ("whale", "🐳киты"), ("top_pnl", "🏆топ-PnL"),
           ("public_figure", "🎤публ"), ("exchange", "🏦биржи"), ("fresh_wallets", "🆕свежие")]
    for key, lbl in seg:
        v = f.get(f"{key}_net_flow_usd")
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if abs(v) < 1000:
            continue
        sign = "+" if v >= 0 else "-"
        parts.append(f"{lbl} {sign}${_usd(abs(v))}")
    if not parts:
        return None
    return "🧠 <b>Nansen потоки 24ч:</b> " + " · ".join(parts[:5])


def nansen_score_line(chain, token_address):
    """Строка Nansen Score: сводка risk/reward индикаторов. -> str | None."""
    d = tgm_indicators(chain, token_address)
    if not d:
        return None
    risk = d.get("risk_indicators") or []
    reward = d.get("reward_indicators") or []
    hi_risk = sum(1 for r in risk if str(r.get("score")).lower() == "high")
    bull = sum(1 for r in reward if str(r.get("score")).lower() == "bullish")
    bear = sum(1 for r in reward if str(r.get("score")).lower() == "bearish")
    bits = []
    if risk:
        bits.append(f"риск {'🔴 высокий' if hi_risk >= 2 else ('🟡 средний' if hi_risk == 1 else '🟢 низкий')}")
    if reward:
        if bull > bear:
            bits.append(f"потенциал 🟢 бычий ({bull}/{len(reward)})")
        elif bear > bull:
            bits.append(f"потенциал 🔴 медвежий ({bear}/{len(reward)})")
        else:
            bits.append("потенциал ⚪ нейтральный")
    if not bits:
        return None
    return "📊 <b>Nansen Score:</b> " + " · ".join(bits)


def labeled_holders_line(chain, token_address, top=20):
    """Строка «кто в топ-холдерах по меткам»: сколько SM/фондов/бирж/китов. -> str | None."""
    rows = tgm_holders(chain, token_address, per_page=top)
    if not rows:
        return None
    buckets = {}
    for r in rows:
        lbl = (r.get("address_label") or "").strip()
        if not lbl:
            continue
        low = lbl.lower()
        if "smart" in low or "trader" in low:
            k = "🧠 smart money"
        elif "fund" in low:
            k = "🏛 фонды"
        elif "exchange" in low or "🏦" in lbl:
            k = "🏦 биржи"
        elif "whale" in low:
            k = "🐳 киты"
        elif "public" in low or "figure" in low:
            k = "🎤 публ.фигуры"
        else:
            continue
        buckets[k] = buckets.get(k, 0) + 1
    if not buckets:
        return None
    inner = ", ".join(f"{v} {k}" for k, v in sorted(buckets.items(), key=lambda x: -x[1]))
    return f"🏷 <b>В топ-{top} холдерах:</b> {inner}"


def pnl_leaders_block(chain, token_address, top=5):
    """Блок «топ-трейдеры токена по PnL» для отдельной карточки/кнопки. -> str | None."""
    rows = tgm_pnl_leaderboard(chain, token_address, per_page=top)
    if not rows:
        return None
    L = [f"🏆 <b>Топ-трейдеры по PnL</b> (реализ.):"]
    for i, r in enumerate(rows[:top], 1):
        lbl = (r.get("trader_address_label") or "").strip()
        addr = r.get("trader_address") or ""
        who = lbl or (f"{addr[:6]}…{addr[-4:]}" if addr else "?")
        pnl = r.get("pnl_usd_realised")
        roi = r.get("roi_percent_realised") or r.get("roi_percent_total")
        try:
            pnl_s = ("+$" if float(pnl) >= 0 else "-$") + _usd(abs(float(pnl)))
        except (TypeError, ValueError):
            pnl_s = "?"
        roi_s = (f" · ROI {float(roi):+.0f}%") if roi not in (None, "") else ""
        L.append(f"{i}. {who}: {pnl_s}{roi_s}")
    return "\n".join(L)


def wallet_profile_block_ex(address, chain="ethereum", premium=False):
    """Профиль кошелька И ПРИЧИНА пустоты. -> (str|None, reason).

    reason: 'ok' | 'nokey' | 'nocredits' | 'ratelimit' | 'timeout' | 'http' | 'empty'.
    Раньше все шесть миров склеивались в одну фразу «нет ключа/меток или адрес неактивен» -
    три диагноза в одном предложении, и ни один нельзя проверить."""
    if not _key():
        return None, 'nokey'
    _tele.clear()
    txt = wallet_profile_block(address, chain, premium)
    return (txt, 'ok') if txt else (None, fail_reason('empty'))


def wallet_profile_block(address, chain="ethereum", premium=False):
    """Полный профиль кошелька для карточки: метки + PnL/winrate + связанные. -> str | None."""
    labels = profiler_labels(address, chain, premium=premium) or []
    pnl = profiler_pnl_summary(address, chain) or {}
    rel = profiler_related_wallets(address, chain, per_page=5) or []
    if not (labels or pnl or rel):
        return None
    short = f"{address[:6]}…{address[-4:]}"
    L = [f"👤 <b>Профиль кошелька</b> <code>{short}</code> [{chain}]"]
    # ЧТО НЕ ПРИЕХАЛО - НАЗЫВАЕТСЯ ЗДЕСЬ, В САМОМ БЛОКЕ. Профиль собирается из ТРЁХ запросов,
    # и раньше хватало одного удачного, чтобы блок вернулся как 'ok': человек видел целую
    # карточку без меток и без PnL и не мог узнать, что их не спрашивали успешно. Живой прогон
    # 14.09: два запроса из трёх отдали 422, на экран приехала одна строка про связанные
    # кошельки, и выглядело это как «у адреса больше ничего нет».
    _miss = missing_note('ru', total=3)
    if _miss:
        L.append(_miss)
    if labels:
        tags = " · ".join((l.get("label") or "") for l in labels[:6] if l.get("label"))
        if tags:
            L.append(f"🏷 {tags}")
    if pnl:
        wr = pnl.get("win_rate")
        rp = pnl.get("realized_pnl_usd")
        rpp = pnl.get("realized_pnl_percent")
        n = pnl.get("traded_times") or pnl.get("traded_token_count")
        seg = []
        if rp is not None:
            try:
                seg.append(("реализ. PnL +$" if float(rp) >= 0 else "реализ. PnL -$") + _usd(abs(float(rp))))
            except (TypeError, ValueError):
                pass
        if rpp not in (None, ""):
            try:
                seg.append(f"ROI {float(rpp):+.0f}%")
            except (TypeError, ValueError):
                pass
        if wr not in (None, ""):
            try:
                seg.append(f"winrate {float(wr)*100:.0f}%" if float(wr) <= 1 else f"winrate {float(wr):.0f}%")
            except (TypeError, ValueError):
                pass
        if n:
            seg.append(f"сделок {n}")
        if seg:
            L.append("📈 " + " · ".join(seg))
        top5 = pnl.get("top5_tokens") or []
        if top5:
            toks = ", ".join((t.get("token_symbol") or "?") for t in top5[:5])
            L.append(f"💼 топ-токены: {toks}")
    if rel:
        rl = ", ".join((r.get("relation") or "?") for r in rel[:4])
        L.append(f"🔗 связанных кошельков: {len(rel)}+ ({rl})")
    return with_source("\n".join(L))


def perp_leaders_block(top=8, days=7, rows=None, bot_un=None):
    """Блок «топ прибыльных перп-трейдеров (HL)» для фида/карточки. -> str | None.
    rows: если переданы (уже загружены вызывающим) — не дёргаем API повторно.
    bot_un: если задан — имя трейдера становится ССЫЛКОЙ (deep-link ?start=acc_<addr>
    -> экран счёта DeBank), как названия в «Трендах». Иначе обычный текст (фид/карточка)."""
    if rows is None:
        rows = perp_leaderboard(per_page=top, days=days)
    if not rows:
        return None
    L = [f"🏆 <b>Топ перп-трейдеры (Hyperliquid, {days}д):</b>"]
    for i, r in enumerate(rows[:top], 1):
        lbl = (r.get("trader_address_label") or "").strip()
        addr = r.get("trader_address") or ""
        who = lbl or (f"{addr[:6]}…{addr[-4:]}" if addr else "?")
        if bot_un and addr:
            who = '<a href="https://t.me/%s?start=acc_%s">%s</a>' % (bot_un, addr, who)
        pnl = r.get("total_pnl")
        roi = r.get("roi")
        try:
            pnl_s = ("+$" if float(pnl) >= 0 else "-$") + _usd(abs(float(pnl)))
        except (TypeError, ValueError):
            pnl_s = "?"
        roi_s = (f" · ROI {float(roi):+.0f}%") if roi not in (None, "") else ""
        L.append(f"{i}. {who}: {pnl_s}{roi_s}")
    if bot_un:
        L.append("\nТапни трейдера — открою его счёт (DeBank).")
    return with_source("\n".join(L))



# ═══════════════════════════════════════════════════════════════════════════
# ЧЕТЫРЕ ФУНКЦИИ, КОТОРЫЕ БЫЛИ НАПИСАНЫ И НЕДОСТИЖИМЫ (ТЗ B, пункт B3)
#
# `tgm_who_bought_sold`, `tgm_token_information`, `profiler_counterparties`,
# `profiler_current_balance` не имели НИ ОДНОГО вызывающего во всём репо (проверено картой
# по имени БЕЗ скобки, закон №47). Клиент есть, провода нет - для человека этого не
# существует. Ниже провод: форматтер + причина отказа, дальше команда в `oc_dm` и строка в
# справке (закон №25).
#
# ПОЛЯ ОТВЕТОВ ЧИТАЮТСЯ ЗАЩИТНО И С ДИАГНОСТИКОЙ. Схемы этих четырёх эндпоинтов живым
# ключом не сняты (из контейнера сети к площадке нет), поэтому имена полей перебираются
# списком кандидатов, а на непонятной строке в лог уходит НАБОР КЛЮЧЕЙ, который правда
# приехал: гадать по документации значило бы выдать пустой экран вместо ответа и не
# оставить следа, по которому это чинится одной правкой.
# ═══════════════════════════════════════════════════════════════════════════
_SEEN_SHAPE = set()


def _shape(tag, row):
    """Один раз на процесс напечатать реальный набор полей незнакомой строки."""
    if not isinstance(row, dict) or tag in _SEEN_SHAPE:
        return
    _SEEN_SHAPE.add(tag)
    print("[nansen] %s: поля ответа %s" % (tag, sorted(row.keys())[:14]))


def _num_or_none(x):
    """В число или None, без исключений. -> float | None.

    Нужен там, где из двух полей считается третье (доли × цена = доллары): `float()` на
    отсутствующем поле бросает, а нам нужно ЧЕСТНОЕ «нет числа», чтобы экран сказал это
    словом вместо того, чтобы подставить ноль.
    """
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None          # NaN - тоже не число


def _first(row, names, default=None):
    """Первое присутствующее поле из списка кандидатов."""
    if not isinstance(row, dict):
        return default
    for n in names:
        if row.get(n) not in (None, ""):
            return row.get(n)
    return default


#: ПОЛЯ, КОТОРЫЕ КОНЧАЮТСЯ НА `_usd`, НО НЕ ЯВЛЯЮТСЯ СУММОЙ СДЕЛКИ. Без этого списка
#: «универсальный поиск денег» подставил бы `price_usd` (цена одного токена, $0.9998 у
#: стейбла) в строку «зашли на $…», и это была бы не пустота, а НЕВЕРНОЕ ЧИСЛО - хуже
#: прочерка, потому что прочерк видно, а $0.99 читается как настоящий объём.
_NOT_MONEY = ('price', 'pnl', 'fee', 'gas', 'balance', 'market_cap', 'mcap', 'fdv',
              'liquidity', 'supply', 'net_worth', 'networth', 'roi', 'apy')
#: приоритет имён: чем раньше подстрока, тем охотнее берём поле
_MONEY_RANK = ('value_usd', 'volume_usd', 'amount_usd', 'notional', 'usd_value', 'size_usd',
               'total_usd', 'usd')


def _usd_any(row, names=()):
    """Сумма в долларах из строки ответа. -> (значение | None, имя поля | None).

    ДВА ЭТАЖА, И ВТОРОЙ ПОЯВИЛСЯ ПОСЛЕ ЖИВОГО ПРОГОНА 15.09. Сперва - названные поля
    (`names`): там, где схема снята с площадки, читаем ровно её. Если ни одного нет -
    ищем ПО СОГЛАШЕНИЮ ИМЁН Nansen: денежные поля у них кончаются на `_usd`.

    ЗАЧЕМ ВТОРОЙ ЭТАЖ. «Смарт сделки» вернули 12 строк, где тикеры и адреса прочитались, а
    объём во ВСЕХ двенадцати был `$?`: список кандидатов (`value_usd`, `volume_usd`,
    `amount_usd`) угадан по соседним эндпоинтам и не совпал ни одним именем. Догадка №4 в
    том же списке стоила бы ещё круг живого прогона, а соглашение `*_usd` покрывает разом
    все имена вида `usd_amount`, `trade_value_usd`, `token_bought_amount_usd`.

    ЧТО ЭТО НЕ ДЕЛАЕТ: не выдумывает число. Не нашли - вернули None, и вызывающий обязан
    сказать словом, что суммы нет (см. `schema_gap_note`), а не печатать прочерк 12 раз.
    """
    if not isinstance(row, dict):
        return None, None
    for n in names:
        if row.get(n) not in (None, ''):
            return row.get(n), n
    cand = []
    for k, v in row.items():
        kl = str(k).lower()
        if not kl.endswith('usd') or v in (None, ''):
            continue
        if any(b in kl for b in _NOT_MONEY):
            continue
        try:
            float(v)
        except (TypeError, ValueError):
            continue
        rank = next((i for i, p in enumerate(_MONEY_RANK) if p in kl), len(_MONEY_RANK))
        cand.append((rank, kl, k))
    if not cand:
        return None, None
    cand.sort()                      # порядок ОДНОЗНАЧЕН: rank, потом имя по алфавиту
    k = cand[0][2]
    return row.get(k), k


def schema_gap_note(row, what, lang='ru'):
    """Строка «поле не приехало, и вот что приехало вместо него». -> str.

    ТРЕТИЙ КЛАСС, КОТОРОГО НЕ БЫЛО. Отказ - это «мы не смогли спросить». `missing_note` -
    «часть запросов блока упала». А здесь запрос ПРОШЁЛ, вернул 200 и строки, но в схеме нет
    поля, которое мы читаем. Снаружи это выглядело как прочерк в каждой строке, то есть как
    «данных нет» - опять пустота, выданная за проверку.

    ПЕЧАТАЕМ РЕАЛЬНЫЕ ИМЕНА ПОЛЕЙ. Это чинится ровно за один круг: Ren присылает строку, имя
    поля становится известным, догадки кончаются. Без имён - три круга по живому прогону.
    """
    keys = sorted(row.keys())[:12] if isinstance(row, dict) else []
    ks = ', '.join('<code>%s</code>' % str(k)[:28] for k in keys) or '—'
    if lang == 'en':
        return ('⚠️ <i>%s did not arrive: the response has no such field. Nansen returned: '
                '%s. Request went through (200), so this is a schema mismatch on our side, '
                'not missing data.</i>' % (what, ks))
    return ('⚠️ <i>%s не приехал: такого поля в ответе нет. Nansen вернул: %s. Запрос прошёл '
            '(200), значит это расхождение схемы у нас, а не отсутствие данных.</i>'
            % (what, ks))


def _who(row):
    """Кто это: метка, иначе укороченный адрес, иначе '?'."""
    lbl = _first(row, ("address_label", "trader_address_label", "counterparty_label",
                       "label", "entity", "entity_name"))
    addr = _first(row, ("address", "trader_address", "wallet_address", "counterparty_address",
                        "counterparty", "to_address"), "")
    if lbl:
        return str(lbl)[:40]
    addr = str(addr)
    return ("%s…%s" % (addr[:6], addr[-4:])) if len(addr) > 12 else (addr or "?")


def who_bought_sold_block(chain, token_address, days=7, top=5, lang='ru'):
    """«Кто входил и кто выходил за период» по токену. -> (str|None, reason). ~2 кр.

    Готовый сценарий, названный в ТЗ первым кандидатом: два дешёвых запроса, один экран."""
    if not _key():
        return None, 'nokey'
    _tele.clear()
    buys = tgm_who_bought_sold(chain, token_address, "BUY", top, days) or []
    sells = tgm_who_bought_sold(chain, token_address, "SELL", top, days) or []
    if not buys and not sells:
        return None, fail_reason('empty')
    _t = ("🟢 <b>Входили</b>", "🔴 <b>Выходили</b>") if lang != 'en' else \
         ("🟢 <b>Bought</b>", "🔴 <b>Sold</b>")
    head = ("🔄 <b>Кто входил и выходил</b> · %s · %sд" % (chain, days)) if lang != 'en' else \
           ("🔄 <b>Who bought and sold</b> · %s · %sd" % (chain, days))
    L = [head]
    for title, rows, keys in ((_t[0], buys, ("bought_volume_usd", "buy_volume_usd")),
                              (_t[1], sells, ("sold_volume_usd", "sell_volume_usd"))):
        if not rows:
            continue
        L.append("\n" + title + ":")
        for i, r in enumerate(rows[:top], 1):
            _shape("who-bought-sold", r)
            v = _first(r, keys + ("volume_usd", "net_volume_usd", "total_volume_usd"))
            try:
                vs = "$" + _usd(abs(float(v)))
            except (TypeError, ValueError):
                vs = "?"
            L.append("%d. %s · %s" % (i, _who(r), vs))
    _miss = missing_note(lang, total=2)
    if _miss:
        L.append("\n" + _miss)      # одна нога из двух могла не приехать - это видно словом
    return with_source("\n".join(L), lang), 'ok'


def token_info_block(chain, token_address, lang='ru'):
    """Справка по токену от Nansen: капитализация, объём, держатели, ликвидность.
    -> (str|None, reason). ~1 кр."""
    if not _key():
        return None, 'nokey'
    _tele.clear()
    d = tgm_token_information(chain, token_address)
    if not d:
        return None, fail_reason('empty')
    row = d[0] if isinstance(d, list) and d else d
    if not isinstance(row, dict):
        return None, fail_reason('empty')
    _shape("token-information", row)
    sym = _first(row, ("symbol", "token_symbol"), "?")
    name = _first(row, ("name", "token_name"), "")
    head = ("🪪 <b>Nansen · справка по токену</b> %s%s [%s]"
            % (sym, (" (%s)" % name) if name else "", chain))
    L = [head]
    _pairs = (("market_cap", "капитализация", "market cap"),
              ("fully_diluted_valuation", "FDV", "FDV"),
              ("fdv", "FDV", "FDV"),
              ("volume_24h_usd", "объём 24ч", "volume 24h"),
              ("volume_usd", "объём", "volume"),
              ("liquidity_usd", "ликвидность", "liquidity"),
              ("total_supply", "supply", "supply"),
              ("holders", "держателей", "holders"),
              ("holder_count", "держателей", "holders"),
              ("buyers", "покупателей", "buyers"),
              ("sellers", "продавцов", "sellers"))
    _shown = set()
    for key, ru, en in _pairs:
        lbl = ru if lang != 'en' else en
        if lbl in _shown or row.get(key) in (None, ""):
            continue
        v = row.get(key)
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        _shown.add(lbl)
        L.append("• %s: %s%s" % (lbl, "$" if 'supply' not in key and 'holder' not in key
                                 and key not in ('buyers', 'sellers', 'holders') else "",
                                 _usd(fv) if fv >= 1000 else ("%.4g" % fv)))
    if len(L) == 1:
        return None, fail_reason('empty')
    return with_source("\n".join(L), lang), 'ok'


def counterparties_block(address, chain="ethereum", top=8, days=30, lang='ru'):
    """С кем этот кошелёк торгует чаще всего. -> (str|None, reason). Дёшево."""
    if not _key():
        return None, 'nokey'
    _tele.clear()
    rows = profiler_counterparties(address, chain, per_page=top, days=days) or []
    if not rows:
        return None, fail_reason('empty')
    short = "%s…%s" % (address[:6], address[-4:])
    head = ("🤝 <b>Контрагенты</b> <code>%s</code> [%s] · %sд" % (short, chain, days)) \
        if lang != 'en' else \
        ("🤝 <b>Counterparties</b> <code>%s</code> [%s] · %sd" % (short, chain, days))
    L = [head]
    for i, r in enumerate(rows[:top], 1):
        _shape("counterparties", r)
        v = _first(r, ("total_volume_usd", "volume_usd", "combined_volume_usd"))
        n = _first(r, ("transaction_count", "tx_count", "trades", "count"))
        try:
            vs = "$" + _usd(abs(float(v)))
        except (TypeError, ValueError):
            vs = "?"
        L.append("%d. %s · %s%s" % (i, _who(r), vs, (" · %s tx" % n) if n else ""))
    return with_source("\n".join(L), lang), 'ok'


def wallet_balance_block(address, chain="ethereum", top=12, lang='ru'):
    """Текущий портфель кошелька по данным Nansen. -> (str|None, reason). Дёшево."""
    if not _key():
        return None, 'nokey'
    _tele.clear()
    rows = profiler_current_balance(address, chain, per_page=top) or []
    if not rows:
        return None, fail_reason('empty')
    short = "%s…%s" % (address[:6], address[-4:])
    head = ("💼 <b>Портфель</b> <code>%s</code> [%s] (данные Nansen)" % (short, chain)) \
        if lang != 'en' else \
        ("💼 <b>Portfolio</b> <code>%s</code> [%s] (Nansen data)" % (short, chain))
    L = [head]
    _tot = 0.0
    for i, r in enumerate(rows[:top], 1):
        _shape("current-balance", r)
        sym = _first(r, ("token_symbol", "symbol", "name"), "?")
        v = _first(r, ("value_usd", "usd_value", "balance_usd"))
        amt = _first(r, ("token_amount", "amount", "balance", "quantity"))
        try:
            fv = float(v)
            _tot += fv
            vs = "$" + _usd(fv)
        except (TypeError, ValueError):
            vs = "?"
        _amt = ""
        try:
            _amt = " · %s шт" % _usd(float(amt)) if amt not in (None, "") else ""
        except (TypeError, ValueError):
            _amt = ""
        L.append("%d. <b>%s</b> — %s%s" % (i, sym, vs, _amt))
    if _tot:
        L.append("\n%s $%s" % ("Итого по показанным:" if lang != 'en' else "Shown total:",
                               _usd(_tot)))
    return with_source("\n".join(L), lang), 'ok'


def token_nansen_block_ex(chain, token_address):
    """То же, что token_nansen_block, но ВОЗВРАЩАЕТ И ПРИЧИНУ пустоты. -> (text|None, reason).
    reason: 'ok' | 'nokey' | 'nocredits' | 'ratelimit' | 'timeout' | 'http' | 'empty'.

    Зачем: раньше пустота и сбой были неразличимы, и человек всегда получал «нет данных
    (или нужен ключ/платный план)» — даже когда ключ подключён и виноват был сам запрос.
    Такое сообщение уводит от причины вместо того, чтобы её назвать.

    ПРИЧИНА БОЛЬШЕ НЕ СЧИТАЕТСЯ ИСКЛЮЧЕНИЯМИ. Прежняя редакция считала `errs` по
    `except Exception`, а `_post` исключений не бросает — он возвращал `None`. Поэтому 429,
    402, 500 и таймаут приезжали сюда как `empty`, и человек читал «ключ работает, но по
    этому токену данных нет» там, где на самом деле кончились кредиты. Дверь была честная,
    диагноз врал. Теперь класс отказа приходит из горловины (`nansen_log`), то есть ровно
    оттуда, где известен код ответа."""
    if not _key():
        return None, 'nokey'
    _tele.clear()
    parts = []
    for fn in (flow_intelligence_line, nansen_score_line, labeled_holders_line):
        try:
            s = fn(chain, token_address)
        except Exception as e:
            _tele.note('http')
            print("[nansen] %s(%s): %s" % (getattr(fn, '__name__', '?'), chain, str(e)[:100]))
            s = None
        if s:
            parts.append(s)
    try:
        pnl = pnl_leaders_block(chain, token_address, top=5)
    except Exception as e:
        _tele.note('http')
        print("[nansen] pnl_leaders(%s): %s" % (chain, str(e)[:100]))
        pnl = None
    if pnl:
        parts.append(pnl)
    if parts:
        # ЧАСТИЧНЫЙ РАЗБОР НАЗЫВАЕТ ПРОПАЖУ. Четыре запроса, и хватало одного удачного, чтобы
        # вернуть 'ok': человек нажимал 🧠 ради Nansen Score, получал одни потоки и читал это
        # как «Score у токена нет». Отсутствие красного флага снова читалось бы как его
        # отсутствие, только теперь внутри непустого блока.
        _miss = missing_note('ru', total=4)
        _body = "🧠 <b>Nansen · разбор токена</b>\n\n" + "\n\n".join(parts)
        if _miss:
            _body += "\n\n" + _miss
        return with_source(_body), 'ok'
    return None, fail_reason('empty')


def token_nansen_block(chain, token_address):
    """Единый Nansen-блок по токену (кнопка 🧠 на карточке контракта / глубокий паспорт):
    потоки по сегментам + Nansen Score + метки топ-холдеров + топ-трейдеры по PnL. -> str | None."""
    return token_nansen_block_ex(chain, token_address)[0]



# ── Smart Money netflow с ТАЙМФРЕЙМАМИ (1h/24h/7d/30d) ────────────────────────
# Отдельный endpoint /smart-money/netflow отдаёт ВСЕ окна в одном ответе
# (net_flow_1h/24h/7d/30d_usd) — разбивка по таймингам, а не только 24ч.
_SMNF_FIELD = {"1h": "net_flow_1h_usd", "24h": "net_flow_24h_usd",
               "7d": "net_flow_7d_usd", "30d": "net_flow_30d_usd"}
_SMNF_LBL = {"1h": "1ч", "24h": "24ч", "7d": "7д", "30d": "30д"}


def sm_netflow(chains=None, tf="24h", per_page=12, direction="DESC"):
    """Нетто-потоки smart money по токенам за окно tf (1h/24h/7d/30d). -> [dict]. Дёшево."""
    chains = chains or ["ethereum", "solana", "base"]
    tf = tf if tf in _SMNF_FIELD else "24h"
    field = _SMNF_FIELD[tf]
    body = {"chains": chains, "filters": {"include_stablecoins": False},
            "pagination": {"page": 1, "per_page": per_page},
            "order_by": [{"field": field, "direction": direction}]}
    return _rows(_post("smart-money/netflow", body,
                       ckey=f"smnf:{','.join(chains)}:{tf}:{per_page}:{direction}"))


def sm_netflow_block(chains=None, tf="24h", top=10, rows=None, bot_un=None):
    """Готовый блок «приток smart money за <tf>» для карточки/подменю. -> str | None.
    rows: если переданы (уже загружены вызывающим) — не дёргаем API повторно.
    bot_un: если задан — тикер становится ССЫЛКОЙ (deep-link ?start=tok_<addr>
    -> карточка/паспорт токена), как названия в «Трендах». Иначе обычный текст."""
    tf = tf if tf in _SMNF_FIELD else "24h"
    if rows is None:
        rows = sm_netflow(chains, tf, top)
    if not rows:
        return None
    field = _SMNF_FIELD[tf]
    L = [f"🧠 <b>Приток smart money за {_SMNF_LBL[tf]}</b> (Nansen netflow):"]
    for i, r in enumerate(rows[:top], 1):
        sym = r.get("token_symbol") or "?"
        addr = (r.get("token_address") or "").strip()
        ch = r.get("chain") or ""
        v = r.get(field)
        try:
            vs = ("+$" if float(v) >= 0 else "-$") + _usd(abs(float(v)))
        except (TypeError, ValueError):
            vs = "?"
        sym_disp = f"<b>{sym}</b>"
        if bot_un and addr:
            sym_disp = '<a href="https://t.me/%s?start=tok_%s"><b>%s</b></a>' % (bot_un, addr, sym)
        L.append(f"{i}. {sym_disp} [{ch}] · {vs}")
    tail = "тапни тикер" if bot_un else "пришли тикер"
    L.append(f"\nТФ ниже переключает окно · {tail} — открою карточку.")
    return with_source("\n".join(L))



# ═══════════════════════════════════════════════════════════════════════════
# ОСТАЛЬНОЙ API: ТО, ЧЕГО У НАС НЕ БЫЛО (снято с docs.nansen.ai/api/overview 14.09.2026)
#
# До этого захода клиент покрывал 24 эндпоинта из ~60. Ниже - остальные, сгруппированные так
# же, как у площадки. Схемы НЕ выдуманы: имена полей взяты по образцу уже работающих соседей
# из тех же разделов (`date` как `_date_range`, `pagination`, `order_by`), потому что проба
# 14.09 показала - у Nansen единая форма тела внутри раздела, и отклонения он называет прямо
# («Did you mean 'bought_volume_usd'?»). Каждая функция читается защитно, и первый живой вызов
# печатает РЕАЛЬНЫЙ набор полей (`_shape`), чтобы расхождение чинилось одной правкой, а не
# гаданием.
#
# ЦЕНА: у большинства 1-5 кредитов, у исторических 5-25. В `nansen_log._EP_EST` заведены те,
# чья цена названа в overview; остальные идут «цена неизвестна» - ноль вместо догадки.
# ═══════════════════════════════════════════════════════════════════════════

# ── Token God Mode: то, чего не было ──────────────────────────────────────────
def tgm_flows(chain, token_address, days=1):
    """Приток и отток токена по сегментам (биржи, smart money, публ.фигуры, киты).
    -> [dict]. ~1 кр. ОТЛИЧАЕТСЯ от flow-intelligence: там нетто по сегментам, здесь
    раздельно вход и выход - «набирают» и «сливают» видно порознь.

    СХЕМА СНЯТА ЖИВОЙ ПРОБОЙ 19.09, и она оказалась другой: эндпоинт требует `date` (окно) и
    НЕ ЗНАЕТ поля `timeframe`, которое мы ему посылали. Ремонт по словам площадки прошёл ровно
    эти два шага сам («подставил обязательное поле date», «убрал поле timeframe»), и здесь
    результат пришпилен - чтобы каждый холодный старт не платил за то, что уже выяснено.

    И ГЛАВНАЯ НЕОЖИДАННОСТЬ ТОЙ ЖЕ ПРОБЫ: на USDC эндпоинт ответил не пустотой, а словами -
    «этот токен стейблкоин, потоки стейблкоинов эндпоинт не поддерживает». Это ГРАНИЦА
    ПОКРЫТИЯ, а не наш баг и не отсутствие данных; под неё заведён отдельный класс отказа
    `unsupported` (см. `_REFUSAL`), иначе человек читал бы «потоков нет» как свойство токена.
    """
    return _rows(_post_fix("tgm/flows",
                       {"chain": _nc(chain), "token_address": token_address,
                        "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": 20}},
                       ckey=f"tgmflows:{chain}:{token_address}:{days}"))


def tgm_dex_trades(chain, token_address, per_page=20, days=1):
    """Все DEX-сделки по токену за период. -> [dict]. ~1 кр."""
    return _rows(_post("tgm/dex-trades",
                       {"chain": _nc(chain), "token_address": token_address,
                        "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"tgmdex:{chain}:{token_address}:{per_page}:{days}"))


def tgm_transfers(chain, token_address, per_page=20, days=1):
    """Крупнейшие переводы токена за период. -> [dict]. ~1 кр."""
    return _rows(_post("tgm/token-transfers",
                       {"chain": _nc(chain), "token_address": token_address,
                        "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"tgmtr:{chain}:{token_address}:{per_page}:{days}"))


def tgm_price_ohlcv(chain, token_address, timeframe="1d", days=30):
    """Свечи токена НЕ из беты, а из основного API. -> [dict]. ~1 кр.

    Отдельно от `historical_ohlcv` (бета, 5 кр, 180 дней): для карточки и графика хватает
    этого, а бета нужна бэктесту с длинной историей."""
    return _rows(_post("tgm/price-ohlcv",
                       {"chain": _nc(chain), "token_address": token_address,
                        "timeframe": timeframe, "date": _date_range(days)},
                       ckey=f"tgmohlcv:{chain}:{token_address}:{timeframe}:{days}"))


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОБА ПУТЕЙ 20.09: ДВА ЭНДПОИНТА ВЕРНУЛИСЬ, ДВА ОСТАЛИСЬ МЁРТВЫМИ
#
# 19.09 три эндпоинта ответили 404, и я их удалил, написав: «404 бывает двух сортов - такого
# нет и переехало; отличить можно только перебором соседних путей». Перебор сделан
# (`--run --only perp`, 11 запросов), и он окупился вдвое:
#
#   ЖИВЫ, ПРОСТО ПО ДРУГОМУ ПУТИ - ВОЗВРАЩЕНЫ НИЖЕ:
#     * `perp-screener` (БЕЗ префикса tgm) -> 422 «Required field 'body -> date' is missing».
#       422 на отсутствующее поле означает, что РУЧКА СУЩЕСТВУЕТ и разбирает тело.
#     * `profiler/perp-positions` (без `address` в пути) -> 422 «Field 'pagination' is not
#       recognized». Тоже живая ручка, просто не хочет пагинации.
#
#   МЁРТВЫ ОКОНЧАТЕЛЬНО (404 на все кандидаты, вопрос закрыт вторым способом):
#     * `tgm/perp-screener`, `tgm/perp-token-screener`, `tgm/perp-tokens`
#     * `profiler/address/perp-positions`, `profiler/address/perp`, `perp-positions`
#     * `portfolio/positions`, `profiler/address/portfolio`, `portfolio/address/positions`
#       -> DeFi-позиций по адресу у Nansen нет ни под одним из проверенных путей.
#
# ЧЕМУ ЭТО УЧИТ, И ЭТО ДОРОЖЕ ДВУХ ВОССТАНОВЛЕННЫХ РУЧЕК: «404» НЕ РАВНО «ФИЧИ НЕТ». Я удалил
# рабочую функциональность на один день, потому что поверил первому коду ответа. Правильный
# порядок - сперва перебрать соседние пути (это дешево: 404 кредитов не стоит), и только потом
# хоронить. И наоборот: 422 - это ХОРОШАЯ новость, потому что отвечает только существующая
# ручка, и она же говорит, чего ей не хватает.
# ═══════════════════════════════════════════════════════════════════════════════


def perp_screener(per_page=15, order_field="volume_24h", days=1):
    """Перп-токены по объёму и активности smart money. -> [dict].

    ПУТЬ БЕЗ ПРЕФИКСА `tgm/`, И ЭТО СНЯТО ПРОБОЙ, А НЕ УГАДАНО: `tgm/perp-screener` отвечает
    404, а `perp-screener` - 422 с требованием поля `date`. Обязательное окно даты и есть всё,
    чего ему не хватало."""
    return _rows(_post_fix("perp-screener",
                           {"date": _date_range(days),
                            "pagination": {"page": 1, "per_page": per_page},
                            "order_by": [{"field": order_field, "direction": "DESC"}]},
                           ckey=f"perpscr:{per_page}:{order_field}:{days}"))


def profiler_perp_positions(address):
    """Позиции, PnL и здоровье счёта адреса на перпах. -> dict | None.

    ЗДОРОВЬЕ СЧЁТА - ТО, ЧЕГО НЕ БЫЛО: раньше мы видели позиции кита, но не его запас до
    ликвидации, а это и есть главный вопрос про кита с плечом.

    ПУТЬ `profiler/perp-positions`, БЕЗ `address/` В СЕРЕДИНЕ И БЕЗ `pagination` В ТЕЛЕ - оба
    факта из пробы 20.09: прежний путь даёт 404, а этот отвечает 422 «Field 'pagination' is not
    recognized», то есть живёт и разбирает тело. Пагинацию не посылаем вовсе."""
    rows = _rows(_post_fix("profiler/perp-positions", {"address": address},
                           ckey=f"pperp:{address}"))
    return rows[0] if rows else None


def perp_positions(token, per_page=20):
    """ОТКРЫТЫЕ ПОЗИЦИИ по перп-токену: плечо, PnL, цена ликвидации. -> [dict]. ~5 кр.

    Это то, чего у нас не было ни в каком виде: раньше про ликвидации мы могли только
    догадываться по цене."""
    # ПОЛЕ НАЗЫВАЕТСЯ `token_symbol`, И ЭТО СНЯТО ЖИВОЙ ПРОБОЙ 19.09, а не угадано:
    #   {"error":"Missing field","message":"Required field 'body -> token_symbol' is missing"}
    # Мы посылали `token` - по образцу соседних эндпоинтов, - и получали 422 на каждом тапе.
    # Ремонт по словам площадки остановился здесь честно («нужно обязательное поле
    # token_symbol, а построить его нам нечем») и тем самым НАЗВАЛ имя: построить-то нечем,
    # а вот подставить значение аргумента - как раз есть чем, и теперь оно на месте.
    #
    # `_post_fix` ОСТАЁТСЯ, хотя главное поле известно: про `order_by` и `pagination` этого
    # эндпоинта мы по-прежнему знаем только по образцу соседей. Ремонт стоит ноль, когда
    # чинить нечего, и экономит круг живого прогона, когда есть.
    return _rows(_post_fix("tgm/perp-positions",
                       {"token_symbol": str(token).upper(),
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "position_value_usd", "direction": "DESC"}]},
                       ckey=f"perppos:{token}:{per_page}"))


def perp_pnl_leaderboard(token, per_page=10, days=7):
    """PnL трейдеров по КОНКРЕТНОМУ перп-токену. -> [dict]. ~5 кр."""
    return _rows(_post_fix("tgm/perp-pnl-leaderboard",
                       {"token": str(token).upper(), "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "total_pnl", "direction": "DESC"}]},
                       ckey=f"perppnl:{token}:{per_page}:{days}"))


# ── Smart Money: то, чего не было ─────────────────────────────────────────────
def sm_dex_trades(chains=None, per_page=25):
    """Сделки smart money на DEX за последние 24ч. -> [dict]. ~1-5 кр.

    САМОЕ БЛИЗКОЕ К «ЧТО ОНИ ДЕЛАЮТ ПРЯМО СЕЙЧАС»: netflow это агрегат за окно, а здесь
    отдельные сделки - видно, кто и во что зашёл, а не только итог.

    Схема подтверждена живой пробой 19.09, поэтому обычный `_post`, а не `_post_fix`:
    capped corpus считает один client invocation как один физический запрос; автоматические
    repair-retries здесь могли пробить обещанный hard cap."""
    chains = chains or ["ethereum", "solana", "base"]
    return _rows(_post("smart-money/dex-trades",
                       {"chains": chains,
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "block_timestamp", "direction": "DESC"}]},
                       ckey=f"smdex:{','.join(chains)}:{per_page}"))


def sm_perp_trades(per_page=25):
    """Что smart money торгует на Hyperliquid. -> [dict]. ~1-5 кр.

    СХЕМА ПОДТВЕРЖДЕНА ЖИВОЙ ПРОБОЙ 19.09 (200, строки есть). Поля ответа:
    action, side, type, token_symbol, token_amount, price_usd, value_usd, block_timestamp,
    trader_address, trader_address_label, transaction_hash.
    ВАЖНОЕ ПРО ДЕНЬГИ: размер сделки - `value_usd`, а `price_usd` это ЦЕНА ОДНОГО токена.
    Спутать их значит показать $0.99 вместо $48K, то есть не пустоту, а неверное число -
    поэтому `price_usd` стоит в списке `_NOT_MONEY` и под сумму не берётся никогда."""
    return _rows(_post_fix("smart-money/perp-trades",
                       {"pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "block_timestamp", "direction": "DESC"}]},
                       ckey=f"smperp:{per_page}"))


# ── Profiler: то, чего не было ────────────────────────────────────────────────
def profiler_transactions(address, chain="ethereum", per_page=20, days=30):
    """Транзакции адреса за период. -> [dict]."""
    return _rows(_post("profiler/address/transactions",
                       {"address": address, "chain": _nc(chain), "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"ptx:{chain}:{address}:{per_page}:{days}"))


def profiler_dex_trades(address, chain="ethereum", per_page=20, days=30):
    """Все DEX-сделки адреса. -> [dict]."""
    return _rows(_post("profiler/dex-trades",
                       {"address": address, "chain": _nc(chain), "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"pdex:{chain}:{address}:{per_page}:{days}"))


def profiler_perp_trades(address, per_page=20, days=30):
    """Сделки адреса на Hyperliquid. -> [dict]."""
    return _rows(_post("profiler/address/perp-trades",
                       {"address": address, "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"pperptr:{address}:{per_page}:{days}"))


def profiler_historical_balances(address, chain="ethereum", days=30, per_page=50):
    """Историческиe холдинги адреса: как менялся портфель. -> [dict]. ~5 кр."""
    return _rows(_post("profiler/address/historical-token-balances",
                       {"address": address, "chain": _nc(chain), "date": _date_range(days),
                        "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"phist:{chain}:{address}:{days}:{per_page}"))


# ── Prediction Market: было 4 из 12 ───────────────────────────────────────────
def pm_categories():
    """Агрегированная статистика по всем категориям рынков. -> [dict]."""
    return _rows(_post("prediction-market/categories", {}, ckey="pmcat"))


def pm_events(query="", per_page=15):
    """События Polymarket (событие = группа рынков). -> [dict]."""
    return _rows(_post("prediction-market/events",
                       {"query": query or "", "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "volume_24hr", "direction": "DESC"}]},
                       ckey=f"pmev:{query}:{per_page}"))


def pm_orderbook(market_id):
    """Стакан рынка. -> dict {'bids': [...], 'asks': [...]} | None.

    СТАКАН ОТВЕЧАЕТ НА ВОПРОС, КОТОРЫЙ ЦЕНА НЕ ОТВЕЧАЕТ: «45%» при пустом стакане и «45%»
    при плотном - разные вещи, и вторая половина видна только здесь.

    ФОРМА ОТВЕТА СНЯТА ЖИВОЙ ПРОБОЙ 20.09, И ОНА НЕ ТА, ЧТО МЫ ЖДАЛИ. Приходит ПЛОСКИЙ СПИСОК
    уровней (asset_id, market_id, outcome, outcome_index, price, side, size, cumulative_size,
    snapshot_timestamp), а не словарь с `bids`/`asks`. Прежний код брал `rows[0]`, то есть ОДИН
    уровень, форматтер не находил в нём ни bids, ни asks и возвращал None - человек читал
    «стакана нет» на живом стакане из десяти уровней. Отказ, которого не было.

    Группируем по `side` здесь, а не в форматтере: форма ответа - дело клиента, и знать о ней
    должен один слой.
    """
    j = _post_fix("prediction-market/orderbook", {"market_id": str(market_id)},
              ckey=f"pmob:{market_id}")
    if isinstance(j, dict) and (j.get('bids') or j.get('asks')):
        return j
    rows = _rows(j)
    if not rows:
        return None
    bids, asks = [], []
    for r in rows:
        if not isinstance(r, dict):
            continue
        _shape('orderbook-level', r)
        _sd = str(_first(r, ('side', 'order_side')) or '').upper()
        (bids if _sd.startswith('B') else asks).append(r)
    if not bids and not asks:
        return None
    # ЛУЧШИЕ УРОВНИ СВЕРХУ: покупка по убыванию цены, продажа по возрастанию. Иначе «глубина»
    # считается по случайным пяти уровням, а не по тем, по которым правда исполнится сделка.
    try:
        bids.sort(key=lambda r: -(_num_or_none(r.get('price')) or 0))
        asks.sort(key=lambda r: (_num_or_none(r.get('price')) or 0))
    except TypeError:
        pass
    return {'bids': bids, 'asks': asks}


def pm_ohlcv(market_id, outcome_index=0):
    """Свечи рынка: как менялась вероятность. -> [dict], ОДИН исход, по времени.

    ЭТО ГОТОВЫЙ РЯД ДЛЯ ГРАФИКА - то, из чего рисуется картинка «вероятность во времени».

    ДВА ИСПРАВЛЕНИЯ ПО ЖИВОЙ ПРОБЕ 20.09, И ВТОРОЕ ВАЖНЕЕ ПЕРВОГО:
      1. поля `hours` эндпоинт НЕ ЗНАЕТ - ремонт по словам площадки убрал его сам, здесь
         результат пришпилен, чтобы не платить за это на каждом холодном старте;
      2. в ответе приходят свечи ОБОИХ исходов сразу (в строках есть `outcome_index`, `side`,
         `token_id`). Отдать их графику как один ряд значит нарисовать ломаную, которая
         прыгает между «да» и «нет» - линию, которой на рынке не существовало. Это не
         неточность, а выдуманный график, поэтому фильтр здесь, а не «потом в картинке».

    Сортировка по времени тоже здесь: порядок строк площадка не обещает, а график по
    перемешанному ряду - это шум, выданный за динамику.
    """
    rows = _rows(_post_fix("prediction-market/ohlcv",
                       {"market_id": str(market_id)},
                       ckey=f"pmohlcv:{market_id}"))
    if not rows:
        return []
    _want = int(outcome_index)
    _one = [r for r in rows if isinstance(r, dict)
            and _num_or_none(r.get('outcome_index')) in (None, float(_want))]
    # ЕСЛИ ФИЛЬТР УБРАЛ ВСЁ - отдаём как приехало, а не пустоту: возможно, поля исхода в
    # ответе нет вовсе, и тогда ряд и так один.
    _one = _one or [r for r in rows if isinstance(r, dict)]
    try:
        _one.sort(key=lambda r: str(r.get('period_start') or r.get('timestamp') or ''))
    except TypeError:
        pass
    return _one


def pm_market_trades(market_id, per_page=20):
    """Недавние сделки рынка. -> [dict]."""
    return _rows(_post_fix("prediction-market/trades",
                       {"market_id": str(market_id),
                        "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"pmtr:{market_id}:{per_page}"))


def pm_wallet_trades(address, per_page=20):
    """Сделки кошелька по всем рынкам. -> [dict]."""
    return _rows(_post("prediction-market/wallet-trades",
                       {"address": address, "pagination": {"page": 1, "per_page": per_page}},
                       ckey=f"pmwtr:{address}:{per_page}"))


def pm_top_holders(market_id, per_page=10):
    """Крупнейшие держатели позиций рынка. -> [dict].

    «Кто на той стороне» - вопрос, который на предсказательном рынке важнее цены."""
    return _rows(_post("prediction-market/top-holders",
                       {"market_id": str(market_id),
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "position_size", "direction": "DESC"}]},
                       ckey=f"pmth:{market_id}:{per_page}"))


# `pm_holders_positions` УДАЛЁН: `prediction-market/holders-positions` отвечает 404 (живая
# проба 20.09, вместе со свежим market_id из скринера - то есть дело не в id). Четвёртый
# похороненный эндпоинт. Клиента без данных не держим: он выглядит как работающая фича при
# чтении файла. Держатели рынка есть в `pm_top_holders`, и экран репутации стоит на нём.


# ── Backtesting: было 2 из 11 ─────────────────────────────────────────────────
def hist_who_bought_sold(chain, token_address, day, buy_or_sell="BUY", per_page=10):
    """Кто покупал/продавал токен В КОНКРЕТНЫЙ ДЕНЬ (бэктест). -> [dict]. 5 кр.

    ЗАЧЕМ ЭТО ВАЖНО ДЛЯ ДЕНЕГ: сигнал «умные деньги заходят» мы собирали посуточным
    `historical_flow_summary_day` - 5 кредитов ЗА ДЕНЬ, то есть 450 за 90 дней. Здесь тот же
    вопрос за те же 5 кредитов, но с ИМЕНАМИ покупателей, а не только с итогом."""
    d = str(day)[:10]
    return _rows(_post_beta("tgm/historical-who-bought-sold",
                            {"chain": _nc(chain), "token_address": token_address,
                             "buy_or_sell": buy_or_sell,
                             "date_range": {"from": d, "to": d},
                             "pagination": {"page": 1, "per_page": per_page}},
                            ckey=f"hwbs:{chain}:{token_address}:{buy_or_sell}:{d}:{per_page}",
                            ttl=30 * 24 * 3600))


def hist_top_holders(chain, token_address, day, per_page=20):
    """Топ-холдеры токена НА ДАТУ. -> [dict]. 25 кр."""
    d = str(day)[:10]
    return _rows(_post_beta("tgm/historical-top-holders",
                            {"chain": _nc(chain), "token_address": token_address,
                             "as_of_date": d,
                             "pagination": {"page": 1, "per_page": per_page}},
                            ckey=f"hth:{chain}:{token_address}:{d}:{per_page}",
                            ttl=30 * 24 * 3600))


def hist_quant_scores(chain, token_address, day):
    """Квант-скоры токена НА ДАТУ (риск/награда в прошлом). -> dict | None. 25 кр."""
    d = str(day)[:10]
    rows = _rows(_post_beta("tgm/historical-token-quant-scores",
                            {"chain": _nc(chain), "token_address": token_address,
                             "as_of_date": d},
                            ckey=f"hqs:{chain}:{token_address}:{d}",
                            ttl=30 * 24 * 3600))
    return rows[0] if rows else None


def hist_token_screener(day, chains=None, per_page=20):
    """Скринер токенов НА ДАТУ: что было в топе тогда. -> [dict]. 5 кр."""
    d = str(day)[:10]
    chains = chains or ["ethereum", "solana", "base"]
    return _rows(_post_beta("token-screener/historical",
                            {"chains": chains, "as_of_date": d,
                             "pagination": {"page": 1, "per_page": per_page}},
                            ckey=f"hscr:{','.join(chains)}:{d}:{per_page}",
                            ttl=30 * 24 * 3600))


# ═══════════════════════════════════════════════════════════════════════════
# SPOT TRADING (/api/v1/trade/*) — СВОП ЧЕРЕЗ АГРЕГАТОРЫ, ПОДПИСЬ НАШИМ КЛЮЧОМ
#
# «КОШЕЛЬКА NANSEN» НЕ СУЩЕСТВУЕТ, и это первое, что надо понять про этот раздел. Nansen
# здесь не кастодиан и не биржа: он сравнивает маршруты у агрегаторов, собирает НЕПОДПИСАННУЮ
# транзакцию и принимает уже подписанную обратно, чтобы отправить в сеть. Приватный ключ к
# нему не уходит ни на каком шаге, депозита «на счёт Nansen» не нужно вовсе, и торговать можно
# с ЛЮБОГО своего адреса. Экран с «Deposit Funds» в их вебе - это другое: перпы Hyperliquid,
# где депозит правда нужен.
#
# ЧТО ЭТО СТОИТ: кредитов НОЛЬ (docs: «Trading endpoints do not consume plan credits»).
# Платим только ончейн-фи и роутинг самой сделки. Поэтому лимиты Nansen сюда не применяются -
# ограничение здесь ДЕНЕЖНОЕ, и живёт оно в `trade_cap_usd()`.
#
# ГРАНИЦЫ ПЛОЩАДКИ (docs/api/trade/spot-trading): только solana и base; хотя бы одна сторона
# свопа обязана быть USDC или нативным токеном (SOL/ETH), «мем в мем» не маршрутизируется -
# сначала в USDC; кросс-чейн от ~$5; 403 по юрисдикции и по санкционным спискам.
#
# `quote` - GET С QUERY-ПАРАМЕТРАМИ, а не POST. Единственный такой эндпоинт во всём клиенте,
# и перепутать легко: остальные шестьдесят - POST с JSON.
# ═══════════════════════════════════════════════════════════════════════════
_TRADE = "https://api.nansen.ai/api/v1/trade"

#: адреса, которые нужны на каждом свопе (docs). Держим здесь, чтобы не искать в чате.
NATIVE = {'base': '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
          'solana': 'So11111111111111111111111111111111111111112'}
USDC = {'base': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
        'solana': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'}
DECIMALS = {'sol': 9, 'eth': 18, 'usdc': 6}

TRADE_CHAINS = ('solana', 'base')


def trade_cap_usd():
    """Потолок ОДНОЙ сделки в долларах. Ручка админа, дефолт по решению Ren - 300."""
    try:
        import admin_config as _ac
        return _ac.int_value(_ac.K_NANSEN_TRADE_CAP, 300)
    except Exception as e:
        print('[nansen] потолок сделки не прочитан (%s) - беру 300' % str(e)[:80])
        return 300


def base_units(amount, decimals):
    """Человеческую сумму -> базовые единицы СТРОКОЙ, как требует площадка. -> str.

    ЦЕЛОЕ ЧИСЛО И СТРОКА, А НЕ float: 0.1 USDC в float это 0.09999999999999999, и в базовых
    единицах такая ошибка становится расхождением на единицы - а суммы тут настоящие.
    Поэтому через Decimal и без экспоненты."""
    from decimal import Decimal, ROUND_DOWN
    q = (Decimal(str(amount)) * (Decimal(10) ** int(decimals))).quantize(Decimal(1), ROUND_DOWN)
    return str(int(q))


def trade_quote(chain, from_token, to_token, amount_units, wallet, to_chain=None,
                to_wallet=None, slippage_bps=50, timeout=45):
    """Квоты на своп. -> (список квот, reason). Кредитов НЕ стоит.

    ЭТО ЕДИНСТВЕННЫЙ GET В КЛИЕНТЕ (docs: /trade/quote с query-параметрами). `amount_units` -
    строка в базовых единицах, готовить её должен `base_units`."""
    if chain not in TRADE_CHAINS:
        return [], 'badreq'
    if not _key():
        _tele.note('nokey')
        return [], 'nokey'
    _tele.clear()
    params = {'chain': chain, 'from_token': from_token, 'to_token': to_token,
              'amount': str(amount_units), 'wallet_address': wallet,
              'slippage': int(slippage_bps)}
    if to_chain:
        params['to_chain'] = to_chain
    if to_wallet:
        params['to_wallet_address'] = to_wallet
    t0 = time.time()
    http, j = 0, None
    try:
        r = httpx.get('%s/quote' % _TRADE, headers=_headers(), params=params, timeout=timeout)
        http = r.status_code
        _note_credits(r.headers)
        if http != 200:
            print('[nansen trade] quote HTTP %s: %s | %s' % (http, r.text[:200], params))
            _tele.note(_classify(http), http, 'trade/quote')
        else:
            j = r.json()
            _tele.note_age(0)
            _tele.note('ok', http, 'trade/quote')
    except Exception as e:
        print('[nansen trade] quote: %s' % e)
        _tele.note('timeout' if isinstance(e, httpx.TimeoutException) else 'http', 0,
                   'trade/quote')
    # СТРОКУ ТЕЛЕМЕТРИИ ПИШЕМ, А КРЕДИТЫ НЕ СЧИТАЕМ: у торговых эндпоинтов их нет, и
    # приписать им цену значило бы завысить расход конкурса на сделках.
    _tele.record('trade/quote', ms=int((time.time() - t0) * 1000), http=http,
                 ok=(http == 200), empty=not (j or {}).get('quotes') if http == 200 else False,
                 cache=False, rem=None, used=None)
    quotes = (j or {}).get('quotes') or []
    if http == 200 and not quotes:
        # 400 у них означает «маршрута нет», но и пустой список тоже возможен
        return [], 'empty'
    return quotes, ('ok' if quotes else fail_reason('empty'))


def trade_prepare(chain, wallet, quote, skip_simulation=False, timeout=60):
    """Квота -> транзакция, готовая к подписи. -> (dict, reason). Кредитов НЕ стоит.

    СИМУЛЯЦИЯ ЗДЕСЬ И ЕСТЬ ПРЕДПРОСМОТР: `simulationPassed` в ответе говорит, прошла бы
    сделка, и это ЕДИНСТВЕННЫЙ способ проверить её, ничего не отправляя. `skip_simulation`
    оставлен параметром, но по умолчанию False: пропускать проверку, которая ловит отказ до
    траты подписи, здесь незачем."""
    if not _key():
        return {}, 'nokey'
    _tele.clear()
    body = {'chain': chain, 'wallet_address': wallet, 'quote': quote,
            'skip_simulation': bool(skip_simulation)}
    j, http = _http_post(_TRADE, 'prepare', body, timeout, ' trade')
    if http != 200 or not isinstance(j, dict):
        return {}, fail_reason('http')
    return j, 'ok'


def trade_execute(chain, signed_transaction, request_id=None, timeout=90):
    """Отправить ПОДПИСАННУЮ транзакцию в сеть. -> (dict, reason). Кредитов НЕ стоит.

    ⚠️ У ЭТОГО ВЫЗОВА НЕТ СУХОГО РЕЖИМА. Документация говорит прямо: каждый вызов, прошедший
    валидацию, отправляет транзакцию в сеть, и успешный ответ означает СОСТОЯВШУЮСЯ сделку с
    настоящими деньгами; ни одно поле запроса этого не отменяет. Поэтому звать её имеет право
    только путь, где человек уже нажал подтверждение на карточке с числами."""
    if not _key():
        return {}, 'nokey'
    _tele.clear()
    body = {'signed_transaction': signed_transaction, 'chain': chain}
    if request_id:
        body['request_id'] = request_id
    j, http = _http_post(_TRADE, 'execute', body, timeout, ' trade')
    if http != 200 or not isinstance(j, dict):
        return {}, fail_reason('http')
    return j, 'ok'


def trade_bridge_status(chain, tx_hash, timeout=45):
    """Судьба кросс-чейн свопа по хэшу исходной сети. -> (dict, reason)."""
    if not _key():
        return {}, 'nokey'
    j, http = _http_post(_TRADE, 'bridge-status',
                         {'chain': chain, 'tx_hash': tx_hash}, timeout, ' trade')
    if http != 200 or not isinstance(j, dict):
        return {}, fail_reason('http')
    return j, 'ok'


def _money(x):
    """Деньги С КОПЕЙКАМИ. -> str.

    `_usd` округляет до целых, и для витрины это верно («приток $231.9K»), а для карточки
    ПОДТВЕРЖДЕНИЯ - нет: газ $0.12 печатался как «$0», а получаемая сумма $298.40 как «$298».
    Человек подтверждает ТО, ЧТО ВИДИТ, и округление в карточке сделки это не косметика, а
    расхождение между подтверждённым и отправленным."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return '?'
    if abs(x) >= 1e6:
        return '%.2fM' % (x / 1e6)
    if abs(x) >= 1000:
        return '%,.2f'.replace(',', '') % x if False else '{:,.2f}'.format(x)
    if abs(x) >= 1:
        return '%.2f' % x
    return '%.4f' % x          # газ и мелочь: $0.0012 это не «$0.00»


def perp_positions_block(rows, token, lang='ru'):
    """Открытые позиции по перп-токену: плечо и ЦЕНА ЛИКВИДАЦИИ. -> str | None.

    ЛИКВИДАЦИЯ - ГЛАВНОЕ ЧИСЛО ЗДЕСЬ, и до этого эндпоинта его у нас не было вовсе: про
    ликвидации мы могли только догадываться по цене входа."""
    if not rows:
        return None
    _t = ('⚡ <b>Открытые позиции · %s</b>' % token) if lang != 'en' else \
         ('⚡ <b>Open positions · %s</b>' % token)
    L = [_t]
    _shown, _with_val, _first_row = 0, 0, None
    for i, r in enumerate(rows[:12], 1):
        if not isinstance(r, dict):
            continue
        _shape('perp-positions', r)
        if _first_row is None:
            _first_row = r
        _shown += 1
        who = _who(r)
        side = (_first(r, ('side', 'direction', 'position_side')) or '').upper()[:5]
        # ТА ЖЕ ПОДСТРАХОВКА ПО СОГЛАШЕНИЮ ИМЁН, что в смарт-сделках: схема этого эндпоинта
        # живым ключом не снята, и три угаданных имени могут не совпасть ни одним.
        val, _vf = _usd_any(r, ('position_value_usd', 'notional_usd', 'value_usd'))
        if val not in (None, ''):
            _with_val += 1
        lev = _first(r, ('leverage', 'leverage_x'))
        liq = _first(r, ('liquidation_price', 'liq_price'))
        pnl = _first(r, ('unrealized_pnl', 'unrealized_pnl_usd', 'pnl_usd'))
        seg = []
        if val not in (None, ''):
            seg.append('$%s' % _usd(val))
        if lev not in (None, ''):
            try:
                seg.append('%.0fx' % float(lev))
            except (TypeError, ValueError):
                pass
        if pnl not in (None, ''):
            try:
                seg.append(('PnL +$' if float(pnl) >= 0 else 'PnL -$') + _usd(abs(float(pnl))))
            except (TypeError, ValueError):
                pass
        if liq not in (None, ''):
            try:
                seg.append(('ликв. $%s' if lang != 'en' else 'liq $%s') % _money(float(liq)))
            except (TypeError, ValueError):
                pass
        L.append('%d. %s%s · %s' % (i, who, (' [%s]' % side) if side else '',
                                    ' · '.join(seg) or '?'))
    if len(L) == 1:
        return None
    if _shown and not _with_val:
        L.append('\n' + schema_gap_note(_first_row, 'Размер позиции' if lang != 'en'
                                        else 'Position size', lang))
    return with_source('\n'.join(L), lang)


# ФОРМАТТЕР ВЕРНУЛСЯ ИЗ GIT ВМЕСТЕ СО СВОИМ ЭНДПОИНТОМ (проба путей 20.09 нашла его живым
# по адресу `profiler/perp-positions`). Он никуда не пропадал - удалён был на день, и это
# ровно то, зачем удалять честно: вернуть из истории дешевле, чем переписывать.
def wallet_perp_block(d, address, lang='ru'):
    """Счёт кошелька на перпах: позиции, PnL и ЗАПАС ДО ЛИКВИДАЦИИ. -> str | None.

    Запас до ликвидации - тот вопрос про кита с плечом, на который мы раньше не отвечали:
    позиции видели, а сколько ему осталось - нет."""
    if not isinstance(d, dict) or not d:
        return None
    _shape('wallet-perp', d)
    short = '%s…%s' % (address[:6], address[-4:])
    L = [('🩺 <b>Счёт на перпах</b> <code>%s</code>' % short) if lang != 'en'
         else ('🩺 <b>Perp account</b> <code>%s</code>' % short)]
    eq = _first(d, ('account_value', 'equity', 'account_value_usd'))
    mar = _first(d, ('margin_used', 'margin_used_usd', 'total_margin_used'))
    pnl = _first(d, ('unrealized_pnl', 'unrealized_pnl_usd'))
    health = _first(d, ('account_health', 'health', 'margin_ratio'))
    seg = []
    if eq not in (None, ''):
        seg.append(('капитал $%s' if lang != 'en' else 'equity $%s') % _usd(eq))
    if mar not in (None, ''):
        seg.append(('под залогом $%s' if lang != 'en' else 'margin $%s') % _usd(mar))
    if pnl not in (None, ''):
        try:
            seg.append(('нереализ. +$' if float(pnl) >= 0 else 'нереализ. -$') + _usd(abs(float(pnl)))
                       if lang != 'en' else
                       ('unrealized +$' if float(pnl) >= 0 else 'unrealized -$') + _usd(abs(float(pnl))))
        except (TypeError, ValueError):
            pass
    if seg:
        L.append('📈 ' + ' · '.join(seg))
    if health not in (None, ''):
        L.append(('🩺 здоровье счёта: %s' if lang != 'en' else '🩺 account health: %s') % health)
    pos = d.get('positions') if isinstance(d.get('positions'), list) else []
    for p in pos[:8]:
        if not isinstance(p, dict):
            continue
        _c = _first(p, ('coin', 'token', 'symbol')) or '?'
        _sd = (_first(p, ('side', 'direction')) or '').upper()[:5]
        _lv = _first(p, ('leverage', 'leverage_x'))
        _lq = _first(p, ('liquidation_price', 'liq_price'))
        _bits = [x for x in (
            ('%sx' % int(float(_lv))) if _lv not in (None, '') else None,
            (('ликв. $%s' if lang != 'en' else 'liq $%s') % _money(_lq))
            if _lq not in (None, '') else None) if x]
        L.append('• %s %s %s' % (_c, _sd, ' · '.join(_bits)))
    if len(L) == 1:
        return None
    return with_source('\n'.join(L), lang)


def sm_trades_block(rows, bot_un=None, lang='ru', top=12):
    """Сделки smart money за последние сутки. -> str | None.

    ОТЛИЧИЕ ОТ NETFLOW, И ОНО СУЩЕСТВЕННОЕ: netflow это итог за окно («набрали на 231К»), а
    здесь отдельные сделки - видно, КТО и во ЧТО зашёл, а не только сумма."""
    if not rows:
        return None
    L = [('🧠 <b>Сделки smart money за сутки</b>' if lang != 'en'
          else '🧠 <b>Smart money trades, 24h</b>')]
    _shown, _with_val, _first_row = 0, 0, None
    for i, r in enumerate(rows[:top], 1):
        if not isinstance(r, dict):
            continue
        _shape('sm-dex-trades', r)
        if _first_row is None:
            _first_row = r
        sym = _first(r, ('token_bought_symbol', 'token_symbol', 'symbol')) or '?'
        addr = (_first(r, ('token_bought_address', 'token_address')) or '').strip()
        # ИМЯ ДЕНЕЖНОГО ПОЛЯ - `trade_value_usd`, СНЯТО ЖИВОЙ ПРОБОЙ 19.09. Раньше здесь
        # стояли три имени, угаданных по соседним эндпоинтам, ни одно не совпало, и человек
        # видел прочерк во всех двенадцати строках. Поиск по соглашению (`*_usd`) оставлен
        # вторым этажом: он и нашёл бы это поле, но названное имя не требует перебора и не
        # может однажды выбрать не то поле.
        val, _vf = _usd_any(r, ('trade_value_usd', 'value_usd', 'volume_usd', 'amount_usd'))
        who = _who(r)
        ch = _first(r, ('chain',)) or ''
        _sym = '<b>%s</b>' % sym
        if bot_un and addr:
            _sym = '<a href="https://t.me/%s?start=tok_%s"><b>%s</b></a>' % (bot_un, addr, sym)
        _shown += 1
        if val not in (None, ''):
            _with_val += 1
        # ═══ КАПИТАЛИЗАЦИЯ И ВОЗРАСТ ТОКЕНА ПРИЕЗЖАЮТ В ЭТОМ ЖЕ ОТВЕТЕ - БЕСПЛАТНО ═══
        # Проба показала, что `smart-money/dex-trades` отдаёт `token_bought_market_cap` и
        # `token_bought_age_days` вместе со сделкой. Мы их не читали, и зря: «$48K зашли в
        # токен» - это ни о чём, пока не сказано, во ЧТО именно. $48K в токен на $2.1M - это
        # 2.3% всей капитализации и настоящий сигнал; те же $48K в токен на $50B - шум.
        # Ровно закон «признак наличия ≠ признак пользы»: раньше строка сообщала ФАКТ покупки,
        # теперь - ВЕЛИЧИНУ относительно размера токена. Дополнительных запросов ноль.
        _mc = _first(r, ('token_bought_market_cap', 'market_cap'))
        _age = _first(r, ('token_bought_age_days', 'age_days'))
        _tail = []
        if _mc not in (None, ''):
            try:
                _tail.append(('капа $%s' if lang != 'en' else 'mcap $%s') % _usd(_mc))
                if val not in (None, '') and float(_mc) > 0:
                    _pct = 100.0 * float(val) / float(_mc)
                    if _pct >= 0.1:
                        _tail.append(('%.1f%% капы' if lang != 'en' else '%.1f%% of mcap')
                                     % _pct)
            except (TypeError, ValueError):
                pass
        if _age not in (None, ''):
            try:
                _tail.append(('%dд' if lang != 'en' else '%dd') % int(float(_age)))
            except (TypeError, ValueError):
                pass
        L.append('%d. %s %s%s · $%s%s'
                 % (i, who, _sym, (' [%s]' % ch) if ch else '',
                    _usd(val) if val not in (None, '') else '?',
                    (' · ' + ' · '.join(_tail)) if _tail else ''))
    if len(L) == 1:
        return None
    # ПРОЧЕРК В КАЖДОЙ СТРОКЕ - НЕ ОТВЕТ. Если суммы не нашлось НИ У ОДНОЙ строки, это не
    # свойство сделок, а расхождение схемы, и оно называется вслух вместе с именами полей,
    # которые площадка правда прислала. Иначе человек читает «$?» как «объём неизвестен
    # рынку» и делает вывод по пустоте.
    if _shown and not _with_val:
        L.append('\n' + schema_gap_note(_first_row, 'Объём сделки' if lang != 'en'
                                        else 'Trade size', lang))
    L.append('\n' + ('Тапни тикер — открою карточку.' if lang != 'en'
                     else 'Tap a ticker for the card.'))
    return with_source('\n'.join(L), lang)


def pm_orderbook_block(ob, market_id, lang='ru', depth=5):
    """Стакан рынка Polymarket. -> str | None.

    ЗАЧЕМ СТАКАН, ЕСЛИ ЕСТЬ ЦЕНА: «45%» при пустом стакане и «45%» при плотном - разные
    вещи. Цена говорит, во что верят; стакан - сколько это стоит проверить деньгами."""
    if not isinstance(ob, dict) or not ob:
        return None
    _shape('orderbook', ob)
    bids = ob.get('bids') or ob.get('buy') or []
    asks = ob.get('asks') or ob.get('sell') or []
    if not bids and not asks:
        return None
    L = [('📖 <b>Стакан рынка</b> <code>%s</code>' % market_id) if lang != 'en'
         else ('📖 <b>Orderbook</b> <code>%s</code>' % market_id)]

    # ═══ РАЗМЕР В СТАКАНЕ - ЭТО ДОЛИ, А НЕ ДОЛЛАРЫ ═══
    # Третий случай одного и того же класса за два дня (после держателей рынка и после
    # смарт-сделок): поле `size` печаталось со знаком $, и «глубина покупки $4.2K» на деле
    # означала 4200 ДОЛЕЙ. Доля тут стоит 43-47 центов, то есть ошибка вдвое - и в строке,
    # ради которой экран и открывают.
    # Доллары считаем сами, из того же уровня: цена × доли. Доли печатаем без знака валюты.
    def _side(rows, title):
        out = ['\n<b>%s</b>' % title]
        _usd_tot, _sh_tot = 0.0, 0.0
        for r in (rows or [])[:depth]:
            if not isinstance(r, dict):
                continue
            p = _num_or_none(_first(r, ('price', 'p')))
            sz = _num_or_none(_first(r, ('size', 'quantity', 's')))
            if p is None or sz is None:
                continue
            _sh_tot += sz
            _usd_tot += p * sz
            out.append(('%.0f%% · %s долей ($%s)' if lang != 'en'
                        else '%.0f%% · %s shares ($%s)')
                       % (p * (100 if p <= 1 else 1), _usd(sz), _usd(p * sz)))
        return out, _usd_tot, _sh_tot

    _b, _bt, _bs = _side(bids, 'Заявки на покупку' if lang != 'en' else 'Bids')
    _a, _at, _as = _side(asks, 'Заявки на продажу' if lang != 'en' else 'Asks')
    L += _b + _a
    if _bt or _at:
        L.append('\n' + (('Глубина в деньгах: покупка $%s против продажи $%s'
                          if lang != 'en' else 'Depth in money: bids $%s vs asks $%s')
                         % (_usd(_bt), _usd(_at))))
        L.append(('<i>Доллары посчитаны как цена × доли: в ответе их нет.</i>' if lang != 'en'
                  else '<i>Dollars are computed as price × shares: the response has none.</i>'))
    return with_source('\n'.join(L), lang)


def quote_card(q, chain, sell_sym='', buy_sym='', lang='ru'):
    """Карточка квоты ЧИСЛАМИ, по которым человек принимает решение. -> str.

    ЧЕЛОВЕК ПОДТВЕРЖДАЕТ ТО, ЧТО ВИДИТ. Числа берутся из САМОЙ квоты, а не пересчитываются
    нами заново: пересчёт разошёлся бы с тем, что уйдёт в сеть, и подтверждение перестало бы
    относиться к сделке."""
    def _g(*names):
        for n in names:
            v = q.get(n) if isinstance(q, dict) else None
            if v not in (None, ''):
                return v
        return None
    _in = _g('fromAmountUsd', 'from_amount_usd', 'sellAmountUsd', 'amountInUsd')
    _out = _g('toAmountUsd', 'to_amount_usd', 'buyAmountUsd', 'amountOutUsd')
    _prov = _g('provider', 'aggregator', 'source', 'dex') or '?'
    _impact = _g('priceImpact', 'price_impact', 'priceImpactPct')
    _gas = _g('gasUsd', 'gas_usd', 'estimatedGasUsd')
    _min = _g('minAmountOut', 'min_amount_out', 'minReceived')
    L = ['💱 <b>Своп</b> %s → %s · %s' % (sell_sym or '?', buy_sym or '?', chain)]
    if _in is not None:
        L.append('Отдаём: <b>$%s</b>' % _money(_in))
    if _out is not None:
        L.append('Получаем: <b>$%s</b>' % _money(_out))
    if _impact not in (None, ''):
        try:
            L.append('Влияние на цену: %.2f%%' % (float(_impact) * (100 if abs(float(_impact)) < 1 else 1)))
        except (TypeError, ValueError):
            pass
    if _gas not in (None, ''):
        L.append('Газ примерно: $%s' % _money(_gas))
    if _min not in (None, ''):
        L.append('Минимум к получению: %s' % _min)
    L.append('Маршрут: %s' % _prov)
    L.append('')
    L.append('<i>Отправка идёт ТОЛЬКО по твоему подтверждению. Ключ не покидает сервер: '
             'Nansen отдаёт неподписанную транзакцию, подпись локальная.</i>')
    return with_source('\n'.join(L), lang)


# ═══════════════════════════════════════════════════════════════════════════
# PREDICTION MARKET (Polymarket) — отдельная категория Nansen API.
# Пути /api/v1/prediction-market/*. Nansen пока покрывает только Polymarket.
# Рынок (market_id) = один Yes/No вопрос; цена 0..1 = вероятность.
# ═══════════════════════════════════════════════════════════════════════════
def pm_market_screener(query="", status="active", tags=None, per_page=12,
                       order_field="volume_24hr"):
    """Трендовые/активные рынки Polymarket (сорт по объёму/ликвидности). -> [dict]."""
    body = {"order_by": [{"direction": "DESC", "field": order_field}],
            "query": query or "", "status": status or "active",
            "pagination": {"page": 1, "per_page": per_page}}
    if tags:
        body["tags"] = tags
    return _rows(_post("prediction-market/market-screener", body,
                       ckey=f"pmscr:{query}:{status}:{order_field}:{per_page}"))


def pm_address_summary(address, timeout=10):
    """Лайфтайм-сводка кошелька на Polymarket. -> dict | None.

    10 секунд, а не общий 60-секундный timeout: reputation-screen спрашивает пять адресов
    параллельно и обязан уложиться в 30–60-секундное demo. Один зависший адрес не должен
    держать весь экран минуту.
    """
    j = _post("prediction-market/address-summary",
              {"address": address, "pagination": {"page": 1, "per_page": 10}},
              ckey=f"pmsum:{address}", timeout=timeout)
    if j is None:
        return None
    expected = {'win_rate', 'winrate', 'win_rate_pct', 'total_pnl_usd', 'markets_traded',
                'wallet_age_days', 'address'}
    # Терпим три подтверждённые формы: список, {data:[...]}/{result:[...]}, прямой объект.
    if isinstance(j, dict) and expected.intersection(j):
        return j
    rows = _rows(j)
    if isinstance(rows, dict) and expected.intersection(rows):
        return rows
    if isinstance(rows, list):
        if not rows and (isinstance(j, list) or
                         (isinstance(j, dict) and ('data' in j or 'result' in j))):
            return None                         # распознанная честная пустота
        if rows and isinstance(rows[0], dict) and expected.intersection(rows[0]):
            return rows[0]
    # НЕПУСТОЙ 200 В НЕЗНАКОМОЙ ФОРМЕ — не «у кошелька нет истории». Это schema drift у
    # интеграции; помечаем badreq в текущей worker-сцене, чтобы hero-screen назвал частичный
    # сбой. Имена полей печатаются — следующий фикс займёт один круг, а не три догадки.
    if j not in ({}, [], None):
        keys = sorted(j.keys())[:20] if isinstance(j, dict) else [type(j).__name__]
        print('[nansen] address-summary 200 НЕЗНАКОЙ ФОРМЫ: %s' % keys)
        _tele.note('badreq', 200, 'prediction-market/address-summary')
    return None


def pm_pnl_by_address(address, per_page=10):
    """PnL кошелька по всем рынкам Polymarket (по рынкам). -> [dict]."""
    return _rows(_post("prediction-market/pnl-by-address",
                       {"address": address, "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"direction": "DESC", "field": "total_pnl_usd"}]},
                       ckey=f"pmpnla:{address}:{per_page}"))


def pm_pnl_by_market(market_id, per_page=10):
    """PnL всех трейдеров в конкретном рынке (топ-победители/лузеры). -> [dict]."""
    return _rows(_post("prediction-market/pnl-by-market",
                       {"market_id": str(market_id), "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"direction": "DESC", "field": "total_pnl_usd"}]},
                       ckey=f"pmpnlm:{market_id}:{per_page}"))


def _winrate_pct(wr):
    try:
        wr = float(wr)
    except (TypeError, ValueError):
        return None
    return wr * 100 if wr <= 1 else wr


# ── форматтеры Polymarket для карточек/меню ──
def pm_market_id(row):
    """ID рынка из строки скринера. -> str | None.

    ЗАЧЕМ ОТДЕЛЬНОЙ ФУНКЦИЕЙ. Три экрана Polymarket (график вероятности, стакан,
    топ-трейдеры рынка) принимают `market_id`, и человеку взять его было НЕОТКУДА: подсказка
    в меню обещала «из скринера рынков», а скринер id не печатал вовсе. Обещание источника,
    которого нет, - это та же пустота, выданная за проверку: команда есть, позвать её нельзя.

    Имя поля живым ключом не снято, поэтому сперва названные кандидаты, потом соглашение
    (ключ вида `*_id`/`id`, у которого значение похоже на идентификатор). Не нашли - None, и
    вызывающий обязан сказать это словом, а не подставить пустую строку в кнопку.
    """
    if not isinstance(row, dict):
        return None
    v = _first(row, ('market_id', 'id', 'condition_id', 'conditionId', 'clob_token_id',
                     'token_id', 'market'))
    if v in (None, ''):
        for k in sorted(row.keys()):
            kl = str(k).lower()
            if (kl == 'id' or kl.endswith('_id')) and row.get(k) not in (None, ''):
                v = row.get(k)
                break
    if v in (None, ''):
        return None
    v = str(v)
    # 64 БАЙТА - ПОТОЛОК callback_data ТЕЛЕГРАМА, и id рынка Polymarket бывает 66-символьным
    # хэшем. Поэтому в кнопку едет НЕ id, а номер строки (см. `oc_dm`), а сюда id приходит
    # только для печати человеку. Обрезать его нельзя: обрезанный id - неверный id.
    return v[:80]


def pm_markets_block(query="", top=10, lang='ru', rows=None):
    """Блок «трендовые рынки Polymarket» (по объёму 24ч). -> str | None.

    `rows` СНАРУЖИ - чтобы вызывающий, которому нужны ещё и кнопки, не платил за ВТОРОЙ
    запрос к скринеру и не строил кнопки по своему списку. Один список - один экран: иначе
    номер кнопки «2» однажды укажет на другой рынок, чем строка «2» в тексте.
    """
    if rows is None:
        rows = pm_market_screener(query=query, per_page=top)
    if not rows:
        return None
    head = "🎲 <b>Трендовые рынки Polymarket</b>" + (f" · «{query}»" if query else " (объём 24ч)")
    L = [head + ":"]
    _no_id = 0
    for i, r in enumerate(rows[:top], 1):
        q = (r.get("question") or "?")[:70]
        pr = r.get("last_trade_price")
        try:
            prob = f"{float(pr)*100:.0f}%" if pr not in (None, "") else "?"
        except (TypeError, ValueError):
            prob = "?"
        vol = _usd(r.get("volume_24hr"))
        L.append(f"{i}. <b>{q}</b> · {prob} · vol24 ${vol}")
        # ID ПЕЧАТАЕМ ОТДЕЛЬНОЙ СТРОКОЙ И КОПИРУЕМЫМ: он нужен командам «топ рынка <id>»,
        # «полимаркет график <id>», «полимаркет стакан <id>». Без него эти три команды
        # существовали формально.
        mid = pm_market_id(r)
        if mid:
            L.append("   <code>%s</code>" % mid)
        else:
            _no_id += 1
    if _no_id and _no_id == min(len(rows), top):
        L.append('\n' + schema_gap_note(rows[0], 'ID рынка' if lang != 'en' else 'Market ID',
                                        lang))
    L.append("\nРазбор трейдера: «полимаркет профиль 0x…»." if lang != 'en'
             else "\nTrader breakdown: «полимаркет профиль 0x…».")
    return with_source("\n".join(L), lang)


# ═══════════════════════════════════════════════════════════════════════════════
# РЫНОК, ВЗВЕШЕННЫЙ ПО РЕПУТАЦИИ ДЕРЖАТЕЛЕЙ
#
# ВОПРОС, НА КОТОРЫЙ ЦЕНА НЕ ОТВЕЧАЕТ. «78% Yes» - это консенсус, но КОГО? Предсказательный
# рынок показывает одно число, и оно одинаково выглядит в двух противоположных случаях:
#   * $2.1M на Yes поставили кошельки, которые угадывали в 70% рынков;
#   * те же $2.1M поставили кошельки с винрейтом 35%, то есть толпа, которая систематически
#     ошибается.
# Первое - сигнал, второе - приглашение встать против. Цена их не различает вовсе.
#
# ЭТО ТОТ ЖЕ ЗАКОН «ВЕЛИЧИНА ВМЕСТО ФЛАГА», ПРИМЕНЁННЫЙ К ВЕРОЯТНОСТИ. «Рынок верит в Yes» -
# флаг. «$1.4M из $2.1M на Yes лежат у кошельков с винрейтом ниже 40%» - величина.
#
# ЧЕГО ЗДЕСЬ НЕТ: совета и предсказания. Винрейт в прошлом не обещает будущего, и подпись
# говорит это словами - иначе экран читается как «ставь против толпы», а мы такого не мерили.
#
# ЦЕНА ЭКРАНА НАЗЫВАЕТСЯ ЧЕСТНО И ЧИСЛОМ ЗАПРОСОВ, А НЕ КРЕДИТОВ: цена этих эндпоинтов в
# официальном списке не названа (они в `_EP_UNKNOWN`), и придумать её значило бы соврать в
# самой проверяемой части. Запросов ровно `1 + top`.
# ═══════════════════════════════════════════════════════════════════════════════
#: сколько держателей разбираем по репутации. Пять - не «чтобы дешевле»: на крупных рынках
#: первые пять адресов держат основную часть денег, а шестой-десятый уже не меняют вывод,
#: зато удваивают цену экрана.
PM_REP_TOP = 5
#: винрейт, ниже которого деньги считаются «деньгами тех, кто чаще ошибался». 40% - не
#: истина, а ПОРОГ ДЛЯ АРИФМЕТИКИ, и он назван в тексте, чтобы человек мог не согласиться.
PM_WEAK_WR = 40.0


def pm_holder_side(row):
    """Сторону держателя - словом. -> str ('Yes'/'No'/имя исхода/'?').

    Отдельной функцией, потому что имя поля у этого эндпоинта живым ключом не снято, а сторона
    здесь - половина смысла: «$800K у кошелька с винрейтом 30%» без стороны не говорит НИЧЕГО.
    """
    v = _first(row, ('outcome', 'outcome_name', 'side', 'position_side', 'token_outcome'))
    if v in (None, ''):
        i = _first(row, ('outcome_index', 'outcomeIndex'))
        if i in (None, ''):
            return '?'
        try:
            return 'Yes' if int(i) == 0 else 'No'
        except (TypeError, ValueError):
            return '?'
    return str(v)[:12]


def pm_reputation(market_id, top=PM_REP_TOP):
    """Кто держит рынок и КАК ОНИ УГАДЫВАЛИ РАНЬШЕ. -> dict | None.

    Запросов: 1 (держатели) + top (лайфтайм-сводка каждого). Обе схемы подтверждены живой
    пробой 20.09. Истории кошельков идут параллельно с timeout 15с; каждый отказ возвращается
    отдельным классом и НЕ превращается в «истории у кошелька нет».

    -> {'holders': [...], 'by_side': {...}, 'weak_usd', 'strong_usd', 'known', 'unknown',
        'total_usd', 'calls'} либо None, если держателей не отдали вовсе.

    ЧТО СЧИТАЕТСЯ И ПОЧЕМУ ИМЕННО ТАК:
      * `weak_usd` - деньги держателей с винрейтом НИЖЕ порога. Это и есть главное число;
      * `unknown` - сколько держателей БЕЗ лайфтайм-истории. Их деньги не попадают ни в
        `weak`, ни в `strong`: приписать кошельку винрейт, которого мы не знаем, значит
        подогнать вывод. Число названо отдельно, и вызывающий обязан его показать.
    """
    # СХЕМА ПОДТВЕРЖДЕНА ЖИВОЙ ПРОБОЙ 20.09: тело верное, строки приходят. `order_by` проба
    # проверила и с ним, и без него - работает одинаково, оставляем (сортировка по размеру
    # позиции нам нужна: первые пять адресов и держат основные деньги).
    rows = _rows(_post_fix("prediction-market/top-holders",
                           {"market_id": str(market_id),
                            "pagination": {"page": 1, "per_page": max(int(top) * 2, 10)},
                            "order_by": [{"field": "position_size", "direction": "DESC"}]},
                           ckey=f"pmth:{market_id}:{max(int(top) * 2, 10)}", timeout=10))
    if not rows:
        return None
    holders, calls = [], 1
    by_side, total = {}, 0.0
    for r in rows:
        if not isinstance(r, dict):
            continue
        _shape('pm-top-holders', r)
        addr = _first(r, ('address', 'wallet_address', 'holder_address', 'user_address'))
        # ═══ ДОЛЛАРОВ В ЭТОМ ОТВЕТЕ НЕТ ВОВСЕ, И ЭТО ГЛАВНОЕ ПРО ЭКРАН ═══
        # Живая проба 20.09 показала поля: address, avg_entry_price, current_price, market_id,
        # outcome_index, owner_address, position_size, side, unrealized_pnl_usd.
        # Единственное поле на `_usd` - это НЕРЕАЛИЗОВАННЫЙ PNL, а не размер позиции. Размер
        # приходит в ДОЛЯХ (`position_size`).
        #
        # ПЕРВАЯ РЕДАКЦИЯ ЭТОГО МЕСТА ПЕЧАТАЛА ДОЛИ СО ЗНАКОМ $. То есть «$1.40M из $2.00M» на
        # деле означало «1.4M долей из 2.0M долей», а доля на предсказательном рынке стоит от
        # одного до ста центов - ошибка до ста раз, и В ГЛАВНОЙ СТРОКЕ экрана. Это ровно тот
        # запрет, который мы сами и ввели: правдоподобное неверное число хуже прочерка.
        #
        # Считаем САМИ и только из того, что правда приехало: доли × текущая цена = доллары.
        # Нет цены - нет и денег: `None`, и экран скажет это словом.
        _sz = _num_or_none(_first(r, ('position_size', 'size', 'shares')))
        _px = _num_or_none(_first(r, ('current_price', 'price', 'last_trade_price')))
        val, _vf = _usd_any(r, ('position_value_usd', 'value_usd', 'position_size_usd',
                                'size_usd'))
        try:
            val = float(val) if val not in (None, '') else None
        except (TypeError, ValueError):
            val = None
        if val is None and _sz is not None and _px is not None:
            val = _sz * _px
            _vf = 'position_size×current_price'
        side = pm_holder_side(r)
        holders.append({'addr': str(addr or ''), 'who': _who(r), 'side': side, 'usd': val,
                        'shares': _sz, 'entry': _num_or_none(_first(r, ('avg_entry_price',))),
                        'px': _px, 'wr': None, 'pnl': None, 'markets': None, 'status': None})
        if val:
            total += val
            by_side[side] = by_side.get(side, 0.0) + val
    if not holders:
        return None
    weak = strong = 0.0
    known = no_history = no_winrate = failed = 0
    failure_reasons = {}
    target = holders[:int(top)]
    uid = None
    try:
        uid = (_tele.box() or {}).get('uid')
    except Exception:
        pass

    def _summary_one(h):
        """Один адрес в своей сцене: результат + точная причина пустоты/сбоя."""
        if not h['addr']:
            return h, None, 'empty'
        with _tele.scene('pm_reputation', uid):
            row = pm_address_summary(h['addr'], timeout=10)
            why = None if row else fail_reason('empty')
        return h, row, why

    # ПЯТЬ ИСТОРИЙ ПАРАЛЛЕЛЬНО, а не 5×60 секунд последовательно. Верхняя граница холодного
    # экрана теперь около 15 секунд плюс top-holders, что укладывается в 30–60с demo.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    jobs = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(target), 5))) as pool:
        for h in target:
            if h['addr']:
                jobs[pool.submit(_summary_one, h)] = h
            else:
                no_history += 1
        calls += len(jobs)
        results = []
        for fut in as_completed(jobs):
            try:
                results.append(fut.result())
            except Exception as e:
                print('[nansen] pm reputation summary worker: %s' % str(e)[:100])
                results.append((jobs[fut], None, 'http'))

    # РЕНДЕР ОСТАЁТСЯ В ИСХОДНОМ ПОРЯДКЕ ДЕРЖАТЕЛЕЙ, хотя сеть закончила в другом.
    by_addr = {h['addr']: (s, why) for h, s, why in results}
    for h in target:
        if not h['addr']:
            continue
        s, why = by_addr.get(h['addr'], (None, 'http'))
        if not isinstance(s, dict) or not s:
            if why in (None, 'empty'):
                no_history += 1
                h['status'] = 'no_history'
            else:
                failed += 1
                h['status'] = 'failed:' + str(why)
                failure_reasons[why] = failure_reasons.get(why, 0) + 1
            continue
        _shape('pm-address-summary', s)
        wr = _winrate_pct(_first(s, ('win_rate', 'winrate', 'win_rate_pct')))
        h['wr'] = wr
        h['pnl'] = _first(s, ('total_pnl_usd', 'total_pnl', 'realized_pnl_usd'))
        h['markets'] = _first(s, ('markets_traded', 'markets_count', 'total_markets'))
        if wr is None:
            no_winrate += 1
            h['status'] = 'no_winrate'
            continue
        h['status'] = 'ok'
        known += 1
        if h['usd']:
            if wr < PM_WEAK_WR:
                weak += h['usd']
            else:
                strong += h['usd']
    unexamined = max(0, len(holders) - int(top))
    unknown = no_history + no_winrate + failed + unexamined
    return {'holders': holders, 'by_side': by_side, 'weak_usd': weak, 'strong_usd': strong,
            'known': known, 'unknown': unknown, 'no_history': no_history,
            'no_winrate': no_winrate, 'failed': failed, 'unexamined': unexamined,
            'failure_reasons': failure_reasons,
            'total_usd': total, 'calls': calls, 'market_id': str(market_id)}


def pm_reputation_block(rep, market_id='', lang='ru', top=PM_REP_TOP):
    """Рынок, взвешенный по репутации держателей. -> str | None.

    ГЛАВНАЯ СТРОКА - ВЕЛИЧИНА, и она первая. Дальше стороны, дальше сами держатели, и в конце
    оговорки: про кого мы НЕ знаем и что винрейт в прошлом не обещает будущего.
    """
    if not isinstance(rep, dict) or not rep.get('holders'):
        return None
    en = (lang == 'en')
    L = [('🎭 <b>Кто держит этот рынок</b>' if not en else '🎭 <b>Who holds this market</b>')]
    if market_id:
        L.append('<code>%s</code>' % market_id)
    L.append('')
    _w, _s, _tot = rep['weak_usd'], rep['strong_usd'], rep['total_usd']
    if _w or _s:
        _sum = _w + _s
        _pct = (100.0 * _w / _sum) if _sum else 0.0
        # ВЕДЁМ ЧИСЛОМ: сколько денег у тех, кто чаще ошибался. Порог назван прямо в строке -
        # человек имеет право с ним не согласиться, а для этого должен его видеть.
        L.append((('💰 Из $%s разобранных денег <b>$%s (%.0f%%)</b> лежат у кошельков с '
                   'винрейтом ниже %.0f%%.')
                  if not en else
                  ('💰 Of $%s examined, <b>$%s (%.0f%%)</b> sits with wallets whose win rate '
                   'is below %.0f%%.'))
                 % (_usd(_sum), _usd(_w), _pct, PM_WEAK_WR))
    elif _tot:
        L.append(('💰 Всего у держателей $%s, но лайфтайм-историю не отдали ни по одному - '
                  'взвесить по репутации нечем.' if not en else
                  '💰 Holders hold $%s in total, but no lifetime history came back - nothing '
                  'to weigh by.') % _usd(_tot))
    if rep['by_side']:
        _sides = sorted(rep['by_side'].items(), key=lambda x: -x[1])
        L.append(('📊 По сторонам: ' if not en else '📊 By side: ')
                 + ' · '.join('%s $%s' % (k, _usd(v)) for k, v in _sides[:4]))
    L.append('')
    L.append(('<b>Держатели</b> (разобрано %d из %d):' if not en
              else '<b>Holders</b> (%d of %d examined):')
             % (min(int(top), len(rep['holders'])), len(rep['holders'])))
    for i, h in enumerate(rep['holders'][:int(top)], 1):
        seg = []
        if h['usd']:
            seg.append('$%s' % _usd(h['usd']))
        elif h.get('shares'):
            # ДОЛИ БЕЗ ЦЕНЫ - НЕ ДЕНЬГИ, и знак $ к ним не ставится. Пишем как есть и словом,
            # иначе получится та самая ошибка «доли под видом долларов» (до ста раз).
            seg.append(('%s долей' if not en else '%s shares') % _usd(h['shares']))
        if h.get('entry') is not None and h.get('px') is not None:
            # ВОШЁЛ ПО 12¢, СЕЙЧАС 45¢ - это и есть «он уже прав» или «он уже неправ», и это
            # приехало в том же ответе, бесплатно.
            seg.append(('вход %.0f¢ → %.0f¢' if not en else 'entry %.0f¢ → %.0f¢')
                       % (h['entry'] * 100 if h['entry'] <= 1 else h['entry'],
                          h['px'] * 100 if h['px'] <= 1 else h['px']))
        if h['wr'] is not None:
            seg.append(('винрейт %.0f%%' if not en else 'win rate %.0f%%') % h['wr'])
        elif str(h.get('status') or '').startswith('failed:'):
            # НЕ «ИСТОРИИ НЕТ»: мы пытались спросить, но не смогли. Смешать эти два мира —
            # повторить исходный дефект интеграции внутри hero-screen.
            seg.append(('история НЕ приехала' if not en else 'history NOT delivered'))
        elif h.get('status') == 'no_winrate':
            seg.append(('поле винрейта не приехало' if not en else 'win-rate field missing'))
        else:
            seg.append('истории нет' if not en else 'no history')
        if h['pnl'] not in (None, ''):
            try:
                seg.append(('PnL +$' if float(h['pnl']) >= 0 else 'PnL -$')
                           + _usd(abs(float(h['pnl']))))
            except (TypeError, ValueError):
                pass
        if h['markets'] not in (None, ''):
            try:
                seg.append(('%d рынков' if not en else '%d markets') % int(float(h['markets'])))
            except (TypeError, ValueError):
                pass
        L.append('%d. %s [%s] · %s' % (i, h['who'], h['side'], ' · '.join(seg)))
    if rep.get('failed'):
        L.append('')
        rs = ', '.join('%s×%d' % (k, v) for k, v in
                       sorted((rep.get('failure_reasons') or {}).items()))
        L.append((('⚠️ <i>История %d держател(ей) НЕ приехала из-за сбоя (%s). Их деньги '
                   'не посчитаны ни в одну сторону; это наш неполный ответ, а не свойство '
                   'кошельков.</i>') if not en else
                  ('⚠️ <i>History for %d holder(s) was NOT delivered due to a failure (%s). '
                   'Their money is counted on neither side; this is our partial response, '
                   'not a property of those wallets.</i>')) % (rep['failed'], rs or '?'))
    natural_unknown = (rep.get('no_history', 0) + rep.get('no_winrate', 0)
                       + rep.get('unexamined', 0))
    if natural_unknown:
        L.append('')
        L.append((('⚠️ <i>По %d держател(ям) нет измеримого винрейта - их деньги НЕ '
                   'посчитаны ни в одну сторону. Приписать винрейт, которого мы не знаем, '
                   'значит подогнать вывод.</i>') if not en else
                  ('⚠️ <i>%d holder(s) have no measurable win rate - their money is counted '
                   'on NEITHER side. Assigning a win rate we do not know would be fitting '
                   'the answer.</i>')) % natural_unknown)
    L.append('')
    # ОТКУДА ВЗЯЛИСЬ ДОЛЛАРЫ - СКАЗАНО ПРЯМО. Площадка отдаёт размер позиции в ДОЛЯХ и
    # текущую цену отдельно; доллары здесь ПОСЧИТАНЫ нами (доли × цена), а не приехали готовыми.
    # Человек имеет право знать, какое число измерено, а какое выведено.
    if any(h.get('shares') and h.get('px') for h in rep['holders'][:int(top)]):
        L.append(('<i>Доллары посчитаны как доли × текущая цена: готовой суммы в ответе нет.</i>'
                  if not en else
                  '<i>Dollars are computed as shares × current price: the response has no '
                  'ready total.</i>'))
    L.append(('<i>Винрейт в прошлом не обещает будущего: это состав денег, а не прогноз и не '
              'совет. Запросов на экран: %d.</i>' if not en else
              '<i>Past win rate does not promise the future: this is the composition of the '
              'money, not a forecast or advice. Requests spent on this screen: %d.</i>')
             % rep.get('calls', 0))
    return with_source('\n'.join(L), lang)


def pm_wallet_block(address):
    """Профиль трейдера Polymarket: PnL/winrate/возраст + топ-рынки по PnL. -> str | None."""
    s = pm_address_summary(address)
    by = pm_pnl_by_address(address, per_page=5) or []
    if not s and not by:
        return None
    short = f"{address[:6]}…{address[-4:]}"
    L = [f"🎰 <b>Polymarket · профиль</b> <code>{short}</code>"]
    if s:
        tot = s.get("total_pnl_usd")
        rp = s.get("realized_pnl_usd")
        up = s.get("unrealized_pnl_usd")
        try:
            tots = ("+$" if float(tot) >= 0 else "-$") + _usd(abs(float(tot)))
        except (TypeError, ValueError):
            tots = "?"
        seg = [f"PnL {tots}"]
        try:
            seg.append("реализ. " + ("+$" if float(rp) >= 0 else "-$") + _usd(abs(float(rp))))
        except (TypeError, ValueError):
            pass
        try:
            seg.append("нереализ. " + ("+$" if float(up) >= 0 else "-$") + _usd(abs(float(up))))
        except (TypeError, ValueError):
            pass
        L.append("📈 " + " · ".join(seg))
        wr = _winrate_pct(s.get("win_rate"))
        won = s.get("markets_won")
        tr = s.get("markets_traded")
        age = s.get("wallet_age_days")
        seg2 = []
        if wr is not None:
            seg2.append(f"winrate {wr:.0f}%")
        if won is not None and tr is not None:
            seg2.append(f"выиграно {won}/{tr}")
        if age not in (None, ""):
            seg2.append(f"возраст {int(float(age))}д")
        if seg2:
            L.append("🎯 " + " · ".join(seg2))
    if by:
        L.append("💼 топ-рынки по PnL:")
        for r in by[:5]:
            q = (r.get("question") or "?")[:52]
            side = r.get("side_held") or ""
            v = r.get("total_pnl_usd")
            try:
                vs = ("+$" if float(v) >= 0 else "-$") + _usd(abs(float(v)))
            except (TypeError, ValueError):
                vs = "?"
            L.append(f"• {q} [{side}] · {vs}")
    return with_source("\n".join(L))


def pm_market_leaders_block(market_id, top=10):
    """Топ-трейдеры конкретного рынка Polymarket по PnL. -> str | None."""
    rows = pm_pnl_by_market(market_id, per_page=top)
    if not rows:
        return None
    q = (rows[0].get("question") or rows[0].get("event_title") or f"рынок {market_id}")[:70]
    L = [f"🏆 <b>Топ-трейдеры рынка</b>\n<i>{q}</i>:"]
    for i, r in enumerate(rows[:top], 1):
        addr = r.get("address") or ""
        who = f"{addr[:6]}…{addr[-4:]}" if addr else "?"
        side = r.get("side_held") or ""
        v = r.get("total_pnl_usd")
        try:
            vs = ("+$" if float(v) >= 0 else "-$") + _usd(abs(float(v)))
        except (TypeError, ValueError):
            vs = "?"
        L.append(f"{i}. {who} [{side}] · {vs}")
    return with_source("\n".join(L))



# ═══════════════════════════════════════════════════════════════════════════
# HISTORICAL / POINT-IN-TIME (/api/v1beta1) — данные для БЭКТЕСТА.
# Отдельная база: обычные эндпоинты живут на /api/v1, исторические на /api/v1beta1.
# Схемы НЕ угаданы по документации, а снятые с живого ключа на проде: в примере самой
# документации label_type='all' — невалидное значение, API поправил на 'all_holders'.
#
# ВАЖНО ПРО ДЕНЬГИ. Тут два разных класса эндпоинтов, и путать их дорого:
#  - historical-token-ohlcv отдаёт РЯД: 89 дневных свечей за один вызов, 5 кредитов.
#    Это дёшево, годится на тап.
#  - historical-token-flow-summary отдаёт ОДНУ строку — агрегат за весь date_range,
#    а не серию. Чтобы получить сигнал по дням, нужен вызов на КАЖДЫЙ день: 90 дней
#    это 90 вызовов и 450 кредитов. На тап такое вешать нельзя (замерено живьём).
# Поэтому здесь пока только OHLCV. Потоки по сегментам холдеров — задача для фонового
# расчёта по расписанию с записью в БД, а не для кнопки.
# ═══════════════════════════════════════════════════════════════════════════
_BETA = "https://api.nansen.ai/api/v1beta1"
# свеча за прошедший день не меняется, поэтому кэш живёт долго и повторные тапы бесплатны
_TTL_HIST = 6 * 3600
# сколько дней истории просим по умолчанию: с запасом на разрез 70/30 в бэктесте
HIST_DAYS = 180
# сдвиг конца окна: у последней незакрытой свечи объём и close ещё доедают
HIST_LAG_DAYS = 2


def _post_beta(path, body, ckey=None, ttl=_TTL_HIST, timeout=90):
    """POST к /api/v1beta1. -> распарсенный JSON | None. Ошибки не поднимаем: карточки
    не должны падать из-за того, что бета сменила схему."""
    if not _key():
        _tele.note('nokey')
        return None
    if ckey:
        c = _cache_get(ckey, ttl=ttl)
        if c is not None:
            _cache_hit(path, c)
            return c
    j, http = _http_post(_BETA, path, body, timeout, " beta")
    if j is not None and ckey:
        _cache_put(ckey, j, ttl=ttl)
    return j


def _f(x):
    """В число или None. Отдельная функция, потому что market_cap приходит ВЛОЖЕННЫМ
    словарём {open,high,low,close}, и наивный float() на нём бросает TypeError."""
    if isinstance(x, dict) or isinstance(x, (list, tuple)):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None          # NaN отсекаем


def historical_ohlcv(chain, token_address, timeframe="1d", days=HIST_DAYS, with_dates=False):
    """Свечи токена из ончейн-данных Nansen. -> (o, h, l, cl, vol, 'Nansen') | None.

    Форма возврата СОВПАДАЕТ с oc_chart.cex_ohlc, поэтому индикаторы и бэктест берут
    эти свечи без единой правки: движку всё равно, откуда пришёл ряд.

    Зачем вообще: у DEX-токенов свечи брались с GeckoTerminal, а там окно максимум
    ~60 точек и только внутридневное (до 7 дней на 4h). Для бэктеста этого не хватает
    physically. Nansen отдаёт дневные свечи за месяцы, и это открывает бэктест по мемам.

    Цена: 5 кредитов за вызов, дальше кэш на 6 часов.
    Проверено живьём: timeframe='1d' -> 89 свечей на окне 90 дней.

    with_dates=True добавляет СЕДЬМЫМ элементом список дат (YYYY-MM-DD). Отдельным флагом,
    а не всегда: шестёрка совпадает с cex_ohlc, и ломать её нельзя. Даты нужны там, где ряд
    сшивается с другим ряду по дню (потоки смарт-мани), а сшивать по индексу нельзя —
    у свечей бывают пропуски, и ряды разъедутся молча.
    """
    if not token_address:
        return None
    to = _dt.datetime.utcnow().date() - _dt.timedelta(days=HIST_LAG_DAYS)
    frm = to - _dt.timedelta(days=int(days))
    body = {"chain": _nc(chain), "token_address": str(token_address),
            "date_from": frm.isoformat(), "as_of_date": to.isoformat(),
            "timeframe": timeframe}
    rows = _rows(_post_beta("tgm/historical-token-ohlcv", body,
                            ckey="histohlcv:%s:%s:%s:%s:%s" % (chain, token_address, timeframe,
                                                               days, to.isoformat())))
    if not rows:
        return None
    # по времени сортируем САМИ: порядок в ответе не документирован, а перепутанный ряд
    # тихо превратит бэктест в шум вместо того, чтобы упасть
    try:
        rows = sorted(rows, key=lambda r: str(r.get("interval_start") or ""))
    except Exception:
        pass
    o, h, l, cl, vol, days_ = [], [], [], [], [], []
    for r in rows:
        if not isinstance(r, dict):
            continue
        _o, _h, _l, _c = _f(r.get("open")), _f(r.get("high")), _f(r.get("low")), _f(r.get("close"))
        if None in (_o, _h, _l, _c) or _c <= 0 or _o <= 0:
            continue                      # дырявую свечу выбрасываем целиком
        # volume в токенах (как у Binance x[5]), volume_usd отдельным полем
        _v = _f(r.get("volume"))
        o.append(_o); h.append(_h); l.append(_l); cl.append(_c); vol.append(_v or 0.0)
        days_.append(str(r.get("interval_start") or "")[:10])
    if len(cl) < 4:
        return None
    if with_dates:
        return (o, h, l, cl, vol, "Nansen", days_)
    return (o, h, l, cl, vol, "Nansen")


def historical_flow_summary_day(chain, token_address, day):
    """Потоки по сегментам за ОДИН КОНКРЕТНЫЙ день. -> dict | None. 5 кредитов.

    Отдельная функция, а не days=1: окно тут задаётся ЯВНОЙ датой, потому что из этих
    точек собирается ряд, и «день назад от сегодня» поехал бы при каждом запуске.
    Кэш длинный: закрытый день уже не изменится.
    """
    d = str(day)[:10]
    rows = _rows(_post_beta("tgm/historical-token-flow-summary",
                            {"chain": _nc(chain), "token_address": str(token_address),
                             "date_range": {"from": d, "to": d}},
                            ckey="histflowday:%s:%s:%s" % (chain, token_address, d),
                            ttl=30 * 24 * 3600))
    return rows[0] if rows else None


def historical_flow_summary(chain, token_address, days=30):
    """Агрегат потоков по сегментам холдеров за ОКНО (не ряд!). -> dict | None. 5 кредитов.

    Возвращает ОДНУ строку с итогами за весь период: smart_trader / whale / exchange /
    public_figure / top_pnl / fresh_wallets, у каждого net_flow_usd, avg_flow_usd и
    wallet_count. Именно поэтому на бэктест по дням это не годится (см. шапку раздела):
    серии здесь нет, и собрать её можно только вызовом на каждый день.
    """
    to = _dt.datetime.utcnow().date() - _dt.timedelta(days=HIST_LAG_DAYS)
    frm = to - _dt.timedelta(days=int(days))
    rows = _rows(_post_beta("tgm/historical-token-flow-summary",
                            {"chain": _nc(chain), "token_address": str(token_address),
                             "date_range": {"from": frm.isoformat(), "to": to.isoformat()}},
                            ckey="histflow:%s:%s:%s:%s" % (chain, token_address, days,
                                                           to.isoformat())))
    return rows[0] if rows else None
