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

from . import config, ignition, store

#: Окно поиска по X. Час-полтора, а не сутки: сводка нужна к движению ПОСЛЕДНИХ минут, а
#: суточная выборка утонет в обычном фоне тикера и покажет вчерашнее как объяснение сегодняшнего.
X_WINDOW_MIN = int(os.getenv('SENTINEL_X_WINDOW_MIN') or 90)
X_LIMIT = int(os.getenv('SENTINEL_X_LIMIT') or 3)
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
    base = (name or '').split(',')[0].strip()
    for tail in (' Inc', ' Corporation', ' Corp', ' Company', ' plc', ' Ltd', ' Trust',
                 ' Swap on', 'Swap on '):
        base = base.replace(tail, '').strip()
    parts = []
    if tick:
        parts.append('$%s' % tick)
    if base and base.lower() != (tick or '').lower():
        parts.append('"%s"' % base)
    return ' OR '.join(parts) if parts else (tick or '')


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
               'risk management is key', 'entry zone')


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


def _relevant(t, tick, name, tw):
    """Твит вообще про этот актив? -> bool.

    Проверка по тексту, а не по доверию к поиску: провайдер отдаёт «похожее», и в выборку
    попадают чужие инструменты с тем же словом. Порог мягкий (тикер ИЛИ первое слово имени) —
    жёсткий отсёк бы нормальные твиты, где актив назван иначе.
    """
    txt = (str(t.get('text') or '') + ' ' + str(t.get('fullText') or '')).lower()
    if not txt.strip():
        return False
    if tick and tick.lower() in txt:
        return True
    head = (name or '').split(',')[0].split()[0:1]
    return bool(head and len(head[0]) > 3 and head[0].lower() in txt)


async def _x_lines(tick, name, uid=None):
    """Твиты вокруг события. -> (строки, отказ). Отсев жёсткий и НАЗВАН в строке-заголовке."""
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
    kept, dropped = [], {'old': 0, 'small': 0, 'offtopic': 0, 'spam': 0, 'copy': 0}
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
        if not _relevant(t, tick, name, tw):
            dropped['offtopic'] += 1
            continue
        _txt = str(t.get('text') or '')
        if _is_spam(_txt):
            dropped['spam'] += 1
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
        return [], ('X: свежих и по делу нет (отсеяно: старше %d мин — %d, мелкие — %d, '
                    'не про актив — %d, сигнальный спам — %d, копипаста — %d)'
                    % (config.x_max_age_min(), dropped['old'], dropped['small'],
                       dropped['offtopic'], dropped['spam'], dropped['copy']))
    lines = ['<b>X</b> <i>(за %d мин, аккаунты от %s подписчиков)</i>'
             % (config.x_max_age_min(), _short_n(config.x_min_followers()))]
    for t in kept:
        lines.append(_tweet_line(t, tw, now))
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


def _who_lines(rows, head, bot_un=None, limit=4):
    """Строки «кто входил/выходил». Деньги берём ТОЛЬКО из полей объёма.

    `price_usd` в ответах Nansen — цена ОДНОГО токена, а не размер сделки, и спутать их значит
    напечатать $0.99 вместо $48K. В проекте это уже ловилось, поэтому здесь закрытый список
    полей, а не «первое похожее».
    """
    from .cards import esc, _usd
    if not rows:
        return []
    out = ['<b>%s</b>' % esc(head)]
    for r in rows[:limit]:
        if not isinstance(r, dict):
            continue
        addr = (r.get('address') or r.get('trader_address') or '')
        label = (r.get('address_label') or r.get('trader_address_label') or r.get('label') or '')
        vol = None
        for k in _VOL_FIELDS:
            if r.get(k) not in (None, ''):
                try:
                    vol = float(r[k])
                    break
                except (TypeError, ValueError):
                    pass
        # ИМЯ ЧЕЛОВЕКА, А НЕ СОРОК ДВА СИМВОЛА HEX. Адрес целиком человек не читает и не
        # сравнивает; метка читается, а полный адрес доступен тапом по ссылке на его экран.
        who = label or (addr[:6] + '…' + addr[-4:] if len(addr) > 12 else addr) or '?'
        who = esc(who)
        if addr and bot_un:
            try:
                import nansen_api as _n
                who = _n.acc_link(who, addr, bot_un)
            except Exception:
                pass
        out.append('• %s — %s' % (who, (_usd(vol) if vol is not None else 'размер не назван')))
    return out


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

    if 'nansen' not in parts:
        pass                                  # человек выключил ончейн - молчим, это не отказ
    elif store.budget_block():
        refusals.append('ончейн не смотрели: %s' % store.budget_block())
    elif ev.get('kind') == 'ignition':
        # У ЗАЖИГАНИЯ КОНТРАКТ УЖЕ ЕСТЬ - он пришёл из той же ленты, что и событие. Второй запрос
        # за тем же адресом был бы платой за то, что мы уже знаем.
        lines.append('<b>Ончейн</b>')
        lines.append('• %s · <code>%s</code>' % (esc(p.get('chain') or '?'),
                                                 esc(p.get('address') or '?')))
        lines.append('• куплено на %s за %d мин, сделок %s'
                     % (_usd(p.get('usd')), int(p.get('window_min') or 0),
                        p.get('trades') or '?'))
        if p.get('labels'):
            lines.append('• метки: %s' % esc(', '.join(p['labels'][:6])))
    else:
        conf = await ignition.confirm(tick, p.get('mark'))
        credits += int(conf.get('credits') or 0)
        if conf.get('address'):
            lines.append('<b>Ончейн</b> <i>(контракт сопоставлен по цене)</i>')
            lines.append('• %s · <code>%s</code>' % (esc(conf.get('chain') or '?'),
                                                     esc(conf['address'])))
            lines += _who_lines(conf.get('buyers'), 'Покупали за сутки', bot_un)
            lines += _who_lines(conf.get('sellers'), 'Продавали за сутки', bot_un)
        if conf.get('refused'):
            refusals.append('ончейн: %s' % conf['refused'])

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
                refusals.append('предсказательный рынок: %s' % pr)
        except Exception as _pe:                  # noqa: BLE001
            # СВОДКА НЕ ПАДАЕТ ИЗ-ЗА ОДНОГО БЛОКА: отказ становится названной причиной.
            refusals.append('предсказательный рынок: %s: %s'
                            % (type(_pe).__name__, str(_pe)[:80]))

    if 'news' in parts:
        xl, xr = await _x_lines(tick, name, uid=uid)
        if xl:
            if lines:
                lines.append('')
            lines += xl
        if xr:
            refusals.append(xr)

    brief = {'lines': lines, 'refused': ('; '.join(refusals) if refusals else None),
             'summary': '', 'credits': credits}
    brief['summary'] = await _summary(ev, lines)
    brief['cost_line'] = ('Сводка: %d кр Nansen · %s' % (credits, store.spend_line()))
    return brief


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
    r = llm_router.public_create(
        model=os.getenv('SENTINEL_LLM_MODEL') or 'claude-haiku-4-5-20251001',
        system=sysp,
        messages=[{'role': 'user', 'content': (head + '\n' + body)[:2500]}],
        max_tokens=200, source='sentinel')
    txt = ''.join(getattr(b, 'text', '') for b in (getattr(r, 'content', None) or []))
    return (txt or '').strip().replace('—', '-')[:600]


async def _summary(ev, lines):
    """-> строка вывода | ''. Провал МОЛЧАЛИВ для человека и ГРОМОК в логе.

    Пустой вывод не ломает сводку: числа выше стоят сами по себе, и это главная причина, по
    которой модель здесь стоит последней, а не первой.
    """
    if not config.enrich_on() or os.getenv('SENTINEL_LLM_OFF') == '1':
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
