# -*- coding: utf-8 -*-
"""sentinel/engine.py — ТИКИ: опрос, обнаружение, отправка, обогащение, исход, уборка.

ПОЧЕМУ ФУНКЦИИ-ТИКИ, А НЕ ВЕЧНЫЙ ЦИКЛ ВНУТРИ. Ровно одна причина: дозорный переезжает. Сейчас
его тикает планировщик бота (`add_svc`), потом — отдельный юнит (`sentinel/main.py`), и обе
дороги зовут ЭТИ ЖЕ функции. Домен не знает, кто его позвал, и переезд не меняет ни одной
строки логики; иначе у нас было бы две копии обнаружения, которые разошлись бы на первой правке.

═══ ДВА КОЛЬЦА, И ЭТО ГЛАВНОЕ РЕШЕНИЕ ФАЙЛА ═══
Наивная схема «писать каждый опрос в базу» не работает арифметически: 15 секунд × 7 суток × 553
инструмента = 22 МИЛЛИОНА строк. Поэтому кольца два, и у каждого своя работа:

  ГОРЯЧЕЕ (в памяти, точка раз в 60с, 90 минут) — для доходностей за 15 и 60 минут. Живёт в
  процессе и после рестарта пустует; это НЕ баг, а цена: пока оно не набралось, движение
  просто не публикуется, и об этом говорит строка в логе. Терять точность ради выживания
  кольца при деплое нельзя — 15-минутная доходность по 15-минутной сетке измеряла бы сетку.

  ХОЛОДНОЕ (в базе, точка раз на 15 минут, 7 суток) — для сигмы, процентиля фандинга и
  медианы спреда, то есть для ответа «а это вообще необычно ДЛЯ НЕГО?». 672 точки на
  инструмент, ~371к строк на всю площадку: уже нормальный размер.

Детектор об этой конструкции ЗНАЕТ по существу: он принимает `rows` (горячее — считать
движение) и `ring` (холодное — считать необычность) как ДВА аргумента. Одно кольцо на оба
вопроса дало бы либо неверную сигму, либо неподъёмную базу.

СТРОКУ ИТОГА ПЕЧАТАЕТ КАЖДЫЙ ТИК, даже пустой. «Дозорный молчит» — самое опасное состояние:
оно одинаково выглядит при мёртвом опросе, пустых подписках, упоре в потолок и правдивой
тишине рынка. Строка называет, что именно.
"""

import time

from . import cards, config, detector, ignition, outbox, store, variational_feed as feed

#: Глубина горячего кольца. 90 минут — ровно чтобы закрыть 60-минутное окно с запасом на
#: пропуски опроса. Разрешение кольца равно темпу опроса: точка на каждый опрос (см. `_hot_put`,
#: там разобрано, почему прореживание здесь стоило нам всех событий движения).
HOT_KEEP = 90 * 60
#: Разрешение холодного кольца. Совпадает с окном детектора (`detector.W15`) НАРОЧНО: сигма
#: считается по 15-минутным доходностям, и сетка обязана быть той же.
COLD_RES = detector.W15

_HOT = {}            # ticker -> [(ts, mark, vol24, oi_l, oi_s, funding, spread, quote_ts)]
_COLD = {}           # ticker -> тот же кортеж, точка на 15 минут (кэш прочитанного из базы)
_COLD_BUCKET = {}    # ticker -> номер последнего записанного 15-минутного окна
_TICK_BUSY = False   # свой замок поверх max_instances: тик не имеет права наслоиться


def _row(x, ts):
    return (int(ts), x.mark, x.volume_24h, x.oi_long, x.oi_short, x.funding_raw,
            x.spread_bps, int(x.quote_ts) if x.quote_ts else None)


def _hot_put(x, ts):
    """Точка в горячее кольцо. -> список точек инструмента.

    ═══ ЗДЕСЬ БЫЛ ТИХИЙ БАГ, И ОН ОБЪЯСНЯЕТ «ПОЧЕМУ НЕ ПРИХОДЯТ ДВИЖЕНИЯ» ═══
    Первая редакция при опросе чаще `HOT_RES` ПЕРЕЗАПИСЫВАЛА последнюю точку целиком - вместе с
    её временем. А значит интервал до неё НИКОГДА не накапливался: каждый следующий опрос снова
    оказывался «слишком рано», снова перезаписывал, и кольцо на любом инструменте вечно
    оставалось ДЛИНОЙ В ОДНУ ТОЧКУ. Дальше по цепочке: нет второй точки - нет доходности за 15 и
    60 минут - нет ни одного события движения. Замер (три опроса с шагом 35с): «в кольце 553
    инструментов, 1 точек на инструмент».
    Класс бага ровно тот, что в проекте называют тихим: тик печатал «опрошено 553 инстр.»,
    кольцо жило, снимки писались - и при этом главный вопрос дозорного был невычислим.

    ТЕПЕРЬ ТОЧКА НА КАЖДЫЙ ОПРОС, а прореживание отдано ХОЛОДНОМУ кольцу (оно и заведено ради
    экономии). Память: при опросе раз в 30с и глубине 90 минут это 180 точек на инструмент,
    553 инструмента - около ста тысяч кортежей, то есть десятки мегабайт. Плата понятная, и
    она меньше, чем неработающий дозор.
    ЗАЩИТА ОТ НАЛОЖЕНИЯ ТИКОВ ОСТАЛАСЬ: два тика в одну секунду дают одну точку.
    """
    arr = _HOT.setdefault(x.ticker, [])
    if arr and ts <= arr[-1][0]:
        arr[-1] = _row(x, ts)
        return arr
    arr.append(_row(x, ts))
    cut = ts - HOT_KEEP
    while arr and arr[0][0] < cut:
        arr.pop(0)
    return arr


def _cold(ticker):
    """Холодное кольцо инструмента. Из базы — ОДИН раз за процесс, дальше дописываем в памяти.

    Запрос в базу на каждый инструмент каждый тик — это 553 запроса раз в 15 секунд; при таком
    темпе дозорный стал бы главной нагрузкой на базу бота. Кэш здесь не оптимизация, а условие
    существования.
    """
    if ticker not in _COLD:
        try:
            _COLD[ticker] = store.history(ticker, since_ts=int(time.time())
                                          - config.ring_days() * 86400)
        except Exception as e:
            print('[sentinel] холодное кольцо %s не прочитано: %s' % (ticker, str(e)[:110]))
            _COLD[ticker] = []
    return _COLD[ticker]


def _cold_due(x, ts):
    """Пора ли писать точку в базу. -> True/False."""
    b = int(ts) // COLD_RES
    return _COLD_BUCKET.get(x.ticker) != b


def _cold_put(x, ts):
    _COLD_BUCKET[x.ticker] = int(ts) // COLD_RES
    arr = _COLD.setdefault(x.ticker, [])
    arr.append(_row(x, ts))
    cut = ts - config.ring_days() * 86400
    while arr and arr[0][0] < cut:
        arr.pop(0)


def _interesting(watched):
    """Какие инструменты вообще проверять. -> функция-предикат.

    ПОДПИСКА '*' ЕСТЬ, И ОНА ЧЕСТНО СТОИТ ДЕНЕГ ПАМЯТИ: человек, подписанный на всю площадку,
    получает обход всех 553 инструментов. Отдельно `ALL` обрабатывать нельзя — иначе «подписан
    на всё» и «подписан на BTC» проверялись бы разным кодом, и однажды разошлись бы.
    """
    if store.ALL in watched:
        return lambda t: True
    return lambda t: t in watched


async def ingest_tick():
    """ОДИН круг: опрос площадки -> кольца -> обнаружение -> очередь доставки. -> строка итога.

    НИКОГДА НЕ БРОСАЕТ. Тик, уронивший планировщик, убивает не себя, а все остальные джобы
    бота — этот класс отказа в проекте уже стоил четырёх окон и GitHub-радара.
    """
    global _TICK_BUSY
    if _TICK_BUSY:
        return 'тик пропущен: предыдущий ещё идёт'
    _TICK_BUSY = True
    try:
        return await _ingest()
    except Exception as e:
        return 'тик упал: %s: %s' % (type(e).__name__, str(e)[:160])
    finally:
        _TICK_BUSY = False


async def _ingest():
    import asyncio
    now = int(time.time())
    if not store.lease('variational'):
        owner, until = store.lease_owner('variational')
        return 'опрос не наш: аренда у %s ещё %dс' % (owner, max(0, until - now))
    try:
        rows, meta = await asyncio.to_thread(feed.fetch)
    except feed.FeedError as e:
        # КЛАСС ОТКАЗА ФИДА НАЗЫВАЕМ. 'http 403' (нужен UA), 'net' (сеть) и 'shape' (площадка
        # сменила форму ответа) требуют совершенно разных действий, и склеить их в «не
        # получилось» значит потерять сутки на следующем разборе.
        return 'площадка не прочитана [%s] %s' % (e.kind, e.detail)
    watched = store.watched()
    if not watched:
        # СНИМКИ ПИШЕМ ВСЁ РАВНО: кольцо нужно ПЕРВОМУ подписчику, а он появится позже. Без
        # этого первый человек ждал бы 20 точек сигмы после подписки и считал бы дозор мёртвым.
        _seed(rows, now)
        return 'подписок нет; кольцо наполняется (%d инструментов, %dмс)' % (
            len(rows), meta.get('latency_ms') or 0)
    keep = _interesting(watched)
    cold_written = 0
    events = []
    for x in rows:
        hot = _hot_put(x, now)
        if _cold_due(x, now):
            _cold_put(x, now)
            cold_written += 1
        if not keep(x.ticker):
            continue
        try:
            evs = detector.detect(x, hot, now=now, ring=_cold(x.ticker))
        except Exception as e:
            print('[sentinel] детектор упал на %s: %s: %s'
                  % (x.ticker, type(e).__name__, str(e)[:110]))
            continue
        events += evs
    if cold_written:
        await asyncio.to_thread(_flush_cold, rows, now)
    planned, skipped = 0, []
    fresh = 0
    for ev in events:
        if not store.event_new(ev):
            continue                      # это тот же выброс, уже учтённый: молчим
        fresh += 1
        n, why = outbox.plan(ev)
        planned += n
        skipped += why
    store.spend_add(events=fresh)
    note = ('опрошено %d инстр. за %dмс; в дозоре %s; событий новых %d; доставок в очередь %d'
            % (len(rows), meta.get('latency_ms') or 0,
               ('вся площадка' if store.ALL in watched else str(len(watched))),
               fresh, planned))
    if skipped:
        note += '; не отправлено: ' + '; '.join(skipped[:4])
    return note


def _seed(rows, now):
    """Наполнение колец без подписчиков: горячее в памяти, холодное в базу по расписанию."""
    due = []
    for x in rows:
        _hot_put(x, now)
        if _cold_due(x, now):
            _cold_put(x, now)
            due.append(x)
    if due:
        store.snapshot_put(due, ts=now)


def _flush_cold(rows, now):
    """Записать в базу те инструменты, у которых окно сменилось. Одним проходом, в потоке."""
    b = int(now) // COLD_RES
    due = [x for x in rows if _COLD_BUCKET.get(x.ticker) == b]
    if due:
        store.snapshot_put(due, ts=now)


async def ignition_tick():
    """Круг смарт-зажигания (Nansen). -> строка итога.

    ОТДЕЛЬНЫМ ТИКОМ ОТ ПЛОЩАДКИ, потому что у него другая цена и другой темп: опрос
    Variational бесплатен и идёт раз в 15 секунд, а лента Nansen стоит кредиты — её темп
    задаётся бюджетом, а не желанием.
    """
    _stop = store.budget_block()
    if _stop:
        return 'зажигание пропущено: %s' % _stop
    try:
        import asyncio
        evs, note = await asyncio.to_thread(ignition.scan)
    except Exception as e:
        return 'зажигание упало: %s: %s' % (type(e).__name__, str(e)[:150])
    planned, skipped, fresh = 0, [], 0
    for ev in evs:
        if not store.event_new(ev):
            continue
        fresh += 1
        n, why = outbox.plan(ev)
        planned += n
        skipped += why
    out = '%s; новых событий %d; доставок %d' % (note, fresh, planned)
    if skipped:
        out += '; не отправлено: ' + '; '.join(skipped[:4])
    return out


async def deliver_tick():
    try:
        ok, bad = await outbox.deliver_due()
    except Exception as e:
        return 'отправка упала: %s: %s' % (type(e).__name__, str(e)[:150])
    if not ok and not bad:
        return 'очередь пуста'
    return 'отправлено %d, отказов %d' % (ok, bad)


async def enrich_tick(limit=3):
    """Сводки к уже доставленным алертам. -> строка итога.

    ПОТОЛОК ЗА ТИК СТОИТ НАРОЧНО МАЛЕНЬКИЙ: сводка это кредиты и вызов модели, и волатильная
    минута с двадцатью событиями не должна превращаться в двадцать одновременных запросов.
    """
    if not config.enrich_on():
        return 'обогащение выключено рубильником'
    done = 0
    for key in store.enrich_pending(limit=limit):
        if not store.enrich_claim(key):
            continue
        ev = store.event(key)
        if ev is None:
            store.enrich_done(key, '', err='событие пропало из базы')
            continue
        try:
            from . import enrichment
            # СВОДКУ СОБИРАЕМ ПОД ПЕРВОГО ПОЛУЧАТЕЛЯ, А НЕ «ВООБЩЕ». Состав сводки - личная
            # настройка (`store.parts_for`), и собирать её без человека значило бы платить за
            # Nansen тому, кто ончейн выключил. Событие у нескольких подписчиков - сводка идёт
            # по максимуму их наборов, поэтому берём первого доставленного как основу.
            _who = (store.delivered_users(key) or [None])[0]
            brief = await enrichment.build(ev, uid=_who, bot_un=await outbox.bot_un())
            sent = await outbox.deliver_enrichment(key, brief)
            store.enrich_done(key, cards.enrich_card(ev, brief),
                              credits=brief.get('credits') or 0,
                              err=(None if sent else 'никому не ушло'))
            done += 1
        except Exception as e:
            # ПРОВАЛ СВОДКИ НЕ ТРОГАЕТ ПЕРВОЕ СООБЩЕНИЕ. Он записывается строкой с причиной и
            # НЕ откатывает доставку: алерт человек уже получил, и «переотправить» его нельзя.
            store.enrich_done(key, '', err='%s: %s' % (type(e).__name__, str(e)[:120]))
            print('[sentinel] сводка %s не собралась: %s' % (key[:10], str(e)[:140]))
    return 'сводок собрано %d' % done


#: Горизонты, на которых мерим исход. 60 минут — «успел бы человек»; 24 часа — «а движение
#: вообще было тем, чем казалось». Один горизонт отвечал бы только на половину вопроса.
HORIZONS = (60, 1440)


async def outcome_tick():
    """Замер исходов: цена в момент алерта против цены через горизонт. -> строка итога.

    ПОЧЕМУ ЭТО ЕСТЬ ВООБЩЕ. Алертер без замера исхода — это генератор мнений: он не может
    отличить «работает» от «шумит», и первым, кто это заметит, будет человек, потерявший
    деньги. Замер идёт по НАШИМ ЖЕ снимкам одним и тем же фидом, то есть его нельзя подкрутить
    рассказом.
    """
    import asyncio
    n = 0
    for h in HORIZONS:
        for key, ticker, ts in await asyncio.to_thread(store.outcome_due, h):
            ev = store.event(key)
            if ev is None:
                continue
            then = (ev.get('payload') or {}).get('mark')
            after = _mark_at(ticker, ts + h * 60)
            if then is None or after is None:
                # СТРОКУ ВСЁ РАВНО ПИШЕМ (с None): иначе события, по которым замер невозможен,
                # возвращались бы в очередь вечно, и «исход не записан» означало бы «мы ещё
                # ждём» — а мы не ждём.
                store.outcome_put(key, h, then, after)
                continue
            store.outcome_put(key, h, then, after)
            n += 1
    return 'исходов замерено %d' % n


def _mark_at(ticker, ts):
    """Цена инструмента около момента. Берём из ХОЛОДНОГО кольца: горячее не переживает
    рестарт, а исход мерится часами и сутками позже."""
    rows = _cold(ticker)
    r = detector.at(rows, ts, tol=COLD_RES)
    return r[1] if r else None


async def prune_tick():
    import asyncio
    n = await asyncio.to_thread(store.prune)
    await asyncio.to_thread(store.seen_prune)
    return 'снимков убрано %s' % ('не сказано СУБД' if n < 0 else n)


def hit_rate(kind=None, horizon_min=60, days=7, min_sample=20):
    """Отчёт попаданий. -> строка. ЧЕСТНО ГОВОРИТ «ВЫБОРКА МАЛА» ВМЕСТО КРАСИВОГО ПРОЦЕНТА.

    Порог выборки не косметика: на пяти событиях «80% попаданий» — это четыре из пяти, то есть
    ровно ничего. Цифра, которой нельзя верить, хуже отсутствующей, потому что по ней принимают
    решения.
    """
    since = int(time.time()) - int(days) * 86400
    rows = store.outcomes(kind=kind, horizon_min=horizon_min, since_ts=since)
    if len(rows) < min_sample:
        return ('%s за %dд: событий с замером %d — выборка мала (нужно %d), процент не считаю'
                % (kind or 'все виды', days, len(rows), min_sample))
    ups = [r for r in rows if (r[2] or '').endswith('_up') or r[2] in ('ignition', 'oi_surge')]
    pool = ups or rows
    good = sum(1 for r in pool if (r[1] or 0) > 0)
    med = detector.median([r[1] for r in pool])
    return ('%s за %dд, горизонт %dмин: замеров %d, продолжение движения %d (%.0f%%), '
            'медианный ход %+.2f%%'
            % (kind or 'все виды', days, horizon_min, len(pool), good,
               good * 100.0 / len(pool), med or 0.0))



# ══════════════════════════════════════════════════════════════════════════════════════════
# «А ОН ВООБЩЕ ЖИВОЙ?» — ЭКРАН РЫНКА ПО ЗАПРОСУ
#
# ЖИВОЙ СЛУЧАЙ 25.09: «включил дозорного, пока ничего не пришло». И это было ПРАВДОЙ про рынок,
# а не поломкой: за трое минут ни один из 553 инструментов не изменил марк-цену. Но человек
# этого знать не мог — молчание дозорного и его смерть выглядят ОДИНАКОВО.
#
# Поэтому здесь не «статус ок», а САМ РЫНОК числами: что двигалось сильнее всего, где растёт
# оборот, и НАСКОЛЬКО ДАЛЕКО лучший кандидат от порога. Ответ «ближайшее движение 0.4% против
# порога 1.2%» закрывает вопрос за одну строку и без всякой веры.
# ══════════════════════════════════════════════════════════════════════════════════════════
def market_now(limit=5, now=None):
    """Срез рынка из НАШЕГО кольца. -> dict.

    Читает только память процесса (горячее кольцо): ни одного запроса к площадке и ни одного
    кредита. Это важно по существу — экран «почему тихо» не имеет права сам стоить денег.
    """
    now = int(now if now is not None else time.time())
    moves, vols = [], []
    for ticker, rows in _HOT.items():
        if len(rows) < 2:
            continue
        cur = rows[-1]
        if (cur[2] or 0) < config.min_volume_usd():
            continue
        r60 = detector.at(rows, now - detector.W60, tol=detector.W60)
        r15 = detector.at(rows, now - detector.W15, tol=detector.W15 // 2)
        p15 = detector.pct(cur[1], r15[1]) if r15 else None
        p60 = detector.pct(cur[1], r60[1]) if r60 else None
        best = p15 if p15 is not None else p60
        if best is not None:
            moves.append((abs(best), ticker, best, p15, p60))
        if r60 and r60[2]:
            dv = detector.pct(cur[2], r60[2])
            if dv is not None and dv > 0:
                vols.append((dv, ticker, (cur[2] or 0) - (r60[2] or 0)))
    moves.sort(reverse=True)
    vols.sort(reverse=True)
    # СКОЛЬКО ИНСТРУМЕНТОВ ВООБЩЕ СДВИНУЛОСЬ - ОТДЕЛЬНОЕ ЧИСЛО, И ОНО ГЛАВНОЕ В ТИХИЙ ЧАС.
    # Замер 25.09: за три минуты НИ ОДИН из 553 инструментов не изменил марк-цену. Без этого
    # числа «сильнейшее движение 0.00%» читается как поломка нашего счётчика, а с ним - как
    # факт про площадку.
    stirred = sum(1 for m in moves if m[0] > 0.0001)
    return {'tickers': len(_HOT), 'points': max((len(v) for v in _HOT.values()), default=0),
            'moves': moves[:limit], 'vols': vols[:limit], 'stirred': stirred,
            'measured': len(moves),
            'thr15': config.move_pct_15m(), 'thr_vol': config.vol_pct(),
            'best': (moves[0][0] if moves else None)}
