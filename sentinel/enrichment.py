# -*- coding: utf-8 -*-
"""sentinel/enrichment.py — ВТОРОЕ сообщение: что вокруг этого движения. Nansen + X + вывод.

ПОРЯДОК РАБОТ ПЕРЕВЁРНУТ ОТНОСИТЕЛЬНО ОСТАЛЬНОГО БОТА, И ЭТО ГЛАВНОЕ РЕШЕНИЕ МОДУЛЯ
Обогащаем ТОЛЬКО то, что УЖЕ доставлено. Причин две. Первая: платить кредитами за сводку к
алерту, которого человек не видел, — трата без адресата. Вторая, важнее: пока сводка собирается
(Nansen, поиск по X, модель — секунды), цена живёт. Ехала бы сводка внутри первого сообщения —
человек получал бы цену на секунды позже, ровно в те секунды, за которые хотел успеть.

═══ ПЕРЕПИСАН ПОСЛЕ ЖИВОГО ЧАСА 25.09: СВОДКА БЫЛА МУСОРНОЙ ═══
Замер владельца, три разных дефекта в одной сводке:

1. ТВИТЫ НЕ ИЗ ОКНА. Запрос шёл с `since_minutes=90`, а в сводке стояли твиты возрастом
   **9 дней, 14 дней и 175 дней**. Значит фильтру провайдера доверять нельзя (либо `since_time`
   не работает, либо ответ приходит из кэша с другим окном). Возраст мы умеем считать САМИ
   (`twitter_api.tweet_ts`) — и теперь фильтруем по ФАКТУ. Правило проекта: проверяй величиной,
   а не флагом; «я передал параметр» не равно «провайдер его применил».
2. ТВИТЫ ОТ НИКОГО. В сводке стояли аккаунты на 8, 16 и 93 подписчика: «$TTWO» одним словом,
   «купил на $100, мы все разбогатеем». Пометка «⚠️ мелкий аккаунт» объясняет мусор, но не
   убирает его, а место в сводке конечно.
3. ТВИТЫ НЕ ПРО ТО. Запрос «UKOILP» притащил японский список тикеров форекса и китайский тред
   про другой инструмент. Тикер площадки — плохой поисковый запрос: он либо слишком редкий
   (`UKOILP`), либо слишком общий (`A`, `US`). Теперь запрос строится из ИМЕНИ инструмента и
   `$TICKER`, а результат проверяется на упоминание тикера или имени.
4. «РАЗМЕР НЕ НАЗВАН» У КАЖДОГО КОШЕЛЬКА. Мы искали объём в полях `volume_usd`/`value_usd`, а
   `tgm/who-bought-sold` отдаёт `bought_volume_usd`/`sold_volume_usd` — имена видны в нашем же
   `order_by` в клиенте. Список полей расширен, и кошельки стали ссылками на свои экраны.

ЧТО МОДЕЛЬ ЗДЕСЬ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ. Делает: пересказывает строки, которые УЖЕ посчитаны
и уже отправлены. Не делает: не решает, событие это или нет; не ставит оценку; не добавляет
фактов; не называет цифр, которых нет выше.

БЮДЖЕТ ПРОВЕРЯЕМ ДО ЗАПРОСОВ. Дозорный жжёт кредиты БЕЗ человека, по факту движения рынка.
"""

import os

import nansen_log as _tele

from . import assets, config, ignition, store

#: Окно поиска по X. Час-полтора, а не сутки: сводка нужна к движению ПОСЛЕДНИХ минут, а
#: суточная выборка утонет в обычном фоне тикера и покажет вчерашнее как объяснение сегодняшнего.
X_WINDOW_MIN = int(os.getenv('SENTINEL_X_WINDOW_MIN') or 90)
#: НЕ БОЛЬШЕ ДВУХ (ТЗ 2.7): третий твит в карточке ни разу не добавил смысла, только длину.
X_LIMIT = int(os.getenv('SENTINEL_X_LIMIT') or 2)
#: Сколько твитов запрашиваем, чтобы после отсева осталось X_LIMIT. Отсев жёсткий (свежесть, вес
#: аккаунта, релевантность), поэтому просить ровно три значило бы часто получать ноль.
X_FETCH = int(os.getenv('SENTINEL_X_FETCH') or 25)


def _q_for(tick, name):
    """Поисковый запрос по X. -> str.

    ЗАПРОС ИЗ ИМЕНИ, А НЕ ИЗ ТИКЕРА ПЛОЩАДКИ. Замер: «UKOILP» дал японский список форекс-пар и
    китайский тред про другой инструмент, потому что такого тикера в разговорах нет вовсе. Имя
    («Brent Crude Oil», «Strategy Inc») — то, чем актив называют люди; `$TICKER` — то, чем его
    помечают трейдеры. Берём оба через OR и режем юридические хвосты («, Inc.», «Corporation»),
    которые в твитах не пишут никогда.
    """
    base = _q_base(name)
    parts = []
    if tick:
        parts.append('$%s' % tick)
    if base and base.lower() != (tick or '').lower():
        parts.append('"%s"' % base)
    return ' OR '.join(parts) if parts else (tick or '')


def _q_base(name):
    """Имя без юридического хвоста - так актив называют люди. -> str."""
    base = (name or '').split(',')[0].strip()
    for tail in (' Inc', ' Corporation', ' Corp', ' Company', ' plc', ' Ltd', ' Trust',
                 ' Swap on', 'Swap on '):
        base = base.replace(tail, '').strip()
    return base


def _fresh_enough(t, now, tw):
    """Твит внутри окна? -> bool. НЕТ ВОЗРАСТА = НЕ ПРОПУСКАЕМ.

    Возраст — то, ради чего сводка существует; «разобрать не смогли» здесь не может означать
    «сойдёт»: именно так в сводку попал твит 175-дневной давности.
    """
    ts = tw.tweet_ts(t)
    if not ts:
        return False
    return (now - float(ts)) <= config.x_max_age_min() * 60


#: ПРИЗНАКИ ПЛАТНОГО СИГНАЛЬНОГО СПАМА. Список закрытый и короткий: это НЕ фильтр вкуса, а
#: список форм, которые в живой сводке 25.09 пришли дословно - «TP1/TP2/STOP LOSS» от
#: сигнального канала, «I made $80,000 by following his trades» тремя одинаковыми постами от
#: трёх разных аккаунтов и «Less than 100 votes are needed to list $XPL». Ни одна из этих
#: строк не отвечает на вопрос «почему цена пошла», а место в сводке конечно.
_SPAM_MARKS = ('tp1', 'tp2', 'tp3', 'stop loss', 'leverage: cross', 'free signals',
               'join our free', 'click on the link', 'i made $', 'votes are needed',
               'leaderboard', 'dm me', 'link in bio', 'not financial advice',
               'risk management is key', 'entry zone',
               # ТЗ 2.7: разметка платных сигналов и зазывалки листингов. «entry:» и «sl:» -
               # формат сигнального канала, а не новость про актив.
               'entry:', 'sl:', 'tp:', 'targets:', 'new listing around the corner',
               'community vote', 'vip access', 'launchpad', 'join our official')


def _lang_ok(txt):
    """Твит на русском или английском. -> bool. ЭВРИСТИКА ПО АЛФАВИТУ, и она названа как эвристика.

    Считаем буквы: латиница и кириллица - «свои», всё остальное (иероглифы, хангыль, арабица,
    тайский) - «чужие». Больше 20% чужих букв - твит не показываем. Тикеры и ссылки в счёт не
    идут: `$JUP` латиницей есть в любом твите про JUP, и по нему язык не определить.
    ПОЧЕМУ НЕ ДЕТЕКТОР ЯЗЫКА. Нам не нужно знать, какой это язык, - нужно знать, прочтёт ли его
    человек. На этот вопрос алфавит отвечает без зависимостей и без ошибок на коротком тексте,
    где статистические детекторы как раз ошибаются.
    """
    import re as _re
    t = _re.sub(r'https?://\S+|[$#@]\w+', ' ', str(txt or ''))
    own = foreign = 0
    for ch in t:
        if not ch.isalpha():
            continue
        o = ord(ch)
        if o < 0x250 or 0x400 <= o <= 0x4FF:
            own += 1
        else:
            foreign += 1
    if own + foreign == 0:
        return True
    return foreign <= 0.2 * (own + foreign)


def _norm(txt):
    """Текст -> отпечаток для сверки на копипасту. -> str.

    ЗАЧЕМ. В живой сводке стояли ТРИ ОДИНАКОВЫХ твита от трёх разных аккаунтов («$ARCC $W
    $FTI … I made $80,000»). Дедупликация по автору их не ловит - авторы разные; по ссылке
    тоже - ссылки разные. Ловит только сам текст, приведённый к сравнимому виду: без
    регистра, без ссылок, без знаков и без лишних пробелов.
    """
    import re as _re
    t = _re.sub(r'https?://\S+', ' ', str(txt or '').lower())
    t = _re.sub(r'[^a-zа-я0-9$ ]+', ' ', t)
    return ' '.join(t.split())[:160]


def _is_spam(txt):
    """Платный сигнальный спам и накрутка голосов. -> True/False."""
    low = str(txt or "").lower()
    return any(m in low for m in _SPAM_MARKS)


def _relevant(t, tick, name, tw, klass=None):
    """Твит вообще про этот актив? -> bool.

    Проверка по тексту, а не по доверию к поиску: провайдер отдаёт «похожее», и в выборку
    попадают чужие инструменты с тем же словом. Порог мягкий (тикер ИЛИ первое слово имени) —
    жёсткий отсёк бы нормальные твиты, где актив назван иначе.
    """
    txt = (str(t.get('text') or '') + ' ' + str(t.get('fullText') or '')).lower()
    if not txt.strip():
        return False
    import re as _re
    from .variational_feed import OFFCHAIN_CLASSES as _OFF
    raw = str(t.get('text') or '') + ' ' + str(t.get('fullText') or '')
    tk = str(tick or '').upper()
    # КЭШТЕГ - ВСЕГДА И У ВСЕХ: `$ACE` с границей справа («$ACEX» - другой тикер).
    if tk and _re.search(r'\$' + _re.escape(tk.lower()) + r'(?![a-z0-9])', txt):
        return True
    if klass in _OFF:
        # У АКЦИИ ЗАСЧИТЫВАЕТСЯ ТОЛЬКО КЭШТЕГ (ТЗ 2.7): тикер акции - это часто обычное слово
        # (`A`, `ON`, `NOW`), а имя компании в тексте про её продукты не новость про перп.
        # С ТЗ 2.5 ТО ЖЕ У СЫРЬЯ, МЕТАЛЛОВ И ИНДЕКСОВ: первое слово имени у них «Gold», «Swap».
        return False
    # ═══ ГОЛЫЙ ТИКЕР И ИМЯ - ТОЛЬКО КОГДА ОНИ НЕ ОБЫЧНЫЕ СЛОВА (этап 3, живая карточка ACE) ═══
    # X по ACE притащил твит про «fusionist claim» из политфилософии: имя Fusionist - обычное
    # английское слово, и прежнее правило засчитывало его по первому слову имени. Хуже того,
    # тикер искался ПОДСТРОКОЙ: «ace» находился в «place» и «face».
    # Теперь голый тикер засчитывается только ЗАГЛАВНЫМИ, целым словом, от трёх букв и если это не
    # словарное слово (`bip39_en.txt` - 2048 частых английских слов, уже лежит в репо). Имя - только
    # ЦЕЛОЙ ФРАЗОЙ из двух и больше слов («Ethereum Name Service»): одно слово имени нельзя
    # отличить от обычного слова без словаря, а угадывать запрещено. Остаётся кэштег.
    if (tk and len(tk) >= 3 and tk.isalnum() and tk.lower() not in _common_words()
            and _re.search(r'(?<![A-Za-z0-9$])' + _re.escape(tk) + r'(?![A-Za-z0-9])', raw)):
        return True
    base = _q_base(name)
    if base and len(base.split()) >= 2:
        return bool(_re.search(r'(?<![a-z0-9])' + _re.escape(base.lower()) + r'(?![a-z0-9])',
                               txt))
    return False


_COMMON = {'w': None}


def _common_words():
    """Частые английские слова (BIP-39, 2048 шт.). -> set. Нет файла - пустое множество."""
    if _COMMON['w'] is None:
        try:
            _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'bip39_en.txt')
            with open(_p, encoding='utf-8') as f:
                _COMMON['w'] = {x.strip().lower() for x in f if x.strip()}
        except OSError:
            _COMMON['w'] = set()
    return _COMMON['w']


async def _x_lines(tick, name, uid=None, keep=None, klass=None):
    """Твиты вокруг события. -> (строки, отказ). Отсев жёсткий и НАЗВАН в строке-заголовке.

    `keep` - список, в который кладутся ОСТАВЛЕННЫЕ твиты: из них итог кодом берёт строку
    причины (`verdict_lines`). Отдельным возвратом не сделано, чтобы не менять форму ответа
    для остальных вызывающих.
    `klass` - класс актива: у акции (equity/fund) твит засчитывается только с кэштегом $TICKER
    (ТЗ 2.7). Имя компании релевантностью не считается - «Dell» в тексте про ноутбуки не
    новость про перп DELL.
    """
    try:
        import twitter_api as tw
    except Exception as e:
        return [], 'модуль X не импортирован: %s' % str(e)[:80]
    q = _q_for(tick, name)
    out = {}
    try:
        tweets = await tw.search_tweets(q, latest=True, since_minutes=X_WINDOW_MIN,
                                        limit=X_FETCH, uid=uid, out=out)
    except Exception as e:
        return [], 'поиск по X не дошёл: %s: %s' % (type(e).__name__, str(e)[:90])
    if not out.get('ok'):
        # СЛОВА ПЛОЩАДКИ, А НЕ НАШИ: `out['error']` уже содержит разбор («нет ключа», «HTTP
        # 429»), и переписывать его своими словами значит терять различие между этими случаями.
        return [], 'X: %s' % (out.get('error') or 'отказ без причины')
    import time as _t
    now = _t.time()
    kept, dropped = [], {'old': 0, 'small': 0, 'offtopic': 0, 'spam': 0, 'copy': 0,
                         'lang': 0}
    _seen_fp = set()
    for t in (tweets or []):
        if not isinstance(t, dict):
            continue
        if not _fresh_enough(t, now, tw):
            dropped['old'] += 1
            continue
        f = (tw.tweet_author(t) or {}).get('followers')
        if f is not None and f < config.x_min_followers():
            dropped['small'] += 1
            continue
        if not _relevant(t, tick, name, tw, klass=klass):
            dropped['offtopic'] += 1
            continue
        _txt = str(t.get('text') or '')
        if _is_spam(_txt):
            dropped['spam'] += 1
            continue
        # ЯЗЫК: ТОЛЬКО ТО, ЧТО ЧЕЛОВЕК ПРОЧИТАЕТ (ТЗ 2.7). Живая карточка JUP: твит «$AXS $JUP
        # $INJ 暴富三剑客…» прошёл все фильтры, потому что тикер в нём есть, а язык не проверялся.
        # Карточка на русском с абзацем на китайском - это не контекст, а шум.
        if not _lang_ok(_txt):
            dropped['lang'] += 1
            continue
        # КОПИПАСТА ОТ РАЗНЫХ АВТОРОВ - ОДНА НОВОСТЬ, А НЕ ТРИ. Три одинаковых поста в сводке
        # выглядят как подтверждение, которого нет: это один текст, размноженный ботами.
        _fp = _norm(_txt)
        if _fp in _seen_fp:
            dropped['copy'] += 1
            continue
        _seen_fp.add(_fp)
        kept.append(t)
        if len(kept) >= X_LIMIT:
            break
    if not kept:
        # ЧТО ИМЕННО ОТСЕЯЛИ - ЧИСЛАМИ. «Ничего не нашли» и «нашли двадцать, но все старше трёх
        # часов» требуют разных выводов: второе значит, что новость есть, просто не сейчас.
        return [], ('X: свежих и по делу нет (отсеяно: старше %d мин - %d, мелкие - %d, '
                    'не про актив - %d, сигнальный спам - %d, копипаста - %d, не ru/en - %d)'
                    % (config.x_max_age_min(), dropped['old'], dropped['small'],
                       dropped['offtopic'], dropped['spam'], dropped['copy'], dropped['lang']))
    # ЗАГОЛОВОК БЕЗ ПРАВИЛ ОТБОРА (этап 3): «за 180 мин, аккаунты от 1.5k» - это описание
    # нашего фильтра, а не рынка, и решения оно не меняет. Правила - в справке.
    lines = ['<b>X</b>']
    for t in kept:
        lines.append(_tweet_line(t, tw, now))
    if keep is not None:
        keep.extend(kept)
    return lines, None


def _short_n(v):
    """Вес аккаунта коротко. -> str.

    ДО ДЕСЯТИ ТЫСЯЧ - С ДЕСЯТОЙ ДОЛЕЙ. Округление до «9k» стирает разницу между 8 600 и 9 400
    подписчиков ровно в том диапазоне, где она решает: это граница между «мелкий аккаунт» и
    «на него смотрят». Выше десяти тысяч десятая доля уже ничего не добавляет.
    """
    v = float(v)
    if v >= 1e6:
        return '%.1fM' % (v / 1e6)
    if v >= 10000:
        return '%.0fk' % (v / 1000)
    if v >= 1000:
        return '%.1fk' % (v / 1000)
    return '%.0f' % v


def _tweet_line(t, tw, now):
    """Один твит для сводки. -> HTML-строка.

    ФОРМАТ ПЕРЕДЕЛАН ПО ЖИВОЙ СВОДКЕ 25.09: прежняя строка склеивала автора, вес, возраст и
    180 символов текста в две слипшиеся строки - читать это в телефоне невозможно. Теперь
    первая строка отвечает «кто и когда» (автор ссылкой, вес, возраст), а сам текст идёт
    ЦИТАТОЙ (`blockquote`) - Telegram рисует её отступом, и глаз отделяет чужие слова от
    наших чисел без всякого усилия.
    ТЕКСТ КОРОЧЕ: 180 символов в сводке из трёх твитов - это экран целиком. 140 хватает,
    чтобы понять, о чём речь, а полный текст - в один тап по автору.
    """
    from .cards import esc
    a = tw.tweet_author(t) or {}
    who = a.get('handle') or '?'
    f = a.get('followers')
    ts = tw.tweet_ts(t)
    mins = int((now - float(ts)) / 60) if ts else None
    age = ('%dм' % mins) if mins is not None and mins < 60 else (
        ('%dч' % (mins // 60)) if mins is not None else '?')
    txt = ' '.join(str(t.get('text') or '').split())[:140]
    url = ''
    try:
        url = tw.tweet_url(t) or ''
    except Exception:
        pass
    head = '@%s' % esc(who)
    if url:
        head = '<a href="%s">%s</a>' % (url, head)
    bits = [head]
    if f:
        bits.append(_short_n(f))
    bits.append(age)
    return '%s\n<blockquote>%s</blockquote>' % (' · '.join(bits), esc(txt))

#: ПОЛЯ ОБЪЁМА У NANSEN - СПИСКОМ, И ПЕРВЫЕ ДВА ВАЖНЕЕ ОСТАЛЬНЫХ. `tgm/who-bought-sold` отдаёт
#: `bought_volume_usd`/`sold_volume_usd` (имена видны в `order_by` нашего же клиента), и их
#: отсутствие в прежнем списке давало «размер не назван» у КАЖДОГО кошелька - сводка выглядела
#: собранной и не несла ни одного числа.
_VOL_FIELDS = ('bought_volume_usd', 'sold_volume_usd', 'volume_usd', 'value_usd',
               'trade_value_usd', 'total_usd', 'amount_usd', 'buy_volume_usd', 'sell_volume_usd')


def _meaningful(lbl):
    """Смысловая метка или ''. Одна дверь на весь бот - `nansen_api.meaningful_label`."""
    try:
        import nansen_api as _n
        return _n.meaningful_label(lbl)
    except Exception:                                    # noqa: BLE001
        return str(lbl or '').strip()


def _row_usd(r, side):
    """Размер сделки строки ленты ПО НАПРАВЛЕНИЮ. -> float | None.

    ═══ ЗДЕСЬ ВРАЛИ ЧИСЛА, И ЭТО БЫЛ САМЫЙ ДОРОГОЙ ВИД ОШИБКИ ═══
    В ответе `tgm/who-bought-sold` у КАЖДОЙ строки есть ОБА поля: `bought_volume_usd` и
    `sold_volume_usd`. Прежний код брал ПЕРВОЕ НЕПУСТОЕ из общего списка, а первым в списке
    стоял `bought_volume_usd` - значит у строк ПРОДАЖ печаталась сумма покупок того же адреса.
    Живой замер 26.09: адрес с меткой Token Millionaire продал на $74 959 и купил на $14 773, а
    карточка показывала «$14.8k» в разделе «Продавали»; чистый продавец с нулевыми покупками
    печатался как «$0». То есть человек видел продажу в пять раз меньше настоящей, а иногда и
    нулевую - и это не пустота, а неверное число под правильной подписью.
    ТЕПЕРЬ НАПРАВЛЕНИЕ РЕШАЕТ, КАКОЕ ПОЛЕ ЧИТАТЬ, а общий список остаётся только запасным - для
    ответов, где направленных полей нет вовсе.
    """
    want = 'sold_volume_usd' if str(side).upper() == 'SELL' else 'bought_volume_usd'
    for k in (want,) + tuple(f for f in _VOL_FIELDS if f not in
                             ('bought_volume_usd', 'sold_volume_usd')):
        v = r.get(k)
        if v not in (None, ''):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _who_lines(rows, head, bot_un=None, limit=3, side='BUY'):
    """Строки «кто входил/выходил». Деньги берём ТОЛЬКО из поля объёма НУЖНОЙ стороны.

    `price_usd` в ответах Nansen — цена ОДНОГО токена, а не размер сделки, и спутать их значит
    напечатать $0.99 вместо $48K. В проекте это уже ловилось, поэтому здесь закрытый список
    полей, а не «первое похожее».

    ПУСТЫЕ И НУЛЕВЫЕ СТРОКИ НЕ ПЕЧАТАЮТСЯ ВОВСЕ. «• Token Millionaire — $0» это не информация,
    а шум, который выглядит как измерение: адрес попал в ответ по другой стороне сделки.
    ОДИНАКОВЫЕ МЕТКИ РАЗЛИЧАЮТСЯ ХВОСТОМ АДРЕСА. Три строки «Token Millionaire» подряд читаются
    как один и тот же кошелёк, то есть ровно наоборот смыслу сигнала («несколько РАЗНЫХ»).
    """
    from .cards import esc, _usd
    if not rows:
        return []
    got = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        vol = _row_usd(r, side)
        if vol is None or vol <= 0:
            continue
        got.append((vol, r))
    if not got:
        return []
    got.sort(key=lambda p: -p[0])
    # СКОЛЬКО ОДИНАКОВЫХ МЕТОК ВСТРЕТИЛОСЬ - СЧИТАЕМ ДО ПЕЧАТИ: хвост адреса нужен только там,
    # где метка повторяется, иначе он засоряет строку без пользы.
    seen = {}
    for _v, r in got[:int(limit)]:
        lb = _meaningful(r.get('address_label') or r.get('trader_address_label') or r.get('label'))
        if lb:
            seen[lb] = seen.get(lb, 0) + 1
    out = ['<b>%s</b>' % esc(head)]
    for vol, r in got[:int(limit)]:
        addr = (r.get('address') or r.get('trader_address') or '')
        # ТЕХНИЧЕСКАЯ МЕТКА -> ПУСТО, и тогда печатается короткий адрес со ссылкой на карточку.
        label = _meaningful(r.get('address_label') or r.get('trader_address_label')
                            or r.get('label'))
        # ИМЯ ЧЕЛОВЕКА, А НЕ СОРОК ДВА СИМВОЛА HEX. Адрес целиком человек не читает и не
        # сравнивает; метка читается, а полный адрес доступен тапом по ссылке на его экран.
        who = label or (addr[:6] + '…' + addr[-4:] if len(addr) > 12 else addr) or '?'
        if label and seen.get(label, 0) > 1 and len(str(addr)) >= 4:
            who = '%s …%s' % (label, str(addr)[-4:])
        who = esc(who)
        if addr and bot_un:
            try:
                import nansen_api as _n
                who = _n.acc_link(who, addr, bot_un)
            except Exception:
                pass
        out.append('• %s: %s' % (who, _usd(vol)))
    return out


def _net_line(buys, sells, hours=3):
    """Нетто смарт-мани ЧИСЛОМ - первой строкой блока. -> (строка | None, нетто, оборот).

    ═══ ВЕДЁМ ВЕЛИЧИНОЙ, А НЕ СПИСКОМ (ЗАКОН ПРОЕКТА) ═══
    Три строки «кто покупал» и три «кто продавал» - это данные, а не ответ. Вопрос человека
    «деньги заходят или выходят» требует ОДНОГО числа со знаком, и считать его обязан код: пока
    итог собирал глазами человек, он складывал шесть чисел в уме и делал это на телефоне.
    ОБОРОТ ВОЗВРАЩАЕМ ОТДЕЛЬНО, потому что по нему принимается второе решение - стоит ли вообще
    показывать блок и платить за второй вызов (см. `_ONCHAIN_MIN_USD`).
    """
    from .cards import _usd
    b = [(_row_usd(r, 'BUY') or 0.0) for r in (buys or ()) if isinstance(r, dict)]
    s = [(_row_usd(r, 'SELL') or 0.0) for r in (sells or ()) if isinstance(r, dict)]
    b = [x for x in b if x > 0]
    s = [x for x in s if x > 0]
    bought, sold = sum(b), sum(s)
    turn = bought + sold
    if turn <= 0:
        return None, 0.0, 0.0
    net = bought - sold
    bits = []
    if s:
        bits.append('продавали %d %s на %s' % (len(s), _plural_addr(len(s)), _usd(sold)))
    if b:
        bits.append('покупали %d %s на %s' % (len(b), _plural_addr(len(b)), _usd(bought)))
    line = ('• за %d ч нетто <b>%s%s</b> (%s)'
            % (int(hours), ('+' if net >= 0 else '-'), _usd(abs(net)), ', '.join(bits)))
    return line, net, turn


def _plural_addr(n):
    """«адрес/адреса/адресов» по числу. Мелочь, но текст читает человек, а не тест."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return 'адрес'
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return 'адреса'
    return 'адресов'


#: ПОРОГ ЗНАЧИМОСТИ ОНЧЕЙН-СЛЕДА, доллары. Ниже него блок заменяется одной строкой, и мы не
#: платим за перп-контекст. Абсолютное число нужно рядом с процентным (1% оборота): у мелкого
#: инструмента процент дал бы копейки и пропустил бы всё.
_ONCHAIN_MIN_USD = 25_000.0
#: БЮДЖЕТ ОБОГАЩЕНИЯ: одно на (площадка, тикер) в час. Разбор - в `store.enrich_recent`.
ENRICH_EVERY_S = 3600
#: КОРЗИНА ЦЕНЫ ДЛЯ КЛАСТЕРОВ ЛИКВИДАЦИЙ - 1% от текущей цены (ТЗ 1.6в), и минимальная сумма в
#: корзине, ниже которой кластер не называем: одинокая позиция на $3k не «уровень», а строка шума.
_LIQ_BUCKET_PCT = 1.0
_LIQ_MIN_USD = 100_000.0


async def _perp_lines(tick, address, chain, price, venue=None):
    """Перп-контекст события: чьё плечо стоит и где висят ликвидации. -> (строки, кредиты).

    ═══ ЧТО ЭТО ДОБАВЛЯЕТ К ДВИЖЕНИЮ ЦЕНЫ (ТЗ 1.6 б, в) ═══
    Движение отвечает «что произошло». Человек, который собирается зайти, спрашивает другое:
    кто уже стоит в этом инструменте и где ему будет больно. Оба ответа у нас были В КЛИЕНТЕ и
    не использовались дозорным ни разу: `perp_positioning` (лонги против шортов по сегментам,
    схема снята живой пробой 24.09) и `perp_positions` (открытые позиции с ЦЕНОЙ ЛИКВИДАЦИИ).

    НИКОГДА НЕ БРОСАЕТ: это третий блок сводки, и его отказ не имеет права уронить первые два.
    ЧИСЛА СЧИТАЕТ КОД, А НЕ МОДЕЛЬ: кластеры ликвидаций собираются корзинами по 1% цены, и в
    карточку идут ДВЕ ближайшие - ниже и выше. «Список из двадцати позиций» это данные, а
    «лонги от $1.1M на 16% ниже» - ответ.
    """
    from .cards import esc, _usd
    out, credits = [], 0
    if not tick:
        return out, 0
    try:
        import asyncio
        import nansen_api as _n
    except Exception:                                      # noqa: BLE001
        return out, 0
    # ── (б) ЧЬЁ ПЛЕЧО: сегменты. Берём ЧИСЛА (`perp_positioning_data`), а не готовый блок: у
    #    экрана Nansen свой формат на десять строк, а нам нужна одна строка внутри карточки.
    # КЛЮЧ - ТИКЕР ПЕРП-РЫНКА, А НЕ КОНТРАКТ (живая проба 26.09): по контракту ручка отвечает
    #    нулями на ЛЮБОЙ токен, и эта строка не появлялась никогда - нули здесь молча
    #    отбрасываются, поэтому дефект не был виден даже как «плеча нет». Тикер события уже и
    #    есть тикер перп-рынка: дозорный смотрит именно за перпами.
    _pkey, _how = _n.positioning_key(tick)
    if _pkey:
        try:
            with _tele.scene('sentinel_ignition', None, surface='sentinel'):
                _r = await asyncio.to_thread(_n.perp_positioning, _pkey)
            credits += 1
            # `perp_positioning_data` ОТДАЁТ СЛОВАРЬ {'segments': [...], ...}, А НЕ СПИСОК.
            # Первая редакция (1b) перебирала сам словарь, спотыкалась на строке-ключе и
            # падала в `except` - строка «С плечом» не появилась НИ РАЗУ, а в логе стояло
            # «'str' object has no attribute 'get'». Нашёл живой прогон на настоящем ответе
            # Nansen 26.09: тест на заглушке этого пройти не мог, заглушка была не той формы.
            _d = _n.perp_positioning_data(_r) if _r else None
            segs = (_d or {}).get('segments') if isinstance(_d, dict) else None
            bits = []
            for s in (segs or ()):
                _l, _sh = s.get('longs'), s.get('shorts')
                if _l is None and _sh is None:
                    continue
                if not (_l or _sh):
                    continue
                bits.append('%s лонг %s / шорт %s' % (s.get('ru') or s.get('key'),
                                                      _usd(_l or 0), _usd(_sh or 0)))
            if bits:
                out.append('<b>С плечом</b>')
                out.append('• %s' % esc('; '.join(bits[:3])))
        except Exception as e:                             # noqa: BLE001
            print('[sentinel] позиционирование %s не прочитано: %s' % (tick, str(e)[:110]))
    # ── (в) ЛИКВИДАЦИИ: где висит чужое плечо. Позиции - Hyperliquid, но нужны они любому
    #    событию с тем же тикером: где стоят ликвидации на крупнейшей перп-площадке, там цена и
    #    пойдёт быстро, на какой бы бирже человек ни торговал. Прежде блок был только у событий
    #    Hyperliquid, и у Variational и Lighter его не было никогда.
    #    ОПОРНАЯ ЦЕНА - `mark_price` ИЗ САМОГО ОТВЕТА (поле снято пробой 26.09): расстояние до
    #    ликвидации обязано считаться от цены той же площадки, где стоит позиция, а не от цены
    #    события на другой бирже.
    if tick and _pkey:
        try:
            with _tele.scene('sentinel_ignition', None, surface='sentinel'):
                rows = await asyncio.to_thread(_n.perp_positions, _pkey, 40)
            credits += 5
            _marks = sorted(float(r['mark_price']) for r in (rows or ())
                            if isinstance(r, dict) and r.get('mark_price'))
            ref = _marks[len(_marks) // 2] if _marks else (float(price) if price else None)
            line = _liq_line(rows, ref) if ref else None
            if line:
                out.append('<b>Ликвидации</b>%s' % ('' if venue == 'hyperliquid'
                                                    else ' <i>(Hyperliquid)</i>'))
                out.append('• %s' % line)
        except Exception as e:                             # noqa: BLE001
            print('[sentinel] позиции %s не прочитаны: %s' % (tick, str(e)[:110]))
    return out, credits


#: СЕГМЕНТЫ ПОТОКОВ ДЛЯ СТРОКИ: ключ ответа `tgm/flow-intelligence` -> подпись. Поля сняты живой
#: пробой REST 26.09: `{segment}_net_flow_usd`, `_avg_flow_usd`, `_wallet_count` для smart_trader,
#: whale, public_figure, top_pnl, exchange, fresh_wallets. В строку идут три по решению владельца:
#: смарт-мани (история), киты (размер), свежие кошельки (новые деньги или обход меток).
#: Биржи НЕ берём: их знак читается наоборот (приток на биржу - это продажа), и в одной строке
#: с остальными он запутал бы.
_SEGMENTS = (('smart_trader', 'смарт-мани'), ('whale', 'киты'), ('fresh_wallets', 'свежие кошельки'))


async def _segment_line(chain, address, floor_usd):
    """Нетто по сегментам холдеров за сутки одной строкой. -> (строка | None, кредиты).

    ТОЛЬКО ПРИ ЗНАЧИМЫХ ЧИСЛАХ (решение владельца): сегмент печатается, если его нетто по модулю
    не меньше того же порога значимости, что у трёхчасового следа (`_ONCHAIN_MIN_USD` или 1%
    оборота). Строка «смарт-мани +$3k, киты -$1k» - это шум, выглядящий как анализ.
    НИКОГДА НЕ БРОСАЕТ: блок необязательный, его отказ уходит в лог.
    """
    from .cards import _usd
    if not chain or not address:
        return None, 0
    try:
        import asyncio
        import nansen_api as _n
        with _tele.scene('sentinel_ignition', None, surface='sentinel'):
            r = await asyncio.to_thread(_n.tgm_flow_intelligence, chain, address, '1d')
    except Exception as e:                               # noqa: BLE001
        print('[sentinel] сегменты потоков %s не прочитаны: %s' % (address[:10], str(e)[:100]))
        return None, 1
    return segment_text(r, floor_usd), 1


def segment_text(r, floor_usd):
    """Ответ flow-intelligence -> строка | None. ЧИСТАЯ ФУНКЦИЯ (её проверяет тест)."""
    from .cards import _usd
    if not isinstance(r, dict):
        return None
    bits = []
    for key, name in _SEGMENTS:
        try:
            v = float(r.get('%s_net_flow_usd' % key))
        except (TypeError, ValueError):
            continue
        if abs(v) < float(floor_usd or 0):
            continue
        n = r.get('%s_wallet_count' % key)
        bits.append('%s %s%s%s' % (name, '+' if v >= 0 else '-', _usd(abs(v)),
                                   (' (%d)' % int(n)) if n else ''))
    if not bits:
        return None
    return '• за сутки: %s' % ', '.join(bits)


def _liq_line(rows, price):
    """Позиции с ценой ликвидации -> строка про ДВА ближайших кластера. -> str | None.

    ЧИСТАЯ ФУНКЦИЯ: ни сети, ни базы - её и проверяет тест на фикстуре.
    ПОЧЕМУ КОРЗИНЫ, А НЕ «САМАЯ БЛИЗКАЯ ПОЗИЦИЯ». Одна позиция на $3k у цены ликвидации ничего
    не значит; значение имеет СКОПЛЕНИЕ - когда на одном уровне стоит несколько миллионов, его
    выносят вместе, и цена там идёт быстро. Поэтому суммируем по корзинам в 1% цены и печатаем
    только те, где набралось от $100k: ниже этого «уровень» был бы обещанием, которого нет.
    """
    from .cards import _usd
    if not rows or not price or price <= 0:
        return None
    step = float(price) * (_LIQ_BUCKET_PCT / 100.0)
    if step <= 0:
        return None
    longs, shorts = {}, {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            liq = r.get('liquidation_price') or r.get('liq_price') or r.get('liquidationPrice')
            liq = float(liq) if liq not in (None, '') else None
            val = r.get('position_value_usd') or r.get('value_usd') or r.get('notional_usd')
            val = float(val) if val not in (None, '') else None
        except (TypeError, ValueError):
            continue
        if not liq or not val or liq <= 0 or val <= 0:
            continue
        # СТОРОНУ ОПРЕДЕЛЯЕМ ПО ЦЕНЕ ЛИКВИДАЦИИ, А НЕ ПО ПОЛЮ: поле `side` в этой ручке бывает
        # пустым, а геометрия однозначна - лонг ликвидируется НИЖЕ цены, шорт ВЫШЕ.
        bucket = round(liq / step) * step
        (longs if liq < price else shorts)[bucket] = (
            (longs if liq < price else shorts).get(bucket, 0.0) + val)
    bits = []
    _lo = [(b, v) for b, v in longs.items() if v >= _LIQ_MIN_USD]
    _hi = [(b, v) for b, v in shorts.items() if v >= _LIQ_MIN_USD]
    if _lo:
        b, v = max(_lo, key=lambda p: p[0])          # ближайший снизу
        bits.append('лонгов %s на %.6g (%+.1f%%)' % (_usd(v), b, (b / price - 1.0) * 100.0))
    if _hi:
        b, v = min(_hi, key=lambda p: p[0])          # ближайший сверху
        bits.append('шортов %s на %.6g (%+.1f%%)' % (_usd(v), b, (b / price - 1.0) * 100.0))
    return ', '.join(bits) if bits else None


async def build(ev, uid=None, bot_un=None):
    """Событие -> сводка. -> dict {lines, refused, summary, cost_line, credits}.

    НИКОГДА НЕ БРОСАЕТ: сводка — второе сообщение, и её падение не имеет права ронять тик
    доставки первого. Всё, что не собралось, превращается в НАЗВАННУЮ причину.

    СОСТАВ СВОДКИ - ВЫБОР ЧЕЛОВЕКА (`store.parts_for`): 'nansen' и 'news' включаются отдельно.
    Владелец просил именно так: «в настройках можно включить, что в алерте приходит».
    """
    from .cards import esc, _usd
    p = ev.get('payload') or {}
    tick = ev.get('ticker') or p.get('symbol') or '?'
    name = p.get('name') or ''
    lines, refusals, credits = [], [], 0
    parts = store.parts_for(uid) if uid else {'card', 'nansen', 'news'}
    # ФАКТЫ ДЛЯ ИТОГА КОДОМ (ТЗ 2.8). Собираются по ходу сборки блоков, а не разбором готового
    # текста: итог обязан опираться на ЧИСЛА, а не на то, как мы их напечатали.
    facts = {'sm': None, 'tweets': []}
    # КОНТРАКТ, КОТОРЫЙ ЗНАЕМ К КОНЦУ СБОРКИ (для ссылки «Паспорт» в первой карточке).
    brief_addr = (p.get('address'), p.get('chain'))

    # ═══ КЛАСС АКТИВА РЕШАЕТ, ИДТИ ЛИ В ОНЧЕЙН ВООБЩЕ (ТЗ 1.5) ═══
    # Закон 41: сигнал, который нельзя получить, не подменяется соседним. У акции нет контракта
    # в сети; у нативной монеты на EVM-цепи есть только обёртка, и поток по обёртке отвечает на
    # вопрос «сколько перевезли через мост», а не «что делают с активом». Прежний код звал
    # сопоставление по цене для ЛЮБОГО события - и находил что-нибудь: для NEAR обёртку, для
    # акции Dell любой токен, совпавший по цене. Два платных вызова возвращали ончейн про не тот
    # токен, а это хуже пустоты: пустота видна, неверный ончейн выглядит как ответ.
    # КЛАСС - ИЗ СОБЫТИЯ (этап 3): его посчитал опрашивающий процесс, у которого есть справочник
    # Variational; здесь (часто это бот, без своего опроса) у Hyperliquid имя равно тикеру, и
    # пересчёт по имени дал бы 'unknown' - то есть платный ончейн для акции.
    _klass = p.get('asset_class')
    if not _klass:
        try:
            from .variational_feed import asset_class as _ac
            _klass = _ac(type('_L', (), {'name': name, 'ticker': tick,
                                         'venue': p.get('venue') or 'variational'})())
        except Exception:                                 # noqa: BLE001
            _klass = None
    _no_onchain = assets.onchain_refusal(tick, _klass)
    _kind = ev.get('kind')
    # БЮДЖЕТ: ОДНО ОБОГАЩЕНИЕ НА (ПЛОЩАДКА, ТИКЕР) В ЧАС. Дальше по коду это даст строку «контекст
    # был N минут назад», а не второй такой же блок за те же кредиты.
    _venue = p.get('venue') or 'variational'
    _ago, _prev_key = store.enrich_recent(_venue, tick, within_s=ENRICH_EVERY_S)

    if 'nansen' not in parts:
        pass                                  # человек выключил ончейн - молчим, это не отказ
    elif _no_onchain:
        # ИЗМЕРЕННАЯ ГРАНИЦА, И ЧЕЛОВЕКУ ОНА НЕ ПЕЧАТАЕТСЯ (этап 3): «у акции нет контракта в
        # сети» решения не меняет. Кредиты не тратим, причина - в лог.
        print('[sentinel] %s: %s' % (tick, _no_onchain))
        facts['sm'] = ('none', 0.0, 0.0)
    elif store.budget_block():
        refusals.append('ончейн не смотрели: %s' % store.budget_block())
    elif _ago is not None:
        # ПОВТОР ПО ТОМУ ЖЕ ИНСТРУМЕНТУ: ДОБАВИТЬ НЕЧЕГО - БЛОК НЕ ПЕЧАТАЕТСЯ (этап 3). Строка
        # «контекст по X был N мин назад, он не изменился» стояла в карточке и не меняла ничего.
        print('[sentinel] %s: ончейн-контекст был %d мин назад, повтор не печатаю' % (tick, _ago))
    elif _kind in ('ignition', 'sm_perp'):
        # У ЗАЖИГАНИЯ И СМАРТ-ПЕРПА ДАННЫЕ УЖЕ ЕСТЬ - они пришли из той же ленты, что и событие.
        # Второй запрос за тем же адресом был бы платой за то, что мы уже знаем.
        lines.append('<b>Ончейн</b>')
        if _kind == 'sm_perp':
            lines.append('• %d %s открыли %s на %s за %d мин'
                         % (int(p.get('wallets') or 0), _plural_addr(p.get('wallets') or 0),
                            ('лонг' if p.get('side') == 'long' else 'шорт'),
                            _usd(p.get('usd')), int(p.get('window_min') or 0)))
        else:
            lines.append('• куплено на %s за %d мин, сделок %s'
                         % (_usd(p.get('usd')), int(p.get('window_min') or 0),
                            p.get('trades') or '?'))
        if p.get('is_new'):
            lines.append('• <b>новый токен</b> (метка Nansen), истории у него нет')
        facts['sm'] = ('source', float(p.get('usd') or 0), float(p.get('wallets') or 0))
        if p.get('labels'):
            lines.append('• метки: %s' % esc(', '.join(p['labels'][:6])))
    else:
        conf = await ignition.confirm(tick, p.get('mark'))
        credits += int(conf.get('credits') or 0)
        if conf.get('address'):
            _hrs = int(conf.get('hours') or ignition.CONFIRM_HOURS)
            _net, _netv, _turn = _net_line(conf.get('buyers'), conf.get('sellers'), hours=_hrs)
            # ═══ МЕЛКИЙ СЛЕД - ОДНОЙ СТРОКОЙ, И ДАЛЬШЕ НЕ ПЛАТИМ (ТЗ 1.4) ═══
            # $4k оборота по токену с суточным объёмом $2M не «подтверждают» и не «опровергают»
            # ничего; печатать шесть строк про такие суммы значит выдавать шум за контекст. Порог
            # относительный И абсолютный: 1% от оборота события ловит крупные инструменты, $25k -
            # мелкие, у которых процент дал бы копейки.
            _floor = max(_ONCHAIN_MIN_USD, 0.01 * float(p.get('volume_24h') or 0))
            # КОНТРАКТ - В КАРТОЧКУ ССЫЛКОЙ НА ПАСПОРТ, А НЕ СТРОКОЙ БЛОКА (этап 3): блок «Ончейн»
            # печатается только когда в нём есть числа; адрес без чисел - это служебная строка.
            brief_addr = (conf.get('address'), conf.get('chain'))
            _on = []
            # СЕГМЕНТЫ ЗА СУТКИ ИДУТ ДАЖЕ ПРИ МЕЛКОМ ТРЁХЧАСОВОМ СЛЕДЕ: это другой вопрос («кто
            # набирал за день»), и тишина последних трёх часов на него не отвечает. Строка при
            # этом печатается только при значимых числах (`_segment_line`).
            _sl, _sc = await _segment_line(conf.get('chain'), conf['address'], _floor)
            credits += int(_sc or 0)
            if _sl:
                _on.append(_sl)
            # ПУСТОЙ И МЕЛКИЙ СЛЕД - СТРОКОЙ ИТОГА («смарт-мани молчат»), А НЕ ДВАЖДЫ: прежде
            # тот же факт стоял и в блоке («не показываю»), и в итоге.
            if _turn <= 0:
                facts['sm'] = ('silent', 0.0, 0.0)
            elif _turn < _floor:
                facts['sm'] = ('silent', _netv, _turn)
            else:
                facts['sm'] = ('net', _netv, _turn)
                if _net:
                    _on.append(_net)
                _on += _who_lines(conf.get('sellers'), 'Продавали за %d ч' % _hrs, bot_un,
                                  side='SELL')
                _on += _who_lines(conf.get('buyers'), 'Покупали за %d ч' % _hrs, bot_un,
                                  side='BUY')
            if _on:
                lines.append('<b>Ончейн</b>')
                lines += _on
        if conf.get('refused'):
            refusals.append('ончейн: %s' % conf['refused'])

    # ═══ ПЕРП-КОНТЕКСТ - ОТДЕЛЬНЫМ БЛОКОМ, НЕ ЗАВИСЯЩИМ ОТ КОНТРАКТА (ТЗ 1.6 б, в) ═══
    # В 1b этот блок жил ВНУТРИ ветки «контракт сопоставлен и след значимый». После живой пробы
    # 26.09 (#938) стало ясно, что это неверное место: позиционирование и ликвидации ключуются
    # ТИКЕРОМ ПЕРП-РЫНКА, а не контрактом. Значит у нативов (NEAR, SOL, TAO - контракта нет по
    # построению) и у смарт-перпа (контракта нет вовсе) строки «С плечом» и «Ликвидации» не
    # появились бы НИКОГДА, хотя именно там они и отвечают на вопрос. Проба ручки подтвердила:
    # «native tokens (SOL, ETH, BTC) are fully supported in perps mode».
    # ГРАНИЦЫ БЮДЖЕТА ТЕ ЖЕ, ЧТО В ТЗ: не для расхождения, спреда и толпы; не для акций и фондов;
    # не повтором в течение часа по тому же инструменту.
    if ('nansen' in parts and _ago is None and not store.budget_block()
            and _kind not in ('venue_gap', 'spread_shock', 'crowded')
            and _klass not in ('equity', 'fund')):
        _pl, _pc = await _perp_lines(tick, None, None, p.get('mark') or p.get('price'),
                                     'hyperliquid' if _kind == 'sm_perp' else _venue)
        credits += int(_pc or 0)
        if _pl:
            if lines:
                lines.append('')
            lines += _pl

    # ── ПРЕДСКАЗАТЕЛЬНЫЙ РЫНОК (роудмап 3.7): ЧЕГО ЖДУТ, А НЕ ЧТО УЖЕ БЫЛО ────────────────
    # Живёт под тем же флагом 'nansen', что и ончейн: расклад держателей стоит кредитов, и
    # человек, выключивший платное, не должен получить его через другую дверь. САМ ПОИСК РЫНКА
    # БЕСПЛАТЕН (публичный gamma-api), поэтому при исчерпанном капе приедет хотя бы рынок -
    # см. `predict.lines`, там это разделено.
    if 'nansen' in parts:
        try:
            from . import predict
            pl, pr, pc = await predict.lines(tick, name, uid=uid)
            credits += int(pc or 0)
            if pl:
                if lines:
                    lines.append('')
                lines += pl
            if pr:
                # ОТКАЗ - В ЛОГ, А НЕ ЧЕЛОВЕКУ (ТЗ 2.7). Живая карточка JUP: «Чего не собрали:
                # предсказательный рынок: у инструмента нет полного имени, а по тикеру искать
                # нельзя». Это правда про НАШ поиск, а не про рынок, и человеку с ней делать
                # нечего: рынка про JUP на Polymarket не было и быть не должно. Мост покрывает
                # 4 инструмента из 13 - то есть такая строка стояла бы почти в каждой карточке.
                print('[sentinel] предсказательный рынок для %s не найден: %s' % (tick, pr))
        except Exception as _pe:                  # noqa: BLE001
            print('[sentinel] предсказательный рынок для %s упал: %s: %s'
                  % (tick, type(_pe).__name__, str(_pe)[:80]))

    if 'news' in parts:
        xl, xr = await _x_lines(tick, name, uid=uid, keep=facts['tweets'], klass=_klass)
        if xl:
            if lines:
                lines.append('')
            lines += xl
        if xr:
            refusals.append(xr)

    # ═══ ОТКАЗЫ - В ЛОГ, ЧЕЛОВЕКУ НИКОГДА (этап 3) ═══
    # «Чего не собрали: предсказательный рынок...», «X: свежих и по делу нет (отсеяно...)» - это
    # правда про НАШ сбор, а не про рынок, и решения трейдера она не меняет. Поле `refused` в
    # сводке осталось (его пишет база сводок для разбора), но карточка его не печатает.
    _ref = '; '.join(refusals) if refusals else None
    if _ref:
        print('[sentinel] %s: чего не собрали: %s' % (tick, _ref[:300]))
    brief = {'lines': lines, 'refused': _ref, 'summary': '', 'credits': credits}
    # ИТОГ КОДОМ ВСЕГДА, МОДЕЛЬ - ТОЛЬКО ПО ФЛАГУ (ТЗ 2.8, разбор в `config.llm_summary_on`).
    brief['verdict'] = verdict_lines(ev, facts, parts)
    brief['summary'] = await _summary(ev, lines)
    # КОНТРАКТ ДЛЯ ССЫЛКИ НА ПАСПОРТ В ПЕРВОЙ КАРТОЧКЕ (этап 3): карточка правится сводкой, и
    # в правке у токена с контрактом появляется «Паспорт». Сопоставление по цене уже оплачено.
    brief['address'], brief['chain'] = brief_addr
    # СТРОКИ РАСХОДА В СВОДКЕ БОЛЬШЕ НЕТ НИ У КОГО, ДАЖЕ У ВЛАДЕЛЬЦА (этап 3): расход виден на
    # экране дозорного (`outbox.status_line`), а в карточке он смещал фокус с рынка на бухгалтерию.
    print('[sentinel] сводка %s: %d кр Nansen · %s' % (tick, credits, store.spend_line()))
    return brief


#: СЛОВА НОВОСТИ В ТВИТЕ. Причина движения - это событие (листинг, взлом, анлок, партнёрство),
#: а не мнение («hated rally coming»). Список короткий и закрытый: слово вне него - не причина.
_NEWS_WORDS = ('listing', 'listed', 'lists', 'announce', 'hack', 'exploit', 'etf', 'partnership',
               'mainnet', 'unlock', 'delist', 'acquisition', 'acquire', 'merger', 'launch',
               'airdrop', 'sec ', 'lawsuit', 'upgrade',
               'листинг', 'взлом', 'анлок', 'разлок', 'партн', 'делист', 'запуск', 'аирдроп')


def _event_dir(ev):
    """Направление события. -> +1 | -1 | 0 (у вида нет направления)."""
    k = ev.get('kind') or ''
    p = ev.get('payload') or {}
    if k == 'move_up' or k == 'ignition':
        return 1
    if k == 'move_down':
        return -1
    if k == 'sm_perp':
        return 1 if p.get('side') == 'long' else -1
    return 0


def verdict_lines(ev, facts, parts=None):
    """ИТОГ ТРЕМЯ СТРОКАМИ, СОБРАННЫЙ ИЗ ЧИСЕЛ. -> [str]. ЧИСТАЯ ФУНКЦИЯ (её проверяет тест).

    ═══ ПОЧЕМУ КОД, А НЕ МОДЕЛЬ (живая карточка JUP, 26.09) ═══
    «Вывод модели» написал про «80% bullish настроя в X» - такого числа в данных не было, и
    текст был обрезан на полуслове. У каждой строки ниже один источник, и он в этой же карточке:
      1. СМАРТ-МАНИ: знак нетто за 3 часа ПРОТИВ направления события. «Подтверждают» - нетто в
         ту же сторону, «против» - в обратную, «молчат» - след мелкий или его нет. У вида без
         направления (интерес, оборот) - просто знак: подтверждать там нечего.
      2. ФАНДИНГ: равен ли он базовой ставке площадки (`venues.BASE_FUNDING_APR`, замер всех
         инструментов). Базовая ставка - это НЕ интерес к активу, а то, что площадка берёт,
         когда перекоса нет; в карточке JUP модель прочла её как сигнал.
      3. ПРИЧИНА: первая строка твита со словом новости (листинг, взлом, анлок...). Нет такого
         твита - «в X не найдена», и это честнее, чем мнение, выданное за причину.
    Строка, которую нечем посчитать, не печатается вовсе: выдуманная строка хуже пропущенной.
    """
    from .cards import esc, _usd
    parts = parts or {'card', 'nansen', 'news'}
    p = ev.get('payload') or {}
    d = _event_dir(ev)
    out = []
    sm = facts.get('sm')
    if 'nansen' in parts and sm:
        kind, net, turn = sm
        if kind == 'net':
            if d == 0:
                out.append('смарт-мани за 3 ч: нетто %s%s'
                           % ('+' if net >= 0 else '-', _usd(abs(net))))
            else:
                agree = (net > 0) == (d > 0)
                out.append('смарт-мани <b>%s</b>: нетто %s%s за 3 ч'
                           % ('подтверждают' if agree else 'против',
                              '+' if net >= 0 else '-', _usd(abs(net))))
        elif kind == 'silent':
            out.append('смарт-мани <b>молчат</b>: след за 3 ч %s' % (
                ('мелкий (%s)' % _usd(turn)) if turn else 'пустой'))
        elif kind == 'source':
            out.append('смарт-мани - <b>это и есть событие</b>: %d адресов на %s'
                       % (int(turn or 0), _usd(net)))
        # kind == 'none' (акция, натив) - строки нет: ончейна у актива нет.
        # 'repeat' БОЛЬШЕ НЕ БЫВАЕТ (этап 3): «контекст был N мин назад» решения не меняет.
    # ФАНДИНГ ИЗ ИТОГА УБРАН (этап 3): его состояние («базовый», «повышен») печатает сама карточка
    # (`cards.funding_line`), и вторая строка про то же число в итоге была повтором.
    if 'news' in parts:
        cause = None
        for t in facts.get('tweets') or ():
            txt = ' '.join(str(t.get('text') or '').split())
            low = txt.lower()
            if any(w in low for w in _NEWS_WORDS):
                cause = txt
                break
        if cause:
            out.append('причина в X: %s' % esc(cause[:120] + ('…' if len(cause) > 120 else '')))
        else:
            out.append('причина в X не найдена')
    return out


def _summary_sync(head, body):
    """Вывод ОДНИМ абзацем. Модель дешёвая, источник помечен — расход виден отдельной строкой в
    общей стате, а не растворяется в «прочем»."""
    import llm_router
    sysp = ('Ты аналитик рынка. По ДАННЫМ НИЖЕ напиши ОДИН абзац (максимум три строки) '
            'по-русски: что произошло и что в этих данных подтверждает движение, а что нет. '
            'Правила жёсткие: НЕ добавляй фактов и чисел, которых нет в данных; НЕ советуй '
            'покупать или продавать; НЕ обещай ничего; если данные противоречат друг другу, '
            'скажи это прямо; если подтверждения нет вовсе, так и скажи одной фразой. '
            'Без длинных тире, без вступлений, без разметки.')
    sysp += (' Ровно два предложения. Базовый фандинг площадки не является подтверждением '
             'интереса к активу. Процентов настроения, долей и оценок, которых нет в данных, не '
             'бывает.')
    r = llm_router.public_create(
        model=os.getenv('SENTINEL_LLM_MODEL') or 'claude-haiku-4-5-20251001',
        system=sysp,
        messages=[{'role': 'user', 'content': (head + '\n' + body)[:2500]}],
        max_tokens=350, source='sentinel')
    txt = ''.join(getattr(b, 'text', '') for b in (getattr(r, 'content', None) or []))
    return guard_summary((txt or '').strip().replace('—', '-'), head + '\n' + body)


def guard_summary(txt, data):
    """Сторож пересказа модели. -> текст | '' (выброшен). ЧИСТАЯ ФУНКЦИЯ.

    ДВА ПРАВИЛА, И ОБА ИЗ ЖИВОЙ КАРТОЧКИ JUP:
      * текст обязан закончиться точкой (или «!»/«?») - обрезанный на полуслове вывод это не
        вывод, а признак того, что модель не договорила;
      * КАЖДОЕ ЧИСЛО в тексте обязано встречаться в данных. «80% bullish настроя» не было ни в
        одной строке, и такое число выдумано по определению.
    Выброшенный вывод - не беда: итог кодом стоит в карточке всегда.
    """
    import re as _re
    t = str(txt or '').strip()
    if not t or t[-1] not in '.!?':
        if t:
            print('[sentinel] пересказ модели выброшен: не закончен (%r)' % t[-40:])
        return ''
    src = str(data or '').replace(',', '.').replace(' ', '')
    for n in _re.findall(r'\d+(?:[.,]\d+)?', t):
        if n.replace(',', '.') not in src:
            print('[sentinel] пересказ модели выброшен: числа %s нет в данных' % n)
            return ''
    return t


async def _summary(ev, lines):
    """-> строка вывода | ''. Провал МОЛЧАЛИВ для человека и ГРОМОК в логе.

    Пустой вывод не ломает сводку: числа выше стоят сами по себе, и это главная причина, по
    которой модель здесь стоит последней, а не первой.
    """
    if not config.enrich_on() or not config.llm_summary_on() or os.getenv('SENTINEL_LLM_OFF') == '1':
        return ''
    if not lines:
        return ''
    try:
        import asyncio
        import re
        from . import cards
        # МОДЕЛИ ОТДАЁМ ТЕКСТ БЕЗ ТЕГОВ: HTML в промпте она начинает воспроизводить, и в ответе
        # появляются `<b>` — Telegram отвергает разметку целиком, и сводка не доходит.
        head = re.sub(r'<[^>]+>', '', cards.card(ev))[:1200]
        body = re.sub(r'<[^>]+>', '', '\n'.join(lines))
        return await asyncio.wait_for(asyncio.to_thread(_summary_sync, head, body), 20)
    except Exception as e:
        print('[sentinel] вывод не собрался: %s: %s' % (type(e).__name__, str(e)[:120]))
        return ''
