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

import os
import time

from . import cards, config, detector, ignition, outbox, store, variational_feed as feed
from . import venues

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


def _rk(x):
    # КЛЮЧ ИНСТРУМЕНТА В КОЛЬЦАХ - ПАРА «площадка:тикер», А НЕ ТИКЕР.
    # Без площадки «BTC» с Variational и «BTC» с Hyperliquid легли бы в ОДИН ряд, и на
    # каждом тике ряд прыгал бы между двумя разными ценами: детектор увидел бы
    # «движения», которых на рынке нет. Тот же класс, что склейка однофамильцев токенов,
    # только дороже - там врал один экран, здесь врал бы весь дозор.
    return venues.key(getattr(x, 'venue', 'variational') or 'variational', x.ticker)


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
    arr = _HOT.setdefault(_rk(x), [])
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
    return _COLD_BUCKET.get(_rk(x)) != b


def _cold_put(x, ts):
    _COLD_BUCKET[_rk(x)] = int(ts) // COLD_RES
    arr = _COLD.setdefault(_rk(x), [])
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


#: Сколько ждём мёртвого опрашивающего, прежде чем взять опрос на себя. Три срока аренды:
#: живой юнит продлевает её каждым тиком, так что три пропуска подряд - это уже не заминка.
_TAKEOVER_AFTER = int(os.getenv('SENTINEL_TAKEOVER_SEC') or 0)


def _poller_dead(now=None):
    """Умер ли тот, кто держал опрос. -> bool.

    ═══ ПОЧЕМУ БОТ ОБЯЗАН ПОДХВАТЫВАТЬ ОПРОС ═══
    ЖИВОЙ СЛУЧАЙ 25-26.09: отдельный юнит `sentinel` работал 7 часов и перестал писать снимки
    (служба `active`, процесс жив, CPU растёт - а кольцо пустое). Бот в это время видел
    `SENTINEL_IN_BOT=0` и честно выходил из тика со словами «опрос у отдельного юнита», то есть
    НЕ ДЕЛАЛ НИЧЕГО. Алертов не было полчаса, и вылечить это из интерфейса было нельзя.
    Выключатель `SENTINEL_IN_BOT` защищает от ДВОЙНОГО опроса - это его настоящая работа. Но
    «не опрашивать, потому что опрашивает другой» верно только пока другой ЖИВ, а живость у нас
    уже измеряется арендой. Читая выключатель и игнорируя аренду, мы превращали страховку в
    единственную точку отказа: смерть юнита означала тишину НАВСЕГДА.
    ТЕПЕРЬ ЭТО САМОВОССТАНОВЛЕНИЕ: аренды нет или она истекла - значит опрашивающего нет, и
    бот берёт опрос на себя. Двойного опроса не будет, потому что живой юнит аренду продлевает
    и этот путь не откроется.
    ГРОМКО, А НЕ МОЛЧА: подхват пишется строкой в лог. Тихое самолечение однажды скроет от нас
    то, что юнит вообще не работает.
    """
    now = int(now if now is not None else time.time())
    owner, until = store.lease_owner('variational')
    grace = _TAKEOVER_AFTER or max(90, config.poll_sec() * 3)
    if owner and until > now:
        return False                       # аренда живая - опрашивает кто-то другой, не лезем
    if until and (now - until) < grace:
        return False                       # только что просрочилась - даём шанс продлить
    print('[sentinel] ОПРАШИВАЮЩИЙ НЕ ОТВЕЧАЕТ (аренда %s) - беру опрос на себя'
          % ('истекла %d мин назад' % ((now - until) // 60) if until else 'не взята никем'))
    return True


async def _ingest():
    import asyncio
    now = int(time.time())
    # ВЫКЛЮЧАТЕЛЬ ПРОВЕРЯЕМ ДО АРЕНДЫ: если опрос вынесен в отдельный юнит, тик в боте не
    # должен даже пытаться взять аренду - иначе он отбирал бы её у настоящего опрашивающего на
    # каждом втором круге, и оба писали бы в лог про чужую аренду.
    if not config.in_bot() and not _poller_dead(now):
        ok, bad = await outbox.deliver_due()
        return ('опрос у отдельного юнита; из очереди отправлено %d, отказов %d' % (ok, bad)
                if (ok or bad) else 'опрос у отдельного юнита; очередь пуста')
    if not store.lease('variational'):
        owner, until = store.lease_owner('variational')
        return 'опрос не наш: аренда у %s ещё %dс' % (owner, max(0, until - now))
    # ОПРАШИВАЕМ ВСЕ ВКЛЮЧЁННЫЕ ПЛОЩАДКИ, И ОТКАЗ ОДНОЙ НЕ РОНЯЕТ ОСТАЛЬНЫЕ. Класс отказа
    # называется по каждой отдельно: «Hyperliquid молчит» и «дозорный сломался» - разные
    # новости, и первую человек должен увидеть строкой, а не догадкой.
    rows, notes = await venues.fetch_all()
    _bad = ['%s [%s] %s' % (venues.title(v), n.kind, n.detail)
            for v, n in notes.items() if isinstance(n, feed.FeedError)]
    if not rows:
        return ('ни одна площадка не прочитана: %s'
                % ('; '.join(_bad) or 'причина не названа'))
    meta = {'latency_ms': 0}
    for _v, _n in notes.items():
        if isinstance(_n, dict):
            meta['latency_ms'] = max(meta['latency_ms'], int(_n.get('latency_ms') or 0))
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
            evs = detector.detect(x, hot, now=now, ring=_cold(_rk(x)))
        except Exception as e:
            print('[sentinel] детектор упал на %s: %s: %s'
                  % (x.ticker, type(e).__name__, str(e)[:110]))
            continue
        events += evs
    # РАСХОЖДЕНИЕ МЕЖДУ ПЛОЩАДКАМИ - ОДИН РАЗ НА ТИК, А НЕ НА ИНСТРУМЕНТ: оно живёт между
    # рынками, и считать его в цикле по тикерам значило бы сравнить каждую пару дважды.
    if len(set(getattr(x, 'venue', '') for x in rows)) > 1:
        try:
            events += detector.cross_venue([x for x in rows if keep(x.ticker)], now=now)
        except Exception as e:
            print('[sentinel] сравнение площадок упало: %s: %s'
                  % (type(e).__name__, str(e)[:110]))
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
    _ok_v = [venues.title(v) for v, n in notes.items()
             if not isinstance(n, feed.FeedError)]
    note = ('опрошено %d инстр. (%s) за %dмс; в дозоре %s; событий новых %d; '
            'доставок в очередь %d'
            % (len(rows), ', '.join(_ok_v) or 'никого', meta.get('latency_ms') or 0,
               ('вся площадка' if store.ALL in watched else str(len(watched))),
               fresh, planned))
    if skipped:
        note += '; не отправлено: ' + '; '.join(skipped[:4])
    if _bad:
        note += '; отказ площадок: ' + '; '.join(_bad)
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
    due = [x for x in rows if _COLD_BUCKET.get(_rk(x)) == b]
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
    planned, skipped, fresh, clustered = 0, [], 0, 0
    for ev in evs:
        # ═══ ПРОВЕРКА СВЯЗЕЙ - ДО ЗАПИСИ И ДО ОЧЕРЕДИ, А НЕ В ОБОГАЩЕНИИ ═══
        # Пункт 3.6 роудмапа: три адреса, купившие одно и то же, могут быть ОДНИМ человеком, и
        # это ШТРАФ К УВЕРЕННОСТИ. Значит штраф обязан попасть в событие ДО того, как оно уйдёт
        # человеку: уверенность решает, звонить или везти сводкой (порог `min_sev`), и
        # пересчитанная ПОСЛЕ отправки она не меняет ничего, кроме нашего самочувствия.
        # ЗДЕСЬ СЕТЬ РАЗРЕШЕНА: этот тик и так ходит в Nansen, в отличие от `ignition.judge`,
        # который обязан остаться чистой функцией.
        if await _cluster_mark(ev):
            clustered += 1
        if not store.event_new(ev):
            continue
        fresh += 1
        n, why = outbox.plan(ev)
        planned += n
        skipped += why
    out = '%s; новых событий %d; доставок %d' % (note, fresh, planned)
    if clustered:
        out += '; со связанными адресами %d' % clustered
    if skipped:
        out += '; не отправлено: ' + '; '.join(skipped[:4])
    return out


async def _cluster_mark(ev):
    """Пересчитать уверенность зажигания с учётом связей адресов. -> True, если связи нашлись.

    ПРАВИМ СОБЫТИЕ НА МЕСТЕ И ДО ЗАПИСИ В БАЗУ: `severity` едет в базу вместе с событием и
    оттуда читается порогом звонка, карточкой и отчётом попаданий. Поправить его позже значит
    иметь в базе одно число, а на экране другое.
    НИКОГДА НЕ БРОСАЕТ: отказ этой проверки не имеет права уронить событие, честно посчитанное
    по порогам. Он превращается в строку штрафа «связи не проверены» - и это тоже информация.
    """
    if (ev.get('kind') or '') != 'ignition':
        return False
    p = ev.get('payload') or {}
    addrs = p.get('wallet_addrs') or ()
    if len(addrs) < 2:
        return False
    try:
        from . import clusters
        res = await clusters.check(addrs, p.get('chain') or 'ethereum')
        pen = clusters.penalty(res)
    except Exception as e:                        # noqa: BLE001
        print('[sentinel] проверка связей не удалась: %s' % str(e)[:120])
        return False
    p['independent'] = res.get('independent')
    p['cluster_groups'] = res.get('groups') or []
    p['cluster_checked'] = res.get('checked')
    if res.get('partial'):
        p['cluster_partial'] = res['partial']
    if not pen:
        return False
    # ПЕРЕСЧЁТ УВЕРЕННОСТИ ИДЁТ ТОЙ ЖЕ ДВЕРЬЮ, ЧТО И ВСЕ ОСТАЛЬНЫЕ ШТРАФЫ (`detector.confidence`),
    # а не вычитанием числа руками: иначе два места считали бы уверенность по-разному, и
    # расхождение вылезло бы на живом событии, где его труднее всего заметить.
    from .detector import confidence
    _old = int(ev.get('severity') or 0)
    conf, notes = confidence(_old, [(pen[0], pen[1])])
    ev['severity'] = conf
    p['penalties'] = list(p.get('penalties') or ()) + list(notes)
    if res.get('merged'):
        print('[sentinel] зажигание %s: адресов %d, независимых участников %d - уверенность '
              '%d -> %d' % (ev.get('ticker'), res.get('wallets'), res.get('independent'),
                            _old, conf))
    return bool(res.get('merged'))


async def deliver_tick():
    try:
        ok, bad = await outbox.deliver_due()
    except Exception as e:
        return 'отправка упала: %s: %s' % (type(e).__name__, str(e)[:150])
    if not ok and not bad:
        return 'очередь пуста'
    return 'отправлено %d, отказов %d' % (ok, bad)


async def digest_tick():
    """Круг сводок: отложенное предохранителем уезжает ОДНИМ сообщением. -> строка итога.

    ОТДЕЛЬНОЙ ДЖОБОЙ ОТ ДОСТАВКИ, потому что у неё другой темп: доставка тикает каждые 30
    секунд (алерт ценен минутами), сводка - раз в десять минут, и смешивать их значило бы либо
    задержать алерты, либо превратить сводку в поток.
    """
    try:
        n = store.delivery_unstick()
        if n:
            # СИРОТЫ НАЗЫВАЮТСЯ ЧИСЛОМ. Строка, застрявшая в работе после падения процесса, -
            # это потерянный алерт, и молчать о таком нельзя (см. `store.delivery_unstick`).
            print('[sentinel] вернул в очередь %d застрявших доставок' % n)
        people, rows = await outbox.deliver_digest()
    except Exception as e:
        return 'сводка упала: %s: %s' % (type(e).__name__, str(e)[:150])
    if not people:
        return 'сводок нет'
    return 'сводок отправлено %d (событий в них %d)' % (people, rows)


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
    await asyncio.to_thread(store.digest_prune)
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
    for rkey, rows in _HOT.items():
        _v, ticker = venues.split(rkey)
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
            moves.append((abs(best), ticker, best, p15, p60, _v))
        if r60 and r60[2]:
            dv = detector.pct(cur[2], r60[2])
            if dv is not None and dv > 0:
                vols.append((dv, ticker, (cur[2] or 0) - (r60[2] or 0), _v))
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


# ══════════════════════════════════════════════════════════════════════════════════════════
# СКВОЗНОЙ ПЕРЕХОД: ТИКЕР -> КОНТРАКТ -> НАША КАРТОЧКА ТОКЕНА
#
# ТРЕБОВАНИЕ ВЛАДЕЛЬЦА ДОСЛОВНО: «в что сейчас приходят тикер без ссылок на карточки токенов
# или контрактов (мемов), не забывай, у нас все сценарии сквозные, чтобы сразу на карточку
# попасть и если что в избранное закинуть». И он прав по существу: экран, из которого нельзя
# выйти дальше, заставляет человека набирать тикер руками в другом окне - то есть мы отдаём
# ему работу, которую умеем сделать сами.
#
# ПОЧЕМУ РЕЗОЛВ ЛЕНИВЫЙ, ПО ТАПУ, А НЕ СРАЗУ ССЫЛКАМИ В ТЕКСТЕ. Чтобы поставить ссылку в
# тексте, адрес нужен ДО отправки, то есть на пять тикеров - пять сопоставлений (а это чужие
# запросы и кредиты) ради строк, по которым человек, может быть, и не тапнет. Кнопка же
# платит ровно за тот тикер, который открыли.
#
# СОПОСТАВЛЕНИЕ ИДЁТ ПО ЦЕНЕ, А НЕ ПО ПОХОЖЕСТИ ИМЕНИ: цена у нас есть в кольце, и общая
# дверь `oc_passport.canonical_contract` сверяет кандидатов ЧИСЛОМ и выбирает крупнейший по
# капитализации. Этот класс ошибки в проекте уже стоил трёх экранов (UNI -> Binance-Peg,
# LIT -> солановский однофамилец), и повторять его на кнопке нельзя.
# ══════════════════════════════════════════════════════════════════════════════════════════
def last_mark(ticker, venue=None):
    """Свежая цена тикера из НАШЕГО кольца. -> float | None.

    Берём из кольца, а не запросом: цена уже опрошена секунду назад, и второй поход к
    площадке ради того же числа - это чужой лимит за наши деньги.
    """
    t = str(ticker or "").upper()
    best = None
    for rkey, rows in _HOT.items():
        v, tk = venues.split(rkey)
        if tk != t or (venue and v != venue):
            continue
        if rows and rows[-1][1]:
            best = rows[-1][1] if best is None else best
    return best


async def resolve_ticker(ticker, venue=None):
    """Тикер -> (адрес, сеть, причина отказа). Сопоставление ПО ЦЕНЕ.

    НИКОГДА НЕ БРОСАЕТ: это путь кнопки, и падение здесь человек читает как «бот сломался».
    Причина отказа возвращается СЛОВАМИ - «цены нет в кольце», «ни один контракт не совпал
    с ценой» и «дверь сопоставления упала» требуют разных действий.
    """
    mark = last_mark(ticker, venue)
    if not mark:
        return None, None, "цены нет в кольце: дозорный ещё не видел этот инструмент"
    try:
        import os as _os
        import sys as _sys
        _oc = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            "onchain")
        if _oc not in _sys.path:
            _sys.path.insert(0, _oc)
        import oc_passport as _p
        addr, market, why = await _p.canonical_contract(ticker, float(mark))
    except Exception as e:
        return None, None, "сопоставление не сработало: %s" % str(e)[:110]
    if not addr:
        return None, None, (why or "ни один контракт не совпал с ценой")
    chain = (market or {}).get("chain") if isinstance(market, dict) else None
    return addr, chain, None