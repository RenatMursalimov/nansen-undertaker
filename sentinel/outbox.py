# -*- coding: utf-8 -*-
"""sentinel/outbox.py — ОТПРАВКА: очередь в базе, общая дверь Telegram, «доставлено» только
по подтверждению.

ТРИ ПРАВИЛА, КАЖДОЕ ОПЛАЧЕНО ЧУЖИМ БАГОМ В ЭТОМ ЖЕ РЕПОЗИТОРИИ

1. ИДЁМ ЧЕРЕЗ `tg_send.safe_send`, А НЕ НАПРЯМУЮ `bot.send_message`. Восемь существующих
   рассыльщиков шлют напрямую и каждый по-своему обрабатывает FloodWait — то есть у восьми
   рассылок восемь разных представлений о том, что делать при «подожди 12 секунд». Общая
   дверь знает про троттлинг и про RetryAfter, и она одна.

2. `delivered_at` СТАВИТ ТОТ, КТО ПОЛУЧИЛ ОТВЕТ ТЕЛЕГРАМА. Не тот, кто решил отправить.
   Иначе первая же RetryAfter даёт «доставлено» в базе при пустом экране у человека — и
   суточный потолок начинает считать отправки, которых не было.

3. ПАУЗА ПО ИНСТРУМЕНТУ ОТМЕЧАЕТСЯ ТОЖЕ ТОЛЬКО ПОСЛЕ УСПЕХА. Отметь её до отправки — и сбой
   съедает час тишины: человек не получил алерт И не получит следующий. Ровно эту ошибку
   `perp_watch` уже исправлял отдельной правкой.

СТРОКА В ЛОГ НА КАЖДУЮ ОТПРАВКУ — через общий `alert_log.sent`, тем же форматом, что у
остальных восьми рассыльщиков: «кому / чья подписка / о чём». Разбор следующего случая
«получил алерт, которого не ждал» иначе невозможен — это уже проверено на живом инциденте.
"""

import time

import alert_log

from . import cards, config, store  # noqa: F401

_BOT_TOKEN = None
_BOT = None


def configure(bot_token):
    """Токен для отправки. Таблицы модуль готовит сам (`db.ready`), configure их не требует."""
    global _BOT_TOKEN
    _BOT_TOKEN = bot_token


def _bot():
    global _BOT
    if _BOT is None and _BOT_TOKEN:
        from telegram import Bot
        _BOT = Bot(token=_BOT_TOKEN)
    return _BOT


def quiet_now(settings, now=None):
    """Тихие часы человека. -> True, если сейчас молчим.

    ЧАСЫ В UTC И ОКНО ЧЕРЕЗ ПОЛНОЧЬ РАБОТАЕТ. «С 22 до 8» — самое частое пожелание, и
    наивная проверка `from <= h < to` на нём даёт круглосуточную тишину.
    """
    f, t = settings.get('quiet_from'), settings.get('quiet_to')
    if f is None or t is None:
        return False
    h = int(time.strftime('%H', time.gmtime(now if now is not None else time.time())))
    f, t = int(f) % 24, int(t) % 24
    if f == t:
        return False
    return (f <= h < t) if f < t else (h >= f or h < t)


def plan(ev):
    """Кому этот алерт нужен -> поставить доставки в очередь. -> (сколько поставили, [причины]).

    ПРИЧИНЫ ОТКАЗА ВОЗВРАЩАЮТСЯ СПИСКОМ, А НЕ ГЛОТАЮТСЯ. «Событие было, а алертов ноль» —
    это ровно тот случай, в котором через неделю никто не разберётся: тишина одинаково
    выглядит и при пустой подписке, и при упоре в потолок, и при паузе.
    """
    reasons = []
    uids = store.subscribers(ev.get('ticker') or '')
    if not uids:
        return 0, ['на %s никто не подписан' % ev.get('ticker')]
    n = 0
    for uid in uids:
        s = store.settings(uid)
        if not s.get('alerts_on'):
            reasons.append('uid=%s: алерты выключены' % uid)
            continue
        mp = s.get('min_pct')
        mv = (ev.get('payload') or {}).get('move_pct')
        if mp is not None and mv is not None and abs(float(mv)) < float(mp):
            reasons.append('uid=%s: %.2f%% ниже личного порога %.2f%%' % (uid, abs(mv), mp))
            continue
        if quiet_now(s):
            reasons.append('uid=%s: тихие часы' % uid)
            continue
        left = store.cooldown_left(uid, ev.get('ticker') or '', _cd_kind(ev))
        if left:
            reasons.append('uid=%s: пауза ещё %dмин' % (uid, left // 60))
            continue
        cap = store.cap_for(uid)
        got = store.sent_today(uid)
        if got >= cap:
            # УПОР В ПОТОЛОК ПИШЕМ ЧИСЛОМ. «Кап сработал» без цифр не отвечает на вопрос
            # «поднять или это норма».
            reasons.append('uid=%s: суточный потолок %d/%d' % (uid, got, cap))
            continue
        if store.delivery_plan(ev['key'], uid):
            n += 1
    return n, reasons


def _cd_kind(ev):
    """КЛЮЧ ПАУЗЫ ВКЛЮЧАЕТ СТУПЕНЬ СИЛЫ. Пауза по «движению вверх» не должна глушить весть о
    том, что движение удвоилось: это разные новости, и человек ждёт вторую."""
    p = ev.get('payload') or {}
    return '%s:%d' % (ev.get('kind') or '?', int(p.get('step') or 1))


async def _send(uid, text, label=''):
    """-> объект сообщения | False. Никогда не бросает (это дверь рассылки)."""
    b = _bot()
    if b is None:
        print('[sentinel] отправка невозможна: токен не задан (configure не звали)')
        return False
    try:
        import tg_send
    except Exception as e:
        print('[sentinel] tg_send не импортирован (%s) - шлю напрямую' % str(e)[:80])
        try:
            return await b.send_message(chat_id=uid, text=text)
        except Exception as e2:
            print('[sentinel] tg err uid=%s: %s' % (uid, str(e2)[:150]))
            return False
    err = {}

    def _fail(e):
        err['e'] = e
    res = await tg_send.safe_send(lambda: b.send_message(chat_id=uid, text=text),
                                 chat_key=uid, label=label or 'sentinel', on_fail=_fail)
    if not res and err.get('e'):
        return ('err', err['e'])
    return res


async def deliver_due(limit=25):
    """Один круг отправки. -> (отправлено, отказов).

    ОЧЕРЕДЬ ЧИТАЕМ ИЗ БАЗЫ, А НЕ ИЗ ПАМЯТИ ТИКА: доставка, не удавшаяся из-за сети, обязана
    пережить рестарт. Алерт, исчезнувший вместе с процессом, — это алерт, о котором никто
    никогда не узнает.
    """
    ok = bad = 0
    for event_key, uid, attempts in store.delivery_due(limit=limit):
        ev = store.event(event_key)
        if ev is None:
            store.delivery_fail(event_key, uid, 'событие пропало из базы')
            bad += 1
            continue
        text = cards.card(ev)
        res = await _send(uid, text, label='sentinel:%s' % ev.get('kind'))
        if isinstance(res, tuple) and res and res[0] == 'err':
            state = store.delivery_fail(event_key, uid, res[1])
            print('[sentinel] не доставлено uid=%s %s (%s, попытка %d -> %s)'
                  % (uid, ev.get('ticker'), str(res[1])[:90], attempts + 1, state))
            bad += 1
            continue
        if not res:
            state = store.delivery_fail(event_key, uid, 'telegram отказал без причины')
            bad += 1
            print('[sentinel] не доставлено uid=%s %s (попытка %d -> %s)'
                  % (uid, ev.get('ticker'), attempts + 1, state))
            continue
        store.delivery_ok(event_key, uid, getattr(res, 'message_id', None))
        store.cooldown_mark(uid, ev.get('ticker') or '', _cd_kind(ev))
        # ПОДПИСКА И ПОЛУЧАТЕЛЬ — ОДНО И ТО ЖЕ ЧИСЛО, И ПЕРЕДАЁМ МЫ ИХ ОТДЕЛЬНО НАРОЧНО:
        # общий формат лога сам кричит при расхождении, а расхождение и есть утечка.
        alert_log.sent('sentinel', uid, sub=uid,
                       obj='%s/%s' % (ev.get('kind'), ev.get('ticker')))
        ok += 1
    return ok, bad


async def deliver_enrichment(event_key, brief, limit=25):
    """Второе сообщение — ТОЛЬКО тем, кто получил первое. -> сколько ушло.

    Список получателей берём из ФАКТА доставки (`delivered_at IS NOT NULL`), а не из
    подписки: подписчик, чей первый алерт не дошёл, получил бы сводку к сообщению, которого
    не видел, — и это читается как сбой бота.
    """
    ev = store.event(event_key)
    if ev is None:
        return 0
    text = cards.enrich_card(ev, brief)
    n = 0
    for uid in store.delivered_users(event_key)[:limit]:
        if not store.settings(uid).get('enrich_on'):
            continue
        res = await _send(uid, text, label='sentinel:brief')
        if res and not (isinstance(res, tuple) and res[0] == 'err'):
            alert_log.sent('sentinel_brief', uid, sub=uid,
                           obj='%s/%s' % (ev.get('kind'), ev.get('ticker')))
            n += 1
    return n


def status_line(lang='ru'):
    """Одна строка о состоянии дозорного — для экрана, для пульта и для команды владельца.

    ВЕДЁМ ВЕЛИЧИНАМИ: «дозорный включён» ничего не значит, если кольцо пусто или аренда у
    мёртвого процесса. Поэтому здесь число снимков, число событий за сутки и расход числом.

    ДВА ЯЗЫКА, ПОТОМУ ЧТО СТРОКА ПОПАДАЕТ НА ЭКРАН. Она встроена в меню дозорного, а по меню
    ходит автоматический обходчик e2e и требует, чтобы на `lang=en` не было кириллицы. Русская
    строка внутри английского экрана покраснела бы в ЧУЖОМ тесте и выглядела бы как его поломка.
    """
    now = int(time.time())
    seen = len(store.tickers_seen(now - 3600))
    evs = len(store.events_since(now - 86400, limit=9999))
    owner, until = store.lease_owner()
    if lang == 'en':
        return ('sentinel: instruments in the last hour %d · events in 24h %d · polled by %s '
                '(lease %s) · %s'
                % (seen, evs, owner or 'nobody',
                   ('%ds left' % (until - now)) if until > now else 'expired',
                   store.spend_line('en')))
    return ('дозор: инструментов за час %d · события за сутки %d · опрос у %s (аренда %s) · %s'
            % (seen, evs, owner or 'никого',
               ('ещё %dс' % (until - now)) if until > now else 'истекла',
               store.spend_line()))
