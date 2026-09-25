# -*- coding: utf-8 -*-
"""sentinel/detector.py — ЧИСЛА И ТОЛЬКО ЧИСЛА: из кольца снимков -> список событий.

ЧИСТЫЕ ФУНКЦИИ БЕЗ БАЗЫ, БЕЗ СЕТИ, БЕЗ ТЕЛЕГРАМА. Здесь нет ни одного `import db`, ни одного
запроса — на входе история инструмента и текущий снимок, на выходе список словарей. Причина
не в эстетике: детектор — единственное место, где решается «событие или нет», и проверять это
надо ТЕСТОМ на синтетическом ряду, а не живым рынком. Тест, который ждёт живого выброса,
никогда не краснеет и ничего не доказывает.

ЧЕТЫРЕ ВИДА СОБЫТИЙ, И У КАЖДОГО СВОЯ ПРИЧИНА СУЩЕСТВОВАТЬ
  move_up/move_down — цена ушла И ушла НЕОБЫЧНО ДЛЯ СЕБЯ (процент + сигма);
  oi_surge          — открытый интерес прыгнул: в позицию заходят, даже если цена стоит;
  funding_extreme   — ставка ушла в свой же хвост: за движение платят, и дорого;
  spread_shock      — котировка разъехалась: заходить руками стало дорого, это ПРЕДОСТЕРЕЖЕНИЕ,
                      а не приглашение, и в карточке оно так и названо.

ПОРОГ ПРОЦЕНТА БЕЗ СИГМЫ — ЭТО СПАМ, СИГМА БЕЗ ПРОЦЕНТА — ЭТО ШУМ
3% по MSTR и 3% по низколиквидному альту это события разной редкости; один общий процент
либо завалит человека альтами, либо не заметит акции. Поэтому «движение» = процент ВЫШЕ
порога И не меньше N сигм своей же 15-минутной волатильности. Сигма считается по НАШИМ
снимкам того же инструмента — то есть порог подстраивается сам, и таблицы «у кого какой
порог» не существует.

ЕДИНИЦА ФАНДИНГА НЕ ЗАЯВЛЕНА ПРОВАЙДЕРОМ (см. шапку `variational_feed`), поэтому порог по
фандингу здесь НЕ АБСОЛЮТНЫЙ, а проценти́льный: сравниваем инструмент с САМИМ СОБОЙ за
кольцо. Критерий, не зависящий от единицы, — единственный честный, пока единица не измерена.

ПОВТОРНОЕ СОБЫТИЕ И УСИЛЕНИЕ — РАЗНЫЕ ВЕЩИ. Одно движение живёт минутами и попадает в
десятки тиков; ключ события (`key`) поэтому содержит ОКНО и СТУПЕНЬ силы: 3% дают ступень 1,
6% по тому же порогу — ступень 2, и это НОВОЕ событие, потому что человеку важно узнать, что
движение удвоилось. Между ступенями стоит пауза подписчика, так что «удвоилось» не может
превратиться в поток.
"""

import hashlib
import math

from . import config

#: Окна, по которым считаем доходность. Не «одно универсальное»: 15 минут ловит выброс,
#: 60 минут отличает выброс от тренда, и обе цифры едут в карточку вместе.
W15, W60 = 900, 3600

#: Насколько снимок может отстоять от идеальной точки окна. Опрос идёт раз в 15с, поэтому
#: 180с — это до 12 пропущенных тиков: столько мы прощаем сетевому сбою. Дальше окно
#: объявляется НЕДОСТУПНЫМ (а не «0%»): отсутствие замера не равно отсутствию движения.
TOL = 180

KINDS = ('move_up', 'move_down', 'oi_surge', 'vol_surge', 'funding_extreme',
         'spread_shock', 'ignition', 'venue_gap', 'crowded', 'absorption')


# ── ЭЛЕМЕНТАРНАЯ АРИФМЕТИКА, ВЫНЕСЕННАЯ РАДИ ОДНОГО: ДЕЛЕНИЯ НА НОЛЬ ──────────────────────
def pct(a, b):
    """Изменение от b к a в процентах. -> float | None, если базы нет.

    None, А НЕ 0.0. Ноль означает «не изменилось» — утверждение о рынке; отсутствие базы это
    утверждение о наших данных. Смешать их значит однажды отправить «0.0%» вместо молчания.
    """
    if a is None or b in (None, 0):
        return None
    try:
        return (float(a) - float(b)) / abs(float(b)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def at(rows, target_ts, tol=TOL):
    """Снимок, ближайший к моменту. -> (ts, mark, …) | None. rows отсортированы по ts."""
    best, bestd = None, None
    for r in rows:
        d = abs(int(r[0]) - int(target_ts))
        if bestd is None or d < bestd:
            best, bestd = r, d
    if best is None or bestd is None or bestd > tol:
        return None
    return best


def buckets(rows, step=W15):
    """Ряд, прореженный до одного значения на окно. -> [(bucket_index, mark)].

    ЗАЧЕМ ПРОРЕЖИВАТЬ. Сигма по снимкам раз в 15 секунд измеряет дрожание котировки маркет-
    мейкера, а не волатильность рынка, и была бы в разы меньше настоящей — то есть любое
    движение получало бы «двадцать сигм». Считаем по тем же 15 минутам, по которым ловим
    движение: порог и мерка обязаны быть в одних единицах.
    """
    out = {}
    for r in rows:
        if r[1] is None:
            continue
        out[int(r[0]) // step] = float(r[1])
    return sorted(out.items())


def sigma_pct(rows, step=W15):
    """Сигма 15-минутных доходностей инструмента, %. -> (sigma, сколько точек).

    ВОЗВРАЩАЕТ И РАЗМЕР ВЫБОРКИ. Сигма 0.4% по трём точкам и по двухсотам — разные числа с
    одинаковым видом; решение «публиковать ли по z» принимает вызывающий, и он должен видеть
    ОБА (закон «признак наличия не равен признаку пользы»).
    """
    bs = buckets(rows, step)
    rets = []
    for i in range(1, len(bs)):
        b0, v0 = bs[i - 1]
        b1, v1 = bs[i]
        if b1 - b0 != 1:
            continue          # разрыв в опросе: «доходность» через дыру измеряет дыру
        p = pct(v1, v0)
        if p is not None:
            rets.append(p)
    n = len(rets)
    if n < 2:
        return None, n
    mean = sum(rets) / n
    var = sum((x - mean) ** 2 for x in rets) / (n - 1)
    return math.sqrt(var), n


def tail_share(values, x):
    """Насколько x в хвосте СВОЕГО распределения. -> (доля строго ниже, доля строго выше).

    СТРОГИЕ СРАВНЕНИЯ, И ЭТО НЕ ПРИДИРКА К ЗНАКУ. Первая редакция считала «доля значений НЕ
    БОЛЬШЕ x» и на ПОСТОЯННОМ ряде давала 1.0 — то есть на инструменте, у которого ставка не
    менялась вовсе, дозорный на КАЖДОМ тике объявлял «ставка в верхнем хвосте». Дефект поймал
    тест (`t_detector_needs_both_percent_and_sigma` увидел `funding_extreme` там, где ждал
    только движение цены), и он ровно того сорта, что в проекте называют тихим: события
    печатались исправно, а означали они «ничего не произошло».

    Возвращаем ДВЕ доли, а не одну: «выше всех» и «ниже всех» — разные новости, и считать
    вторую как `1 - первая` неверно при повторяющихся значениях.
    """
    vals = [float(v) for v in values if v is not None]
    if not vals or x is None:
        return None, None
    n = float(len(vals))
    x = float(x)
    return (sum(1 for v in vals if v < x) / n, sum(1 for v in vals if v > x) / n)


def median(values):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    m = len(vals) // 2
    return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2.0


# ── УВЕРЕННОСТЬ: НАЧИНАЕМ СО СТА И ВЫЧИТАЕМ ПО НАЗВАННОЙ ПРИЧИНЕ ──────────────────────────
def confidence(base, penalties):
    """-> (0..100, [строки штрафов]).

    ПОЧЕМУ ОТ СТА ВНИЗ, А НЕ ОТ НУЛЯ ВВЕРХ. Прибавлять баллы «за хорошее» — это оценка,
    которую нельзя оспорить: неясно, чего в ней не хватает. Вычитание же НАЗЫВАЕТ дефект
    словами, и человек видит не «67», а «67, потому что котировка старше двух минут и
    ёмкость на $100k тонкая». Список штрафов едет в карточку целиком.
    """
    score = float(base)
    lines = []
    for why, cost in penalties:
        if cost:
            score -= float(cost)
            lines.append('%s (-%d)' % (why, int(cost)))
        else:
            # ПРИЧИНА БЕЗ ЦЕНЫ - ЭТО ПОЯСНЕНИЕ, А НЕ ШТРАФ. «(-0)» рядом с текстом читается как
            # ошибка счёта, поэтому ноль печатается молча: строка есть, вычета нет.
            lines.append(str(why))
    return max(0, min(100, int(round(score)))), lines


def _quote_penalties(listing, now):
    """Штрафы, НЕ зависящие от вида события: свежесть котировки и ёмкость. -> [(текст, цена)].

    ═══ «ПЛОЩАДКА ЭТОГО НЕ ОТДАЁТ» - НЕ ДЕФЕКТ СОБЫТИЯ ═══
    ЖИВОЙ ПРОГОН 25.09: карточки с Hyperliquid приходили с уверенностью 40/100 и тремя
    штрафами подряд - «возраст котировки провайдер не назвал (-15)», «котировки на $100k нет
    (-10)», «провайдер не дал: oi_long/oi_short, quotes (-10)». Все три про ОДНО И ТО ЖЕ: у
    этой площадки таких полей нет ВООБЩЕ. То есть мы наказывали событие за свойство
    источника, и сильное движение на самой ликвидной площадке выглядело сомнительным.
    ПРАВИЛО: чего площадка не отдаёт НИКОГДА (перечислено в `missing`), то НАЗЫВАЕТСЯ одной
    строкой без штрафа. Штраф остаётся там, где поле есть, но ПЛОХОЕ: котировка старая,
    вход дорогой. Разница принципиальная - «не измерено» и «измерено и плохо» ведут к разным
    решениям, и складывать их в одну цифру значит терять оба.
    """
    out = []
    miss = set(listing.missing or ())
    not_measured = []
    age = listing.quote_age(now)
    if age is None:
        if 'quotes' in miss:
            not_measured.append('возраст котировки')
        else:
            out.append(('возраст котировки провайдер не назвал', 15))
    elif age > config.quote_warn_sec():
        out.append(('котировка старше %ds (возраст %ds)'
                    % (int(config.quote_warn_sec()), int(age)), 20))
    d100 = listing.depth_bps('size_100k')
    if d100 is None:
        if 'quotes' in miss:
            not_measured.append('ёмкость на $100k')
        else:
            out.append(('котировки на $100k нет', 10))
    elif d100 > 50:
        out.append(('вход на $100k стоит %.0f б.п.' % d100, 15))
    if listing.oi_long is None and listing.oi_short is None and listing.oi_total is not None:
        not_measured.append('перекос лонгов и шортов')
    if not_measured:
        # ОДНОЙ СТРОКОЙ И БЕЗ ЦЕНЫ: человек должен знать, чего в карточке нет и почему, но
        # платить уверенностью за выбор площадки событие не обязано.
        out.append(('%s не отдаёт: %s' % (_venue_name(listing),
                                          ', '.join(not_measured)), 0))
    return out


def _venue_name(listing):
    try:
        from .venues import title
        return title(getattr(listing, 'venue', 'variational'))
    except Exception:
        return 'площадка'

def digest_key(*parts):
    """Стабильный короткий ключ из частей. -> 24 символа hex.

    ОДНА ДВЕРЬ НА ВСЕ КЛЮЧИ ДОЗОРНОГО, и лежит она здесь - в модуле без базы и без сети.
    Первая редакция держала её в `store`, и живое доказательство падало с «DB_BACKEND не
    задан»: путь «разобрать ответ площадки и собрать карточку» не должен требовать базы.

    ВОЗВРАЩЕНА ПОСЛЕ СВОЕГО ЖЕ ИСЧЕЗНОВЕНИЯ: широкая замена блока штрафов (круг 6) вырезала
    её вместе с соседями, и `store` упал на реэкспорте - ImportError на ИМПОРТЕ пакета, то
    есть дозорный не поднялся бы вовсе. Урок записан рядом с функцией: заменять НАДО по
    точным границам одной функции, а не «от сих до следующего def» - между ними живут соседи.
    """
    raw = '|'.join('' if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def key(kind, ticker, window_start, step):
    """КЛЮЧ СОБЫТИЯ. Один и тот же выброс обязан дать один и тот же ключ в любом процессе.

    В ключе НЕТ ни времени с точностью до секунды, ни самой величины: и то и другое меняется
    на каждом тике, и дедупликация превратилась бы в её отсутствие — двадцать «алертов» на
    одно движение. В ключе есть ОКНО (частное от паузы подписчика) и СТУПЕНЬ силы.
    """
    return digest_key('sentinel', kind, (ticker or '').upper(), int(window_start), int(step))


def _step(value, threshold):
    """Ступень силы: во сколько порогов уложилась величина. 3% при пороге 3 -> 1, 6% -> 2."""
    if not threshold:
        return 1
    return max(1, int(abs(float(value)) // float(threshold)))


def _window(ts):
    """Номер окна дедупликации. Совпадает с паузой подписчика — чтобы «новое событие» и
    «можно снова писать» не разъезжались на порядок."""
    return int(ts) // max(300, int(config.cooldown_sec()))


def cross_venue(listings, now=None):
    """Один актив на РАЗНЫХ площадках -> события расхождения цены. ЧИСТАЯ функция.

    ЗАЧЕМ ЭТО ЗДЕСЬ, А НЕ В ОБЩЕМ `detect`. `detect` смотрит на ОДИН инструмент и его
    историю; расхождение живёт МЕЖДУ инструментами и требует всего среза сразу. Впихнуть
    его в `detect` значило бы передавать туда весь рынок ради одной проверки - и все
    остальные виды начали бы зависеть от того, что происходит с чужими тикерами.

    ТИКЕРЫ СРАВНИВАЕМ ТОЛЬКО ОДИНАКОВЫЕ И ТОЛЬКО ЖИВЫЕ. «BTC» и «BTC» - один актив на двух
    площадках; «US» на Variational это токен Talus, и никакого «US» на Hyperliquid с тем же
    смыслом может не быть - поэтому пары строятся по точному совпадению тикера, а не по
    похожести, и обе стороны обязаны иметь оборот (расхождение с мёртвым рынком - это
    отсутствие рынка, а не возможность).
    """
    import time as _t
    now = int(now if now is not None else _t.time())
    from . import config as _c
    by = {}
    for x in listings or ():
        if not x.mark or (x.volume_24h or 0) < _c.gap_min_usd():
            continue
        by.setdefault(str(x.ticker).upper(), []).append(x)
    out = []
    for tick, group in by.items():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda z: z.mark)
        lo, hi = group[0], group[-1]
        if lo.venue == hi.venue or not lo.mark:
            continue
        gap = (hi.mark - lo.mark) / lo.mark * 10000.0
        if gap < _c.gap_bps():
            continue
        pen = []
        # ЧЕСТНАЯ ОГОВОРКА: часть расхождения съедает спред на обеих сторонах. Не сказать
        # этого значит показать «возможность», которой после издержек может не быть.
        cost = (lo.depth_bps("size_100k") or lo.spread_bps or 0) + \
               (hi.depth_bps("size_100k") or hi.spread_bps or 0)
        if cost >= gap:
            pen.append(('вход на обеих сторонах стоит %.0f б.п. - больше самого расхождения'
                        % cost, 40))
        elif cost > 0:
            pen.append(('вход на обеих сторонах стоит %.0f б.п.' % cost, 10))
        for z in (lo, hi):
            age = z.quote_age(now)
            if age is not None and age > _c.quote_warn_sec():
                pen.append(('котировка %s старше %ds' % (z.venue, int(age)), 15))
        conf, notes = confidence(90, pen)
        step = _step(gap, _c.gap_bps())
        out.append({'kind': 'venue_gap', 'ticker': tick, 'ts': now,
                    'key': key('venue_gap', tick, _window(now), step),
                    'severity': conf,
                    'payload': {'ticker': tick, 'venue': hi.venue, 'mark': hi.mark,
                                'gap_bps': gap, 'cheap_venue': lo.venue,
                                'cheap_mark': lo.mark, 'rich_venue': hi.venue,
                                'rich_mark': hi.mark, 'cost_bps': cost,
                                'volume_24h': min(lo.volume_24h or 0, hi.volume_24h or 0),
                                'step': step, 'penalties': notes}})
    return out


def detect(listing, rows, now=None, ring=None):
    """Один инструмент -> список событий (может быть пустым).

    `rows`  — история из `store.history` (по возрастанию ts), ВКЛЮЧАЯ текущий снимок;
    `ring`  — та же история за всё кольцо, если она длиннее `rows` (для процентилей);
    `now`   — момент оценки (тесты передают свой).

    НИЧЕГО НЕ ПИШЕТ И НИЧЕГО НЕ ОТПРАВЛЯЕТ. Событие здесь — это описание замера, а не
    решение «сказать человеку»: кому и когда говорить, решает `engine` по подпискам, паузе
    и суточному потолку.
    """
    import time as _t
    now = int(now if now is not None else _t.time())
    ring = ring if ring is not None else rows
    out = []
    if listing.mark is None:
        return out
    # ОБОРОТ - ПОРОГ ВХОДА В ДОЗОР, А НЕ ФИЛЬТР ВКУСА. По инструменту без оборота «движение
    # марк-цены» это движение котировки одного маркет-мейкера, и говорить о рынке нечего.
    if (listing.volume_24h or 0) < config.min_volume_usd():
        return out

    r15 = at(rows, now - W15)
    r60 = at(rows, now - W60)
    p15 = pct(listing.mark, r15[1]) if r15 else None
    p60 = pct(listing.mark, r60[1]) if r60 else None
    sig, npts = sigma_pct(ring)
    z = None
    if p15 is not None and sig and sig > 0:
        z = p15 / sig
    # СИГМА, ИЗМЕРЕННАЯ НУЛЁМ, — ЭТО НЕ «БЕСКОНЕЧНАЯ НЕОБЫЧНОСТЬ». Тест поймал вторую половину
    # того же дефекта: на идеально ровном ряде `sig == 0`, порог в сигмах становился
    # невычислимым, и ветка движения замолкала СОВСЕМ — 4% за 15 минут не публиковались вовсе.
    # Делить на ноль тоже нельзя: нулевая сигма чаще означает, что провайдер повторял одно и то
    # же число (замер 25.09: `quotes.updated_at` отстаёт на 20-90с), а не что рынок стоял. Ниже
    # такой ряд идёт по той же дороге, что короткая выборка: событие публикуется, порог в сигмах
    # объявляется неприменимым, уверенность за это платит.
    sigma_usable = bool(sig and sig > 0 and npts >= config.sigma_min_points())

    base_pen = _quote_penalties(listing, now)
    # ПЛОЩАДКА ЕДЕТ В КАЖДОМ СОБЫТИИ. Без неё карточка «BTC +2%» не отвечает на вопрос
    # «где именно», а он первый: цена, спред и фандинг у двух площадок разные, и заходить
    # человек будет на одной конкретной.
    _venue = getattr(listing, 'venue', 'variational') or 'variational'
    common = {'ticker': listing.ticker, 'name': listing.name, 'mark': listing.mark,
              'venue': _venue,
              'volume_24h': listing.volume_24h, 'oi_long': listing.oi_long,
              'oi_short': listing.oi_short, 'oi_skew': listing.oi_skew,
              'funding_raw': listing.funding_raw,
              'funding_interval_s': listing.funding_interval_s,
              'spread_bps': listing.spread_bps,
              'depth_100k_bps': listing.depth_bps('size_100k'),
              'depth_1m_bps': listing.depth_bps('size_1m'),
              'quote_age_s': listing.quote_age(now),
              'ret15_pct': p15, 'ret60_pct': p60, 'sigma_pct': sig, 'sigma_points': npts,
              'z': z, 'missing': list(listing.missing)}

    # ── ДВИЖЕНИЕ ЦЕНЫ ─────────────────────────────────────────────────────────────────────
    mv, thr, why = None, None, None
    if p15 is not None and abs(p15) >= config.move_pct_15m():
        # СИГМА ОБЯЗАТЕЛЬНА, НО ТОЛЬКО ЕСЛИ ОНА ИЗМЕРЕНА. Выборки меньше `sigma_min_points`
        # не хватает даже на порядок величины: её сигма — случайное число, и «z=40» на ней
        # означает лишь то, что процесс недавно запущен.
        if sigma_usable:
            if z is not None and abs(z) >= config.z_min():
                mv, thr, why = p15, config.move_pct_15m(), '15м'
        else:
            mv, thr, why = p15, config.move_pct_15m(), '15м'
    if mv is None and p60 is not None and abs(p60) >= config.move_pct_60m():
        mv, thr, why = p60, config.move_pct_60m(), '60м'
    if mv is not None:
        pen = list(base_pen)
        if npts < config.sigma_min_points():
            pen.append(('сигма по %d точкам - мало для порога в сигмах' % npts, 25))
        elif not sigma_usable:
            pen.append(('сигма измерена нулём на %d точках - ряд не двигался, порог в сигмах '
                        'неприменим' % npts, 25))
        elif z is not None and abs(z) < config.z_min():
            pen.append(('движение внутри обычного разброса (z=%.1f)' % z, 20))
        if (listing.volume_24h or 0) < config.min_volume_usd() * 10:
            pen.append(('оборот за сутки всего $%.0fk' % ((listing.volume_24h or 0) / 1000), 10))
        conf, notes = confidence(100, pen)
        kind = 'move_up' if mv > 0 else 'move_down'
        step = _step(mv, thr)
        out.append({'kind': kind, 'ticker': listing.ticker, 'ts': now,
                    'key': key(kind, '%s:%s' % (_venue, listing.ticker), _window(now), step),
                    'severity': conf,
                    'payload': dict(common, window=why, move_pct=mv, threshold_pct=thr,
                                    step=step, penalties=notes)})

    # ── ОТКРЫТЫЙ ИНТЕРЕС ──────────────────────────────────────────────────────────────────
    oi_now = listing.oi_total
    if oi_now and r60 is not None:
        oi_then = (r60[3] or 0) + (r60[4] or 0)
        d_oi = pct(oi_now, oi_then if oi_then else None)
        # СКАЧОК В ДЕНЬГАХ, А НЕ ТОЛЬКО В ПРОЦЕНТАХ. +20% к интересу, которого было на $30k, -
        # это $6k: арифметика та же, смысла нет. Интерес площадка отдаёт В КОНТРАКТАХ, поэтому
        # переводим марк-ценой; без цены проверку не выдумываем, а пропускаем событие (иначе
        # «денег много» решалось бы догадкой).
        d_usd = abs(oi_now - oi_then) * (listing.mark or 0)
        if (d_oi is not None and abs(d_oi) >= config.oi_pct()
                and d_usd >= config.oi_min_usd()):
            pen = list(base_pen)
            if oi_then and oi_then * (listing.mark or 0) < config.min_volume_usd():
                pen.append(('час назад интереса почти не было - процент считается от малого',
                            20))
            conf, notes = confidence(90, pen)
            step = _step(d_oi, config.oi_pct())
            out.append({'kind': 'oi_surge', 'ticker': listing.ticker, 'ts': now,
                        'key': key('oi_surge', '%s:%s' % (_venue, listing.ticker), _window(now), step),
                        'severity': conf,
                        'payload': dict(common, oi_change_pct=d_oi, oi_then=oi_then,
                                        oi_now=oi_now, oi_change_usd=d_usd, step=step,
                                        penalties=notes)})

    # ── ОБОРОТ: ДЕНЬГИ ПРИХОДЯТ РАНЬШЕ, ЧЕМ ДВИГАЕТСЯ ЦЕНА ────────────────────────────────
    # ЗАМЕР 25.09 объясняет, зачем этот вид вообще нужен: марк-цена на площадке стоит минутами
    # (за три минуты ни один из 553 инструментов её не изменил), а оборот растёт непрерывно.
    # То есть по цене мы узнаём о приходе денег ПОЗЖЕ, чем по объёму. Просьба владельца -
    # «или просто алерты по объёму» - совпала с тем, что показывает рынок.
    if listing.volume_24h and r60 is not None:
        v_then = r60[2]
        d_vol = pct(listing.volume_24h, v_then if v_then else None)
        d_vusd = (listing.volume_24h - (v_then or 0))
        if (d_vol is not None and d_vol >= config.vol_pct()
                and d_vusd >= config.vol_min_usd()):
            pen = list(base_pen)
            if p60 is None:
                pen.append(('движение цены за тот же час не измерено', 10))
            conf, notes = confidence(85, pen)
            step = _step(d_vol, config.vol_pct())
            out.append({'kind': 'vol_surge', 'ticker': listing.ticker, 'ts': now,
                        'key': key('vol_surge', '%s:%s' % (_venue, listing.ticker), _window(now), step),
                        'severity': conf,
                        'payload': dict(common, vol_change_pct=d_vol, vol_then=v_then,
                                        vol_change_usd=d_vusd, step=step, penalties=notes)})

    # ── ФАНДИНГ: ХВОСТ СВОЕГО ЖЕ РАСПРЕДЕЛЕНИЯ ────────────────────────────────────────────
    if listing.funding_raw is not None and len(ring) >= config.sigma_min_points():
        hist = [r[5] for r in ring if r[5] is not None]
        below, above = tail_share(hist, listing.funding_raw)
        # ХВОСТ СЧИТАЕМ СТРОГО: «выше 98% замеров» или «ниже 98% замеров». Постоянный ряд даёт
        # обе доли нулём и события НЕ порождает — именно этого не делала первая редакция.
        rank = below
        # ═══ АБСОЛЮТНЫЙ ПОРОГ РЯДОМ С ОТНОСИТЕЛЬНЫМ. ТЕПЕРЬ ОН ВОЗМОЖЕН ═══
        # `config.funding_apr_pct()` (60% годовых) был объявлен девять кругов назад и НИ ОДНИМ
        # читателем не читался - мёртвый порог, форма «параметр принят, но не применён». Причина
        # была честной: единица фандинга не измерена, и сравнивать сырое поле с «60% годовых»
        # было не с чем. Долг №1 закрыт замером 26.09 (`venues.FUNDING_UNIT`), и порог ожил.
        # ЗАЧЕМ ОН ЗДЕСЬ. Проценти́ль отвечает «необычно ли это ДЛЯ НЕГО», но не отвечает
        # «дорого ли это». У инструмента с вечно нулевой ставкой 0.3% годовых попадают в верхний
        # процентиль - арифметика верна, новости нет. Ровно тот же закон, что уже заставил
        # поставить абсолютные пороги рядом со спредом, объёмом и открытым интересом.
        # ЕДИНИЦА НЕИЗВЕСТНА -> ПОРОГ НЕ ПРИМЕНЯЕМ, а не считаем нулём: у новой площадки мы
        # ничего не мерили, и молча отсечь ей все события было бы хуже, чем пропустить шум.
        _apr = None
        try:
            from .venues import funding_apr_pct as _fapr
            _apr = _fapr(_venue, listing.funding_raw, listing.funding_interval_s)
        except Exception:
            _apr = None
        _apr_ok = (_apr is None) or (abs(_apr) >= config.funding_apr_pct())
        if (below is not None and max(below, above) >= 0.98 and len(hist) >= 50 and _apr_ok):
            pen = list(base_pen)
            if _apr is None:
                # ЧЕГО НЕ ИЗМЕРИЛИ - ГОВОРИМ ВСЛУХ И ШТРАФУЕМ УВЕРЕННОСТЬ, а не замалчиваем.
                pen.append(('единица фандинга этой площадки не измерена - абсолютную величину '
                            'проверить нечем', 15))
            # ДИВИДЕНД ВЫГЛЯДИТ КАК ПОЗИЦИОНИРОВАНИЕ, И ЭТО НЕ НАША ДОГАДКА: справка
            # площадки (help.variational.io/en/articles/16038446) прямо говорит, что около
            # даты отсечки дивиденд проводится ОТРИЦАТЕЛЬНЫМ фандингом. Значит по акциям
            # хвост ставки может не иметь никакого отношения к рынку, и карточка обязана
            # сказать это сама, а не позволить человеку прочитать «шорты платят лонгам».
            from .variational_feed import asset_class
            if asset_class(listing) in ('equity', 'fund') and (listing.funding_raw or 0) < 0:
                pen.append(('у акций отрицательная ставка бывает дивидендом, а не позиционированием',
                            30))
            conf, notes = confidence(80, pen)
            out.append({'kind': 'funding_extreme', 'ticker': listing.ticker, 'ts': now,
                        'key': key('funding_extreme', '%s:%s' % (_venue, listing.ticker), _window(now), 1),
                        'severity': conf,
                        'payload': dict(common, funding_rank=rank, funding_apr_pct=_apr,
                                        funding_points=len(hist), step=1, penalties=notes)})

    # ── ТЕСНАЯ ТОЛПА: ВСЕ В ОДНУ СТОРОНУ И ДОРОГО ПЛАТЯТ ──────────────────────────────────
    # Роудмап, шаг 2, пункт 2. Сигнал описывает КОНСТРУКЦИЮ рынка, а не направление: когда
    # почти весь интерес в одной стороне и за него платят по верхнему проценти́лю ставки,
    # каскад ликвидаций идёт против толпы. Оба условия обязательны: перекос без платы бывает
    # структурным (кто-то хеджирует спот), и алерт на него один был бы алертом на устройство
    # рынка, а не на событие.
    skew = listing.oi_skew
    if skew is not None and listing.funding_raw is not None and len(ring) >= 50:
        side = max(skew, 1.0 - skew)
        hist_f = [r[5] for r in ring if r[5] is not None]
        below_f, above_f = tail_share(hist_f, listing.funding_raw)
        # ПЛАТИТ ИМЕННО БОЛЬШИНСТВО: лонги платят при высокой ставке, шорты - при низкой.
        pays = (below_f if skew > 0.5 else above_f)
        if (side >= config.crowd_skew() and pays is not None
                and pays >= config.crowd_funding_rank() and len(hist_f) >= 50):
            pen = list(base_pen)
            if (listing.volume_24h or 0) < config.min_volume_usd() * 10:
                pen.append(('оборот за сутки всего $%.0fk - выносить особо некого'
                            % ((listing.volume_24h or 0) / 1000), 20))
            conf, notes = confidence(85, pen)
            out.append({'kind': 'crowded', 'ticker': listing.ticker, 'ts': now,
                        'key': key('crowded', '%s:%s' % (_venue, listing.ticker),
                                   _window(now), 1),
                        'severity': conf,
                        'payload': dict(common, crowd_side=('лонги' if skew > 0.5 else 'шорты'),
                                        crowd_pct=side * 100.0, funding_rank=pays,
                                        step=1, penalties=notes)})

    # ── ПОГЛОЩЕНИЕ: ИНТЕРЕС РАСТЁТ, ЦЕНА СТОИТ ────────────────────────────────────────────
    # Роудмап, шаг 2, пункт 3. Единственный наш сигнал, который срабатывает на ОТСУТСТВИИ
    # хода цены: кто-то набирает против потока, и его пока хватает. Видно ДО движения - в
    # этом вся ценность, и в этом же слабость: подтверждения направления здесь нет, и
    # карточка обязана сказать это прямо, а не намекать на рост.
    if oi_now and r60 is not None and p60 is not None:
        oi_then_a = (r60[3] or 0) + (r60[4] or 0) or (r60[3] if r60[3] else None)
        d_oi_a = pct(oi_now, oi_then_a if oi_then_a else None)
        d_usd_a = abs(oi_now - (oi_then_a or 0)) * (listing.mark or 0)
        if (d_oi_a is not None and d_oi_a >= config.absorb_oi_pct()
                and abs(p60) <= config.absorb_ret_pct()
                and d_usd_a >= config.oi_min_usd()):
            pen = list(base_pen)
            conf, notes = confidence(80, pen)
            step = _step(d_oi_a, config.absorb_oi_pct())
            out.append({'kind': 'absorption', 'ticker': listing.ticker, 'ts': now,
                        'key': key('absorption', '%s:%s' % (_venue, listing.ticker),
                                   _window(now), step),
                        'severity': conf,
                        'payload': dict(common, oi_change_pct=d_oi_a,
                                        oi_change_usd=d_usd_a, step=step,
                                        penalties=notes)})

    # ── СПРЕД: ЭТО ПРЕДОСТЕРЕЖЕНИЕ ────────────────────────────────────────────────────────
    if listing.spread_bps is not None and listing.spread_bps >= config.spread_min_bps():
        # АБСОЛЮТНЫЙ ПОРОГ СТОИТ ПЕРВЫМ, И ЭТО ЗАМЕР, А НЕ ВКУС. Живой час 25.09 дал три алерта
        # подряд по XAGS: «спред 2.4 б.п. - ×9.5 к медиане 0.3». Арифметика верна, новости нет:
        # 2.4 б.п. это две сотых процента. Множитель измеряет НЕОБЫЧНОСТЬ, а не ЗНАЧИМОСТЬ, и у
        # инструмента с идеально узкой книгой любое дыхание даёт «×9». Вердикт владельца:
        # «походит на спам», «это же не алерт».
        med = median([r[6] for r in ring])
        if med and listing.spread_bps >= med * config.spread_mult() and med > 0:
            conf, notes = confidence(75, base_pen)
            step = _step(listing.spread_bps / med, config.spread_mult())
            out.append({'kind': 'spread_shock', 'ticker': listing.ticker, 'ts': now,
                        'key': key('spread_shock', '%s:%s' % (_venue, listing.ticker), _window(now), step),
                        'severity': conf,
                        'payload': dict(common, spread_median_bps=med,
                                        spread_mult=listing.spread_bps / med,
                                        step=step, penalties=notes)})
    return out
