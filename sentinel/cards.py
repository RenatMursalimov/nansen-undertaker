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
}


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
            out.append(_n.tok_link('Карточка токена', addr, bot_un))
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
    return 'Цену входа площадка не отдаёт'


def card(ev, lang='ru', bot_un=None):
    """Событие -> HTML-текст алерта (str).

    КОМПАКТНО И ПО ДЕЛУ: заголовок с величиной, 3-5 строк замеров, уверенность, ссылки. Всё,
    что человек читает один раз и больше не читает, вынесено в справку экрана.
    """
    p = ev.get('payload') or {}
    kind = ev.get('kind') or '?'
    icon = _KIND_TITLE.get(kind, '👁')
    tick = esc(ev.get('ticker') or p.get('symbol') or '?')
    name = esc(p.get('name') or '')
    lines = []

    # ── ПЕРВАЯ СТРОКА: ТИКЕР И ВЕЛИЧИНА. Больше в ней нет ничего. ──────────────────────────
    if kind in ('move_up', 'move_down'):
        lines.append('%s <b>%s</b>  <b>%s</b> / %s'
                     % (icon, tick, _pct(p.get('move_pct')), p.get('window') or '15м'))
    elif kind == 'oi_surge':
        lines.append('%s <b>%s</b>  интерес <b>%s</b> за час (%s)'
                     % (icon, tick, _pct(p.get('oi_change_pct')),
                        _usd(p.get('oi_change_usd'))))
    elif kind == 'vol_surge':
        lines.append('%s <b>%s</b>  оборот <b>%s</b> за час (+%s)'
                     % (icon, tick, _pct(p.get('vol_change_pct')),
                        _usd(p.get('vol_change_usd'))))
    elif kind == 'crowded':
        lines.append('%s <b>%s</b>  <b>%.0f%%</b> интереса в %s и платят по верхней ставке'
                     % (icon, tick, p.get('crowd_pct') or 0, p.get('crowd_side') or '?'))
    elif kind == 'absorption':
        lines.append('%s <b>%s</b>  интерес <b>%s</b> за час, а цена стоит'
                     % (icon, tick, _pct(p.get('oi_change_pct'))))
    elif kind == 'venue_gap':
        lines.append('%s <b>%s</b>  расхождение <b>%.0f б.п.</b> между площадками'
                     % (icon, tick, p.get('gap_bps') or 0))
    elif kind == 'ignition':
        lines.append('%s <b>%s</b>  %d умных адреса купили на <b>%s</b>'
                     % (icon, tick, int(p.get('wallets') or 0), _usd(p.get('usd'))))
    elif kind == 'funding_extreme':
        lines.append('%s <b>%s</b>  ставка в своём хвосте' % (icon, tick))
    elif kind == 'spread_shock':
        lines.append('%s <b>%s</b>  спред <b>%.0f б.п.</b> (×%.1f к медиане)'
                     % (icon, tick, p.get('spread_bps') or 0, p.get('spread_mult') or 0))
    else:
        lines.append('%s <b>%s</b>' % (icon, tick))
    # ПОДЗАГОЛОВОК НЕ ПОВТОРЯЕТ ЗАГОЛОВОК. У движения вид события уже сказан иконкой и знаком
    # процента, и слово «вверх» рядом с «+4.50%» - это строка, которая ничего не добавляет.
    # Название вида пишем там, где заголовок его не называет.
    # ПЛОЩАДКА - ПЕРВОЙ В ПОДЗАГОЛОВКЕ. Человек заходит руками на КОНКРЕТНОЙ площадке, и
    # «BTC +2%» без ответа «где» заставляет его угадывать; цена и спред у двух площадок
    # разные, так что угадывание стоит денег.
    _sub = [x for x in (venue_title(p.get('venue')),
                        name if name != tick else '',
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
    elif kind == 'ignition':
        if p.get('mcap_bps') is not None:
            lines.append('Это <b>%.2f%%</b> капитализации (%s)'
                         % (p['mcap_bps'] / 100.0, _usd(p.get('mcap'))))
        else:
            lines.append('Долю от капитализации проверить не вышло: провайдер её не дал')
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
                _row.append('необычность <b>%.1fσ</b>' % abs(p['z']))
        lines.append(' · '.join(_row))
        _mkt = ['оборот 24ч <b>%s</b>' % _usd(p.get('volume_24h'))]
        oi = (p.get('oi_long') or 0) + (p.get('oi_short') or 0)
        if oi:
            skew = p.get('oi_skew')
            _mkt.append('ОИ %s%s' % (_num(oi),
                                     ('' if skew is None else ', лонгов %.0f%%' % (skew * 100))))
        lines.append(' · '.join(_mkt))
        # ЦЕНА ВХОДА - ЕДИНСТВЕННОЕ, ЧТО ЧЕЛОВЕК ДЕЛАЕТ ПОСЛЕ АЛЕРТА, поэтому строка есть
        # всегда. Базовый спред отдельной строкой не идёт: заходят на сумму, а не на копейку.
        lines.append(depth_or_spread(p))
        # ФАНДИНГ ТОЛЬКО ТАМ, ГДЕ ОН СОБЫТИЕ ИЛИ НЕ НУЛЕВОЙ: строка «funding_rate: 0» в каждом
        # алерте - шум, а единица у поля всё равно не заявлена провайдером (долг №1 в спеке).
        fr = p.get('funding_raw')
        if kind == 'funding_extreme' or (fr not in (None, 0)):
            iv = int(p.get('funding_interval_s') or 0)
            lines.append('Фандинг (поле <code>funding_rate</code>): %.6g%s'
                         % (fr or 0, (' / %dч' % (iv // 3600)) if iv >= 3600 else ''))

    # ── УВЕРЕННОСТЬ: ЧИСЛО ВСЕГДА, ПРИЧИНЫ - ТОЛЬКО ЕСЛИ ОНИ ЕСТЬ ─────────────────────────
    lines.append('')
    sev = int(ev.get('severity') or 0)
    pen = p.get('penalties') or []
    if pen:
        lines.append('Уверенность <b>%d/100</b>: %s' % (sev, esc('; '.join(str(x) for x in pen))))
    else:
        lines.append('Уверенность <b>%d/100</b>' % sev)
    if kind == 'spread_shock':
        lines.append('<i>Это предостережение о цене входа, а не сигнал.</i>')
    elif kind == 'crowded':
        # НАПРАВЛЕНИЕ НЕ НАЗЫВАЕМ. Сигнал описывает конструкцию («выносить будут против
        # толпы»), а не предсказывает ход; подмена одного другим - это финсовет, которого
        # дозорный не даёт.
        lines.append('<i>Это описание конструкции: каскад ликвидаций идёт против толпы. '
                     'Направление дозорный не предсказывает.</i>')
    elif kind == 'absorption':
        lines.append('<i>Кто-то набирает против потока, и его пока хватает. '
                     'Подтверждения направления здесь нет.</i>')
    else:
        # ОДНА СТРОКА ВМЕСТО ЧЕТЫРЁХ ПУНКТОВ: длинный дисклеймер в каждом алерте перестают
        # читать на третьем, и тогда он не защищает никого.
        lines.append('<i>Причину движения дозорный не читает: сверьте новость и свой риск.</i>')
    _l = _links(ev, bot_un)
    if _l:
        lines.append('')
        lines.append(_l)
    return '\n'.join(lines)


def digest_line(ev):
    """Одна строка сводки: тикер, величина, площадка. -> str.

    ОДНА СТРОКА НА СОБЫТИЕ, И В НЕЙ ОБЯЗАНА БЫТЬ ВЕЛИЧИНА. Сводка из тикеров («ENA, MSTR, XAU»)
    не даёт человеку решить ничего - ему придётся открыть все три. Величина в строке делает
    сводку читаемой за десять секунд, а это единственная причина, по которой она существует.
    """
    p = ev.get('payload') or {}
    kind = ev.get('kind') or '?'
    icon = _KIND_TITLE.get(kind, '👁')
    tick = esc(ev.get('ticker') or p.get('symbol') or '?')
    if kind in ('move_up', 'move_down'):
        val = '%s / %s' % (_pct(p.get('move_pct')), p.get('window') or '15м')
    elif kind == 'oi_surge':
        val = 'интерес %s (%s)' % (_pct(p.get('oi_change_pct')), _usd(p.get('oi_change_usd')))
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
    return ('%s <b>%s</b>  %s <i>· %s · %d/100</i>'
            % (icon, tick, val, esc(venue_title(p.get('venue'))),
               int(ev.get('severity') or 0)))


def digest_card(items, extra=0, window_min=10, lang='ru'):
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
        out.append(digest_line(it['ev']))
    if extra:
        out.append('')
        out.append('<i>И ещё %d событий слабее — они не потеряны, лежат в базе.</i>' % int(extra))
    out.append('')
    out.append('<i>Тап по тикеру ниже — карточка инструмента. Настройки: «Дозорный».</i>')
    return '\n'.join(out)


def digest_kb(items, limit=6):
    """Кнопки-тикеры под сводкой. -> InlineKeyboardMarkup | None.

    СКВОЗНОЙ СЦЕНАРИЙ - ТРЕБОВАНИЕ ВЛАДЕЛЬЦА, ПОВТОРЁННОЕ ДВАЖДЫ: «у нас все сценарии сквозные,
    чтобы сразу на карточку попасть и если что в избранное закинуть». Сводка без перехода
    заставляла бы человека искать тикер руками - то есть сама создавала бы работу, ради экономии
    которой она и написана.
    ШЕСТЬ, А НЕ ВСЕ: клавиатура на двенадцать кнопок занимает пол-экрана и перестаёт быть
    навигацией. Шесть сильнейших - ровно те, по которым человек пойдёт.
    ПОВТОРЫ ТИКЕРА СКЛЕИВАЕМ: два события по одному инструменту дали бы две одинаковые кнопки.
    """
    try:
        from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup
    except Exception:
        return None
    seen, row, rows = set(), [], []
    for it in items:
        ev = it['ev']
        t = ev.get('ticker') or ''
        v = ((ev.get('payload') or {}).get('venue')) or 'variational'
        if not t or t in seen:
            continue
        seen.add(t)
        row.append(B('📊 %s' % t, callback_data='sen:card:%s:%s' % (v, t)))
        if len(row) == 3:
            rows.append(row)
            row = []
        if len(seen) >= int(limit):
            break
    if row:
        rows.append(row)
    if not rows:
        return None
    rows.append([B('⚙️ Дозорный', callback_data='sen:home')])
    return InlineKeyboardMarkup(rows)


def enrich_card(ev, brief, lang='ru'):
    """ВТОРОЕ сообщение: сводка вокруг события. -> HTML-строка.

    Отдельным сообщением, а не дописыванием в первое: правка уже отправленного незаметна
    (телефон не звякнет второй раз), а ждать сводку внутри первого значило бы задержать цену
    ради слов.
    """
    tick = esc(ev.get('ticker') or '?')
    out = ['🧭 <b>%s</b> — что вокруг' % tick]
    if brief.get('lines'):
        out.append('')
        out += list(brief['lines'])
    if brief.get('refused'):
        # ОТКАЗ НАЗЫВАЕТ КЛАСС, А НЕ «НЕ УДАЛОСЬ»: «нет кредитов», «площадка молчит» и «тикер
        # не сопоставлен контракту» требуют РАЗНЫХ действий от человека.
        out.append('')
        out.append('<i>Чего не собрали: %s</i>' % esc(brief['refused']))
    if brief.get('summary'):
        out.append('')
        out.append('<b>Вывод модели</b> <i>(пересказ данных выше, не новые факты)</i>')
        out.append(esc(brief['summary']))
    if brief.get('cost_line'):
        out.append('')
        out.append('<i>%s</i>' % esc(brief['cost_line']))
    return '\n'.join(out)
