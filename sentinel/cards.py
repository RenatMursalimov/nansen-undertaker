# -*- coding: utf-8 -*-
"""sentinel/cards.py — событие -> текст алерта. ДЕТЕРМИНИРОВАННО, БЕЗ МОДЕЛИ И БЕЗ СЕТИ.

ЧТО ЗДЕСЬ ЗАПРЕЩЕНО ПО ПОСТРОЕНИЮ: вызовы LLM, вызовы сети, обращения к базе. Карточка — это
пересказ уже посчитанных чисел, и собираться она обязана мгновенно: человек торгует руками, и
секунды между «рынок дёрнулся» и «телефон звякнул» — единственное, за что этот модуль отвечает.
Обогащение (Нансен + твиттер + пересказ моделью) приходит ВТОРЫМ сообщением и живёт в
`enrichment.py`.

ПЕРВАЯ СТРОКА ВЕДЁТ ВЕЛИЧИНОЙ, А НЕ ФЛАГОМ. Не «сильное движение по BTC», а «BTC +4.2% за 15
минут». Закон проекта: признак наличия не равен признаку пользы, и человек, читающий алерт с
телефона, должен увидеть ЧИСЛО раньше прилагательного.

БЕЗ MARKDOWN. Отправляем обычным текстом (как `perp_watch`): в тикерах и метках адресов живут
подчёркивания и звёздочки, и разметка ломала бы сообщение ровно на самых интересных строках.

ЧЕГО В КАРТОЧКЕ НЕТ И НЕ БУДЕТ: совета покупать или продавать, целей, «вероятностей». Есть
замеры, названная неуверенность и чек-лист того, что человек проверит сам, прежде чем нажать
на площадке. Дозорный не торгует и не советует торговать.
"""

from . import config

#: ССЫЛКА ТОЛЬКО НА КОРЕНЬ, И ЭТО ЗАМЕР, А НЕ ЛЕНЬ. Пути вида `/trade/BTC` и `/markets/BTC`
#: отвечают 403 (Cloudflare), а `?market=BTC` даёт 200 ровно так же, как и корень без
#: параметра, — то есть 200 не доказывает, что параметр работает: у одностраничного
#: приложения любой query-параметр вернёт 200. Пока прямая ссылка на инструмент НЕ ИЗМЕРЕНА,
#: её не существует; ставить ссылку «по догадке» значит вести человека в никуда в момент,
#: когда он спешит.
VAR_URL = 'https://omni.variational.io/'

_KIND_TITLE = {
    'move_up': '📈 Движение вверх',
    'move_down': '📉 Движение вниз',
    'oi_surge': '🧱 Скачок открытого интереса',
    'funding_extreme': '💸 Ставка в хвосте',
    'spread_shock': '⚠️ Котировка разъехалась',
    'ignition': '🔥 Смарт-зажигание',
}


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


def _age(sec):
    if sec is None:
        return 'возраст не назван'
    s = int(sec)
    return ('%dс' % s) if s < 90 else ('%dмин' % (s // 60))


def confidence_line(ev):
    """Уверенность числом + ПРИЧИНЫ, по которым она не сто.

    Штрафы печатаются ЦЕЛИКОМ, а не «низкая уверенность»: человек решает сам, мешает ли ему
    именно эта причина. «67» без причин — это оценка, которую нельзя оспорить.
    """
    pen = (ev.get('payload') or {}).get('penalties') or []
    head = 'Уверенность: %d/100' % int(ev.get('severity') or 0)
    if not pen:
        return head + ' (штрафов нет)'
    return head + '\n  • ' + '\n  • '.join(str(p) for p in pen)


def _quote_block(p):
    """Что стоит вход РУКАМИ. Именно это человек делает после алерта, поэтому строка есть
    всегда: базовый спред — цена сделки на копейку, а заходят на сумму."""
    lines = []
    if p.get('spread_bps') is not None:
        lines.append('Спред базовый: %.1f б.п.' % p['spread_bps'])
    d100 = p.get('depth_100k_bps')
    if d100 is not None:
        lines.append('Вход на $100k: %.1f б.п. от середины' % d100)
    else:
        lines.append('Вход на $100k: площадка котировку не дала')
    d1m = p.get('depth_1m_bps')
    if d1m is not None:
        lines.append('Вход на $1M: %.1f б.п.' % d1m)
    lines.append('Котировка обновлена: %s назад' % _age(p.get('quote_age_s')))
    return lines


def _market_block(p):
    lines = []
    lines.append('Марк-цена: %s' % _price(p.get('mark')))
    lines.append('Оборот 24ч: %s' % _usd(p.get('volume_24h')))
    oi = (p.get('oi_long') or 0) + (p.get('oi_short') or 0)
    if oi:
        skew = p.get('oi_skew')
        lines.append('Открытый интерес: %s контрактов%s'
                     % ('%.4g' % oi,
                        ('' if skew is None else ', лонгов %.0f%%' % (skew * 100))))
    fr = p.get('funding_raw')
    if fr is not None:
        iv = int(p.get('funding_interval_s') or 0)
        # ЕДИНИЦУ НЕ ЗАЯВЛЯЕМ. Провайдер отдаёт `funding_rate` без единицы, и его же справка
        # противоречит замеру (разбор в шапке `variational_feed`). Печатаем ИМЯ ПОЛЯ и
        # интервал: число, у которого не названа единица, честнее числа с выдуманной.
        lines.append('Фандинг (поле провайдера funding_rate): %.6g%s'
                     % (fr, (', интервал %dч' % (iv // 3600)) if iv >= 3600 else ''))
    return lines


def _checklist(kind, p):
    """ЧЕК-ЛИСТ ПЕРЕД РУЧНЫМ ВХОДОМ. Не совет, а список того, что алерт НЕ проверял.

    Почему он в карточке, а не в документации: человек читает алерт на телефоне за десять
    секунд до нажатия, и «мы про это не знаем» обязано быть рядом с числом, а не в вики.
    """
    out = ['Что алерт НЕ проверял:']
    out.append('• фундаментальную причину движения — новость дозорный не читает')
    if p.get('quote_age_s') is not None and p['quote_age_s'] > config.quote_warn_sec():
        out.append('• цена на площадке может уже отличаться: котировке %s'
                   % _age(p.get('quote_age_s')))
    if kind in ('move_up', 'move_down'):
        out.append('• куда ушёл базовый актив на споте — сверьте, движение это или котировка')
    if kind == 'funding_extreme':
        out.append('• у акций отрицательная ставка бывает дивидендом (справка площадки), '
                   'а не позиционированием')
    if kind == 'ignition':
        out.append('• умный адрес мог купить в чужой сети однофамильца — сверьте контракт')
    out.append('• ваш собственный риск: размер, плечо, запас до ликвидации')
    return out


def card(ev, lang='ru'):
    """Событие -> текст алерта (str). Никогда не пустой: событие без строк — это молчание,
    которое человек прочитает как поломку."""
    p = ev.get('payload') or {}
    kind = ev.get('kind') or '?'
    title = _KIND_TITLE.get(kind, '👁 Дозорный')
    tick = ev.get('ticker') or p.get('symbol') or '?'
    name = p.get('name') or ''
    head = '%s · %s%s' % (title, tick, (' (%s)' % name if name and name != tick else ''))

    lines = [head]
    if kind in ('move_up', 'move_down'):
        mv, win = p.get('move_pct'), p.get('window') or '15м'
        lines.append('%s за %s%s' % (_pct(mv), win,
                                     ('' if p.get('step', 1) <= 1
                                      else ' · ступень %d (движение усилилось)' % p['step'])))
        if p.get('ret15_pct') is not None and p.get('ret60_pct') is not None:
            lines.append('15м %s · 60м %s' % (_pct(p['ret15_pct']), _pct(p['ret60_pct'])))
        if p.get('z') is not None and p.get('sigma_pct'):
            lines.append('Это %.1f сигмы своей 15-минутной волатильности (σ=%.2f%%, %d точек)'
                         % (p['z'], p['sigma_pct'], int(p.get('sigma_points') or 0)))
    elif kind == 'oi_surge':
        lines.append('Открытый интерес %s за час (%s → %s контрактов)'
                     % (_pct(p.get('oi_change_pct')), '%.4g' % (p.get('oi_then') or 0),
                        '%.4g' % (p.get('oi_now') or 0)))
        if p.get('ret60_pct') is not None:
            lines.append('Цена за тот же час: %s' % _pct(p['ret60_pct']))
    elif kind == 'funding_extreme':
        rank = p.get('funding_rank')
        lines.append('Ставка в %s своего распределения за кольцо (%d замеров)'
                     % (('верхних %.0f%%' % ((1 - rank) * 100)) if rank and rank > 0.5
                        else ('нижних %.0f%%' % (rank * 100 if rank else 0)),
                        int(p.get('funding_points') or 0)))
    elif kind == 'spread_shock':
        lines.append('Спред %.1f б.п. — это ×%.1f к своей медиане (%.1f б.п.)'
                     % (p.get('spread_bps') or 0, p.get('spread_mult') or 0,
                        p.get('spread_median_bps') or 0))
        lines.append('Это ПРЕДОСТЕРЕЖЕНИЕ, а не сигнал: заходить руками стало дороже.')
    elif kind == 'ignition':
        lines.append('%d разных адреса смарт-денег купили %s на %s за %d мин'
                     % (int(p.get('wallets') or 0), p.get('symbol') or '?',
                        _usd(p.get('usd')), int(p.get('window_min') or 0)))
        if p.get('mcap_bps') is not None:
            lines.append('Это %.2f%% капитализации (%s)'
                         % (p['mcap_bps'] / 100.0, _usd(p.get('mcap'))))
        else:
            lines.append('Долю от капитализации проверить не вышло: провайдер её не дал')
        if p.get('labels'):
            lines.append('Метки адресов: %s' % ', '.join(p['labels'][:5]))
        if p.get('age_days') is not None:
            lines.append('Возраст токена: %.1f дн' % p['age_days'])
        lines.append('Сеть: %s · контракт %s' % (p.get('chain') or '?', p.get('address') or '?'))

    if kind != 'ignition':
        lines.append('')
        lines += _market_block(p)
        lines += _quote_block(p)
    lines.append('')
    lines.append(confidence_line(ev))
    lines.append('')
    lines += _checklist(kind, p)
    lines.append('')
    # ИСТОЧНИК НАЗЫВАЕМ ВСЕГДА, И РАЗНЫЙ ДЛЯ РАЗНЫХ СОБЫТИЙ: половина карточек собрана из
    # публичной ручки площадки (без ключа, бесплатно), половина — из Nansen (за кредиты).
    # Человек, читающий алерт, должен знать, кто это сказал.
    if kind == 'ignition':
        lines.append('Источник: Nansen smart-money/dex-trades · ' + VAR_URL)
    else:
        lines.append('Источник: Variational Omni, публичная ручка /metadata/stats · ' + VAR_URL)
    return '\n'.join(lines)


def enrich_card(ev, brief, lang='ru'):
    """ВТОРОЕ сообщение: сводка вокруг события. -> str.

    Отдельным сообщением, а не дописыванием в первое: правка уже отправленного сообщения
    незаметна (телефон не звякнет второй раз), а ждать сводку внутри первого значило бы
    задержать цену на секунды ради слов.
    """
    tick = ev.get('ticker') or '?'
    out = ['🧭 Сводка по %s (к алерту выше)' % tick]
    if brief.get('lines'):
        out += list(brief['lines'])
    if brief.get('refused'):
        # ОТКАЗ НАЗЫВАЕТ КЛАСС, А НЕ «НЕ УДАЛОСЬ». «Нет кредитов», «площадка молчит» и
        # «тикер не сопоставлен контракту» требуют РАЗНЫХ действий от человека.
        out.append('Чего не собрали: %s' % brief['refused'])
    if brief.get('summary'):
        out.append('')
        out.append('Пересказ моделью (не данные, а пересказ данных выше):')
        out.append(brief['summary'])
    if brief.get('cost_line'):
        out.append('')
        out.append(brief['cost_line'])
    return '\n'.join(out)
