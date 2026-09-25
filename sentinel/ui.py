# -*- coding: utf-8 -*-
"""sentinel/ui.py — слова человека -> действия дозорного. Одна дверь для лички.

РАЗБОР ОТДЕЛЁН ОТ ДЕЙСТВИЯ НАРОЧНО: `parse()` — чистая функция без базы, и весь набор фраз
проверяется тестом на строках, а не живым ботом. Перехваты ТОЧНЫЕ и по ГОЛОВЕ сообщения
(закон №11): «дозор» — слово частое, и подстрочный матч выхватывал бы его из тела письма.

ЧЕГО ЗДЕСЬ НЕТ: кнопок «купить». Дозорный не торгует и не ведёт к торговле: он показывает
замеры и ссылку на площадку, где человек всё делает сам. Ни один импорт этого файла не ведёт
в торговый контур, и это проверяется тестом графа импортов.

ОТКАЗ ВСЕГДА СО СЛОВОМ. «Ничего не произошло» человек читает как поломку — поэтому каждая
ветка возвращает строку, включая «уже в дозоре» и «такого инструмента на площадке нет».
"""

import re

from . import config, engine, outbox, store

#: Инструмент на площадке пишется латиницей и цифрами (ЗАМЕР по живому списку: `US100S`,
#: `XAU`, `HYPE`). Точку и дефис разрешаем — в списке есть `USDC.E`-подобные формы.
_TICK = r'[A-Za-z0-9._-]{1,16}'
_HEAD = 160


def _head(text):
    return (text or '').strip().split('\n')[0][:_HEAD].strip()


def parse(text):
    """Строка -> (действие, аргументы) | None. ЧИСТАЯ ФУНКЦИЯ: ни базы, ни сети."""
    h = _head(text)
    tl = h.lower().rstrip(' .!?…')
    if not re.match(r'^дозор\b', tl):
        return None
    rest = tl[len('дозор'):].strip()
    if not rest:
        return ('status', {})
    if re.match(r'^(вс[её]|вся площадка|all)$', rest):
        return ('add', {'ticker': store.ALL})
    m = re.match(r'^(?:убрать|удалить|стоп)\s+(вс[её]|all|%s)$' % _TICK, rest)
    if m:
        g = m.group(1)
        return ('del', {'ticker': store.ALL if g in ('всё', 'все', 'all') else g.upper()})
    m = re.match(r'^алерты\s+(вкл|выкл|on|off)$', rest)
    if m:
        return ('alerts', {'on': m.group(1) in ('вкл', 'on')})
    m = re.match(r'^сводки\s+(вкл|выкл|on|off)$', rest)
    if m:
        return ('enrich', {'on': m.group(1) in ('вкл', 'on')})
    m = re.match(r'^порог\s+([0-9]+(?:[.,][0-9]+)?)$', rest)
    if m:
        return ('minpct', {'pct': float(m.group(1).replace(',', '.'))})
    m = re.match(r'^тихо\s+(\d{1,2})\s+(\d{1,2})$', rest)
    if m:
        return ('quiet', {'from': int(m.group(1)) % 24, 'to': int(m.group(2)) % 24})
    if re.match(r'^тихо\s+(выкл|off)$', rest):
        return ('quiet', {'from': None, 'to': None})
    if re.match(r'^(отч[её]т|попадания)$', rest):
        return ('report', {})
    if re.match(r'^(стата|состояние|статус)$', rest):
        return ('health', {})
    m = re.match(r'^(%s)$' % _TICK, rest)
    if m:
        return ('add', {'ticker': m.group(1).upper()})
    return ('help', {})


HELP = (
    '👁 Дозорный — живые алерты по Variational Omni и смарт-деньгам.\n'
    '\n'
    'дозор BTC — взять инструмент под дозор\n'
    'дозор всё — вся площадка (553 инструмента)\n'
    'дозор убрать BTC — снять\n'
    'дозор — что под дозором и в каком состоянии\n'
    'дозор порог 5 — молчать про движения слабее 5%\n'
    'дозор тихо 22 8 — тихие часы (UTC), «дозор тихо выкл» — снять\n'
    'дозор алерты выкл — пауза без потери списка\n'
    'дозор сводки выкл — только цифры, без Нансена и твиттера\n'
    'дозор отчёт — попадания за неделю (или честное «выборка мала»)\n'
    '\n'
    'Что приходит: движение цены (с оценкой «необычно ли это ДЛЯ НЕГО»), скачок открытого '
    'интереса, ставка в хвосте, разъехавшаяся котировка, смарт-зажигание (несколько разных '
    'умных адресов купили один токен).\n'
    'Дозорный НЕ торгует и НЕ советует. Вход руками на omni.variational.io.'
)


def status_text(uid):
    """Что под дозором и в каком состоянии. ВЕДЁМ ВЕЛИЧИНАМИ, а не флагами."""
    subs = store.sub_list(uid)
    s = store.settings(uid)
    lines = ['👁 Дозорный']
    if not subs:
        lines.append('Под дозором: ничего. «дозор BTC» или «дозор всё».')
    elif store.ALL in subs:
        others = [t for t in subs if t != store.ALL]
        lines.append('Под дозором: вся площадка%s'
                     % (' (+ отдельно %s)' % ', '.join(others) if others else ''))
    else:
        lines.append('Под дозором (%d): %s' % (len(subs), ', '.join(subs)))
    lines.append('Алерты: %s · сводки: %s'
                 % ('вкл' if s.get('alerts_on') else 'ВЫКЛ',
                    'вкл' if s.get('enrich_on') else 'выкл'))
    if s.get('min_pct'):
        lines.append('Личный порог движения: %.2f%%' % float(s['min_pct']))
    if s.get('quiet_from') is not None:
        lines.append('Тихие часы (UTC): %02d:00–%02d:00' % (int(s['quiet_from']),
                                                           int(s['quiet_to'])))
    cap = store.cap_for(uid)
    lines.append('Сегодня доставлено: %d из %d' % (store.sent_today(uid), cap))
    lines.append('')
    lines.append(outbox.status_line())
    lines.append('')
    lines.append('Пороги сейчас: 15м %.1f%% · 60м %.1f%% · %.1f сигмы · интерес %.0f%% · '
                 'зажигание %d адреса/$%.0fk'
                 % (config.move_pct_15m(), config.move_pct_60m(), config.z_min(),
                    config.oi_pct(), config.ign_wallets(), config.ign_usd() / 1000))
    return '\n'.join(lines)


def route(uid, text):
    """-> строка ответа | None (значит это не наша фраза, пусть идёт дальше).

    НИКОГДА НЕ БРОСАЕТ: падение разбора команды не имеет права съесть сообщение человека.
    """
    try:
        got = parse(text)
    except Exception as e:
        print('[sentinel] разбор команды упал: %s' % str(e)[:120])
        return None
    if not got:
        return None
    act, a = got
    try:
        if act == 'status':
            return status_text(uid)
        if act == 'help':
            return HELP
        if act == 'add':
            t = a['ticker']
            if t != store.ALL and not _exists(t):
                # ЧЕСТНЫЙ ОТКАЗ ВМЕСТО МОЛЧАЛИВОЙ ПОДПИСКИ НА НЕСУЩЕСТВУЮЩЕЕ. Иначе человек
                # ждал бы алертов по опечатке неделю и решил бы, что дозорный сломан.
                return ('На площадке нет инструмента %s (или кольцо ещё пустое). '
                        'Проверьте тикер на omni.variational.io.' % t)
            ok, why = store.sub_add(uid, t)
            # ЗВЁЗДОЧКУ ЧЕЛОВЕКУ НЕ ПОКАЗЫВАЕМ: «✅ * под дозором» — это наш внутренний ключ,
            # вытекший на экран. Человек просил «всё», и ответ обязан говорить его словами.
            nm = 'вся площадка (553 инструмента)' if t == store.ALL else t
            return ('✅ %s под дозором' % nm) if ok else ('• %s: %s' % (nm, why))
        if act == 'del':
            return ('✅ %s снят с дозора' % a['ticker']) if store.sub_del(uid, a['ticker']) \
                else ('• %s под дозором и не был' % a['ticker'])
        if act == 'alerts':
            store.settings_set(uid, alerts_on=1 if a['on'] else 0)
            return ('✅ Алерты включены' if a['on']
                    else '🔇 Алерты выключены. Список инструментов сохранён.')
        if act == 'enrich':
            store.settings_set(uid, enrich_on=1 if a['on'] else 0)
            return ('✅ Сводки включены (Нансен + твиттер вторым сообщением)' if a['on']
                    else '✅ Сводки выключены. Цифры площадки приходить будут.')
        if act == 'minpct':
            store.settings_set(uid, min_pct=a['pct'])
            return '✅ Личный порог: молчу про движения слабее %.2f%%' % a['pct']
        if act == 'quiet':
            store.settings_set(uid, quiet_from=a['from'], quiet_to=a['to'])
            if a['from'] is None:
                return '✅ Тихие часы сняты'
            return '✅ Тихо с %02d:00 до %02d:00 UTC' % (a['from'], a['to'])
        if act == 'report':
            out = ['📊 Попадания дозорного за 7 дней (по нашим же снимкам):']
            for kind in ('move_up', 'move_down', 'ignition', 'oi_surge'):
                out.append('• ' + engine.hit_rate(kind=kind, horizon_min=60))
            out.append('')
            out.append('Горизонт 60 минут: «продолжение движения» значит, что через час цена '
                       'была дальше в ту же сторону. Это НЕ доходность и не обещание.')
            return '\n'.join(out)
        if act == 'health':
            return outbox.status_line()
    except Exception as e:
        print('[sentinel] команда %s упала uid=%s: %s: %s' % (act, uid, type(e).__name__,
                                                              str(e)[:150]))
        return 'Дозорный споткнулся: %s. Детали в bot.log.' % type(e).__name__
    return None


def _exists(ticker):
    """Есть ли такой инструмент в нашем кольце. -> bool.

    СПРАШИВАЕМ КОЛЬЦО, А НЕ ПЛОЩАДКУ: живой запрос на каждую подписку — это лишний расход
    чужого лимита ради того, что мы и так опросили секунду назад. Пустое кольцо (первые
    минуты после старта) даёт False, и ответ честно называет эту причину.
    """
    try:
        return ticker.upper() in store.tickers_seen()
    except Exception as e:
        print('[sentinel] проверка тикера не удалась: %s' % str(e)[:110])
        return True     # НЕ БЛОКИРУЕМ из-за своей поломки: подписка дешевле отказа
