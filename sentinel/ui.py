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
            return outbox.status_line(_lang(uid))
    except Exception as e:
        print('[sentinel] команда %s упала uid=%s: %s: %s' % (act, uid, type(e).__name__,
                                                              str(e)[:150]))
        return 'Дозорный споткнулся: %s. Детали в bot.log.' % type(e).__name__
    return None


# ═══════════════════════════════════════════════════════════════════════════════════════════
# ЭКРАН С КНОПКАМИ. Ниже всё, что раньше жило только словами.
#
# ЗАЧЕМ ОН ЕСТЬ. Требование владельца дословно: «пороги пусть такие, но они должны быть
# настраиваемые, и само включение/выключение дозора должно идти через какое-то меню». Команды
# словами остаются — они быстрее, — но человек, не читавший спеку, о них не узнает: кнопка
# отвечает на вопрос «а что тут вообще можно», а команда требует заранее знать ответ.
#
# ДВА ЯЗЫКА, И ЭТО НЕ ВЕЖЛИВОСТЬ. По меню бота ходит автоматический обходчик e2e и требует,
# чтобы на `lang=en` НИ ОДИН достижимый экран не отдавал кириллицу. Экран, добавленный только
# по-русски, покраснеет не здесь, а в чужом тесте — и выглядеть это будет как его поломка.
#
# ЧЕГО НА ЭКРАНЕ НЕТ: правки ОБЩИХ порогов (3% / 2.5σ / зажигание). Они одни на всех
# подписчиков, и кнопка «+1%» у одного человека молча поменяла бы поведение у остальных.
# Общие числа показаны СТРОКОЙ (видно, по чему работает дозор) и правятся в `.env`; кнопками
# крутится ЛИЧНОЕ — порог движения, пауза, суточный потолок, тихие часы.
# ═══════════════════════════════════════════════════════════════════════════════════════════
_T = {
    'title': {'ru': '👁 Дозорный', 'en': '👁 Sentinel'},
    'watch_none': {'ru': 'Под дозором: ничего', 'en': 'Watching: nothing'},
    'watch_all': {'ru': 'Под дозором: вся площадка', 'en': 'Watching: the whole venue'},
    'watch_n': {'ru': 'Под дозором (%d): %s', 'en': 'Watching (%d): %s'},
    'alerts_on': {'ru': '🔔 Алерты: вкл', 'en': '🔔 Alerts: on'},
    'alerts_off': {'ru': '🔇 Алерты: ВЫКЛ', 'en': '🔇 Alerts: OFF'},
    'brief_on': {'ru': '🧭 Сводки: вкл', 'en': '🧭 Briefs: on'},
    'brief_off': {'ru': '🧭 Сводки: выкл', 'en': '🧭 Briefs: off'},
    'all_on': {'ru': '🌍 Вся площадка: да', 'en': '🌍 Whole venue: yes'},
    'all_off': {'ru': '🌍 Вся площадка: нет', 'en': '🌍 Whole venue: no'},
    'mp': {'ru': 'Порог движения: %s', 'en': 'Move threshold: %s'},
    'mp_off': {'ru': 'как общий', 'en': 'the shared one'},
    'cd': {'ru': 'Пауза: %d мин', 'en': 'Cooldown: %d min'},
    'cap': {'ru': 'Потолок: %d в сутки', 'en': 'Cap: %d per day'},
    'quiet': {'ru': 'Тихие часы: %s', 'en': 'Quiet hours: %s'},
    'quiet_off': {'ru': 'нет', 'en': 'none'},
    'today': {'ru': 'Сегодня доставлено: %d из %d', 'en': 'Delivered today: %d of %d'},
    'shared': {'ru': 'Общие пороги (правятся в .env, одни на всех): 15м %.1f%% · 60м %.1f%% · '
                     '%.1f сигмы · интерес %.0f%% · зажигание %d адреса/$%.0fk',
               'en': 'Shared thresholds (edited in .env, same for everyone): 15m %.1f%% · '
                     '60m %.1f%% · %.1f sigma · OI %.0f%% · ignition %d addresses/$%.0fk'},
    'btn_report': {'ru': '📊 Попадания', 'en': '📊 Hit rate'},
    'k_move': {'ru': 'Движения', 'en': 'Moves'},
    'k_oi': {'ru': 'Интерес', 'en': 'Open interest'},
    'k_vol': {'ru': 'Объём', 'en': 'Volume'},
    'k_gap': {'ru': 'Расхождение', 'en': 'Venue gap'},
    'k_ign': {'ru': 'Зажигание', 'en': 'Ignition'},
    'k_fund': {'ru': 'Фандинг', 'en': 'Funding'},
    'k_spread': {'ru': 'Спред', 'en': 'Spread'},
    'p_nansen': {'ru': 'Нансен', 'en': 'Nansen'},
    'p_news': {'ru': 'Новости', 'en': 'News'},
    'what_comes': {'ru': 'Что присылать:', 'en': 'What to send:'},
    'what_inside': {'ru': 'Что внутри алерта:', 'en': 'Inside the alert:'},
    'btn_refresh': {'ru': '🔄 Обновить', 'en': '🔄 Refresh'},
    'btn_now': {'ru': '📈 Что сейчас', 'en': '📈 Market now'},
    'venues': {'ru': 'Площадки:', 'en': 'Venues:'},
    'preset': {'ru': '⚙️ Пресет: %s', 'en': '⚙️ Preset: %s'},
    'p_test': {'ru': 'поток', 'en': 'firehose'},
    'p_normal': {'ru': 'рабочий', 'en': 'normal'},
    'p_quiet': {'ru': 'тихий', 'en': 'quiet'},
    'day': {'ru': 'За сутки:', 'en': 'Last 24h:'},
    'nothing': {'ru': 'ничего', 'en': 'nothing'},
    'btn_help': {'ru': '❓ Как это работает', 'en': '❓ How it works'},
    'saved': {'ru': 'Готово', 'en': 'Saved'},
    'free': {'ru': 'Nansen на время хакатона бесплатен: суточный кап расхода выключен, '
                   'но расход измеряется и виден строкой выше.',
             'en': 'Nansen is free for the hackathon: the daily spend cap is off, but spend is '
                   'still measured and shown in the line above.'},
}


def _t(key, lang='ru'):
    v = _T.get(key) or {}
    return v.get('en' if lang == 'en' else 'ru') or key


def _lang(uid):
    """Язык человека ОДНОЙ дверью бота, а не своим полем. Сбой резолвера -> русский."""
    try:
        import oc_menu
        return oc_menu.lang_of(uid)
    except Exception:
        return 'ru'


def _venue_row(lang, uid):
    """Ряд тумблеров площадок. -> [InlineKeyboardButton]. Выключенные площадки
    показываются с причиной в тексте экрана, а не пропадают молча."""
    from telegram import InlineKeyboardButton as B
    from . import venues as _v
    on = store.venues_for(uid)
    return [B(_mark(_v.title(k), k in on), callback_data='sen:v:%s' % k)
            for k in _v.live()]


def _mark(text, on):
    """Подпись тумблера с отметкой состояния. -> str.

    ГАЛОЧКА И КРЕСТИК, А НЕ СЛОВО «вкл/выкл»: в ряду из трёх кнопок подпись обрезается, и
    «Движения: в…» не говорит ничего. Знак читается первым и не обрезается никогда.
    """
    return ('✓ ' if on else '✗ ') + text


def menu_text(uid, lang=None):
    """Экран состояния. ВЕДЁТ ВЕЛИЧИНАМИ: что под дозором, сколько дошло, по чему работает."""
    lang = lang or _lang(uid)
    s = store.settings(uid)
    subs = store.sub_list(uid)
    out = [_t('title', lang), '']
    if not subs:
        out.append(_t('watch_none', lang))
    elif store.ALL in subs:
        out.append(_t('watch_all', lang))
    else:
        out.append(_t('watch_n', lang) % (len(subs), ', '.join(subs)))
    out.append(_t('today', lang) % (store.sent_today(uid), store.cap_for(uid)))
    _k = store.kinds_for(uid)
    _p = store.parts_for(uid)
    _kn = {'move_up': _t('k_move', lang), 'vol_surge': _t('k_vol', lang),
           'venue_gap': _t('k_gap', lang),
           'oi_surge': _t('k_oi', lang),
           'ignition': _t('k_ign', lang), 'funding_extreme': _t('k_fund', lang),
           'spread_shock': _t('k_spread', lang)}
    _on = [v for k, v in _kn.items() if k in _k]
    out.append('%s %s' % (_t('what_comes', lang),
                          ', '.join(_on) if _on else _t('quiet_off', lang)))
    try:
        from . import venues as _vv
        _on = store.venues_for(uid)
        _vline = ', '.join(('%s ✓' if k in _on else '%s ✗') % _vv.title(k)
                           for k in _vv.enabled())
        # ВЫКЛЮЧЕННАЯ ПЛОЩАДКА НАЗЫВАЕТ ПРИЧИНУ. «Её тут нет» человек читает как
        # «забыли», а причина превращает это в решение.
        _off = [(k, _vv.why_off(k, lang)) for k in _vv.VENUES
                if not (_vv.VENUES[k] or {}).get('fetch')]
        _tpl = ' · %s not yet (%s)' if lang == 'en' else ' · %s пока нет (%s)'
        for _k, _w in _off:
            if _w:
                _vline += _tpl % (_vv.title(_k), _w)
        out.append('%s %s' % (_t('venues', lang), _vline))
    except Exception as _ve:
        print('[sentinel] строка площадок не собралась: %s' % str(_ve)[:90])
    out.append('%s %s' % (_t('what_inside', lang),
                          ', '.join([_t('p_nansen', lang)] if 'nansen' in _p else [])
                          + (', ' if ('nansen' in _p and 'news' in _p) else '')
                          + (_t('p_news', lang) if 'news' in _p else '')))
    # СОБЫТИЯ ЗА СУТКИ - РАЗРЕЗОМ ПО ВИДАМ. «Событий 12» не отвечает на вопрос «а движения-то
    # были?»: двенадцать спредов и ноль движений выглядят как двенадцать событий. Живой случай
    # 25.09 разобрался бы этой строкой за секунду.
    try:
        import time as _tm
        _by = store.events_by_kind(int(_tm.time()) - 86400)
        _parts = ['%s %d' % (_kn.get(k, k), v) for k, v in sorted(_by.items(), key=lambda x: -x[1])
                  if k in _kn]
        out.append('%s %s' % (_t('day', lang), ', '.join(_parts) if _parts
                              else _t('nothing', lang)))
    except Exception as _e:
        print('[sentinel] разрез событий не собрался: %s' % str(_e)[:90])
    out.append('')
    out.append(outbox.status_line(lang))
    out.append('')
    out.append(_t('shared', lang) % (config.move_pct_15m(), config.move_pct_60m(),
                                     config.z_min(), config.oi_pct(),
                                     config.ign_wallets(), config.ign_usd() / 1000))
    # ПРО «БЕСПЛАТНО» ГОВОРИМ ВСЛУХ И ТОЛЬКО КОГДА ЭТО ПРАВДА: выключенный кап - решение
    # владельца, а не дефект, и человек, читающий «кап выключен», должен видеть, что так и
    # задумано. Как только кап включат числом, строка исчезнет сама.
    if config.nansen_day_credits() <= 0:
        out.append('')
        out.append(_t('free', lang))
    return '\n'.join(out)


def menu_kb(uid, lang=None):
    """Клавиатура экрана. -> InlineKeyboardMarkup. Префикс наш: `sen:`."""
    lang = lang or _lang(uid)
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup
    s = store.settings(uid)
    subs = store.sub_list(uid)
    mp = s.get('min_pct')
    cd = int(s.get('cooldown_min') or (config.cooldown_sec() // 60))
    cap = store.cap_for(uid)
    q = (_t('quiet_off', lang) if s.get('quiet_from') is None
         else '%02d-%02d UTC' % (int(s['quiet_from']), int(s['quiet_to'])))
    kinds = store.kinds_for(uid)
    parts = store.parts_for(uid)
    rows = [
        # ТУМБЛЕРЫ ПОДПИСАНЫ ТЕКУЩИМ СОСТОЯНИЕМ, А НЕ ДЕЙСТВИЕМ. «Алерты: вкл» отвечает на
        # вопрос «как сейчас»; кнопка «Выключить алерты» на него не отвечает, и человек жмёт
        # её, чтобы проверить, что было (класс бага «кнопка режима включает режим из своей
        # подписи» в этом проекте уже ловили).
        [B(_t('alerts_on' if s.get('alerts_on') else 'alerts_off', lang),
           callback_data='sen:t:al')],
        [B(_t('brief_on' if s.get('enrich_on') else 'brief_off', lang),
           callback_data='sen:t:br'),
         B(_t('all_on' if store.ALL in subs else 'all_off', lang), callback_data='sen:t:all')],
        [B('−', callback_data='sen:mp:-1'),
         B(_t('mp', lang) % (('%.1f%%' % float(mp)) if mp else _t('mp_off', lang)),
           callback_data='sen:mp:0'),
         B('+', callback_data='sen:mp:1')],
        [B('−', callback_data='sen:cd:-15'), B(_t('cd', lang) % cd, callback_data='sen:cd:0'),
         B('+', callback_data='sen:cd:15')],
        [B('−', callback_data='sen:cap:-5'), B(_t('cap', lang) % cap, callback_data='sen:cap:0'),
         B('+', callback_data='sen:cap:5')],
        [B(_t('quiet', lang) % q, callback_data='sen:q:next')],
        # ЧТО ПРИСЫЛАТЬ - ТУМБЛЕРАМИ С ГАЛОЧКОЙ. Просьба владельца дословно: «настраивать, что
        # приходят алерты движения плюс нансен движения существенные, или просто Нансен сигналы,
        # или просто алерты по объёму». Галочка в подписи говорит СОСТОЯНИЕ: кнопка «Движения»
        # без отметки не отвечает на вопрос «а сейчас они идут?».
        [B(_mark(_t('k_move', lang), 'move_up' in kinds), callback_data='sen:k:move'),
         B(_mark(_t('k_vol', lang), 'vol_surge' in kinds), callback_data='sen:k:vol'),
         B(_mark(_t('k_oi', lang), 'oi_surge' in kinds), callback_data='sen:k:oi')],
        [B(_mark(_t('k_ign', lang), 'ignition' in kinds), callback_data='sen:k:ign'),
         B(_mark(_t('k_gap', lang), 'venue_gap' in kinds), callback_data='sen:k:gap'),
         B(_mark(_t('k_fund', lang), 'funding_extreme' in kinds), callback_data='sen:k:fund'),
         B(_mark(_t('k_spread', lang), 'spread_shock' in kinds), callback_data='sen:k:spread')],
        # ЧТО ВНУТРИ АЛЕРТА. 'card' (числа площадки) в тумблерах НЕТ нарочно: алерт без чисел -
        # это уведомление «что-то случилось» без ответа «что именно». Выключается дорогое.
        [B(_mark(_t('p_nansen', lang), 'nansen' in parts), callback_data='sen:p:nansen'),
         B(_mark(_t('p_news', lang), 'news' in parts), callback_data='sen:p:news')],
        # «ЧТО СЕЙЧАС» - ПЕРВОЙ КНОПКОЙ В ЭТОМ РЯДУ. Она отвечает на вопрос, который человек
        # задаёт раньше всех остальных: «оно вообще работает?». Молчание дозорного и его смерть
        # выглядят одинаково, и только числа рынка их различают.
        # ПЛОЩАДКИ ТУМБЛЕРАМИ. Отдельный ряд, а не строка в тексте: человек их включает и
        # выключает так же часто, как виды событий, и чужая площадка в потоке мешает ровно
        # так же, как чужой вид.
        _venue_row(lang, uid),
        [B(_t('preset', lang) % _t('p_test', lang), callback_data='sen:pr:test'),
         B(_t('preset', lang) % _t('p_normal', lang), callback_data='sen:pr:normal'),
         B(_t('preset', lang) % _t('p_quiet', lang), callback_data='sen:pr:quiet')],
        [B(_t('btn_now', lang), callback_data='sen:now'),
         B(_t('btn_report', lang), callback_data='sen:rep')],
        [B(_t('btn_help', lang), callback_data='sen:help')],
        [B(_t('btn_refresh', lang), callback_data='sen:home')],
    ]
    return InlineKeyboardMarkup(rows)


#: ЛЕСТНИЦА ТИХИХ ЧАСОВ - ЗАКРЫТЫЙ СПИСОК, А НЕ ВВОД ЧИСЛА. Ввод часов кнопками требует двух
#: экранов и даёт «23-24», а закрытая лестница из четырёх привычных вариантов покрывает то, что
#: люди просят, и не может собрать бессмысленное окно.
_QUIET_LADDER = ((None, None), (22, 8), (0, 6), (23, 7))


def _quiet_next(s):
    cur = (s.get('quiet_from'), s.get('quiet_to'))
    cur = (None, None) if cur[0] is None else (int(cur[0]), int(cur[1]))
    try:
        i = _QUIET_LADDER.index(cur)
    except ValueError:
        i = -1
    return _QUIET_LADDER[(i + 1) % len(_QUIET_LADDER)]


def _step_pct(cur, delta):
    """Порог движения ступенями по 1%. 0 = «как общий» (личного порога нет).

    НИЖЕ НУЛЯ НЕ УХОДИМ И ВЫШЕ 50 НЕ ПОДНИМАЕМСЯ: отрицательный порог пропускал бы всё, а
    порог в сто процентов означал бы тишину навсегда — и то и другое человек прочитал бы как
    поломку дозорного, а не как своё же значение.
    """
    base = float(cur or 0)
    v = round(base + delta, 1)
    if v <= 0:
        return None
    return min(50.0, v)


async def handle_callback(update, context):
    """Роутер префикса `sen:` (регистрируется в bot.py). -> None.

    СБОЙ КНОПКИ ОБЯЗАН БЫТЬ ВИДЕН СООБЩЕНИЕМ. `q.answer()` уже вызван, а второй ответ на тот
    же callback Telegram молча выбрасывает — значит «нажимаю, ничего не происходит» было бы
    неотличимо от «кнопка не привязана». Этот разбор в проекте уже оплачен один раз (`oc_menu`).
    """
    q = getattr(update, 'callback_query', None)
    data = (getattr(q, 'data', '') or '')
    if not data.startswith('sen:'):
        return
    uid = q.from_user.id if getattr(q, 'from_user', None) else 0
    lang = _lang(uid)
    try:
        await q.answer()
    except Exception:
        pass
    try:
        parts = data.split(':')
        act = parts[1] if len(parts) > 1 else 'home'
        arg = parts[2] if len(parts) > 2 else ''
        if act == 't':
            s = store.settings(uid)
            if arg == 'al':
                store.settings_set(uid, alerts_on=0 if s.get('alerts_on') else 1)
            elif arg == 'br':
                store.settings_set(uid, enrich_on=0 if s.get('enrich_on') else 1)
            elif arg == 'all':
                if store.ALL in store.sub_list(uid):
                    store.sub_del(uid, store.ALL)
                else:
                    store.sub_add(uid, store.ALL)
        elif act == 'mp':
            s = store.settings(uid)
            store.settings_set(uid, min_pct=(None if arg == '0'
                                             else _step_pct(s.get('min_pct'), float(arg))))
        elif act == 'cd':
            s = store.settings(uid)
            if arg == '0':
                store.settings_set(uid, cooldown_min=None)
            else:
                base = int(s.get('cooldown_min') or (config.cooldown_sec() // 60))
                store.settings_set(uid, cooldown_min=max(5, min(1440, base + int(arg))))
        elif act == 'cap':
            s = store.settings(uid)
            if arg == '0':
                store.settings_set(uid, daily_cap=None)
            else:
                store.settings_set(uid, daily_cap=max(1, min(200,
                                                             store.cap_for(uid) + int(arg))))
        elif act == 'k':
            # ДВИЖЕНИЯ - ОДИН ТУМБЛЕР НА ДВА ВИДА. Разделять «вверх» и «вниз» кнопками значит
            # предлагать человеку подписку на половину рынка: тот, кто хочет знать о падении,
            # хочет знать и о росте.
            _map = {'move': ('move_up', 'move_down'), 'oi': ('oi_surge',),
                    'vol': ('vol_surge',), 'gap': ('venue_gap',),
                    'ign': ('ignition',), 'fund': ('funding_extreme',),
                    'spread': ('spread_shock',)}
            cur = store.kinds_for(uid)
            group = _map.get(arg) or ()
            if set(group) & cur:
                cur -= set(group)
            else:
                cur |= set(group)
            store.kinds_set(uid, cur)
        elif act == 'p':
            store.part_toggle(uid, arg)
        elif act == 'v':
            store.venue_toggle(uid, arg)
        elif act == 'pr':
            _nm, _why = store.preset_apply(uid, arg)
            await _send(q, context,
                        ('⚙️ Пресет «%s»: %s' % (_nm, _why)) if _nm else
                        ('Не вышло: %s' % _why))
        elif act == 'q':
            f, t = _quiet_next(store.settings(uid))
            store.settings_set(uid, quiet_from=f, quiet_to=t)
        elif act == 'now':
            return await _send(q, context, now_text(lang))
        elif act == 'rep':
            return await _send(q, context, report_text(lang))
        elif act == 'help':
            return await _send(q, context, HELP if lang != 'en' else HELP_EN)
        await _show(q, context, uid, lang)
    except Exception as e:
        print('[sentinel] кнопка %r: %s: %s' % (data, type(e).__name__, e))
        await _send(q, context, ('Кнопка не сработала: %s. Скажи словами - сделаю.'
                                 % str(e)[:90]) if lang != 'en' else
                    ('That button failed: %s. Tell me in words instead.' % str(e)[:90]))


async def route_send(bot, uid, text):
    """Команда словами -> ОТПРАВЛЕННЫЙ ответ. -> True, если ответили; False, если фраза не наша.

    ИМЯ БЕЗ ХВОСТА «-bot» НАРОЧНО: скруббер публичной выжимки запрещает в коде всё, что похоже
    на имя телеграм-бота (слово, оканчивающееся этим хвостом), и первая редакция с таким именем
    остановила сборку. Ослаблять скруббер ради имени функции нельзя: он держит целый класс
    утечки, а имя переименовать дешевле.

    ЗАЧЕМ ОТДЕЛЬНО ОТ `route`. `route` возвращает строку и остаётся для тестов и для любого
    вызывающего, которому нужен текст. Но у экрана состояния есть КНОПКИ, а клавиатуру к
    возвращённой строке прикрепить негде — значит отправлять должен тот, у кого есть `bot`.
    Обе двери ведут в ОДИН разбор (`parse`): разойдись они, «дозор порог 5» работал бы словами
    и не работал бы кнопкой, и никто бы этого не заметил месяц.
    """
    got = parse(text)
    if not got:
        return False
    act = got[0]
    lang = _lang(uid)
    # ЭКРАН СОСТОЯНИЯ - ЕДИНСТВЕННЫЙ, У КОГО КЛАВИАТУРА. Остальные ответы (отчёт, отказ,
    # подтверждение) короткие и одноразовые; клавиатура под ними только копила бы экраны.
    if act == 'status':
        await bot.send_message(chat_id=uid, text=menu_text(uid, lang),
                               reply_markup=menu_kb(uid, lang), parse_mode='HTML',
                               disable_web_page_preview=True)
        return True
    txt = route(uid, text)
    if not txt:
        return False
    await bot.send_message(chat_id=uid, text=txt, parse_mode='HTML',
                           disable_web_page_preview=True)
    # ПОСЛЕ ЛЮБОЙ ПРАВКИ ПОКАЗЫВАЕМ ЭКРАН: человек, сказавший «дозор порог 5», хочет увидеть,
    # что изменилось, а не только слово «готово». Это же и путь к кнопкам для того, кто про
    # них не знал.
    if act in ('add', 'del', 'alerts', 'enrich', 'minpct', 'quiet'):
        await bot.send_message(chat_id=uid, text=menu_text(uid, lang),
                               reply_markup=menu_kb(uid, lang), parse_mode='HTML',
                               disable_web_page_preview=True)
    return True


async def _show(q, context, uid, lang):
    """Перерисовать экран НА МЕСТЕ. Новое сообщение на каждый тап превратило бы настройку
    порога в простыню из десяти одинаковых экранов."""
    kb = menu_kb(uid, lang)
    txt = menu_text(uid, lang)
    try:
        await q.edit_message_text(txt, reply_markup=kb, parse_mode='HTML',
                                  disable_web_page_preview=True)
        return
    except Exception as e:
        # «Message is not modified» - не ошибка: человек вернул значение к прежнему.
        if 'not modified' in str(e).lower():
            return
        print('[sentinel] экран не перерисован (%s) - шлю новым' % str(e)[:90])
    await _send(q, context, txt, kb)


async def _send(q, context, text, kb=None):
    """Сообщение экрана. ВСЕГДА с HTML: иначе человек читает теги глазами.

    ЖИВОЙ СЛУЧАЙ 25.09: экран «Что сейчас» пришёл владельцу как `<b>Что сейчас на площадке</b>`
    - буквально, с тегами в тексте. Карточки алертов ходят через `outbox`, где parse_mode задан,
    а экраны ui отправлялись здесь БЕЗ него: одна дверь знала про разметку, вторая нет. Класс
    бага тот же, что «пятая копия тега разъедется с остальными» - разметка обязана жить В ОДНОМ
    месте на каждый канал отправки, и обе двери должны о ней знать.
    """
    chat = (getattr(getattr(q, 'message', None), 'chat_id', None)
            or (q.from_user.id if getattr(q, 'from_user', None) else None))
    if chat is None:
        return
    await context.bot.send_message(chat_id=chat, text=text, reply_markup=kb,
                                   parse_mode='HTML', disable_web_page_preview=True)


def now_text(lang='ru'):
    """СРЕЗ РЫНКА ИЗ НАШЕГО КОЛЬЦА. -> str. Ни одного запроса к площадке, ни одного кредита.

    ГЛАВНАЯ СТРОКА ЗДЕСЬ - ПОСЛЕДНЯЯ: насколько лучший кандидат далёк от порога. Живой случай
    25.09 («включил, пока ничего не пришло») был правдой про рынок - за три минуты ни один из
    553 инструментов не изменил марк-цену, - но узнать это человеку было негде. Ответ «ближайшее
    движение 0.4% против порога 1.2%» закрывает вопрос числом, а не обещанием.
    """
    m = engine.market_now()
    ru = lang != 'en'
    out = ['📈 <b>%s</b>' % ('Что сейчас на площадке' if ru else 'Market right now')]
    if not m['tickers']:
        out.append('Кольцо пустое: дозорный только что запущен, первые точки появятся через '
                   'минуту.' if ru else
                   'The ring is empty: the sentinel has just started; first points in a minute.')
        return '\n'.join(out)
    out.append('<i>%s: %d %s, %d %s</i>'
               % ('в кольце' if ru else 'in the ring', m['tickers'],
                  'инструментов' if ru else 'instruments', m['points'],
                  'точек на инструмент' if ru else 'points per instrument'))
    out.append('')
    out.append('<b>%s</b>' % ('Сильнее всего двигались' if ru else 'Biggest moves'))
    if m['moves']:
        for _a, t, best, p15, p60, _v in m['moves']:
            bits = []
            if p15 is not None:
                bits.append('15м %+.2f%%' % p15)
            if p60 is not None:
                bits.append('60м %+.2f%%' % p60)
            out.append('• <b>%s</b> <i>%s</i> %s'
                       % (t, _vt(_v), ' · '.join(bits)))
    else:
        out.append('• %s' % ('движений не измерено (кольцо ещё набирается)' if ru
                             else 'no moves measured yet'))
    if m['vols']:
        out.append('')
        out.append('<b>%s</b>' % ('Растёт оборот' if ru else 'Turnover growing'))
        for dv, t, dusd, _v in m['vols']:
            out.append('• <b>%s</b> <i>%s</i> +%.0f%% (+%s)'
                       % (t, _vt(_v), dv, _money(dusd)))
    out.append('')
    # ГЛАВНАЯ СТРОКА ТИХОГО ЧАСА - СКОЛЬКО ИНСТРУМЕНТОВ ВООБЩЕ СДВИНУЛОСЬ. «Сильнейшее движение
    # 0.00%» само по себе читается как сломанный счётчик; рядом с «из 192 измеренных сдвинулись
    # 0» это уже факт про площадку, и вопрос «а дозорный жив?» закрывается числом.
    if m.get('measured'):
        out.append(('Сдвинулись с места: <b>%d</b> из %d измеренных.' if ru else
                    'Moved at all: <b>%d</b> of %d measured.')
                   % (m.get('stirred') or 0, m['measured']))
    if m.get('best') is not None:
        if m['best'] >= m['thr15']:
            out.append('Сильнейшее движение <b>%.2f%%</b> — порог %.2f%% взят, событие записано '
                       'или ждёт паузы и фильтров.' % (m['best'], m['thr15']) if ru else
                       'Strongest move <b>%.2f%%</b> — the %.2f%% threshold is met; the event is '
                       'stored or waiting on cooldown and filters.' % (m['best'], m['thr15']))
        else:
            out.append(('Сильнейшее движение <b>%.2f%%</b> против порога %.2f%% — тихо на рынке, '
                        'а не в дозорном.' if ru else
                        'Strongest move <b>%.2f%%</b> against a %.2f%% threshold — the market is '
                        'quiet, not the sentinel.') % (m['best'], m['thr15']))
    return '\n'.join(out)


def _vt(venue):
    """Короткое имя площадки для строки списка. Общая дверь - в `venues`."""
    from .venues import title
    return title(venue)[:4]


def _money(v):
    from .cards import _usd
    return _usd(v)


def report_text(lang='ru'):
    out = ['📊 Попадания дозорного за 7 дней (по нашим же снимкам):' if lang != 'en'
           else '📊 Sentinel hit rate over 7 days (from our own snapshots):']
    for kind in ('move_up', 'move_down', 'ignition', 'oi_surge'):
        out.append('• ' + engine.hit_rate(kind=kind, horizon_min=60))
    out.append('')
    out.append('Горизонт 60 минут: «продолжение движения» значит, что через час цена была '
               'дальше в ту же сторону. Это НЕ доходность и не обещание.' if lang != 'en' else
               'Horizon 60 minutes: "continuation" means the price was further in the same '
               'direction an hour later. That is NOT a return and not a promise.')
    return '\n'.join(out)


#: АНГЛИЙСКАЯ СПРАВКА - НЕ ПЕРЕВОД РАДИ ГАЛОЧКИ. Обходчик e2e открывает справку на `lang=en` и
#: требует отсутствия кириллицы, но главное не в тесте: показать англоязычному человеку РУССКУЮ
#: команду значит дать подсказку, которую он физически не наберёт. Поэтому команды здесь
#: английские и они РАБОТАЮТ - реестр `en_triggers` переписывает голову в канонический русский
#: триггер ДО разбора (английский в этом проекте - данные, а не вторая ветка кода).
HELP_EN = (
    '👁 Sentinel - live alerts on Variational Omni and smart money.\n'
    '\n'
    'sentinel BTC - watch an instrument (or: watch BTC)\n'
    'sentinel all - the whole venue (553 instruments)\n'
    'sentinel remove BTC - stop watching\n'
    'sentinel - state screen with buttons\n'
    'sentinel threshold 5 - stay silent below 5%\n'
    'sentinel quiet 22 8 - quiet hours in UTC, "sentinel quiet off" clears them\n'
    'sentinel off / sentinel on - pause alerts without losing the list\n'
    'sentinel briefs off - numbers only, no Nansen and no X\n'
    'sentinel report - hit rate, or an honest "sample too small"\n'
    '\n'
    'What arrives: a price move (with a measure of how unusual it is FOR THAT instrument), an '
    'open-interest surge, funding in its own tail, a widened quote, and Smart Ignition '
    '(several distinct smart-money addresses bought one token).\n'
    'The sentinel does NOT trade and does NOT advise. You enter by hand on omni.variational.io.'
)


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
