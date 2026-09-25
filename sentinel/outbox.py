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


_BOT_UN = {'un': None, 'asked': False}


async def bot_un():
    """username бота для deep-link в свои же экраны. -> str | None.

    СПРАШИВАЕМ ЖИВОГО БОТА (`get_me`) ОДИН РАЗ И КЭШИРУЕМ. Хардкодить прод-имя нельзя: на
    тест-боте тап по ссылке увёл бы человека В ПРОД - ровно та граница, которую держит
    `nansen_api.tok_link` («нет имени - нет ссылки, молча»). Спрашиваем один раз: `get_me` это
    сетевой вызов, а ссылок в карточке три.
    """
    if _BOT_UN['un'] or _BOT_UN['asked']:
        return _BOT_UN['un']
    _BOT_UN['asked'] = True
    b = _bot()
    if b is None:
        return None
    try:
        me = await b.get_me()
        _BOT_UN['un'] = getattr(me, 'username', None)
    except Exception as e:
        # НЕ ПАДАЕМ И НЕ ПОДСТАВЛЯЕМ ЧУЖОЕ ИМЯ: карточка уедет без ссылок, и это честнее, чем
        # ссылка не в того бота.
        print('[sentinel] имя бота не прочитано (%s) - карточки пойдут без ссылок'
              % str(e)[:100])
    return _BOT_UN['un']


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


# ══════════════════════════════════════════════════════════════════════════════════════════
# ОДНА ДВЕРЬ РЕШЕНИЯ «МОЖНО ЛИ СЕЙЧАС ГОВОРИТЬ ЭТОМУ ЧЕЛОВЕКУ»
#
# ═══ ПОЧЕМУ ЭТА ФУНКЦИЯ ПОЯВИЛАСЬ: ВЫКЛЮЧАТЕЛЬ, КОТОРЫЙ НЕ ВЫКЛЮЧАЛ ═══
# ЖИВОЙ ИНЦИДЕНТ 25.09, СЛОВА ВЛАДЕЛЬЦА: «я сейчас отключил алерты в Дозорном, всё равно всё
# шлёт мне сигналы, что ты изменил такое, что сейчас шлётся даже несмотря на отключение и тихий
# пресет». Ответ нашёлся по коду за две минуты, и он не про пресеты: ВСЕ СЕМЬ ПРОВЕРОК (алерты
# включены, вид события, площадка, личный порог, тихие часы, пауза, суточный потолок) стояли
# ТОЛЬКО в `plan` - то есть в момент ПОСТАНОВКИ В ОЧЕРЕДЬ. А `deliver_due` читал очередь из базы
# и настроек не смотрел ВООБЩЕ. Значит выключатель управлял правом ВСТАТЬ в очередь, а не правом
# ПРИЙТИ на телефон: всё, что успело встать раньше, выезжало несмотря на «выключено».
#
# ЭТО НЕ ОПЕЧАТКА, А КЛАСС ОШИБКИ: решение принималось в одном месте, а действие совершалось в
# другом, и между ними лежала БАЗА, то есть время. Любая настройка, прочитанная до записи в
# очередь, к моменту отправки уже история. Лечится ровно одним способом - проверкой на выходе,
# у самой двери Telegram, и ТОЙ ЖЕ функцией, что решала при планировании. Две копии проверки
# разъехались бы на первой же правке.
#
# ТРИ ИСХОДА, И РАЗНИЦА МЕЖДУ НИМИ ПРИНЦИПИАЛЬНАЯ:
#   * None      - можно звонить;
#   * 'drop'    - человек ЭТОГО НЕ ХОЧЕТ (выключил алерты, вид, площадку, задал порог выше).
#                 В дайджест НЕ идёт: дайджест не имеет права стать лазейкой для того, что
#                 человек отключил руками;
#   * 'digest'  - хочет, но не сейчас (предохранитель темпа, слабое событие, пауза, потолок,
#                 тихие часы). Едет сводкой одним сообщением - и это не то же, что выбросить.
# ══════════════════════════════════════════════════════════════════════════════════════════
def mute_reason(uid, ev, now=None):
    """Можно ли отправить это событие этому человеку ПРЯМО СЕЙЧАС. -> (verdict, причина).

    verdict: None | 'drop' | 'digest'. Зовут ДВА места - `plan` (перед очередью) и
    `deliver_due` (перед самой отправкой). Именно поэтому она одна: см. врезку выше.
    """
    s = store.settings(uid)
    kind = ev.get('kind') or '?'
    p = ev.get('payload') or {}
    # ── 'drop': ЧЕЛОВЕК СКАЗАЛ «НЕТ». Это уважается буквально и без дайджеста. ─────────────
    if not s.get('alerts_on'):
        return 'drop', 'алерты выключены'
    # ВИД СОБЫТИЯ - ЛИЧНЫЙ ВЫБОР. Владелец просил именно так: «настраивать, что приходят алерты
    # движения плюс нансен движения существенные, или просто Нансен сигналы, или просто алерты
    # по объёму». Отсев стоит ЗДЕСЬ, а не в детекторе: событие одно на всех и пишется в базу
    # целиком (оно понадобится отчёту попаданий), а получатели у него разные.
    if kind not in store.kinds_for(uid):
        return 'drop', 'вид %s выключен в настройках' % kind
    # ПЛОЩАДКА - ТОЖЕ ЛИЧНЫЙ ВЫБОР. Тот, кто торгует только на одной, не должен получать алерты
    # второй: цена и спред там другие, и зайти по такому алерту он не может.
    _venue = p.get('venue') or 'variational'
    if _venue not in store.venues_for(uid):
        return 'drop', 'площадка %s выключена' % _venue
    mp, mv = s.get('min_pct'), p.get('move_pct')
    if mp is not None and mv is not None and abs(float(mv)) < float(mp):
        return 'drop', '%.2f%% ниже личного порога %.2f%%' % (abs(mv), mp)
    # ── 'digest': ХОЧЕТ, НО НЕ СЕЙЧАС ─────────────────────────────────────────────────────
    if quiet_now(s, now):
        return 'digest', 'тихие часы'
    # СЛАБОЕ СОБЫТИЕ НЕ ЗВОНИТ. Уверенность у нас считается со штрафами, и 40/100 - это событие,
    # к которому мы сами написали три причины сомневаться. Будить им нельзя, скрыть - потерять.
    # ПОРОГ ЛИЧНЫЙ (кнопка в меню), общий из `.env` остаётся дефолтом: требование владельца
    # 26.09 - «порог силы тоже надо настраивать, что алертить при выше какого-то порога».
    sev, _need = int(ev.get('severity') or 0), store.min_sev_for(uid)
    if sev < _need:
        return 'digest', 'уверенность %d/100 ниже порога звонка %d' % (sev, _need)
    # ═══ ПРЕДОХРАНИТЕЛЬ ТЕМПА. НАСТРАИВАЕМЫЙ, НО С ПОТОЛКОМ - ПРЕСЕТ ЕГО НЕ СНИМАЕТ ═══
    # Считается НА ЧЕЛОВЕКА, и это главное отличие от паузы и потолка, которые уже были: те
    # считались по инструменту, а инструментов 787 - то есть у бота было 787 законных
    # разрешений заговорить. См. врезку в `store.burst_for`: кнопка поднимает границу до
    # жёсткого потолка и НЕ ВЫШЕ, иначе граница превратилась бы в комментарий.
    _bm, _bw, _ = store.burst_for(uid)
    _got = store.sent_in_window(uid, _bw, now)
    if _got >= _bm:
        return 'digest', ('предохранитель: %d сообщений за %d мин (граница %d)'
                          % (_got, _bw // 60, _bm))
    left = store.cooldown_left(uid, ev.get('ticker') or '', _cd_kind(ev), now)
    if left:
        return 'digest', 'пауза по инструменту ещё %dмин' % (left // 60)
    cap, got = store.cap_for(uid), store.sent_today(uid, now)
    if got >= cap:
        # УПОР В ПОТОЛОК ПИШЕМ ЧИСЛОМ. «Кап сработал» без цифр не отвечает на вопрос «поднять
        # или это норма».
        return 'digest', 'суточный потолок %d/%d' % (got, cap)
    return None, ''


def plan(ev):
    """Кому этот алерт нужен -> поставить доставки в очередь. -> (сколько поставили, [причины]).

    ПРИЧИНЫ ОТКАЗА ВОЗВРАЩАЮТСЯ СПИСКОМ, А НЕ ГЛОТАЮТСЯ. «Событие было, а алертов ноль» —
    это ровно тот случай, в котором через неделю никто не разберётся: тишина одинаково
    выглядит и при пустой подписке, и при упоре в потолок, и при паузе.

    РЕШЕНИЕ ЗДЕСЬ - ПРЕДВАРИТЕЛЬНОЕ, И ЭТО НАПИСАНО ВСЛУХ: пока строка лежит в очереди, человек
    успевает выключить алерты, уйти в тихие часы или упереться в предохранитель. Окончательное
    слово - за той же `mute_reason` в момент отправки.
    """
    reasons = []
    uids = store.subscribers(ev.get('ticker') or '')
    if not uids:
        return 0, ['на %s никто не подписан' % ev.get('ticker')]
    n = 0
    for uid in uids:
        verdict, why = mute_reason(uid, ev)
        if verdict == 'drop':
            reasons.append('uid=%s: %s' % (uid, why))
            continue
        if verdict == 'digest':
            # НЕ ВЫБРАСЫВАЕМ. Событие ложится в сводку и уезжает одним сообщением раз в десять
            # минут - иначе человек не получил бы алерт И не узнал бы, что его не получил.
            store.digest_add(uid, ev['key'], ev.get('severity'), why)
            reasons.append('uid=%s: в дайджест (%s)' % (uid, why))
            continue
        if store.delivery_plan(ev['key'], uid):
            n += 1
    return n, reasons


def _cd_kind(ev):
    """КЛЮЧ ПАУЗЫ ВКЛЮЧАЕТ СТУПЕНЬ СИЛЫ. Пауза по «движению вверх» не должна глушить весть о
    том, что движение удвоилось: это разные новости, и человек ждёт вторую."""
    p = ev.get('payload') or {}
    return '%s:%d' % (ev.get('kind') or '?', int(p.get('step') or 1))


async def _send(uid, text, label='', kb=None):
    """-> объект сообщения | False. Никогда не бросает (это дверь рассылки).

    `kb` НЕОБЯЗАТЕЛЕН И ПО УМОЛЧАНИЮ ПУСТ: клавиатура нужна только сводке (сквозной переход в
    карточку инструмента), а у обычного алерта переходы живут ссылками в тексте. Добавлять
    кнопки всем «на всякий случай» значило бы менять вид семи путей отправки ради одного.
    """
    b = _bot()
    if b is None:
        print('[sentinel] отправка невозможна: токен не задан (configure не звали)')
        return False
    try:
        import tg_send
    except Exception as e:
        print('[sentinel] tg_send не импортирован (%s) - шлю напрямую' % str(e)[:80])
        try:
            return await b.send_message(chat_id=uid, text=text, parse_mode='HTML',
                                        disable_web_page_preview=True, reply_markup=kb)
        except Exception as e2:
            print('[sentinel] tg err uid=%s: %s' % (uid, str(e2)[:150]))
            return False
    err = {}

    def _fail(e):
        err['e'] = e
    # HTML, А НЕ MARKDOWN, И НЕ «БЕЗ РАЗМЕТКИ». В тикерах и метках адресов живут `_` и `*`, на
    # которых Markdown ломается - поэтому первая редакция шла вообще без разметки и получила от
    # владельца «весь текст без формата, ссылки без линков». В HTML опасны только `&<>`, и они
    # экранируются одной дверью (`cards.esc`).
    # ПРЕВЬЮ ВЫКЛЮЧЕНО: иначе под каждым алертом Telegram разворачивает картинку площадки, и
    # три алерта подряд превращаются в простыню.
    res = await tg_send.safe_send(
        lambda: b.send_message(chat_id=uid, text=text, parse_mode='HTML',
                               disable_web_page_preview=True, reply_markup=kb),
        chat_key=uid, label=label or 'sentinel', on_fail=_fail)
    if not res and err.get('e'):
        return ('err', err['e'])
    return res


async def deliver_due(limit=25):
    """Один круг отправки. -> (отправлено, отказов).

    ОЧЕРЕДЬ ЧИТАЕМ ИЗ БАЗЫ, А НЕ ИЗ ПАМЯТИ ТИКА: доставка, не удавшаяся из-за сети, обязана
    пережить рестарт. Алерт, исчезнувший вместе с процессом, — это алерт, о котором никто
    никогда не узнает.

    ═══ И КАЖДАЯ СТРОКА ПЕРЕПРОВЕРЯЕТСЯ ПЕРЕД ОТПРАВКОЙ ═══
    Раньше эта функция настроек НЕ ЧИТАЛА, и именно поэтому выключенные алерты продолжали
    приходить (живой инцидент 25.09 - см. врезку у `mute_reason`). Очередь это отложенное
    решение, а настройки человека живут своей жизнью: между постановкой и отправкой он успевает
    нажать «выключить». Право прийти на телефон проверяется У ДВЕРИ.
    """
    ok = bad = 0
    # АВАРИЙНЫЙ РУБИЛЬНИК ПРОВЕРЯЕТСЯ ПЕРВЫМ И ДО ЧТЕНИЯ ОЧЕРЕДИ: когда бот заливает человека,
    # ему нужна остановка, не требующая разбирательства в том, какой из фильтров не сработал.
    if not config.deliver_on():
        return 0, 0
    for event_key, uid, attempts in store.delivery_due(limit=limit):
        ev = store.event(event_key)
        if ev is None:
            store.delivery_fail(event_key, uid, 'событие пропало из базы')
            bad += 1
            continue
        # ПЕРЕПРОВЕРКА ПРАВА ГОВОРИТЬ - ТОЙ ЖЕ ДВЕРЬЮ, ЧТО РЕШАЛА ПРИ ПЛАНИРОВАНИИ.
        verdict, why = mute_reason(uid, ev)
        if verdict is not None:
            # ОТМЕНЯЕМ, А НЕ ПРОПУСКАЕМ: пропущенная строка вернулась бы на следующем тике и
            # так каждые 30 секунд вечно. Причина остаётся в базе - «почему мне это не пришло»
            # обязано иметь ответ.
            store.delivery_cancel(event_key, uid, why)
            if verdict == 'digest':
                store.digest_add(uid, event_key, ev.get('severity'), why)
            print('[sentinel] не шлю uid=%s %s/%s: %s'
                  % (uid, ev.get('kind'), ev.get('ticker'), why))
            continue
        # АТОМАРНЫЙ ЗАХВАТ. Очередь читают ДВА процесса (джоба бота и отдельный юнит), и без
        # захвата оба отправляли одни и те же строки - каждый алерт дважды, до 50 сообщений за
        # полминуты. Замер и разбор - в докстринге `store.delivery_claim`.
        if not store.delivery_claim(event_key, uid):
            continue
        text = cards.card(ev, bot_un=await bot_un())
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
    if not config.deliver_on():
        return 0
    text = cards.enrich_card(ev, brief)
    n = 0
    for uid in store.delivered_users(event_key)[:limit]:
        _s = store.settings(uid)
        if not _s.get('enrich_on'):
            continue
        # ВЫКЛЮЧЕННЫЕ АЛЕРТЫ ГЛУШАТ И СВОДКУ. Иначе выключатель оставлял бы половину потока:
        # человек выключил алерты, первое сообщение он уже получил до выключения - и сводка к
        # нему приезжала бы после, как будто ничего не произошло. «Выключено» значит тишина,
        # а не «тишина только в одном из двух каналов».
        if not _s.get('alerts_on'):
            continue
        # ЧЕЛОВЕК, ВЫКЛЮЧИВШИЙ И ОНЧЕЙН, И НОВОСТИ, СВОДКУ НЕ ЖДЁТ. Оставить ему пустое второе
        # сообщение значило бы прислать шум там, где он попросил тишины.
        if not ({'nansen', 'news'} & store.parts_for(uid)):
            continue
        res = await _send(uid, text, label='sentinel:brief')
        if res and not (isinstance(res, tuple) and res[0] == 'err'):
            alert_log.sent('sentinel_brief', uid, sub=uid,
                           obj='%s/%s' % (ev.get('kind'), ev.get('ticker')))
            n += 1
    return n


async def deliver_digest(limit_users=50, now=None):
    """Отправить накопленные сводки. -> (сколько человек получили, сколько строк ушло).

    ОДНО СООБЩЕНИЕ НА ЧЕЛОВЕКА ЗА КРУГ, И ЭТО ГЛАВНОЕ СВОЙСТВО: сводка, которая уезжает
    частями, - это тот же поток под другим именем.

    ТИХИЕ ЧАСЫ УВАЖАЕТ. Сводка - тоже сообщение, и звякнуть ею в четыре утра значило бы обойти
    настройку человека через служебную дверь. Строки не пропадают: они ждут конца тишины и
    уезжают одним письмом, что для сводки как раз естественно.

    `now` АРГУМЕНТОМ - ПРАВИЛО ЭТОГО ПАКЕТА, А НЕ УСТУПКА ТЕСТУ: проверка выдержки, которая
    спала бы десять минут, не запускается, а значит ничего не защищает.
    """
    if not config.deliver_on():
        return 0, 0
    people = rows = 0
    for uid in store.digest_users(config.digest_sec(), now=now)[:limit_users]:
        s = store.settings(uid)
        # ВЫКЛЮЧЕННЫЕ АЛЕРТЫ ГЛУШАТ И СВОДКУ: иначе выключатель оставил бы лазейку, и человек,
        # нажавший «выключить», получал бы вместо потока сводку того же потока.
        if not s.get('alerts_on') or quiet_now(s, now):
            continue
        pend = store.digest_pending(uid)
        if not pend:
            continue
        cut = config.digest_max_rows()
        items, keys = [], []
        for key, sev, why, _ts in pend[:cut]:
            ev = store.event(key)
            keys.append(key)
            if ev is not None:
                items.append({'ev': ev, 'why': why})
        # ХВОСТ ТОЖЕ ОТМЕЧАЕМ ОТПРАВЛЕННЫМ, ПОТОМУ ЧТО О НЁМ СКАЗАНО ЧИСЛОМ («и ещё 34 слабее»).
        # Оставить его в очереди значило бы прислать те же события следующей сводкой - и человек
        # читал бы один и тот же хвост до конца суток.
        tail = [r[0] for r in pend[cut:]]
        if not items:
            store.digest_mark(uid, keys + tail, now=now)
            continue
        text = cards.digest_card(items, extra=len(tail),
                                 window_min=max(1, config.digest_sec() // 60))
        res = await _send(uid, text, label='sentinel:digest', kb=cards.digest_kb(items))
        if not res or (isinstance(res, tuple) and res and res[0] == 'err'):
            # НЕ ОТМЕЧАЕМ: сводка, потерянная из-за сети, обязана уехать следующим кругом.
            print('[sentinel] сводка не ушла uid=%s (%s)'
                  % (uid, str(res[1])[:90] if isinstance(res, tuple) else 'отказ без причины'))
            continue
        store.digest_mark(uid, keys + tail, now=now)
        alert_log.sent('sentinel_digest', uid, sub=uid,
                       obj='сводка %d событий' % (len(items) + len(tail)))
        people += 1
        rows += len(items) + len(tail)
    return people, rows


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
    # ИМЯ СЕРВЕРА В ЧАТ НЕ ОТДАЁМ. В строке состояния стояло полное `host:pid` боевой машины -
    # человеку оно не говорит ничего, а наружу это раскладка инфраструктуры. Нужен ответ на
    # «опрашивает ли КТО-ТО и не умер ли он», и для него достаточно «да/нет + срок аренды».
    owner = ('есть' if lang != 'en' else 'yes') if owner else None
    if lang == 'en':
        return ('sentinel: instruments in the last hour %d · events in 24h %d · poller %s '
                '(lease %s) · %s'
                % (seen, evs, owner or 'none',
                   ('%ds left' % (until - now)) if until > now else 'expired',
                   store.spend_line('en')))
    return ('дозор: инструментов за час %d · события за сутки %d · опрос %s (аренда %s) · %s'
            % (seen, evs, owner or 'никто не ведёт',
               ('ещё %dс' % (until - now)) if until > now else 'истекла',
               store.spend_line()))
