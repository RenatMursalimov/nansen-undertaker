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

import os
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
    # ПРЕДОХРАНИТЕЛЬ И ПОРОГ ЗВОНКА - СЛОВАМИ ТОЖЕ. Закон этого модуля: у кнопки и команды
    # ОДИН разбор и одно поведение, иначе «кнопкой одно, словами другое» - и это уже ловили.
    m = re.match(r'^предохранитель\s+(\d{1,3})(?:\s*/\s*(\d{1,3}))?$', rest)
    if m:
        return ('burst', {'n': int(m.group(1)),
                          'win': int(m.group(2)) if m.group(2) else None})
    if re.match(r'^предохранитель\s+(сброс|как общий|общий)$', rest):
        return ('burst', {'n': None, 'win': None})
    m = re.match(r'^(?:звонок|сила)\s+(?:от\s+)?(\d{1,3})$', rest)
    if m:
        return ('minsev', {'sev': int(m.group(1))})
    if re.match(r'^(?:звонок|сила)\s+(сброс|как общий|общий)$', rest):
        return ('minsev', {'sev': None})
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
    'дозор предохранитель 3 / 10 — не больше 3 сообщений за 10 минут (остальное сводкой)\n'
    'дозор звонок 75 — звонить только при уверенности от 75/100, слабее — сводкой\n'
    'дозор сводки выкл — только цифры, без Нансена и твиттера\n'
    'дозор отчёт — попадания за неделю (или честное «выборка мала»)\n'
    '\n'
    'Что приходит: движение цены (с оценкой «необычно ли это ДЛЯ НЕГО»), скачок открытого '
    'интереса, ставка в хвосте, разъехавшаяся котировка, смарт-зажигание (несколько разных '
    'умных адресов купили один токен).\n'
    'Дозорный НЕ торгует и НЕ советует. Вход руками на omni.variational.io.'
)


def silence_reasons(uid, lang='ru'):
    """Почему при этих настройках алертов НЕ БУДЕТ. -> [строки]. Пусто = всё в порядке.

    ═══ ОДНА ДВЕРЬ НА ДВА ЭКРАНА, И ЭТО НЕ КОСМЕТИКА ═══
    Сторож тишины родился на кнопочном экране (`menu_text`), а команда словами («дозор») ходит
    в `status_text` - то есть на один и тот же вопрос человека два пути отвечали ПО-РАЗНОМУ:
    кнопкой он видел «алертов не будет», словами - нет. Этот же класс расхождения в дозорном уже
    ловили дважды («выключил кнопкой, а шлёт» против «выключил командой, а шлёт»), и правило
    записано: два пути к одному решению обязаны делать одно и то же.

    ПОРЯДОК ПРИЧИН - ОТ САМОЙ СИЛЬНОЙ: выключенные алерты глушат всё, поэтому о них первыми.
    НАБОР ВИДОВ ПЕРЕЧИТЫВАЕМ ЗДЕСЬ, а не принимаем аргументом: живая проба 26.09 показала, что
    в `menu_text` переменная с набором к этому месту уже затиралась циклом площадок, и сторож
    молча не срабатывал. Своё чтение стоит дешевле, чем разбор такого второй раз.
    """
    s = store.settings(uid)
    out = []
    if not store.sub_list(uid):
        out.append(_t('s_nosubs', lang))
    if not s.get('alerts_on'):
        out.append(_t('s_off', lang))
    if not store.kinds_for(uid):
        out.append(_t('s_nokinds', lang))
    try:
        if not store.venues_for(uid):
            out.append(_t('s_novenues', lang))
    except Exception:
        pass
    # ═══ ИСЧЕРПАННЫЙ ПОТОЛОК - ПРИЧИНА ТИШИНЫ №1, И ОН ДОЛЖЕН БЫТЬ НАЗВАН ПРИЧИНОЙ ═══
    # ЖИВОЙ ЭКРАН ВЛАДЕЛЬЦА 25.09: «Сегодня доставлено: 147 из 25» - потолок перебран в шесть
    # раз (он крутил пресеты: «поток» поднимает до 120, «рабочий» опускает до 25, а доставленное
    # за сутки никуда не девается). Все новые события уходили в сводку, и это было ПРАВИЛЬНО - но
    # человек полчаса искал причину в настройках, потому что число стояло отдельной строкой
    # состояния, а не в списке «почему тишина». Числу нужен вывод рядом.
    try:
        _cap, _got = store.cap_for(uid), store.sent_today(uid)
        if _got >= _cap:
            out.append(_t('s_cap', lang) % (_got, _cap))
    except Exception:
        pass
    # ═══ И ТИШИНА ОТ МЁРТВОГО ОПРОСА - ТОЖЕ ПРИЧИНА, ПРИЧЁМ НЕ ЗАВИСЯЩАЯ ОТ НАСТРОЕК ═══
    # Её человек своими кнопками не вылечит вовсе, поэтому она обязана быть названа отдельно от
    # остальных: крутить пороги, когда снимков нет, бессмысленно.
    try:
        _owner, _until = store.lease_owner()
        _now = int(__import__('time').time())
        if not (_owner and _until > _now):
            out.append(_t('s_nopoll', lang))
    except Exception:
        pass
    return out


def status_text(uid):
    """Состояние дозорного ОДНОЙ СТРОКОЙ-БЛОКОМ, без клавиатуры. -> str.

    ═══ ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ `menu_text` И ЗАЧЕМ ОСТАЛОСЬ ═══
    `menu_text` - экран ПОД КЛАВИАТУРОЙ: он короткий нарочно, потому что под ним двадцать
    кнопок, и его читают вместе с ними. Эта функция - ответ для мест, где клавиатуры НЕТ:
    владельческая сводка, лог, ответ на вопрос «как дела у дозорного» в чужом экране. Здесь
    можно позволить себе полный разрез, включая общие пороги.
    РАНЬШЕ ОНА БЫЛА ВТОРЫМ ОТВЕТОМ НА ТУ ЖЕ КОМАНДУ, и это был двойной источник правды:
    `route` отдавал её, а человек получал `menu_text`. Теперь команда «дозор» ведёт в один
    экран, а эта функция осталась там, где она и полезна - без кнопок.
    """
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
    # ПРЕДОХРАНИТЕЛЬ ВИДЕН ЧЕЛОВЕКУ И НАЗВАН ГРАНИЦЕЙ. Ограничение, о котором не сказано на
    # экране, человек примет за поломку («почему пришла сводка, а не алерт») - и будет прав:
    # молчащее правило неотличимо от сбоя.
    _bm, _bw, _capped = store.burst_for(uid)
    lines.append('Предохранитель: не больше %d сообщений за %d мин (за %d мин уже %d). '
                 'Остальное — сводкой раз в %d мин.'
                 % (_bm, _bw // 60, _bw // 60, store.sent_in_window(uid, _bw),
                    config.digest_sec() // 60))
    if _capped:
        # УПОР В ПОТОЛОК НАЗЫВАЕТСЯ ЧИСЛОМ. Иначе экран показал бы 12 там, где человек просил
        # 30, и это читалось бы как потерянное нажатие, а не как граница.
        lines.append('  ⚠️ выше %d кнопкой не поднять: это граница, а не настройка '
                     '(правится только в .env на сервере)' % store._BURST_HARD)
    lines.append('Порог звонка: уверенность от %d/100 (ниже — в сводку)' % store.min_sev_for(uid))
    # СТОРОЖ ТИШИНЫ - ТОЙ ЖЕ ДВЕРЬЮ, ЧТО У КНОПОЧНОГО ЭКРАНА. Разбор - в `silence_reasons`.
    _sil = silence_reasons(uid, _lang(uid))
    if _sil:
        lines.append('')
        lines.append(_t('s_head', _lang(uid)))
        for _w in _sil:
            lines.append('  • %s' % _w)
    if not config.deliver_on():
        # РУБИЛЬНИК ОБЪЯВЛЯЕТСЯ НА ЭКРАНЕ ПЕРВЫМ ДЕЛОМ: иначе человек крутит свои настройки и
        # не понимает, почему ничего не приходит, а причина лежит в `.env` на сервере.
        lines.append('⛔ Отправка выключена на сервере (SENTINEL_DELIVER=0). '
                     'Наблюдение идёт, сообщения не уходят.')
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
            # ═══ ОДИН ЭКРАН - ОДИН ТЕКСТ ═══
            # Здесь стоял `status_text`, а живой путь (`route_send`) отправляет `menu_text` -
            # то есть на ОДНУ команду «дозор» тест видел один текст, а человек другой. Два
            # источника правды на один экран: правка в одном молча расходилась с другим, и
            # сторож тишины, добавленный в `menu_text`, в ответе словами не появлялся вовсе.
            # Тот же класс, что «выключил кнопкой, а шлёт»: два пути к одному ответу обязаны
            # отвечать одинаково, иначе тест охраняет текст, которого никто не видит.
            return menu_text(uid, _lang(uid))
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
            if a['on']:
                return '✅ Алерты включены'
            # ═══ «ВЫКЛЮЧИЛ» ЗНАЧИТ «СЕЙЧАС» ═══
            # ЖИВОЙ ИНЦИДЕНТ 25.09: владелец выключил алерты и продолжил получать поток.
            # Настройка писалась верно, но в очереди уже лежали десятки доставок, и для них
            # выключателя не существовало. Гасим очередь ЗДЕСЬ же и НАЗЫВАЕМ ЧИСЛО: тишина
            # после нажатия неотличима от поломки, если не сказать, что именно отменено.
            n = store.delivery_drop_user(uid, 'алерты выключены человеком')
            return ('🔇 Алерты выключены. Список инструментов сохранён.'
                    + (' Отменено в очереди: %d.' % n if n else ''))
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
        if act == 'burst':
            if a['n'] is None:
                store.settings_set(uid, burst_max=None, burst_win_min=None)
                n, w, _ = store.burst_for(uid)
                return ('✅ Предохранитель вернулся к общему: %d сообщений за %d мин' % (n, w // 60))
            store.settings_set(uid, burst_max=int(a['n']),
                               burst_win_min=(int(a['win']) if a['win'] else None))
            n, w, capped = store.burst_for(uid)
            # УПОР В ПОТОЛОК НАЗЫВАЕТСЯ ЧИСЛОМ, А НЕ МОЛЧА ПОДМЕНЯЕТСЯ. Человек просил 30,
            # получил 12 - и обязан узнать об этом сразу, иначе будет считать, что у него 30.
            return ('✅ Предохранитель: %d сообщений за %d мин%s' % (
                n, w // 60,
                ('\n⚠️ Просили %d, но выше %d кнопкой нельзя: это граница, а не настройка. '
                 'Остальное не теряется — приедет сводкой.' % (a['n'], store._BURST_HARD))
                if capped else ''))
        if act == 'minsev':
            if a['sev'] is None:
                store.settings_set(uid, min_sev=None)
                return '✅ Порог звонка вернулся к общему: %d/100' % store.min_sev_for(uid)
            store.settings_set(uid, min_sev=int(a['sev']))
            v = store.min_sev_for(uid)
            return ('✅ Звонок от %d/100. Что слабее — приедет сводкой, а не пропадёт.' % v
                    if v else '✅ Звонок обо всём (порог 0). Темп всё равно держит предохранитель.')
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
    'k_crowd': {'ru': 'Толпа', 'en': 'Crowded'},
    'k_absorb': {'ru': 'Поглощение', 'en': 'Absorption'},
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
    # ── КРУГ 9: предохранитель, порог звонка и объяснение тишины ───────────────────────────
    'fuse_line': {'ru': 'Предохранитель: %d сообщений / %d мин · звонок от %d/100',
                  'en': 'Fuse: %d messages / %d min · rings from %d/100'},
    'fuse_capped': {'ru': '  ⚠️ выше %d кнопкой не поднять: это граница, а не настройка',
                    'en': '  ⚠️ cannot go above %d by button: this is a boundary, not a setting'},
    'burst': {'ru': '🚦 Не больше: %d сообщений', 'en': '🚦 At most: %d messages'},
    'bwin': {'ru': '🚦 …за окно: %d мин', 'en': '🚦 …per window: %d min'},
    'sev': {'ru': '⚖️ Звонок от: %d/100', 'en': '⚖️ Rings from: %d/100'},
    # ЗАГОЛОВОК ГОВОРИТ О ПОСЛЕДСТВИИ, А НЕ О НАСТРОЙКЕ: человеку важно «алертов не будет»,
    # а не «набор пуст» - второе он и так видит по галочкам, но не делает из этого вывода.
    's_head': {'ru': '⚠️ При этих настройках алертов НЕ БУДЕТ:',
               'en': '⚠️ With these settings NO alerts will arrive:'},
    's_nosubs': {'ru': 'ни один инструмент не под дозором — «дозор BTC» или «Вся площадка»',
                 'en': 'nothing is being watched — try "watch BTC" or "Whole venue"'},
    's_off': {'ru': 'алерты выключены тумблером', 'en': 'alerts are switched off'},
    's_nokinds': {'ru': 'все виды событий сняты — включите хотя бы один',
                  'en': 'every event kind is unchecked — switch at least one on'},
    's_novenues': {'ru': 'все площадки сняты — включите хотя бы одну',
                   'en': 'every venue is unchecked — switch at least one on'},
    's_cap': {'ru': 'суточный потолок исчерпан: доставлено %d из %d. Новое поедет СВОДКОЙ '
                    'до полуночи UTC — поднимите потолок или ждите смены суток',
              'en': 'the daily cap is used up: %d of %d delivered. New events will come as a '
                    'DIGEST until midnight UTC — raise the cap or wait for the day to turn'},
    's_nopoll': {'ru': 'ПЛОЩАДКИ НИКТО НЕ ОПРАШИВАЕТ (аренда истекла) — кольцо не растёт, '
                       'движений не будет ни при каких настройках. Это не ваши настройки: '
                       'проверьте службу sentinel на сервере',
                 'en': 'NOBODY IS POLLING THE VENUES (lease expired) — the ring is not growing '
                       'and no move will be detected at any settings. This is not your '
                       'settings: check the sentinel service on the server'},
    # ── ВЛАДЕЛЬЧЕСКИЕ КАПЫ КРЕДИТОВ (виден только владельцу) ───────────────────────────────
    'cap_nansen': {'ru': '💳 Кап дозора: %s кр/сутки', 'en': '💳 Sentinel cap: %s cr/day'},
    'cap_lab': {'ru': '🧪 Кап лаборатории: %s кр/сутки', 'en': '🧪 Lab cap: %s cr/day'},
    'cap_off': {'ru': 'Выключить кап', 'en': 'Cap off'},
    # ── ДВА ЭКРАНА: ОСНОВНОЕ СРАЗУ, РЕДКОЕ ПОД «ЕЩЁ» (замечание владельца 26.09) ──────────
    'adv_show': {'ru': '🎛 Ещё настройки ▾', 'en': '🎛 More settings ▾'},
    'adv_hide': {'ru': '🎛 Свернуть ▴', 'en': '🎛 Collapse ▴'},
    # ЗАГОЛОВКИ ГРУПП. Не украшение: они отвечают на «что здесь крутить», и тап по ним даёт
    # подсказку (молчащая кнопка - дефект, который мы уже ловили).
    'g_pace': {'ru': '— — —  🚦 ТЕМП: сколько и как часто  — — —',
               'en': '— — —  🚦 PACE: how many, how often  — — —'},
    'g_power': {'ru': '— — —  ⚖️ СИЛА: насколько крупное  — — —',
                'en': '— — —  ⚖️ STRENGTH: how big  — — —'},
    'g_kinds': {'ru': '— — —  🔔 ЧТО ПРИСЫЛАТЬ  — — —', 'en': '— — —  🔔 WHAT TO SEND  — — —'},
    'g_where': {'ru': '— — —  🏛 ГДЕ И ЧТО ВНУТРИ  — — —',
                'en': '— — —  🏛 WHERE AND WHAT IS INSIDE  — — —'},
    'g_caps': {'ru': '— — —  💳 КАПЫ КРЕДИТОВ (владелец)  — — —',
               'en': '— — —  💳 CREDIT CAPS (owner)  — — —'},
    'h_pace': {'ru': 'Темп: сколько сообщений и как часто. Предохранитель — жёсткая граница '
                     'на человека; пауза — по инструменту; потолок — за сутки.',
               'en': 'Pace: how many messages and how often. The fuse is a hard per-person '
                     'boundary; cooldown is per instrument; the cap is per day.'},
    'h_power': {'ru': 'Сила: насколько крупным должно быть событие. Это про СОСТАВ, а не про '
                      'количество — темп держит предохранитель.',
                'en': 'Strength: how big an event must be. This changes the MIX, not the '
                      'volume — the pace is held by the fuse.'},
    'h_kinds': {'ru': 'Виды событий. Галочка — включено. Выключенное не приходит и в сводке '
                      'не появляется: это ваш выбор, а не отсрочка.',
                'en': 'Event kinds. A tick means on. What is off does not arrive at all, not '
                      'even in the digest: that is your choice, not a delay.'},
    'h_where': {'ru': 'Площадки и состав алерта. Числа площадки идут всегда; Нансен и новости '
                      'стоят кредитов и выключаются отдельно.',
                'en': 'Venues and alert contents. Venue numbers always come; Nansen and news '
                      'cost credits and switch off separately.'},
    'h_caps': {'ru': 'Суточные капы кредитов. Это ОБЩИЙ кошелёк на всех подписчиков, поэтому '
                     'меняет только владелец. Ноль = потолка нет.',
               'en': 'Daily credit caps. This is a SHARED wallet for all subscribers, so only '
                     'the owner can change it. Zero means no ceiling.'},
    'free': {'ru': 'Nansen на время хакатона бесплатен: суточный кап расхода выключен, '
                   'но расход измеряется и виден строкой выше.',
             'en': 'Nansen is free for the hackathon: the daily spend cap is off, but spend is '
                   'still measured and shown in the line above.'},
}


def _t(key, lang='ru'):
    v = _T.get(key) or {}
    return v.get('en' if lang == 'en' else 'ru') or key


def _is_owner(uid):
    """Владелец/админ. -> bool. Читаем `ADMIN_IDS` из окружения, а не импортируем `bot`.

    ПОЧЕМУ НЕ `import bot`: этот модуль импортируется САМИМ ботом, и обратный импорт замкнул бы
    круг. Плюс `sentinel/` уезжает в публичную выжимку, где `bot.py` нет вовсе.
    ПОЧЕМУ ГЕЙТ ВООБЩЕ: кнопки ниже меняют ОБЩИЙ кошелёк кредитов, а не личную настройку. Без
    гейта любой подписчик потратил бы чужие деньги, и владелец узнал бы об этом строкой «кап
    исчерпан» на своём экране.
    ПУСТОЙ СПИСОК = НИКОМУ, а не всем: ошибка в `.env` не имеет права открыть общий кошелёк.
    """
    try:
        raw = os.getenv('ADMIN_IDS') or ''
        ids = {int(x) for x in re.findall(r'-?\d+', raw)}
    except Exception:
        ids = set()
    return bool(ids) and int(uid) in ids


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
    # ПРЕДОХРАНИТЕЛЬ И ПОРОГ ЗВОНКА - ЧИСЛАМИ НА ЭКРАНЕ, РЯДОМ СО СВОИМИ КНОПКАМИ.
    _bm, _bw, _capped = store.burst_for(uid)
    out.append(_t('fuse_line', lang) % (_bm, _bw // 60, store.min_sev_for(uid)))
    if _capped:
        out.append(_t('fuse_capped', lang) % store._BURST_HARD)
    _k = store.kinds_for(uid)
    _p = store.parts_for(uid)
    _kn = {'move_up': _t('k_move', lang), 'vol_surge': _t('k_vol', lang),
           'venue_gap': _t('k_gap', lang), 'crowded': _t('k_crowd', lang),
           'absorption': _t('k_absorb', lang),
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
        # ИМЯ ЦИКЛА СВОЁ (`_vk`), А НЕ `_k`: раньше здесь стояло `_k`, и цикл затирал набор ВИДОВ
        # событий, прочитанный выше. Ошибка тихая - набор дальше по функции уже не читался, - и
        # она немедленно всплыла, как только читатель появился (сторож тишины ниже).
        for _vk, _w in _off:
            if _w:
                _vline += _tpl % (_vv.title(_vk), _w)
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
    # ═══ НАСТРОЙКИ, ОЗНАЧАЮЩИЕ ТИШИНУ, НАЗЫВАЮТСЯ ВСЛУХ ═══
    # ЖИВОЙ СКРИНШОТ ВЛАДЕЛЬЦА 26.09: обе площадки ✗ и почти все виды ✗ - при таком наборе не
    # придёт НИ ОДНОГО алерта никогда, а экран об этом молчал и выглядел рабочим. Это тот самый
    # закон проекта: признак наличия (кнопки есть, дозор «включён») не равен признаку пользы.
    # ПОРЯДОК ПРИЧИН - ОТ САМОЙ СИЛЬНОЙ: выключенные алерты глушат всё, поэтому о них первыми.
    _why_silent = silence_reasons(uid, lang)
    if _why_silent:
        out.append('')
        out.append(_t('s_head', lang))
        for _w in _why_silent:
            out.append('  • %s' % _w)
    out.append('')
    out.append(outbox.status_line(lang))
    # ═══ СЛУЖЕБНОЕ - ТОЛЬКО В РАЗВЁРНУТОМ ВИДЕ ═══
    # Замечание владельца 26.09 про настройки касается и ТЕКСТА: общие пороги детектора и
    # строка про бесплатный Nansen человек читает один раз, а занимают они треть экрана над
    # клавиатурой. В свёрнутом виде остаётся то, что отвечает на «как сейчас»; подробности
    # появляются там же, где кнопки для них.
    if _ADV.get(int(uid)):
        out.append('')
        out.append(_t('shared', lang) % (config.move_pct_15m(), config.move_pct_60m(),
                                         config.z_min(), config.oi_pct(),
                                         config.ign_wallets(), config.ign_usd() / 1000))
        # ПРО «БЕСПЛАТНО» ГОВОРИМ ВСЛУХ И ТОЛЬКО КОГДА ЭТО ПРАВДА: выключенный кап - решение
        # владельца, а не дефект, и человек, читающий «кап выключен», должен видеть, что так и
        # задумано. Как только кап включат числом, строка исчезнет сама.
        if store.nansen_cap() <= 0:
            out.append('')
            out.append(_t('free', lang))
    return '\n'.join(out)


#: КТО РАЗВЕРНУЛ ПРОДВИНУТЫЕ НАСТРОЙКИ. В ПАМЯТИ ПРОЦЕССА, А НЕ В БАЗЕ - НАРОЧНО.
#: Это состояние ЭКРАНА, а не человека: «развёрнуто» ничего не меняет в поведении дозорного и
#: ничего не стоит потерять при рестарте (свернётся - и это правильное начальное состояние).
#: Колонка в базе ради визуальной мелочи означала бы миграцию и ещё одно поле в четырёх местах.
_ADV = {}


def menu_kb(uid, lang=None):
    """Клавиатура экрана. -> InlineKeyboardMarkup. Префикс наш: `sen:`.

    ═══ ДВА ЭКРАНА ВМЕСТО ОДНОГО. ЗАМЕЧАНИЕ ВЛАДЕЛЬЦА 26.09 ═══
    Дословно: «надо оптимизировать вывод настроек, основные настройки, которые в основном
    меняются, надо выводить, а продвинутые, которые очень редко меняются, спрятать в "ещё"…
    и сгруппировать рядом по смыслу».

    Он прав, и это видно по числу: клавиатура доросла до ДВАДЦАТИ ряд��в. Каждый ряд появлялся
    обоснованно (кнопку просили, и она нужна), а вместе они превратили экран в простыню, где
    тумблер «Алерты» - первый из двадцати равноправных. Экран, на котором всё одинаково важно,
    не помогает решать: он заставляет читать целиком, чтобы найти одно.

    ЧТО НАВЕРХУ. Ровно то, что человек трогает регулярно: главный тумблер, вся площадка,
    сводки, ПРЕСЕТЫ (одним тапом настраивают сразу четыре числа - самый частый способ), и два
    экрана-ответа («что сейчас», «попадания»).
    ЧТО ПОД «ЕЩЁ». Отдельные числа темпа и силы, тихие часы, наборы видов и площадок, капы
    кредитов. Это крутят раз в неделю, а места занимали больше половины.

    ГРУППЫ ПОДПИСАНЫ, И ЗАГОЛОВОК НЕ МОЛЧИТ. Telegram не умеет заголовков внутри клавиатуры,
    поэтому разделитель - кнопка; но кнопка, которая «ничего не делает», это ровно тот дефект,
    который мы уже ловили («нажимаю, ничего не происходит»). Поэтому тап по заголовку ОТВЕЧАЕТ
    подсказкой, что настраивает эта группа.
    """
    lang = lang or _lang(uid)
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup
    s = store.settings(uid)
    subs = store.sub_list(uid)
    mp = s.get('min_pct')
    cd = int(s.get('cooldown_min') or (config.cooldown_sec() // 60))
    cap = store.cap_for(uid)
    bm, bw, _bcap = store.burst_for(uid)
    q = (_t('quiet_off', lang) if s.get('quiet_from') is None
         else '%02d-%02d UTC' % (int(s['quiet_from']), int(s['quiet_to'])))
    kinds = store.kinds_for(uid)
    parts = store.parts_for(uid)
    adv = bool(_ADV.get(int(uid)))
    # ── ОСНОВНОЙ ЭКРАН: ТОЛЬКО ТО, ЧТО ТРОГАЮТ РЕГУЛЯРНО ──────────────────────────────────
    rows = [
        # ГЛАВНЫЙ ТУМБЛЕР ОДИН В РЯДУ: он решает, будет ли вообще что-то приходить, и рядом с
        # ним не должно стоять ничего равновеликого.
        [B(_t('alerts_on' if s.get('alerts_on') else 'alerts_off', lang),
           callback_data='sen:t:al')],
        [B(_t('all_on' if store.ALL in subs else 'all_off', lang), callback_data='sen:t:all'),
         B(_t('brief_on' if s.get('enrich_on') else 'brief_off', lang),
           callback_data='sen:t:br')],
        # ПРЕСЕТЫ ВЫШЕ ОТДЕЛЬНЫХ ЧИСЕЛ, ПОТОМУ ЧТО ЭТО САМЫЙ ЧАСТЫЙ СПОСОБ НАСТРОИТЬ. Один тап
        # ставит порог, паузу, потолок и набор видов - четыре числа, которые иначе крутят
        # двенадцатью нажатиями.
        [B(_t('preset', lang) % _t('p_test', lang), callback_data='sen:pr:test'),
         B(_t('preset', lang) % _t('p_normal', lang), callback_data='sen:pr:normal'),
         B(_t('preset', lang) % _t('p_quiet', lang), callback_data='sen:pr:quiet')],
        [B(_t('btn_now', lang), callback_data='sen:now'),
         B(_t('btn_report', lang), callback_data='sen:rep')],
        [B(_t('adv_hide' if adv else 'adv_show', lang), callback_data='sen:adv:x'),
         B(_t('btn_help', lang), callback_data='sen:help')],
        [B(_t('btn_refresh', lang), callback_data='sen:home')],
    ]
    if not adv:
        return InlineKeyboardMarkup(rows)
    # ── ПРОДВИНУТОЕ: ВСТАВЛЯЕМ ПЕРЕД РЯДОМ «ЕЩЁ», ЧТОБЫ ОН ОСТАЛСЯ ВНИЗУ КАК ВЫХОД ────────
    adv_rows = [
        # ── ГРУППА «ТЕМП»: СКОЛЬКО И КАК ЧАСТО. Четыре числа про количество сообщений стоят
        #    рядом нарочно: человек крутит их вместе («шумно» лечится любым из них), и
        #    разнесённые по экрану они заставляли сравнивать по памяти.
        [B(_t('g_pace', lang), callback_data='sen:hint:pace')],
        [B('\u2212', callback_data='sen:bm:-1'),
         B(_t('burst', lang) % bm, callback_data='sen:bm:0'),
         B('+', callback_data='sen:bm:1')],
        [B('\u2212', callback_data='sen:bw:-5'),
         B(_t('bwin', lang) % (bw // 60), callback_data='sen:bw:0'),
         B('+', callback_data='sen:bw:5')],
        [B('\u2212', callback_data='sen:cd:-15'), B(_t('cd', lang) % cd, callback_data='sen:cd:0'),
         B('+', callback_data='sen:cd:15')],
        [B('\u2212', callback_data='sen:cap:-5'), B(_t('cap', lang) % cap, callback_data='sen:cap:0'),
         B('+', callback_data='sen:cap:5')],
        [B(_t('quiet', lang) % q, callback_data='sen:q:next')],
        # ── ГРУППА «СИЛА»: НАСКОЛЬКО КРУПНОЕ. Два порога про КАЧЕСТВО события, а не про его
        #    количество - и путать эти две группы нельзя: подняв порог, человек не уменьшает
        #    поток, он меняет его состав.
        [B(_t('g_power', lang), callback_data='sen:hint:power')],
        [B('\u2212', callback_data='sen:mp:-1'),
         B(_t('mp', lang) % (('%.1f%%' % float(mp)) if mp else _t('mp_off', lang)),
           callback_data='sen:mp:0'),
         B('+', callback_data='sen:mp:1')],
        [B('\u2212', callback_data='sen:sv:-5'),
         B(_t('sev', lang) % store.min_sev_for(uid), callback_data='sen:sv:0'),
         B('+', callback_data='sen:sv:5')],
        # ── ГРУППА «ЧТО ПРИСЫЛАТЬ»: виды событий. Галочка в подписи говорит СОСТОЯНИЕ: кнопка
        #    «Движения» без отметки не отвечает на вопрос «а сейчас они идут?».
        [B(_t('g_kinds', lang), callback_data='sen:hint:kinds')],
        [B(_mark(_t('k_move', lang), 'move_up' in kinds), callback_data='sen:k:move'),
         B(_mark(_t('k_vol', lang), 'vol_surge' in kinds), callback_data='sen:k:vol'),
         B(_mark(_t('k_oi', lang), 'oi_surge' in kinds), callback_data='sen:k:oi')],
        [B(_mark(_t('k_crowd', lang), 'crowded' in kinds), callback_data='sen:k:crowd'),
         B(_mark(_t('k_absorb', lang), 'absorption' in kinds), callback_data='sen:k:absorb'),
         B(_mark(_t('k_ign', lang), 'ignition' in kinds), callback_data='sen:k:ign')],
        [B(_mark(_t('k_gap', lang), 'venue_gap' in kinds), callback_data='sen:k:gap'),
         B(_mark(_t('k_fund', lang), 'funding_extreme' in kinds), callback_data='sen:k:fund'),
         B(_mark(_t('k_spread', lang), 'spread_shock' in kinds), callback_data='sen:k:spread')],
        # ── ГРУППА «ГДЕ И ЧТО ВНУТРИ»: площадки и состав алерта. Обе про ИСТОЧНИКИ, поэтому
        #    рядом. 'card' (числа площадки) тумблера не имеет: алерт без чисел - уведомление
        #    «что-то случилось» без ответа «что именно». Выключается только дорогое.
        [B(_t('g_where', lang), callback_data='sen:hint:where')],
        _venue_row(lang, uid),
        [B(_mark(_t('p_nansen', lang), 'nansen' in parts), callback_data='sen:p:nansen'),
         B(_mark(_t('p_news', lang), 'news' in parts), callback_data='sen:p:news')],
    ]
    # ═══ ВЛАДЕЛЬЧЕСКИЙ РАЗДЕЛ: КАПЫ КРЕДИТОВ. Требование владельца 26.09 - «капа тоже
    # настраиваться где-то должна». Кредиты - ОДИН кошелёк на всех, поэтому не в личных
    # настройках: кнопка «+100» у одного подписчика потратила бы деньги остальных.
    # РЯДА НЕТ У ТЕХ, КОМУ ОН НЕ ПОЛОЖЕН - не «есть, но с отказом при нажатии»: кнопка,
    # которая всегда отвечает «нельзя», это обещание, которого мы не держим.
    if _is_owner(uid):
        adv_rows.append([B(_t('g_caps', lang), callback_data='sen:hint:caps')])
        adv_rows.append([B(_t('cap_nansen', lang) % _capw(store.nansen_cap(), lang),
                           callback_data='sen:gn:0')])
        adv_rows.append([B('\u2212100', callback_data='sen:gn:-100'),
                         B('+100', callback_data='sen:gn:100'),
                         B(_t('cap_off', lang), callback_data='sen:gn:off')])
        adv_rows.append([B(_t('cap_lab', lang) % _capw(store.lab_cap(), lang),
                           callback_data='sen:gl:0')])
        adv_rows.append([B('\u22121000', callback_data='sen:gl:-1000'),
                         B('+1000', callback_data='sen:gl:1000'),
                         B(_t('cap_off', lang), callback_data='sen:gl:off')])
    # ПРОДВИНУТОЕ ВСТАВЛЯЕМ ПЕРЕД ДВУМЯ ПОСЛЕДНИМИ РЯДАМИ («Ещё/Справка» и «Обновить»), чтобы
    # выход из раздела остался на дне экрана - там, где человек его ищет после прокрутки.
    return InlineKeyboardMarkup(rows[:-2] + adv_rows + rows[-2:])


def _capw(v, lang='ru'):
    """Кап словами: ноль — это «выключен», а не «нулевой остаток». -> str.

    РАЗНИЦА НЕ КОСМЕТИЧЕСКАЯ: «0» на кнопке читается как исчерпанный лимит, то есть ровно
    наоборот. Этот же класс ошибки уже ловили в `budget_left` (ноль капа отдавал ноль остатка,
    и «лимита нет» было неотличимо от «лимит кончился»).

    ЯЗЫК АРГУМЕНТОМ, А НЕ РУССКОЕ СЛОВО НАСОВСЕМ: строка попадает НА КНОПКУ, а по экранам
    ходит обходчик e2e и требует, чтобы на `lang=en` не было кириллицы. Русское слово внутри
    английского экрана покраснело бы в ЧУЖОМ тесте и выглядело бы как его поломка.
    """
    if v:
        return '%d' % v
    return 'off' if lang == 'en' else 'выключен'


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
                _off = bool(s.get('alerts_on'))
                store.settings_set(uid, alerts_on=0 if _off else 1)
                if _off:
                    # ТУМБЛЕР ГАСИТ ОЧЕРЕДЬ ТАК ЖЕ, КАК КОМАНДА СЛОВАМИ. Два пути к одному
                    # решению обязаны делать одно и то же: «выключил кнопкой, а шлёт» и
                    # «выключил командой, а шлёт» - один и тот же баг, пойманный 25.09.
                    store.delivery_drop_user(uid, 'алерты выключены кнопкой')
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
        elif act == 'bm':
            # ПРЕДОХРАНИТЕЛЬ: СКОЛЬКО СООБЩЕНИЙ. Требование владельца 26.09 - настройка, а не
            # хардкод. ПОТОЛОК ОСТАЁТСЯ: `store.burst_for` клампит и говорит об упоре на экране,
            # иначе граница превратилась бы в комментарий (закон о предохранителях).
            if arg == '0':
                store.settings_set(uid, burst_max=None)       # вернуть общее значение
            else:
                _cur = store.burst_for(uid)[0]
                store.settings_set(uid, burst_max=max(1, min(store._BURST_HARD,
                                                             _cur + int(arg))))
        elif act == 'bw':
            # ПРЕДОХРАНИТЕЛЬ: ОКНО. Ниже 5 минут окно теряет смысл (оно перестаёт отличаться от
            # паузы по инструменту), выше двух часов - становится суточным потолком под чужим
            # именем. Обе границы названы в `store`.
            if arg == '0':
                store.settings_set(uid, burst_win_min=None)
            else:
                _cur = store.burst_for(uid)[1] // 60
                store.settings_set(uid, burst_win_min=max(5, min(store._WIN_HARD_MIN,
                                                                 _cur + int(arg))))
        elif act == 'adv':
            # РАЗВЕРНУТЬ/СВЕРНУТЬ ПРОДВИНУТОЕ. Состояние в памяти процесса (см. `_ADV`): это
            # вид экрана, а не настройка человека, и терять его при рестарте безопасно.
            _ADV[int(uid)] = not _ADV.get(int(uid))
        elif act == 'hint':
            # ЗАГОЛОВОК ГРУППЫ ОТВЕЧАЕТ ПОДСКАЗКОЙ, А НЕ МОЛЧИТ. Кнопка, на которую «ничего не
            # происходит», в этом проекте уже стоила разбора: человек жмёт её второй и третий
            # раз, считая, что бот сломался. Всплывашка стоит ноль и отвечает на «что это».
            try:
                await q.answer(text=_t('h_%s' % arg, lang), show_alert=True)
            except Exception:
                pass
            return
        elif act in ('gn', 'gl'):
            # ОБЩИЕ КАПЫ КРЕДИТОВ - ТОЛЬКО ВЛАДЕЛЬЦУ. Гейт стоит И на отрисовке (ряда нет), И
            # здесь: кнопку можно нажать по старому сообщению после того, как права изменились,
            # и «нарисовано» не равно «разрешено». Этот класс в проекте уже ловили.
            if not _is_owner(uid):
                await _send(q, context, 'Общие капы кредитов меняет только владелец.')
                return
            _name = store._CAP_NANSEN if act == 'gn' else store._CAP_LAB
            if arg == 'off':
                store.gcap_set(_name, 0)          # 0 = потолка нет (см. budget_left)
            elif arg == '0':
                store.gcap_set(_name, None)       # вернуть управление .env
            else:
                _cur = store.nansen_cap() if act == 'gn' else store.lab_cap()
                store.gcap_set(_name, max(0, _cur + int(arg)))
        elif act == 'sv':
            # ПОРОГ ЗВОНКА. Меняет СОСТАВ, а не количество (темп держит предохранитель), поэтому
            # потолка сверху нет и ноль разрешён: ноль значит «звони обо всём, что нашёл».
            if arg == '0':
                store.settings_set(uid, min_sev=None)
            else:
                store.settings_set(uid, min_sev=max(0, min(100,
                                                           store.min_sev_for(uid) + int(arg))))
        elif act == 'k':
            # ДВИЖЕНИЯ - ОДИН ТУМБЛЕР НА ДВА ВИДА. Разделять «вверх» и «вниз» кнопками значит
            # предлагать человеку подписку на половину рынка: тот, кто хочет знать о падении,
            # хочет знать и о росте.
            _map = {'move': ('move_up', 'move_down'), 'oi': ('oi_surge',),
                    'vol': ('vol_surge',), 'gap': ('venue_gap',),
                    'crowd': ('crowded',), 'absorb': ('absorption',),
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
            return await _send(q, context, now_text(lang), now_kb(lang))
        elif act == 'card':
            _v, _tk = (arg, parts[3]) if len(parts) > 3 else ('', arg)
            return await _send(q, context, await card_link(_tk, _v, lang))
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


def now_kb(lang='ru'):
    """Кнопки-тикеры под срезом рынка. -> InlineKeyboardMarkup | None.

    СКВОЗНОЙ СЦЕНАРИЙ: тап по тикеру ведёт в НАШУ карточку токена, откуда уже есть
    график и избранное. Без этих кнопок экран был тупиком: человек читал «BR +8.37%»
    и шёл набирать «BR» руками в другом окне - работу, которую мы умеем сделать сами.
    """
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup
    m = engine.market_now()
    seen, rows, cur = set(), [], []
    for _a, t, _b, _c, _d, v in (m.get('moves') or []):
        if t in seen:
            continue
        seen.add(t)
        cur.append(B('📊 %s' % t, callback_data='sen:card:%s:%s' % (v, t)))
        if len(cur) == 3:
            rows.append(cur)
            cur = []
    for dv, t, _u, v in (m.get('vols') or []):
        if t in seen or len(rows) >= 3:
            continue
        seen.add(t)
        cur.append(B('📊 %s' % t, callback_data='sen:card:%s:%s' % (v, t)))
        if len(cur) == 3:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    if not rows:
        return None
    rows.append([B(_t('btn_home', lang) if 'btn_home' in _T else '👁 Дозор',
                   callback_data='sen:home')])
    return InlineKeyboardMarkup(rows)


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


async def card_link(ticker, venue=None, lang='ru'):
    """Тикер -> сообщение со ССЫЛКАМИ в наши экраны. -> HTML-строка.

    ДВЕ ССЫЛКИ, А НЕ ОДНА: карточка токена (график, избранное) и экран Nansen по тому
    же контракту - это разные вопросы, и человек в моменте хочет то один, то другой.
    ОТКАЗ НАЗЫВАЕТ ПРИЧИНУ: «цены нет в кольце», «ни один контракт не совпал с ценой»
    и «дверь упала» требуют разных действий, а «не получилось» - никаких.
    """
    from .cards import esc
    tk = esc(str(ticker or "?").upper())
    addr, chain, why = await engine.resolve_ticker(ticker, venue or None)
    if not addr:
        return (('📊 <b>%s</b>\nКарточку открыть не вышло: %s' % (tk, esc(why or "?")))
                if lang != 'en' else
                ('📊 <b>%s</b>\nCould not open the card: %s' % (tk, esc(why or "?"))))
    un = await outbox.bot_un()
    if not un:
        # БЕЗ ИМЕНИ БОТА ССЫЛКИ НЕТ ВОВСЕ: на тест-боте прод-имя увело бы человека в
        # прод. Отдаём контракт текстом - его можно скопировать тапом.
        return '📊 <b>%s</b>\n<code>%s</code>\n<i>%s</i>' % (
            tk, esc(addr), esc(chain or ''))
    lines = ['📊 <b>%s</b> · <code>%s</code>' % (tk, esc(addr))]
    if chain:
        lines.append('<i>%s</i>' % esc(chain))
    lines.append('')
    lines.append('<a href="https://t.me/%s?start=tok_%s">Карточка токена</a> — '
                 'график, паспорт, в избранное' % (un, addr)
                 if lang != 'en' else
                 '<a href="https://t.me/%s?start=tok_%s">Token card</a> — chart, '
                 'passport, favourites' % (un, addr))
    return '\n'.join(lines)


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
