# -*- coding: utf-8 -*-
"""sentinel/predict.py — СВЯЗКА «ПРЕДСКАЗАТЕЛЬНЫЙ РЫНОК → ПЕРП» (пункт 3.7 роудмапа).

ЗАЧЕМ. Все сигналы дозорного отвечают на «что уже случилось с ценой». Предсказательный рынок
отвечает на другое: «чего ЖДУТ». Когда по инструменту под дозором идёт движение, а на Polymarket
про этот же актив стоит рынок с ценой исхода, это две независимые картины одного события — и
вместе они говорят больше, чем каждая по себе.

═══ ГЛАВНАЯ ОПАСНОСТЬ ЗДЕСЬ НЕ ТЕХНИЧЕСКАЯ, А СМЫСЛОВАЯ ═══
Роудмап предупреждает про это прямым текстом, и предупреждение оплачено: связку «тикер площадки
→ внешний объект» брать можно ТОЛЬКО из проверенного сопоставления, потому что вывод по совпадению
тикера уже стоил этому проекту трёх экранов (UNI → Binance-Peg, LIT → солановский однофамилец).
На Variational это не теория: в живом ответе тикер `A` — это НЕ Agilent, а токен Vaulta, а `US` —
не США и не индекс, а токен Talus. Поиск на Polymarket по строке «A» вернёт что угодно.

ПОЭТОМУ ЗДЕСЬ ТРИ ЗАМКА, И НИ ОДИН ИЗ НИХ НЕ ПРО УДОБСТВО:
  1. ИЩЕМ ПО ПОЛНОМУ ИМЕНИ, А НЕ ПО ТИКЕРУ. Имя даёт сама площадка (`Listing.name`: 'Bitcoin',
     'Ethereum'), и оно на порядок однозначнее трёх букв. Нет имени — нет поиска.
  2. КОРОТКИЕ И НЕОДНОЗНАЧНЫЕ ИМЕНА ОТСЕКАЕМ ЦЕЛИКОМ (`_TOO_AMBIGUOUS`). «A», «US», «ETF» не
     сопоставляются никогда, сколько бы совпадений ни нашлось.
  3. НАЙДЕННЫЙ РЫНОК ПЕРЕПРОВЕРЯЕМ ОБРАТНО: его заголовок обязан содержать имя актива, а
     категория — быть той, к которой актив относится (общая дверь `poly_read._market_cat`).
     Совпадение по одному признаку принимаем за совпадение только если сошлись ОБА.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Событие «по рынку двинулись именно те кошельки, которые угадывали
раньше» роудмап называет целью, и оно НЕ СДЕЛАНО событием — сделано ОБОГАЩЕНИЕМ. Причина
измеримая, а не вкусовая: поток сделок по рынку отдаёт только `prediction-market/trades`, схема
ответа которой в проекте НЕ СНЯТА живой пробой, а строить алерт на неразобранной форме — это
ровно «признак наличия вместо признака пользы». Расклад держателей мы берём готовой дверью
`nansen_api.pm_reputation` (её схема снята пробой 20.09) и показываем ВТОРЫМ сообщением, где
задержка ничего не стоит. Когда схема сделок будет снята живым вызовом, отсюда вырастет событие.

ЦЕНА. Публичный поиск рынка бесплатен (gamma-api, без ключей). Расклад кошельков стоит кредитов
(1 запрос top-holders + до 5 запросов по адресам), поэтому он идёт ТОЛЬКО в сводке, только если
человек включил 'nansen', и только под общим капом дозорного.
"""

import os
import re

from . import store

#: ИМЕНА, КОТОРЫЕ НЕ СОПОСТАВЛЯЕМ НИКОГДА. Не «редко», а никогда: одно ложное сопоставление
#: дороже сотни пропущенных, потому что человек читает его как факт.
#: ПОЧЕМУ ДЛИНА 1-2 СИМВОЛА ВНЕ СПИСКА: такие имена совпадают со всем подряд, и проверить их
#: обратным поиском нечем.
_TOO_AMBIGUOUS = {
    'us', 'a', 'ai', 'eu', 'it', 'me', 'on', 'go', 'up', 'id', 'op', 'so',
    'etf', 'fund', 'trust', 'index', 'gold', 'oil', 'crude', 'spx', 'vix',
    'the', 'and', 'all', 'new', 'one', 'top',
}

#: МИНИМАЛЬНЫЙ ОБОРОТ РЫНКА. Рынок без денег — это не мнение толпы, а чья-то одинокая ставка;
#: приводить его как «чего ждут» значит выдавать шум за консенсус. Тот же закон, что заставил
#: поставить абсолютные пороги рядом со спредом, объёмом и интересом.
MIN_VOLUME_USD = float(os.getenv('SENTINEL_PM_MIN_VOLUME') or 50000)

#: Винрейт, с которого кошелёк считаем «угадывавшим». Взят ИЗ УЖЕ СУЩЕСТВУЮЩЕГО порога проекта
#: (`nansen_api.PM_WEAK_WR` = 40%, ниже него кошелёк считается слабым), чтобы два экрана не
#: называли одного и того же человека по-разному.
STRONG_WR = float(os.getenv('SENTINEL_PM_STRONG_WR') or 55)


def _norm(s):
    return re.sub(r'[^a-z0-9 ]+', ' ', str(s or '').lower()).strip()


def ambiguous(name):
    """Имя, по которому искать НЕЛЬЗЯ. -> причина (str) | None.

    Отдельной функцией, чтобы причину можно было ПОКАЗАТЬ: «не сопоставлено» без объяснения
    выглядит как поломка, а «имя слишком общее» — как решение.
    """
    n = _norm(name)
    if not n:
        return 'у инструмента нет полного имени, а по тикеру искать нельзя'
    if len(n) <= 2:
        return 'имя %r слишком короткое: совпадёт с чем угодно' % n
    if n in _TOO_AMBIGUOUS:
        return 'имя %r слишком общее, сопоставлять по нему запрещено' % n
    return None


def confirms(title, slug, name, cat=None, want_cat='крипто'):
    """ОБРАТНАЯ ПРОВЕРКА найденного рынка. -> True, если рынок ПРАВДА про этот актив.

    ЧИСТАЯ ФУНКЦИЯ - И ЭТО ПРАВДА, А НЕ ОБЕЩАНИЕ В ДОКСТРИНГЕ. Первая редакция звала
    `poly_read._market_cat` внутри себя, то есть тянула модуль с сетевым клиентом; на машине без
    `httpx` импорт падал, `except` возвращал False, и функция МОЛЧА отвечала «не подтверждено» на
    правильные заголовки. Проба это и поймала: три верных рынка из пяти получили False. Категорию
    теперь передаёт ВЫЗЫВАЮЩИЙ (`market_for` берёт её у `poly_read`), а правило живёт здесь и
    проверяется на фикстурах настоящих заголовков.
    `cat=None` значит «категорию не считали» - тогда проверяем только по имени, но вызывающий
    обязан знать, что один замок из двух остался открытым (см. `market_for`).

    ДВА ПРИЗНАКА ОБЯЗАТЕЛЬНЫ СРАЗУ. Заголовок с именем — недостаточно: рынок «Will Bitcoin
    Conference sell out?» содержит «bitcoin» и не про цену. Категория — тоже недостаточно: любой
    крипторынок попадёт в 'крипто'. Вместе они отсекают и то и другое.
    """
    hay = '%s %s' % (_norm(title), _norm(slug))
    n = _norm(name)
    if not n or n not in hay:
        return False
    if cat is not None and cat != want_cat:
        return False
    # ═══ ТРЕТИЙ ЗАМОК: РЫНОК ОБЯЗАН БЫТЬ ПРО ЦЕНУ ═══
    # ЭТО НАШЁЛ ЗАМЕР, А НЕ РАЗМЫШЛЕНИЕ. Живая проба 26.09 прогнала фикстуру «Will the Bitcoin
    # Conference sell out?» и получила True: имя в заголовке есть, категория 'крипто' (слово
    # bitcoin в ней тоже есть) - оба замка пройдены, а рынок НЕ про цену актива. То есть двух
    # признаков не хватало, и я это обещал в докстринге раньше, чем код научился.
    # ПОЧЕМУ ЭТО ВАЖНО ИМЕННО ДЛЯ ДОЗОРНОГО: он показывает рынок рядом с движением цены. Рынок
    # про конференцию, листинг или судебный иск в этом месте читается как «вот чего ждут ОТ
    # ЦЕНЫ» - то есть подпись врёт, даже когда данные верны.
    if not _RE_PRICEY.search(hay):
        return False
    return True


#: ПРИЗНАКИ ЦЕНОВОГО ВОПРОСА. Список проверен на живых заголовках: «What price will Bitcoin hit
#: in September?», «Bitcoin above ___ on September 25?», «Solana Up or Down - October 5»,
#: «What price will XRP hit in September?» - каждый ловится.
_RE_PRICEY = re.compile(
    r'\b(price|prices|above|below|hit|reach|dip|dips|touch|close|open|high|low|'
    r'up or down|all time high|ath|market cap|flip|outperform|'
    r'\$|percent|pct)\b', re.I)


async def market_for(ticker, name, want_cat='крипто'):
    """Рынок Polymarket про этот актив. -> (dict | None, причина).

    БЕСПЛАТНО: публичный gamma-api, ключей не требует. Возвращает ПРИЧИНУ отказа всегда —
    «связки нет» и «связку не искали» человеку нужно различать.

    АСИНХРОННАЯ, ПОТОМУ ЧТО ТАКОВА ЧУЖАЯ ДВЕРЬ (`poly_read.find_event` — корутина). Первая
    редакция звала её синхронно и получила `'coroutine' object has no attribute 'get'` на живой
    пробе: функция «работала», не сделав ни одного запроса. Ровно тот случай, когда тест на
    заглушке был бы зелёным, а живой вызов — нет.
    """
    why = ambiguous(name)
    if why:
        return None, why
    try:
        import poly_read
    except Exception as e:
        return None, 'слой Polymarket недоступен (%s)' % str(e)[:60]
    try:
        got = await poly_read.find_event(name, limit=5)
    except Exception as e:                       # noqa: BLE001
        return None, 'поиск рынка не ответил: %s: %s' % (type(e).__name__, str(e)[:70])
    if not got:
        return None, 'рынка про %s на Polymarket не нашлось' % name
    title, slug = got.get('title') or '', got.get('slug') or ''
    # КАТЕГОРИЮ СЧИТАЕМ ОБЩЕЙ ДВЕРЬЮ ПРОЕКТА (`poly_read._market_cat`), а не своим списком слов:
    # вторая таблица категорий разъехалась бы с первой на первом же пополнении.
    # ЕЁ ОТСУТСТВИЕ - НЕ ПОВОД ОСЛАБИТЬ ПРОВЕРКУ: нет категории - нет сопоставления, потому что
    # из двух замков остался бы один, а цена ложного сопоставления здесь - экран с выдумкой.
    try:
        cat = poly_read._market_cat(title, slug)
    except Exception as e:                       # noqa: BLE001
        return None, 'категорию рынка проверить нечем (%s) - сопоставлять не берусь' % str(e)[:50]
    if not confirms(title, slug, name, cat, want_cat):
        # НАШЛИ, НО НЕ ПОВЕРИЛИ - И ГОВОРИМ ИМЕННО ТАК. Это не «нет рынка»: это «найденный рынок
        # не подтверждает, что он про наш актив», и человеку полезно видеть, что мы проверяли.
        return None, ('найден рынок «%s», но он не подтверждает связь с %s - не показываю'
                      % (title[:60], name))
    vol = float(got.get('volume') or 0)
    if vol < MIN_VOLUME_USD:
        return None, ('рынок «%s» есть, но оборот $%.0f ниже порога $%.0f - это не мнение толпы'
                      % (title[:40], vol, MIN_VOLUME_USD))
    return {'title': title, 'slug': slug, 'volume': vol,
            'url': 'https://polymarket.com/event/%s' % slug}, None


def sharp_split(rep):
    """Расклад по силе кошельков из готового `pm_reputation`. -> dict | None. ЧИСТАЯ ФУНКЦИЯ.

    ВЕДЁМ ДЕНЬГАМИ И СТОРОНОЙ, А НЕ ЧИСЛОМ КОШЕЛЬКОВ: пять мелких против одного крупного — это
    перевес крупного, и «5 против 1» соврало бы. Долларов в ответе площадки нет, их считает
    `pm_reputation` (доли × текущая цена) — мы берём уже посчитанное и не считаем второй раз.

    КОШЕЛЬКИ БЕЗ ИСТОРИИ НЕ ПРИЧИСЛЯЕМ НИ К КОМУ. Это готовое решение соседнего экрана
    (`status='no_history'`), и оно правильное: отсутствие винрейта — не признак слабости.
    """
    if not rep or not rep.get('holders'):
        return None
    strong, weak, unknown = {}, {}, 0.0
    for h in rep['holders']:
        side, usd, wr = h.get('side') or '?', float(h.get('usd') or 0), h.get('wr')
        if wr is None:
            unknown += usd
            continue
        box = strong if float(wr) >= STRONG_WR else weak
        box[side] = box.get(side, 0.0) + usd
    if not strong and not weak:
        return None
    top_side = max(strong, key=strong.get) if strong else None
    return {'strong': strong, 'weak': weak, 'unknown_usd': unknown,
            'strong_side': top_side,
            'strong_usd': (strong.get(top_side) or 0.0) if top_side else 0.0,
            'checked': len(rep['holders']),
            'no_history': int(rep.get('no_history') or 0)}


async def lines(ticker, name, uid=None, want_cat='крипто'):
    """Блок для сводки: рынок + расклад сильных кошельков. -> (list[str], причина, кредиты).

    НИКОГДА НЕ БРОСАЕТ: это второе сообщение, и его отказ обязан стать НАЗВАННОЙ причиной, а не
    исключением в тике доставки.
    ПОИСК РЫНКА БЕСПЛАТЕН И ИДЁТ ВСЕГДА; РАСКЛАД КОШЕЛЬКОВ СТОИТ КРЕДИТОВ И ИДЁТ ТОЛЬКО ПОД КАПОМ.
    Разделение не косметическое: без него отсутствие кредитов прятало бы и бесплатную половину.
    """
    from .cards import esc
    mk, why = await market_for(ticker, name, want_cat)
    if mk is None:
        return [], why, 0
    out = ['<b>Предсказательный рынок</b>',
           '• <a href="%s">%s</a> · оборот %s'
           % (mk['url'], esc(mk['title'][:70]), _money(mk['volume']))]
    blocked = store.budget_block()
    if blocked:
        # РЫНОК ПОКАЗАЛИ, РАСКЛАД НЕТ - И СКАЗАЛИ ПОЧЕМУ. Половина бесплатной пользы лучше, чем
        # тишина из-за платной половины.
        return out, 'расклад кошельков не смотрели: %s' % blocked, 0
    rep, credits = None, 0
    try:
        import asyncio

        import nansen_api as _n
        import nansen_log as _tele
        with _tele.scene('pm_reputation', uid, surface='sentinel'):
            # ID РЫНКА У NANSEN СВОЙ, И СЛАГ ЕМУ НЕ ПОДХОДИТ: ищем в ЕГО системе по имени актива.
            rows = await asyncio.to_thread(_n.pm_market_screener, name, 'active', None, 5)
            mid = None
            for r in rows or []:
                _t = str((r or {}).get('question') or (r or {}).get('title') or '')
                _s = str((r or {}).get('slug') or '')
                _c = _cat_of(_t, _s)
                # НЕТ КАТЕГОРИИ - НЕ СОПОСТАВЛЯЕМ. `confirms` с `cat=None` проверяет только имя,
                # то есть один замок из двух; принимать это за совпадение здесь нельзя ровно по
                # той же причине, что и в `market_for`.
                if _c is not None and confirms(_t, _s, name, _c, want_cat):
                    mid = _n.pm_market_id(r)
                    break
            if not mid:
                _why2 = 'рынок в Nansen не сопоставлен - расклад кошельков не читаю'
                return out, _why2, 0
            rep = await asyncio.to_thread(_n.pm_reputation, mid)
            credits = int((rep or {}).get('calls') or 0)
        if credits:
            store.spend_add(credits=credits)
    except Exception as e:                       # noqa: BLE001
        return out, 'расклад кошельков не собрался: %s: %s' % (type(e).__name__, str(e)[:80]), 0
    sp = sharp_split(rep)
    if not sp:
        return out, 'у держателей рынка нет истории - судить об их точности нечем', credits
    if sp['strong_side']:
        out.append('• кошельки с винрейтом от %.0f%% стоят в <b>%s</b> на %s'
                   % (STRONG_WR, esc(sp['strong_side']), _money(sp['strong_usd'])))
    if sp['weak']:
        _w = max(sp['weak'], key=sp['weak'].get)
        out.append('• слабые (винрейт ниже %.0f%%) — в %s на %s'
                   % (STRONG_WR, esc(_w), _money(sp['weak'][_w])))
    # ЧЕГО НЕ ЗНАЕМ - ОТДЕЛЬНОЙ СТРОКОЙ И ЧИСЛОМ, а не молчанием: доля без истории говорит,
    # насколько вообще можно верить раскладу.
    if sp['no_history']:
        out.append('• без истории %d из %d держателей — на них расклад не опирается'
                   % (sp['no_history'], sp['checked']))
    out.append('<i>Это ожидания рынка, а не прогноз дозорного.</i>')
    return out, None, credits


def _cat_of(title, slug):
    """Категория рынка общей дверью. -> str | None (None = проверить нечем).

    None, А НЕ 'крипто' ПО УМОЛЧАНИЮ: подставив ожидаемую категорию, мы превратили бы отсутствие
    проверки в её успешное прохождение - самый тихий способ соврать.
    """
    try:
        import poly_read
        return poly_read._market_cat(str(title or ''), str(slug or ''))
    except Exception:
        return None


def _money(v):
    v = float(v or 0)
    if v >= 1e9:
        return '$%.1fB' % (v / 1e9)
    if v >= 1e6:
        return '$%.1fM' % (v / 1e6)
    if v >= 1e3:
        return '$%.0fk' % (v / 1e3)
    return '$%.0f' % v
