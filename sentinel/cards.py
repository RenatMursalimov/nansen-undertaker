# -*- coding: utf-8 -*-
"""sentinel/cards.py — событие -> текст алерта. ДЕТЕРМИНИРОВАННО, БЕЗ МОДЕЛИ И БЕЗ СЕТИ.

ЧТО ЗДЕСЬ ЗАПРЕЩЕНО ПО ПОСТРОЕНИЮ: вызовы LLM, вызовы сети, обращения к базе. Карточка — это
пересказ уже посчитанных чисел, и собираться она обязана мгновенно: человек торгует руками, и
секунды между «рынок дёрнулся» и «телефон звякнул» — единственное, за что этот модуль отвечает.

═══ ПЕРЕПИСАН ПОСЛЕ ЖИВОГО ЧАСА 25.09. ВЕРДИКТ ВЛАДЕЛЬЦА ДОСЛОВНО ═══
«Весь текст от алертов без формата», «зачем-то все ссылки без линков внутри», «должно быть
красиво, чётко, содержательно, по делу», «походит на спам». Разбор, что именно было не так, —
он важнее самой правки:

1. ПЛОСКИЙ ТЕКСТ БЕЗ РАЗМЕТКИ. Прежняя редакция отправляла без `parse_mode` НАРОЧНО: в тикерах
   и метках живут `_` и `*`, и Markdown на них ломается. Вывод был верный, решение — нет:
   лечится не отказом от разметки, а HTML (там опасны только `&<>`, и их экранируют). Итог:
   заголовок и величины жирные, ссылки — ссылками, адреса в `<code>` (тапом копируются).
2. ДВАДЦАТЬ ДВЕ СТРОКИ НА ОДНО СОБЫТИЕ. Блок «что алерт НЕ проверял» из четырёх пунктов
   печатался в КАЖДОМ алерте и повторял одно и то же — читать его перестают на третьем.
   Осталась одна строка курсивом; развёрнутая версия живёт в справке экрана.
3. «Источник: Variational Omni, публичная ручка /metadata/stats» — служебная правда, которая
   человеку в момент решения не нужна. Источник теперь в ссылке.
4. ГЛАВНОЕ ЧИСЛО ТОНУЛО. Теперь первая строка — тикер и величина, и больше ничего.

ССЫЛКИ ВЕДУТ В НАШИ ЖЕ ЭКРАНЫ, А НЕ НА ЧУЖИЕ САЙТЫ. `dexscreener.com/<chain>/<addr>` и
`app.nansen.ai/token-god-mode?...` на пробе 25.09 ответили 403 (Cloudflare), то есть формат
пути НЕ ИЗМЕРЕН — ставить такую ссылку значит вести человека в неизвестность в момент, когда он
спешит. Зато у бота УЖЕ ЕСТЬ рабочие экраны токена и кошелька, и переход к ним — deep-link
`?start=tok_<contract>` через общую дверь `nansen_api.tok_link` (пятая копия этого тега
запрещена законом №40). Без имени бота ссылки нет вовсе: на тест-боте прод-имя увело бы
человека в прод.
"""

from . import config

#: ССЫЛКА ТОЛЬКО НА КОРЕНЬ, И ЭТО ЗАМЕР, А НЕ ЛЕНЬ. Пути `/trade/BTC` и `/markets/BTC`
#: отвечают 403, а `?market=BTC` даёт 200 ровно так же, как корень без параметра, — то есть 200
#: не доказывает, что параметр работает: у одностраничного приложения любой query вернёт 200.
VAR_URL = 'https://omni.variational.io/'

_KIND_TITLE = {
    'move_up': '📈',
    'move_down': '📉',
    'oi_surge': '🧱',
    'vol_surge': '💧',
    'funding_extreme': '💸',
    'spread_shock': '⚠️',
    'ignition': '🔥',
    'sm_perp': '🐋',
    'venue_gap': '⚖️',
    'crowded': '🧨',
    'absorption': '🧲',
}

_KIND_WORD = {
    'move_up': 'вверх',
    'move_down': 'вниз',
    'oi_surge': 'открытый интерес',
    'vol_surge': 'всплеск оборота',
    'venue_gap': 'цена расходится между площадками',
    'crowded': 'тесная толпа',
    'absorption': 'поглощение',
    'funding_extreme': 'ставка в хвосте',
    'spread_shock': 'котировка разъехалась',
    'ignition': 'смарт-зажигание',
    'sm_perp': 'умные деньги на перпах',
}


#: ═══ ЗАКОН ЭТАПА 3: СТРОКА, КОТОРАЯ НЕ МЕНЯЕТ РЕШЕНИЕ ТРЕЙДЕРА, НЕ ПЕЧАТАЕТСЯ ═══
#: Каждая подстрока - из живой карточки или сводки владельца 26.09 после деплоя #940.
#: Реестр ЖИВОЙ и в одной копии (закон 40): его читают `tests/test_sentinel.py` и e2e-закон
#: `tests/e2e/50_backend.py`. Новая служебная строка в карточке - сюда, и тест покраснеет.
SERVICE_FORBIDDEN = (
    'Чего не собрали', 'предсказательный рынок', 'кр Nansen', 'сожжено', 'суточный кап',
    'Причину движения дозорный не читает', 'он не изменился', 'контекст был',
    'Уверенность <b>', 'Вывод модели', '0.1095', 'funding_rate', 'Цену входа площадка не отдаёт',
    'не показываю', 'Тап по тикеру ниже', 'Долю от капитализации проверить не вышло',
    'Это не рекомендация', 'контракт сопоставлен по цене', 'у неё нет контракта в сети',
    '—',
)


def esc(s):
    """HTML-экранирование. ОДНА дверь: пропущенный `&` в имени инструмента рвёт всё сообщение,
    и Telegram отвечает отказом на разметку — то есть алерт не доходит вовсе."""
    return (str(s if s is not None else '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _usd(x, digits=0):
    """Деньги словом человека. None -> «нет данных», а НЕ «$0»: ноль это утверждение."""
    if x is None:
        return 'нет данных'
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 'нет данных'
    a = abs(v)
    if a >= 1e9:
        return '$%.2fB' % (v / 1e9)
    if a >= 1e6:
        return '$%.2fM' % (v / 1e6)
    if a >= 1e3:
        return '$%.1fk' % (v / 1e3)
    return ('$%.' + str(digits) + 'f') % v


def _price(x):
    if x is None:
        return 'нет данных'
    v = float(x)
    if v >= 1000:
        return '%.2f' % v
    if v >= 1:
        return '%.4f' % v
    return '%.8f' % v


def _pct(x, sign=True):
    if x is None:
        return 'нет данных'
    return ('%+.2f%%' if sign else '%.2f%%') % float(x)


def _num(x):
    """Контракты/штуки коротко. `1.045e+06` человек не читает — читает «1.05M»."""
    if x is None:
        return 'нет данных'
    v = float(x)
    for lim, suf in ((1e9, 'B'), (1e6, 'M'), (1e3, 'k')):
        if abs(v) >= lim:
            return '%.2f%s' % (v / lim, suf)
    return '%.0f' % v


def _age(sec):
    if sec is None:
        return 'возраст не назван'
    s = int(sec)
    return ('%dс' % s) if s < 90 else ('%dмин' % (s // 60))


def confidence_line(ev):
    """Уверенность числом + ПРИЧИНЫ, по которым она не сто.

    Штрафы печатаются целиком, а не «низкая уверенность»: человек решает сам, мешает ли ему
    именно эта причина. «67» без причин — оценка, которую нельзя оспорить.
    """
    pen = (ev.get('payload') or {}).get('penalties') or []
    head = 'Уверенность: %d/100' % int(ev.get('severity') or 0)
    if not pen:
        return head + ' (штрафов нет)'
    return head + '\n  • ' + '\n  • '.join(str(p) for p in pen)


def venue_title(venue):
    """Человеческое имя площадки. Своего справочника здесь НЕТ: он в `venues`, и второй
    список названий разъехался бы с первым на первом же переименовании."""
    try:
        from .venues import title
        return title(venue or 'variational')
    except Exception:
        return (venue or '').capitalize()


# ══════════════════════════════════════════════════════════════════════════════════════════
# ТИКЕР - ССЫЛКОЙ ВЕЗДЕ (этап 3, требование владельца)
#
# «Тикер иногда выходит не маркированным, сразу же со ссылкой на карточку - чтобы лишние кнопки
# не выводить». Ряд кнопок-тикеров под сводкой занимал пол-экрана и дублировал строки над ним.
# Теперь сам тикер в тексте - deep-link `?start=sen_<площадка>_<ТИКЕР>`, и тап открывает ТУ ЖЕ
# карточку инструмента, что кнопка `sen:card` (одна дверь - `ui.card_link`, закон 40).
# ПАРАМЕТР /start У ТЕЛЕГРАМА - ТОЛЬКО [A-Za-z0-9_-] ДО 64 СИМВОЛОВ. Двоеточие (тикеры вида
# `xyz:TSLA` у Hyperliquid) кодируется дефисом; тикер с другими знаками ссылкой не становится
# и печатается жирным, как раньше: ссылка, которая откроется ошибкой, хуже её отсутствия.
# БЕЗ ИМЕНИ БОТА ССЫЛКИ НЕТ: на тест-боте прод-имя увело бы человека в прод.
# ══════════════════════════════════════════════════════════════════════════════════════════
import re as _re

_START_OK = _re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def sen_start(venue, ticker):
    """Параметр deep-link карточки инструмента. -> 'sen_<venue>_<TICKER>' | None."""
    v = str(venue or 'variational').lower()
    t = str(ticker or '').upper().replace(':', '-')
    arg = 'sen_%s_%s' % (v, t)
    return arg if (t and _START_OK.match(arg)) else None


def parse_sen_start(arg):
    """'sen_<venue>_<TICKER>' -> (venue, TICKER) | None. Обратная сторона `sen_start`."""
    a = str(arg or '').strip()
    if not a.startswith('sen_'):
        return None
    rest = a[4:]
    v, _, t = rest.partition('_')
    if not v or not t:
        return None
    return v.lower(), t.upper().replace('-', ':')


def ev_class(ev):
    """Класс актива события для маркера. -> str.

    Зажигание - DEX-токен: 'meme' при капитализации меньше $100M, иначе 'token'. Остальное - из
    события (класс ставит детектор), 'token' - если контракт сопоставлен, иначе справочник
    Variational по тикеру (события до этапа 3) или 'unknown' (маркера нет).
    """
    p = ev.get('payload') or {}
    if (ev.get('kind') or '') == 'ignition':
        # DEX-ТОКЕН ИЗ ЛЕНТЫ СМАРТ-ДЕНЕГ: мем, если капитализация меньше $100M (признак ТЗ 3.2).
        from .assets import MEME_MCAP_USD
        try:
            _mc = float(p.get('mcap')) if p.get('mcap') not in (None, '') else None
        except (TypeError, ValueError):
            _mc = None
        return 'meme' if (_mc is not None and _mc < MEME_MCAP_USD) else 'token'
    k = p.get('asset_class')
    if k and k != 'unknown':
        return k
    if p.get('address'):
        return 'token'                      # контракт сопоставлен (кэш или сводка) - токен
    if k:
        return k
    # СПРАВОЧНИК ТОЛЬКО ИЗ ПАМЯТИ: карточке запрещены обращения к базе (шапка модуля).
    try:
        from .assets import book_peek
        return book_peek(ev.get('ticker') or p.get('symbol')) or 'unknown'
    except Exception:                                      # noqa: BLE001
        return 'unknown'


def tick_link(ticker, venue=None, bot_un=None, klass=None):
    """Тикер жирным и ССЫЛКОЙ на карточку инструмента, с маркером класса. -> HTML."""
    t = esc(str(ticker or '?').upper())
    mark = ''
    if klass:
        try:
            from .assets import class_mark
            mark = class_mark(klass)
        except Exception:                                  # noqa: BLE001
            mark = ''
    arg = sen_start(venue, ticker) if bot_un else None
    if not arg:
        return '%s<b>%s</b>' % (mark, t)
    return '%s<a href="https://t.me/%s?start=%s"><b>%s</b></a>' % (mark, esc(bot_un), arg, t)


def ev_tick(ev, bot_un=None, mark=True):
    """Тикер события ссылкой с маркером. -> HTML. ОДНА дверь для карточки, сводки, нити."""
    p = ev.get('payload') or {}
    tk = ev.get('ticker') or p.get('symbol') or '?'
    # У ЗАЖИГАНИЯ ПЛОЩАДКИ НЕТ (это DEX-токен): ссылка ведёт в карточку по тикеру без площадки,
    # а та честно назовёт, есть ли такой инструмент на перп-площадках.
    return tick_link(tk, p.get('venue') or 'variational', bot_un,
                     ev_class(ev) if mark else None)


def _links(ev, bot_un=None):
    """Ряд ссылок под карточкой. -> str | ''.

    Ведём в СВОИ экраны там, где есть контракт, и на площадку всегда. Чужие пути, чей формат мы
    не измерили, здесь не появляются вовсе.
    """
    p = ev.get('payload') or {}
    # ССЫЛКА ВЕДЁТ НА ТУ ПЛОЩАДКУ, ГДЕ СОБЫТИЕ. Одна ссылка «Площадка» на все источники
    # отправляла бы человека на Variational по алерту с Hyperliquid - то есть в никуда.
    _v = p.get('venue') or 'variational'
    _tick = ev.get('ticker') or p.get('symbol')
    _u = VAR_URL
    _label = venue_title(_v)
    try:
        from .venues import market_url as _murl, url as _vurl
        # ССЫЛКА ВЕДЁТ НА САМ ИНСТРУМЕНТ, А НЕ НА КОРЕНЬ. Формат измерен браузером 25.09
        # (`/perpetual/<TICKER>`), и это ровно то, чего человеку не хватало: по алерту он
        # попадает на график нужного рынка, а не на главную, где надо искать руками.
        _u = _murl(_v, _tick) or _vurl(_v) or VAR_URL
        _label = ('%s · %s' % (venue_title(_v), _tick)) if _murl(_v, _tick) else venue_title(_v)
    except Exception:
        pass
    out = ['<a href="%s">%s</a>' % (_u, esc(_label))]
    addr = p.get('address')
    if addr and bot_un:
        try:
            import nansen_api as _n
            # ОДНА ССЫЛКА НА ТОКЕН, А НЕ ДВЕ. Первая редакция ставила рядом «Карточка токена» и
            # «🔍 Nansen», и обе вели на ОДИН И ТОТ ЖЕ deep-link `?start=tok_<addr>`: две подписи
            # у одного перехода читаются как два разных экрана, и человек тапает дважды, чтобы
            # убедиться. Отдельного адреса у Nansen-экрана по токену нет (там команда словами),
            # и выдумывать его нельзя.
            out.append(_n.tok_link('🪪 Паспорт', addr, bot_un))
        except Exception as e:
            print('[sentinel] ссылка на токен не собралась: %s' % str(e)[:90])
    return '🔗 ' + ' · '.join(out)


def depth_or_spread(p):
    """Строка цены входа. -> str.

    ОДНА СТРОКА НА ОБЕ ПЛОЩАДКИ, И ОНА НЕ ЖАЛУЕТСЯ. У Variational есть котировки на объём
    ($100k, $1M) - показываем их. У Hyperliquid их нет, зато есть спред из цен исполнения
    на заметный размер - показываем его. Прежняя редакция печатала «Вход на $100k: котировки
    нет · котировке возраст не назван», то есть две жалобы вместо одного числа, которое у
    нас было.
    """
    d100 = p.get('depth_100k_bps')
    if d100 is not None:
        return 'Вход на $100k: %.0f б.п. · котировке %s' % (d100, _age(p.get('quote_age_s')))
    sp = p.get('spread_bps')
    if sp is not None:
        return 'Спред на размер: %.1f б.п.' % sp
    return None


def funding_line(p):
    """Строка фандинга. -> str.

    ═══ ГОДОВЫЕ ПРОЦЕНТЫ ТАМ, ГДЕ ЕДИНИЦА ИЗМЕРЕНА, И ИМЯ ПОЛЯ ТАМ, ГДЕ НЕТ ═══
    Девять кругов здесь стояло «Фандинг (поле funding_rate): 0.1095 / 8ч» - потому что единица
    не была названа ни докой, ни замером, и превратить это число в проценты значило бы выдумать
    человеку цифру, по которой он считает деньги. Долг №1 закрыт замером 26.09 (разбор во врезке
    `venues.FUNDING_UNIT`), и теперь строка отвечает на вопрос, который человек правда задаёт:
    «сколько мне это стоит в год».
    СЫРОЕ ПОЛЕ ОСТАЁТСЯ РЯДОМ, мелким: оно единственное, что можно сверить с экраном площадки,
    и выкинув его, мы лишили бы человека способа нас проверить.
    ЗНАК ВАЖЕН И ОБЪЯСНЁН СЛОВОМ: «+» значит платят лонги, «−» значит платят шорты. Без этого
    «фандинг 10.95%» не говорит, в какую сторону течёт его собственный кошелёк.
    """
    fr = p.get('funding_raw')
    iv = int(p.get('funding_interval_s') or 0)
    apr = None
    try:
        from .venues import funding_apr_pct as _apr
        apr = _apr(p.get('venue') or 'variational', fr, iv)
    except Exception:
        apr = None
    if apr is None:
        # ЕДИНИЦА НЕ ИЗМЕРЕНА - ЧИСЛО БЕЗ ЕДИНИЦЫ РЕШЕНИЯ НЕ МЕНЯЕТ (этап 3): строки нет.
        return None
    try:
        from .venues import funding_state as _fst
        st = _fst(p.get('venue') or 'variational', apr)
    except Exception:                                      # noqa: BLE001
        st = None
    # ═══ БАЗОВАЯ СТАВКА - ОДНИМ СЛОВОМ (этап 3) ═══
    # 10.95% годовых на Variational и Hyperliquid - это то, что площадка берёт без всякого
    # перекоса. «Фандинг +10.95% годовых (платят лонги) · 0.1095 / 8ч» читался как сигнал, хотя
    # это устройство площадки. Сырое поле убрано отовсюду: сверять его с экраном площадки - наша
    # работа, а не трейдера.
    if st == 'base':
        return 'Фандинг базовый'
    if st == 'zero':
        return None
    who = 'платят лонги' if (fr or 0) > 0 else 'платят шорты'
    if st == 'above':
        return 'Фандинг <b>повышен</b>: %+.2f%% годовых, %s' % (apr, who)
    if st == 'below':
        return 'Фандинг ниже базового: %+.2f%% годовых, %s' % (apr, who)
    return 'Фандинг <b>%+.2f%% годовых</b>, %s' % (apr, who)


def card(ev, lang='ru', bot_un=None):
    """Событие -> HTML-текст алерта (str).

    КОМПАКТНО И ПО ДЕЛУ: заголовок с величиной, 3-5 строк замеров, уверенность, ссылки. Всё,
    что человек читает один раз и больше не читает, вынесено в справку экрана.
    """
    p = ev.get('payload') or {}
    kind = ev.get('kind') or '?'
    icon = _KIND_TITLE.get(kind, '👁')
    _plain = esc(ev.get('ticker') or p.get('symbol') or '?')
    # ТИКЕР ССЫЛКОЙ НА КАРТОЧКУ ИНСТРУМЕНТА И С МАРКЕРОМ КЛАССА (этап 3).
    tick = ev_tick(ev, bot_un)
    name = esc(p.get('name') or '')
    lines = []

    # ── ПЕРВАЯ СТРОКА: ТИКЕР, ВЕЛИЧИНА И УВЕРЕННОСТЬ ОДНИМ ЧИСЛОМ (этап 3). ─────────────────
    if kind in ('move_up', 'move_down'):
        lines.append('%s %s  <b>%s</b> / %s'
                     % (icon, tick, _pct(p.get('move_pct')), p.get('window') or '15м'))
    elif kind == 'oi_surge':
        lines.append('%s %s  интерес <b>%s</b> за час (%s)'
                     % (icon, tick, _pct(p.get('oi_change_pct')),
                        _usd(p.get('oi_change_usd'))))
    elif kind == 'vol_surge':
        lines.append('%s %s  оборот <b>%s</b> за час (+%s)'
                     % (icon, tick, _pct(p.get('vol_change_pct')),
                        _usd(p.get('vol_change_usd'))))
    elif kind == 'crowded':
        lines.append('%s %s  <b>%.0f%%</b> интереса в %s и платят по верхней ставке'
                     % (icon, tick, p.get('crowd_pct') or 0, p.get('crowd_side') or '?'))
    elif kind == 'absorption':
        lines.append('%s %s  интерес <b>%s</b> за час, а цена стоит'
                     % (icon, tick, _pct(p.get('oi_change_pct'))))
    elif kind == 'venue_gap':
        lines.append('%s %s  расхождение <b>%.0f б.п.</b> между площадками'
                     % (icon, tick, p.get('gap_bps') or 0))
    elif kind == 'ignition':
        # ═══ ВЕДЁМ ЧИСЛОМ УЧАСТНИКОВ, А НЕ ЧИСЛОМ АДРЕСОВ ═══
        # Пункт 3.6 роудмапа: пять кошельков, заведённых с одного, - это ОДИН участник, и «5
        # умных адресов купили» завышает силу сигнала ровно во столько раз, сколько кошельков он
        # себе нарезал. Где связи проверены и найдены - заголовок называет независимых, а число
        # адресов уходит в скобки: это тот же закон «признак наличия не равен признаку пользы»,
        # только про подсчёт людей.
        _ind, _n = p.get('independent'), int(p.get('wallets') or 0)
        if _ind and int(_ind) < _n:
            lines.append('%s %s  <b>%d</b> независимых участника (адресов %d) купили '
                         'на <b>%s</b>' % (icon, tick, int(_ind), _n, _usd(p.get('usd'))))
        else:
            lines.append('%s %s  %d умных адреса купили на <b>%s</b>'
                         % (icon, tick, _n, _usd(p.get('usd'))))
    elif kind == 'funding_extreme':
        lines.append('%s %s  ставка в своём хвосте' % (icon, tick))
    elif kind == 'spread_shock':
        lines.append('%s %s  спред <b>%.0f б.п.</b> (×%.1f к медиане)'
                     % (icon, tick, p.get('spread_bps') or 0, p.get('spread_mult') or 0))
    else:
        lines.append('%s %s' % (icon, tick))
    # УВЕРЕННОСТЬ - ЧИСЛОМ В КОНЦЕ ЗАГОЛОВКА, А НЕ ОТДЕЛЬНЫМ АБЗАЦЕМ (этап 3). Строка
    # «Уверенность 80/100: вход на обеих сторонах...» стояла внизу каждой карточки и повторяла то,
    # что человек уже прочёл выше.
    sev = int(ev.get('severity') or 0)
    lines[0] = '%s <i>· %d/100</i>' % (lines[0], sev)
    # ПОДЗАГОЛОВОК НЕ ПОВТОРЯЕТ ЗАГОЛОВОК. У движения вид события уже сказан иконкой и знаком
    # процента, и слово «вверх» рядом с «+4.50%» - это строка, которая ничего не добавляет.
    # Название вида пишем там, где заголовок его не называет.
    # ПЛОЩАДКА - ПЕРВОЙ В ПОДЗАГОЛОВКЕ. Человек заходит руками на КОНКРЕТНОЙ площадке, и
    # «BTC +2%» без ответа «где» заставляет его угадывать; цена и спред у двух площадок
    # разные, так что угадывание стоит денег.
    _sub = [x for x in (venue_title(p.get('venue')),
                        name if name != _plain else '',
                        '' if kind in ('move_up', 'move_down') else _KIND_WORD.get(kind, ''))
            if x]
    if _sub:
        lines.append('<i>%s</i>' % ' · '.join(_sub))
    lines.append('')

    # ── ЗАМЕРЫ: ТОЛЬКО ТО, ЧТО МЕНЯЕТ РЕШЕНИЕ ─────────────────────────────────────────────
    if kind == 'venue_gap':
        # ДЕШЕВЛЕ И ДОРОЖЕ - СЛОВАМИ И ЦЕНАМИ. «Расхождение 60 б.п.» без ответа «где дешевле»
        # заставляет человека открывать обе площадки и сравнивать глазами.
        lines.append('Дешевле: <b>%s</b> %s' % (esc(venue_title(p.get('cheap_venue'))),
                                               _price(p.get('cheap_mark'))))
        lines.append('Дороже: <b>%s</b> %s' % (esc(venue_title(p.get('rich_venue'))),
                                              _price(p.get('rich_mark'))))
        lines.append('Вход на двух сторонах: %.0f б.п. · меньший оборот 24ч %s'
                     % (p.get('cost_bps') or 0, _usd(p.get('volume_24h'))))
    elif kind == 'sm_perp':
        # ═══ СМАРТ-ПЕРП: СТОРОНА - ГЛАВНОЕ ЧИСЛО КАРТОЧКИ (ТЗ 1.7) ═══
        # «Двое умных зашли в лонг» и «двое зашли в шорт» - противоположные новости, и сторона
        # обязана стоять рядом с суммой, а не в конце строки мелким текстом.
        lines.append('Сторона: <b>%s</b> · %d %s на %s'
                     % (('лонг' if p.get('side') == 'long' else 'шорт'),
                        int(p.get('wallets') or 0),
                        ('адреса' if int(p.get('wallets') or 0) < 5 else 'адресов'),
                        _usd(p.get('usd'))))
        if p.get('price'):
            lines.append('Вход около <b>%s</b>' % _price(p.get('price')))
        if p.get('labels'):
            lines.append('Метки: %s' % esc(', '.join(list(p['labels'])[:4])))
    elif kind == 'ignition':
        # МЕТКА НОВОГО ТОКЕНА - РЯДОМ С ДОЛЕЙ КАПИТАЛИЗАЦИИ, потому что вместе они и составляют
        # ответ: «ноль дней истории» плюс «половина рынка» это одна новость, а порознь - две
        # разные и обе неполные.
        if p.get('is_new'):
            lines.append('🌱 <b>Новый токен</b> (метка Nansen): истории у него нет')
        if p.get('mcap_bps') is not None:
            lines.append('Это <b>%.2f%%</b> капитализации (%s)'
                         % (p['mcap_bps'] / 100.0, _usd(p.get('mcap'))))
        _t = []
        if p.get('age_days') is not None:
            _t.append('токену %.0f дн' % p['age_days'])
        if p.get('trades'):
            _t.append('сделок %d' % int(p['trades']))
        if p.get('window_min'):
            _t.append('окно %d мин' % int(p['window_min']))
        if _t:
            lines.append(' · '.join(_t))
        if p.get('labels'):
            lines.append('Метки: %s' % esc(', '.join(p['labels'][:4])))
        # СКОЛЬКО АДРЕСОВ МЫ ПРАВДА ПРОВЕРИЛИ - ЧИСЛОМ. «Связей не найдено» без этого числа
        # звучит как вывод про весь набор, хотя смотрели мы три адреса из двенадцати.
        if p.get('cluster_partial'):
            lines.append('Связи проверены у %s' % esc(p['cluster_partial']))
        if p.get('address'):
            lines.append('%s · <code>%s</code>' % (esc(p.get('chain') or '?'),
                                                   esc(p['address'])))
    else:
        _row = ['Цена <b>%s</b>' % _price(p.get('mark'))]
        if kind == 'vol_surge' and p.get('ret60_pct') is not None:
            # ПРИ ВСПЛЕСКЕ ОБОРОТА ГЛАВНЫЙ ВОПРОС - «А ЦЕНА-ТО ПОШЛА?». Оборот без движения это
            # спор на месте, оборот с движением - направление; не сказать этого значит оставить
            # человека с половиной картины.
            _row.append('цена за час %s' % _pct(p['ret60_pct']))
        if kind in ('move_up', 'move_down'):
            if p.get('ret60_pct') is not None:
                _row.append('60м %s' % _pct(p['ret60_pct']))
            if p.get('z') is not None and p.get('sigma_pct'):
                # ОЦЕНКА ПОМЕЧАЕТСЯ ПРЯМО У ЧИСЛА. Часовая сигма, пересчитанная из 15-минутной
                # (`detector`, sigma60 = sigma15 * 2), и измеренная часовая выглядят одинаково
                # «7.1σ», а доверия заслуживают разного. Пометка стоит рядом, а не в сноске:
                # человек читает число, и оговорка обязана быть там же.
                _est = ''
                if p.get('sigma_source') == '15m*sqrt4':
                    _est = (' <i>(оценка по 15-мин)</i>' if lang != 'en'
                            else ' <i>(estimated from 15-min)</i>')
                _row.append('необычность <b>%.1fσ</b>%s' % (abs(p['z']), _est))
        lines.append(' · '.join(_row))
        # ПОСЛЕ РЕСТАРТА ЧАС ПОСЧИТАН ПО ХОЛОДНОМУ КОЛЬЦУ (ТЗ 5.3): пометка у числа, а не в сноске -
        # «за час +3.1%» с окном 45-75 минут и с окном ровно в час выглядят одинаково.
        if p.get('p60_src') == 'cold15' and (kind in ('oi_surge', 'vol_surge')
                                             or p.get('window') == '60м'
                                             or p.get('ret60_pct') is not None):
            lines.append('<i>после рестарта, точность часового окна 15 мин</i>' if lang != 'en'
                         else '<i>after a restart, the hourly window is accurate to 15 min</i>')
        _mkt = ['оборот 24ч <b>%s</b>' % _usd(p.get('volume_24h'))]
        # ОИ - С ЕДИНИЦЕЙ (этап 3): «ОИ 4.27M» без знака доллара читался как контракты. Доллары
        # ставит слой площадки (`oi_usd`); у событий до этапа 3 его нет, и тогда сумма сторон -
        # только у Variational, где стороны приходят в долларах (замер 26.09).
        oi = p.get('oi_usd')
        if oi is None and (p.get('venue') or 'variational') == 'variational':
            oi = ((p.get('oi_long') or 0) + (p.get('oi_short') or 0)) or None
        if oi:
            skew = p.get('oi_skew')
            _mkt.append('ОИ %s%s' % (_usd(oi),
                                     ('' if skew is None else ', лонгов %.0f%%' % (skew * 100))))
        lines.append(' · '.join(_mkt))
        # ═══ ПОЧЕМУ ЭТО СОБЫТИЕ - ЧИСЛОМ ПОРОГА (ТЗ 2.4) ═══
        # Порог у интереса и оборота теперь БОЛЬШЕЕ из нескольких чисел, и у каждого инструмента
        # своё. Без строки порога «оборот +$1.2M за час» не отвечает на вопрос «это много для
        # НЕГО?», а обычный час инструмента (медиана) и есть ответ.
        _en = lang == 'en'
        if kind == 'oi_surge' and p.get('oi_threshold_usd'):
            lines.append(('Threshold %s (%s)' if _en else 'Порог прироста %s (%s)')
                         % (_usd(p['oi_threshold_usd']), esc(p.get('oi_threshold_src') or '')))
        if kind == 'vol_surge' and p.get('vol_threshold_usd'):
            lines.append(('Threshold %s (%s) · usual hour %s over %d h' if _en else
                          'Порог %s (%s) · обычный час %s по %d ч')
                         % (_usd(p['vol_threshold_usd']), esc(p.get('vol_threshold_src') or ''),
                            _usd(p.get('vol_median_usd')), int(p.get('vol_median_points') or 0)))
        # ЦЕНА ВХОДА - ЕДИНСТВЕННОЕ, ЧТО ЧЕЛОВЕК ДЕЛАЕТ ПОСЛЕ АЛЕРТА. Нет её у площадки - строки
        # нет (этап 3): «Цену входа площадка не отдаёт» решения не меняет.
        _dp = depth_or_spread(p)
        if _dp:
            lines.append(_dp)
        # ФАНДИНГ ТОЛЬКО ТАМ, ГДЕ ОН СОБЫТИЕ ИЛИ НЕ НУЛЕВОЙ; строка без измеренной единицы и
        # нулевая ставка не печатаются (`funding_line` отдаёт None).
        fr = p.get('funding_raw')
        if kind == 'funding_extreme' or (fr not in (None, 0)):
            _fl = funding_line(p)
            if _fl:
                lines.append(_fl)

    # ── ПРИЧИНЫ ШТРАФОВ - ТОЛЬКО КОГДА ИХ БОЛЬШЕ ОДНОЙ (этап 3, решение владельца) ─────────
    # Число уже стоит в заголовке. Одна причина («вход на обеих сторонах...») повторяла строку
    # замера над ней; несколько - это уже ответ на вопрос «почему не сто».
    pen = p.get('penalties') or []
    if len(pen) > 1:
        lines.append('')
        lines.append('<i>Уверенность ниже: %s</i>' % esc('; '.join(str(x) for x in pen)))
    if kind == 'spread_shock':
        lines.append('<i>Это предостережение о цене входа, а не сигнал.</i>')
    elif kind == 'crowded':
        # НАПРАВЛЕНИЕ НЕ НАЗЫВАЕМ. Сигнал описывает конструкцию («выносить будут против
        # толпы»), а не предсказывает ход; подмена одного другим - это финсовет, которого
        # дозорный не даёт.
        lines.append('<i>Это описание конструкции: каскад ликвидаций идёт против толпы. '
                     'Направление дозорный не предсказывает.</i>')
    elif kind == 'absorption' or (kind == 'oi_surge' and p.get('absorption')):
        # ПОГЛОЩЕНИЕ - СТРОКА КАРТОЧКИ СКАЧКА ИНТЕРЕСА (ТЗ 2.4), а у старых событий вида
        # `absorption` - та же строка. Цена за час названа числом: «стоит» без числа - оценка.
        if kind == 'oi_surge':
            lines.append(('🧲 <b>Absorption</b>: price over the hour %s' if lang == 'en' else
                          '🧲 <b>Поглощение</b>: цена за час %s') % _pct(p.get('ret60_pct')))
        lines.append('<i>Кто-то набирает против потока, и его пока хватает. '
                     'Подтверждения направления здесь нет.</i>' if lang != 'en' else
                     '<i>Someone is building against the flow and still holding. '
                     'There is no confirmation of direction here.</i>')
    # ДИСКЛЕЙМЕРА «ПРИЧИНУ ДВИЖЕНИЯ ДОЗОРНЫЙ НЕ ЧИТАЕТ» БОЛЬШЕ НЕТ (этап 3): он стоял в каждой
    # карточке и решения не менял. Что дозорный делает и чего нет - в справке экрана.
    _l = _links(ev, bot_un)
    if _l:
        lines.append('')
        lines.append(_l)
    return '\n'.join(lines)


def digest_line(ev, bot_un=None):
    """Одна строка сводки: тикер (ссылкой), величина, площадка. -> str.

    ОДНА СТРОКА НА СОБЫТИЕ, И В НЕЙ ОБЯЗАНА БЫТЬ ВЕЛИЧИНА. Сводка из тикеров («ENA, MSTR, XAU»)
    не даёт человеку решить ничего - ему придётся открыть все три. Величина в строке делает
    сводку читаемой за десять секунд, а это единственная причина, по которой она существует.
    """
    p = ev.get('payload') or {}
    kind = ev.get('kind') or '?'
    icon = _KIND_TITLE.get(kind, '👁')
    # ТИКЕР В КАЖДОЙ СТРОКЕ - ССЫЛКА НА КАРТОЧКУ (этап 3): ряд кнопок-тикеров под сводкой убран.
    tick = ev_tick(ev, bot_un)
    if kind in ('move_up', 'move_down'):
        val = '%s / %s' % (_pct(p.get('move_pct')), p.get('window') or '15м')
    elif kind == 'oi_surge':
        val = 'интерес %s (%s)%s' % (_pct(p.get('oi_change_pct')), _usd(p.get('oi_change_usd')),
                                     ', цена стоит' if p.get('absorption') else '')
    elif kind == 'vol_surge':
        val = 'оборот %s' % _pct(p.get('vol_change_pct'))
    elif kind == 'venue_gap':
        val = 'расхождение %.0f б.п.' % (p.get('gap_bps') or 0)
    elif kind == 'crowded':
        val = '%.0f%% в %s' % (p.get('crowd_pct') or 0, p.get('crowd_side') or '?')
    elif kind == 'absorption':
        val = 'интерес %s, цена стоит' % _pct(p.get('oi_change_pct'))
    elif kind == 'ignition':
        val = '%d адреса на %s' % (int(p.get('wallets') or 0), _usd(p.get('usd')))
    elif kind == 'spread_shock':
        val = 'спред %.0f б.п.' % (p.get('spread_bps') or 0)
    else:
        val = _KIND_WORD.get(kind, kind)
    # ПОМЕТКА «ПОЧЕМУ ТОЛЬКО В СВОДКЕ» - У СВОЕЙ СТРОКИ (ТЗ 2.5). Заголовок сводки называет одну
    # причину на всё сообщение, а у акции вне сессии и у зажигания без капитализации причины
    # разные и принадлежат событию: «биржа закрыта» рядом с DELL, а не над всем списком.
    _mark = (' <i>· %s</i>' % esc(p['digest_only'])) if p.get('digest_only') else ''
    # У ЗАЖИГАНИЯ ПЛОЩАДКИ НЕТ - ЭТО DEX-ТОКЕН: прежде здесь подставлялась Variational.
    _ven = '' if kind == 'ignition' else ' · %s' % esc(venue_title(p.get('venue')))
    return ('%s %s  %s <i>%s · %d/100</i>%s'
            % (icon, tick, val, _ven, int(ev.get('severity') or 0), _mark))


def digest_card(items, extra=0, window_min=10, lang='ru', bot_un=None):
    """СВОДКА ОТЛОЖЕННОГО — одним сообщением вместо потока. -> HTML-строка.

    ═══ ЗАЧЕМ СВОДКА СУЩЕСТВУЕТ ═══
    ЗАМЕР ВЛАДЕЛЬЦА 25.09: «за минут больше 70 сообщений», «даже нажать ничего нельзя». Ответом
    мог быть предохранитель, который просто МОЛЧИТ про лишнее, - и это была бы вторая ложь:
    человек не получил бы алерт и не узнал бы, что его не получил. Сводка закрывает ровно эту
    дыру: поток превращается в ОДНО сообщение, а не в тишину.

    ПОРЯДОК ПО СИЛЕ (его задаёт `store.digest_pending`), а не по времени: лента по времени
    читается как набор случайных строк, и глаз бросает её на третьей. Сверху - самое крупное.

    ОСТАТОК НАЗЫВАЕТСЯ ЧИСЛОМ. «И ещё 34 слабее» - это ответ на вопрос «а сколько я не увидел»;
    без него сводка повторила бы ошибку, от которой создана.
    """
    n = len(items) + int(extra or 0)
    out = ['🗂 <b>Сводка дозора</b> · %d событий за %d мин' % (n, int(window_min))]
    # ПОЧЕМУ СПИСКОМ, А НЕ ЗВОНКОМ - ОДНОЙ СТРОКОЙ И СРАЗУ. Человек, получивший сводку вместо
    # алертов, первым делом спросит «почему»; отвечать на это в справке значит не ответить.
    _why = None
    for it in items:
        if it.get('why'):
            _why = it['why']
            break
    if _why:
        out.append('<i>Не звонили: %s</i>' % esc(_why))
    out.append('')
    for it in items:
        out.append(digest_line(it['ev'], bot_un=bot_un))
    if extra:
        out.append('')
        out.append('<i>И ещё %d слабее.</i>' % int(extra))
    # ПОДСКАЗКИ «ТАП ПО ТИКЕРУ НИЖЕ» БОЛЬШЕ НЕТ: тикеры сами ссылки, кнопок под сводкой нет.
    return '\n'.join(out)


def digest_kb(items, limit=6):
    """Клавиатура под сводкой: ОДНА кнопка «Дозорный». -> InlineKeyboardMarkup | None.

    ═══ РЯД КНОПОК-ТИКЕРОВ УБРАН (этап 3, требование владельца) ═══
    Сквозной переход остался - он переехал в текст: каждый тикер в строке сводки теперь
    deep-link на карточку инструмента (`digest_line` -> `ev_tick`). Шесть кнопок под двенадцатью
    строками повторяли половину строк и занимали пол-экрана. `items` и `limit` оставлены в
    подписи ради прежних вызывающих.
    """
    try:
        from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup
    except Exception:
        return None
    return InlineKeyboardMarkup([[B('⚙️ Дозорный', callback_data='sen:home')]])


def enrich_card(ev, brief, lang='ru', owner=False, bot_un=None, standalone=True):
    """Сводка вокруг события. -> HTML-строка | '' (добавить нечего - блок не печатается).

    ДВА ВИДА. `standalone=False` - блок дописывается в первую карточку правкой (основной путь,
    ТЗ 2.6): тикер там уже стоит в заголовке, и повторять его незачем. `standalone=True` - ответ
    на карточку отдельным сообщением (правка не удалась): тогда тикер ссылкой.
    `owner` ОСТАВЛЕН В ПОДПИСИ, НО НИЧЕГО НЕ МЕНЯЕТ (этап 3): строки расхода кредитов в сводке
    больше нет ни у кого, она на экране дозорного.
    ОТКАЗОВ («Чего не собрали: ...») ЗДЕСЬ НЕТ ПО ПОСТРОЕНИЮ: они в логе (`enrichment.build`).
    """
    body = list(brief.get('lines') or [])
    verdict = list(brief.get('verdict') or [])
    # ПЕРЕСКАЗ МОДЕЛИ - ТОЛЬКО ПРИ ВКЛЮЧЁННОМ ФЛАГЕ, И ПРОВЕРЯЕТСЯ ЭТО ЗДЕСЬ ТОЖЕ (этап 3, п.3).
    # Сводку собирает один процесс, рисует - иногда другой; второй замок стоит у двери вывода,
    # чтобы «Вывод модели» не приехал из сводки, собранной при включённом флаге.
    summ = brief.get('summary') if config.llm_summary_on() else ''
    if not body and not verdict and not summ:
        return ''
    out = (['🧭 %s <b>что вокруг</b>' % ev_tick(ev, bot_un, mark=False)] if standalone
           else ['🧭 <b>Что вокруг</b>'])
    if body:
        out.append('')
        out += body
    # ИТОГ КОДОМ - ПОСЛЕДНИМ СМЫСЛОВЫМ БЛОКОМ (ТЗ 2.8): его читают вместо всех строк выше, и
    # каждое утверждение в нём посчитано из чисел этой же карточки (`enrichment.verdict_lines`).
    if verdict:
        out.append('')
        out.append('<b>Итог</b>')
        out += ['• %s' % v for v in verdict]
    if summ:
        out.append('')
        out.append('<b>Вывод модели</b> <i>(пересказ данных выше, не новые факты)</i>')
        out.append(esc(summ))
    return '\n'.join(out)
