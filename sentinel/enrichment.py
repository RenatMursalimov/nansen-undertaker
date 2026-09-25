# -*- coding: utf-8 -*-
"""sentinel/enrichment.py — ВТОРОЕ сообщение: что вокруг этого движения. Nansen + X + пересказ.

ПОРЯДОК РАБОТ ПЕРЕВЁРНУТ ОТНОСИТЕЛЬНО ОСТАЛЬНОГО БОТА, И ЭТО ГЛАВНОЕ РЕШЕНИЕ МОДУЛЯ
Обогащаем ТОЛЬКО то, что УЖЕ доставлено (`store.enrich_pending` строит список по факту
доставки). Причин две. Первая: платить кредитами за сводку к алерту, которого человек не
видел, — это трата без адресата. Вторая, важнее: пока сводка собирается (запрос к Nansen,
поиск по X, вызов модели — секунды), цена на площадке живёт. Если бы сводка ехала внутри
первого сообщения, человек получал бы цену на секунды позже — ровно в те секунды, за которые
он и хотел успеть. `perp_watch` устроен наоборот (LLM внутри пути отправки, таймаут 12с), и
этот модуль сознательно от него отличается.

ЧТО МОДЕЛЬ ЗДЕСЬ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ
Делает: пересказывает строки, которые УЖЕ посчитаны и уже стоят в сообщении. Не делает:
не решает, событие это или нет; не ставит оценку; не добавляет фактов; не называет цифр,
которых нет выше. В карточке пересказ так и подписан — «пересказ данных выше», чтобы человек
не принял его за источник.

БЮДЖЕТ ПРОВЕРЯЕМ ДО ЗАПРОСОВ, А НЕ ПОСЛЕ. Дозорный жжёт кредиты БЕЗ человека, по факту
движения рынка; один волатильный день мог бы съесть бюджет, из которого живут экраны по
запросу. Поэтому первая строка функции — остаток, и он ВЕЛИЧИНА, а не флаг.

ЧЕСТНЫЙ ОТКАЗ ВМЕСТО ПУСТОТЫ. Каждая строка сводки либо несёт число с названным источником,
либо называет КЛАСС отказа: «нет кредитов», «площадка молчит», «тикер не сопоставлен
контракту», «ключа X нет». Пустая сводка выглядит одинаково при всех четырёх — и это ровно
тот дефект, из-за которого в проекте однажды показали чистую страницу вместо сообщения о
нехватке кредитов.
"""

import os

from . import config, ignition, store

#: Окно поиска по X. Час, а не сутки: сводка нужна к движению ПОСЛЕДНИХ минут, а суточная
#: выборка утонет в обычном фоне тикера и покажет вчерашние новости как объяснение сегодняшних.
X_WINDOW_MIN = int(os.getenv('SENTINEL_X_WINDOW_MIN') or 90)
X_LIMIT = int(os.getenv('SENTINEL_X_LIMIT') or 4)

#: ОТСЕВ ПО ВЕСУ АККАУНТА НЕ ДЕЛАЕМ ЗДЕСЬ: `twitter_api.format_tweets` уже ПОМЕЧАЕТ мелкие
#: аккаунты («⚠️ мелкий аккаунт») и печатает число подписчиков. Пометка честнее отсева: у
#: пострадавшего от слива подписчиков всегда сто, и он пишет первым.


async def _x_lines(query, uid=None):
    """Твиты вокруг события. -> (строки, отказ)."""
    try:
        import twitter_api as tw
    except Exception as e:
        return [], 'модуль X не импортирован: %s' % str(e)[:80]
    out = {}
    try:
        tweets = await tw.search_tweets(query, latest=True, since_minutes=X_WINDOW_MIN,
                                        limit=X_LIMIT, uid=uid, out=out)
    except Exception as e:
        return [], 'поиск по X не дошёл: %s: %s' % (type(e).__name__, str(e)[:90])
    if not out.get('ok'):
        # СЛОВА ПЛОЩАДКИ, А НЕ НАШИ. `out['error']` уже содержит разбор («нет ключа», «HTTP
        # 429»), и переписывать его своими словами значит терять различие между этими случаями.
        return [], 'X: %s' % (out.get('error') or 'отказ без причины')
    if not tweets:
        return [], 'X: за %d мин по запросу «%s» ничего не написали' % (X_WINDOW_MIN, query)
    try:
        body = tw.format_tweets(tweets, limit=X_LIMIT)
    except Exception as e:
        return [], 'твиты не отформатировались: %s' % str(e)[:80]
    lines = ['Что пишут в X за %d мин (запрос «%s»):' % (X_WINDOW_MIN, query)]
    lines += [l for l in (body or '').split('\n') if l.strip()]
    return lines, None


def _who_lines(rows, head, limit=4):
    """Строки «кто входил/выходил» из ответа Nansen. Деньги берём ТОЛЬКО из полей объёма.

    `price_usd` в ответах Nansen — цена ОДНОГО токена, а не размер сделки, и спутать их значит
    напечатать $0.99 вместо $48K. В проекте это уже ловилось, поэтому здесь берём только
    явные поля объёма и, не найдя их, честно говорим «размер не назван».
    """
    if not rows:
        return []
    out = [head]
    for r in rows[:limit]:
        if not isinstance(r, dict):
            continue
        who = (r.get('address_label') or r.get('trader_address_label')
               or r.get('label') or r.get('address') or r.get('trader_address') or '?')
        vol = None
        for k in ('volume_usd', 'value_usd', 'trade_value_usd', 'total_usd', 'amount_usd'):
            if r.get(k) not in (None, ''):
                try:
                    vol = float(r[k])
                    break
                except (TypeError, ValueError):
                    pass
        out.append('  • %s — %s' % (str(who)[:46],
                                    ('$%.0f' % vol) if vol is not None else 'размер не назван'))
    return out


async def build(ev, uid=None):
    """Событие -> сводка. -> dict {lines, refused, summary, cost_line, credits}.

    НИКОГДА НЕ БРОСАЕТ: сводка — второе сообщение, и её падение не имеет права ронять тик
    доставки первого. Всё, что не собралось, превращается в НАЗВАННУЮ причину.
    """
    p = ev.get('payload') or {}
    tick = ev.get('ticker') or p.get('symbol') or '?'
    lines, refusals, credits = [], [], 0

    left = store.budget_left()
    if left <= 0:
        used, _ = store.spend_today()
        refusals.append('ончейн не смотрели: суточный бюджет дозорного исчерпан (%d из %d кр)'
                        % (used, config.nansen_day_credits()))
    elif ev.get('kind') == 'ignition':
        # У ЗАЖИГАНИЯ КОНТРАКТ УЖЕ ЕСТЬ — он пришёл из той же ленты, что и событие, и
        # сопоставлять тикер не нужно вовсе. Второй запрос за тем же адресом был бы платой за
        # то, что мы уже знаем.
        lines.append('Контракт: %s (%s)' % (p.get('address'), p.get('chain')))
        lines.append('Купили: %d разных адреса на $%.0f за %d мин'
                     % (int(p.get('wallets') or 0), float(p.get('usd') or 0),
                        int(p.get('window_min') or 0)))
        if p.get('labels'):
            lines.append('Метки: %s' % ', '.join(p['labels'][:6]))
    else:
        conf = await ignition.confirm(tick, p.get('mark'))
        credits += int(conf.get('credits') or 0)
        if conf.get('address'):
            lines.append('Тот же актив ончейн: %s (%s), сопоставлен по цене'
                         % (conf['address'], conf.get('chain') or '?'))
            lines += _who_lines(conf.get('buyers'), 'Покупали за сутки:')
            lines += _who_lines(conf.get('sellers'), 'Продавали за сутки:')
        if conf.get('refused'):
            refusals.append('ончейн: %s' % conf['refused'])

    # ── ТВИТТЕР. Запрос — ТИКЕР, и это компромисс, названный вслух: по короткому тикеру
    #    («A», «US») выборка будет мусорной, поэтому к короткому добавляем имя инструмента.
    q = tick if len(tick) >= 4 else ('%s %s' % (tick, (p.get('name') or '').split(',')[0])).strip()
    xl, xr = await _x_lines(q, uid=uid)
    if xl:
        lines.append('')
        lines += xl
    if xr:
        refusals.append(xr)

    brief = {'lines': lines, 'refused': ('; '.join(refusals) if refusals else None),
             'summary': '', 'credits': credits}
    brief['summary'] = await _summary(ev, lines)
    used, _ = store.spend_today()
    brief['cost_line'] = ('Стоимость сводки: %d кр Nansen · сегодня дозорный сжёг %d из %d'
                          % (credits, used, config.nansen_day_credits()))
    return brief


def _summary_sync(head, body):
    """Пересказ ОДНИМ абзацем. Модель дешёвая, источник помечен — расход виден отдельной
    строкой в общей стате, а не растворяется в «прочем»."""
    import llm_router
    sysp = ('Ты аналитик рынка. Перескажи ДАННЫЕ НИЖЕ одним абзацем (максимум три строки) '
            'по-русски: что произошло и что в этих данных подтверждает движение, а что нет. '
            'Правила жёсткие: НЕ добавляй фактов и чисел, которых нет в данных; НЕ советуй '
            'покупать или продавать; НЕ обещай ничего; если данные противоречат друг другу, '
            'скажи это прямо. Без длинных тире.')
    r = llm_router.public_create(
        model=os.getenv('SENTINEL_LLM_MODEL') or 'claude-haiku-4-5-20251001',
        system=sysp,
        messages=[{'role': 'user', 'content': (head + '\n' + body)[:2500]}],
        max_tokens=200, source='sentinel')
    txt = ''.join(getattr(b, 'text', '') for b in (getattr(r, 'content', None) or []))
    return (txt or '').strip().replace('—', '-')[:600]


async def _summary(ev, lines):
    """-> строка пересказа | ''. Провал МОЛЧАЛИВ для человека и ГРОМОК в логе.

    Пустой пересказ не ломает сводку: числа выше стоят сами по себе, и это главная причина,
    по которой модель здесь стоит последней, а не первой.
    """
    if not config.enrich_on() or os.getenv('SENTINEL_LLM_OFF') == '1':
        return ''
    if not lines:
        return ''
    try:
        import asyncio
        from . import cards
        head = cards.card(ev)[:1200]
        return await asyncio.wait_for(
            asyncio.to_thread(_summary_sync, head, '\n'.join(lines)), 20)
    except Exception as e:
        print('[sentinel] пересказ не собрался: %s: %s' % (type(e).__name__, str(e)[:120]))
        return ''
