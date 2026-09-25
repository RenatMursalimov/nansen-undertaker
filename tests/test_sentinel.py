# -*- coding: utf-8 -*-
"""Тесты дозорного (sentinel/): фикстура ответа площадки -> ЖИВОЙ разбор -> кольца ->
детектор -> дедупликация -> пауза -> потолок -> отправка -> обогащение -> исход.

Запуск: python3 tests/test_sentinel.py    (сети не требует, БД — временный sqlite).

ЧТО ПОДМЕНЕНО И ПОЧЕМУ ИМЕННО ТАМ
  * СЕТЬ, и только она: тело ответа Variational подставляется словарём в `feed.parse` —
    то есть проверяется ЖИВОЙ разбор, а не заглушка вместо него. Лента Nansen подставляется
    в `ignition.scan(fetch=…)` на той же границе.
  * ЧАСЫ: `now` передаётся аргументом во все чистые функции. Тест, который спал бы час ради
    проверки паузы, не запускают — а значит он ничего не защищает.
  * ОТПРАВКА: фальшивый Bot ЗАПИСЫВАЕТ текст. Проверяем, ЧТО уехало бы человеку, а не факт
    вызова внутренней функции (закон №35): именно текст читает человек, и именно в нём
    случаются дефекты вроде «$0.99 вместо $48K».

ЧЕГО ЗДЕСЬ НЕТ: ожидания живого выброса на рынке. Детектор кормится синтетическим рядом, у
которого известен правильный ответ. Тест, который ждёт настоящего движения, зелен всегда и
не доказывает ничего.
"""
import asyncio
import os
import sys
import tempfile
import time

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ['SENTINEL_LLM_OFF'] = '1'            # пересказ моделью в тестах не зовётся

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'onchain'))

import db                                        # noqa: E402
_TMP = tempfile.mkdtemp(prefix='sentinel_test_')
# ПУТЬ СТАВИМ ПУБЛИЧНОЙ ДВЕРЬЮ `set_path`, А НЕ ВНУТРЕННИМ `_PATHS`. Этот файл уезжает в
# публичную выжимку (`tools/export_nansen_public.py`), а `db.py` там — своя маленькая
# реализация той же двери БЕЗ `_PATHS`. Тест, который лезет во внутренности, работал бы в
# приватном репозитории и падал в публичном первой же строкой — то есть судья увидел бы
# сломанный артефакт вместо доказательства.
for _k in ('onchain', 'main'):
    db.set_path(_k, os.path.join(_TMP, '%s.db' % _k))

from sentinel import cards, config, detector, engine, ignition, outbox, store, ui  # noqa: E402
from sentinel import variational_feed as feed    # noqa: E402

UID = 990001
UID2 = 990002
_OK, _FAIL = 0, 0


def check(name, cond, note=''):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print('  ok  %s' % name)
    else:
        _FAIL += 1
        print('FAIL  %s %s' % (name, note))


class FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, chat_id=None, text=None, **kw):
        if self.fail:
            raise RuntimeError('tg down')
        self.sent.append((chat_id, text))
        return type('M', (), {'message_id': 100 + len(self.sent)})()


def attach(bot):
    outbox._BOT = bot
    outbox._BOT_TOKEN = 'test'


# ── ФИКСТУРА ОТВЕТА ПЛОЩАДКИ: форма снята с живого ответа 25.09.2026 (553 инструмента,
#    числа строками, наносекундная дробь в `updated_at`, `size_1m` есть не у всех).
def payload(ticker='BTC', name='Bitcoin', mark='100.0', vol='800000000', oi_l='1000',
            oi_s='900', funding='0.05', spread='1.0', quote_iso=None, size_1m=True):
    q = {'updated_at': quote_iso or '2026-09-25T00:23:32.422937751Z',
         'base': {'bid': str(float(mark) * 0.9995), 'ask': str(float(mark) * 1.0005)},
         'size_1k': {'bid': str(float(mark) * 0.999), 'ask': str(float(mark) * 1.001)},
         'size_100k': {'bid': str(float(mark) * 0.998), 'ask': str(float(mark) * 1.002)}}
    if size_1m:
        q['size_1m'] = {'bid': str(float(mark) * 0.99), 'ask': str(float(mark) * 1.01)}
    return {'total_volume_24h': '3.2e9', 'open_interest': '1.9e9', 'tvl': '2.4e8',
            'num_markets': 1,
            'listings': [{'ticker': ticker, 'name': name, 'mark_price': mark,
                          'volume_24h': vol,
                          'open_interest': {'long_open_interest': oi_l,
                                            'short_open_interest': oi_s},
                          'funding_rate': funding, 'funding_interval_s': 28800,
                          'base_spread_bps': spread, 'quotes': q}]}


def one(**kw):
    rows, _meta = feed.parse(payload(**kw))
    return rows[0]


def series(n, start_ts, mark=100.0, step=900, funding=0.05, spread=1.0):
    """Холодное кольцо: n точек по 15 минут. Форма кортежа — контракт `store.history`."""
    return [(start_ts + i * step, mark, 8e8, 1000.0, 900.0, funding, spread, start_ts + i * step)
            for i in range(n)]


# ══════════════════════════════════════════════════════════════════════════════════════════
def t_parse_is_real_and_names_what_is_missing():
    """РАЗБОР ОТВЕТА: строки провайдера -> числа, наносекунды -> возраст, пропуск -> имя."""
    rows, meta = feed.parse(payload())
    x = rows[0]
    check('PARSE: числа провайдера строками стали числами',
          x.mark == 100.0 and x.volume_24h == 8e8, (x.mark, x.volume_24h))
    check('PARSE: наносекундная дробь не убила возраст котировки',
          x.quote_ts is not None and abs(x.quote_ts - 1790295812.42) < 1,
          'возраст None -> штраф за свежесть не сработал бы НИКОГДА')
    check('PARSE: возраст считается от now, а не от часов провайдера',
          abs(x.quote_age(x.quote_ts + 55) - 55) < 1, x.quote_age(x.quote_ts + 55))
    check('PARSE: мета несёт задержку и объём ответа', 'fetched_at' in meta)
    # ОТСУТСТВИЕ ПОЛЯ - НЕ НОЛЬ. Живая проба: у одного инструмента из 553 нет ни `quotes`,
    # ни `base_spread_bps`; ноль спреда означал бы идеальную книгу, чего не бывает.
    p = payload()
    p['listings'][0].pop('base_spread_bps')
    p['listings'][0].pop('quotes')
    y = feed.parse(p)[0][0]
    check('PARSE: пропущенное поле названо, а не заменено нулём',
          y.spread_bps is None and 'base_spread_bps' in y.missing and 'quotes' in y.missing,
          (y.spread_bps, y.missing))
    check('PARSE: чужая форма ответа - отказ с классом, а не пустой список',
          _raises_shape({'listings': []}), 'пустой список читался бы как «рынок замер»')
    check('PARSE: класс актива по имени провайдера, а не по тикеру',
          feed.asset_class(one(ticker='MRNA', name='Moderna, Inc.')) == 'equity'
          and feed.asset_class(one(ticker='A', name='Vaulta')) == 'unknown',
          'тикер `A` в живом списке - токен Vaulta, а не Agilent')
    check('PARSE: «не акция» НЕ объявляется криптой',
          feed.asset_class(one(ticker='XAU', name='Gold')) == 'unknown')
    check('PARSE: ёмкость на объём считается от середины',
          abs(one().depth_bps('size_100k') - 20.0) < 0.5, one().depth_bps('size_100k'))


def _raises_shape(p):
    try:
        feed.parse(p)
        return False
    except feed.FeedError as e:
        return e.kind == 'shape'


def t_detector_needs_both_percent_and_sigma():
    """ДЕТЕКТОР: процент без сигмы — спам, сигма без процента — шум."""
    now = 1800000000
    ring = series(60, now - 60 * 900)                       # ровный ряд: сигма нулевая
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    evs = detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now, ring=ring)
    kinds = {e['kind'] for e in evs}
    check('DETECT: 4% за 15 минут - это событие', 'move_up' in kinds, kinds)
    # РОВНЫЙ РЯД ФАНДИНГА - НЕ ХВОСТ. Первая редакция считала «доля не больше x» и на
    # постоянном ряде давала 1.0: «ставка в верхнем хвосте» печаталась на КАЖДОМ тике по
    # инструменту, у которого ставка не менялась вовсе.
    check('DETECT: постоянная ставка не объявляется хвостом', 'funding_extreme' not in kinds,
          kinds)
    check('DETECT: сигма, измеренная нулём, не глушит движение целиком', 'move_up' in kinds,
          'на идеально ровном ряде порог в сигмах невычислим - событие обязано остаться')
    check('DETECT: и говорит об этом словами',
          any('сигма измерена нулём' in p
              for e in evs if e['kind'] == 'move_up' for p in e['payload']['penalties']),
          [e['payload']['penalties'] for e in evs if e['kind'] == 'move_up'])
    evs2 = detector.detect(one(mark='100.5', quote_iso=_iso(now)), hot, now=now, ring=ring)
    check('DETECT: 0.5% - не событие', not [e for e in evs2 if e['kind'].startswith('move')])
    # ВЫБОРКА МАЛА -> СОБЫТИЕ ЕСТЬ, НО УВЕРЕННОСТЬ НИЖЕ И ПРИЧИНА НАЗВАНА
    short = series(3, now - 3 * 900)
    ev3 = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                      ring=short) if e['kind'] == 'move_up']
    check('DETECT: на короткой выборке событие остаётся', ev3)
    check('DETECT: и честно называет, что сигмы ещё нет',
          ev3 and any('сигма по' in p for p in ev3[0]['payload']['penalties']),
          ev3[0]['payload']['penalties'] if ev3 else None)
    check('DETECT: уверенность за это наказана', ev3 and ev3[0]['severity'] < 100,
          ev3[0]['severity'] if ev3 else None)
    # ОКНО НЕДОСТУПНО -> МОЛЧАНИЕ, А НЕ «0%»
    ev4 = detector.detect(one(mark='104.0', quote_iso=_iso(now)), [], now=now, ring=ring)
    check('DETECT: без точки в прошлом движение не объявляется',
          not [e for e in ev4 if e['kind'].startswith('move')],
          'отсутствие замера превратилось бы в утверждение о рынке')
    check('DETECT: pct без базы отдаёт None, а не ноль',
          detector.pct(5, 0) is None and detector.pct(5, None) is None)
    # ОБОРОТ - ПОРОГ ВХОДА
    ev5 = detector.detect(one(mark='104.0', vol='1000', quote_iso=_iso(now)), hot, now=now,
                          ring=ring)
    check('DETECT: инструмент без оборота в дозор не идёт вовсе', not ev5, ev5)


def _iso(ts):
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S.000000000Z')


def t_event_key_is_stable_and_step_escalates():
    """КЛЮЧ СОБЫТИЯ: один выброс — один ключ; удвоение движения — НОВЫЙ ключ."""
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    a = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                    ring=ring) if e['kind'] == 'move_up'][0]
    b = [e for e in detector.detect(one(mark='104.4', quote_iso=_iso(now + 30)), hot,
                                    now=now + 30, ring=ring) if e['kind'] == 'move_up'][0]
    check('KEY: тот же выброс через 30с даёт ТОТ ЖЕ ключ', a['key'] == b['key'],
          'иначе одно движение дало бы десятки алертов')
    c = [e for e in detector.detect(one(mark='107.0', quote_iso=_iso(now + 60)), hot,
                                    now=now + 60, ring=ring) if e['kind'] == 'move_up'][0]
    check('KEY: движение удвоилось - это НОВОЕ событие', c['key'] != a['key'],
          'ступень %s' % c['payload']['step'])
    check('KEY: ступень названа числом', c['payload']['step'] == 2, c['payload']['step'])


def t_oi_funding_and_spread_have_their_own_reasons():
    """ТРИ ОСТАЛЬНЫХ ВИДА: интерес, ставка, спред — каждый ловится своим замером."""
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [(now - 3600, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 3600)]
    evs = detector.detect(one(mark='100.0', oi_l='1600', oi_s='900', quote_iso=_iso(now)),
                          hot, now=now, ring=ring)
    check('OI: скачок интереса при стоящей цене — событие',
          'oi_surge' in {e['kind'] for e in evs}, {e['kind'] for e in evs})
    # ФАНДИНГ: хвост СВОЕГО распределения (единица провайдером не названа, абсолюта нет)
    ring_f = [(now - (60 - i) * 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, 0) for i in range(60)]
    ring_f = ring_f * 1
    evs2 = detector.detect(one(mark='100.0', funding='9.99', quote_iso=_iso(now)), hot,
                           now=now, ring=ring_f)
    check('FUNDING: порог процентильный, не абсолютный',
          'funding_extreme' in {e['kind'] for e in evs2} or len(ring_f) < 50,
          {e['kind'] for e in evs2})
    # ДИВИДЕНД У АКЦИЙ ВЫГЛЯДИТ КАК ПОЗИЦИОНИРОВАНИЕ - КАРТОЧКА ОБЯЗАНА СКАЗАТЬ ЭТО САМА
    ring_n = [(now - (60 - i) * 900, 100.0, 8e8, 1000.0, 900.0, 0.5, 1.0, 0) for i in range(60)]
    evs3 = [e for e in detector.detect(
        one(ticker='MRNA', name='Moderna, Inc.', mark='100.0', funding='-9.9',
            quote_iso=_iso(now)), hot, now=now, ring=ring_n)
        if e['kind'] == 'funding_extreme']
    check('FUNDING: у акции отрицательная ставка помечена как возможный дивиденд',
          evs3 and any('дивиденд' in p for p in evs3[0]['payload']['penalties']),
          evs3[0]['payload']['penalties'] if evs3 else 'события нет')
    evs4 = [e for e in detector.detect(one(mark='100.0', spread='9.0', quote_iso=_iso(now)),
                                       hot, now=now, ring=ring) if e['kind'] == 'spread_shock']
    check('SPREAD: разъехавшаяся котировка - событие', evs4)
    check('SPREAD: и карточка называет это предостережением, а не сигналом',
          evs4 and 'ПРЕДОСТЕРЕЖЕНИЕ' in cards.card(evs4[0]),
          'человек прочитал бы «дёрнулось» как приглашение')


def t_card_leads_with_magnitude_and_admits_limits():
    """КАРТОЧКА: первая строка — число; единицу фандинга не выдумываем; чек-лист есть."""
    now = 1800000000
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    ev = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                     ring=ring) if e['kind'] == 'move_up'][0]
    txt = cards.card(ev)
    check('CARD: величина в первых двух строках', '+4.00%' in txt.split('\n')[1], txt[:120])
    check('CARD: единица фандинга НЕ заявлена - назван источник поля',
          'поле провайдера funding_rate' in txt,
          'провайдер единицу не назвал, а его справка противоречит замеру')
    check('CARD: сказано, во что обойдётся вход на $100k', 'Вход на $100k' in txt)
    check('CARD: возраст котировки числом', 'Котировка обновлена' in txt)
    check('CARD: уверенность числом', 'Уверенность:' in txt)
    check('CARD: есть список того, чего алерт НЕ проверял',
          'Что алерт НЕ проверял' in txt and 'новость дозорный не читает' in txt)
    check('CARD: источник назван', 'Variational Omni' in txt and 'metadata/stats' in txt)
    check('CARD: ссылка только на корень площадки (путь к инструменту НЕ измерен)',
          txt.rstrip().endswith('https://omni.variational.io/'), txt[-80:])
    check('CARD: разметки нет (в тикерах живут звёздочки и подчёркивания)',
          '*' not in txt and '_' not in txt.replace('funding_rate', '').replace(
              'metadata/stats', ''), 'markdown сломался бы на самых интересных строках')
    check('CARD: деньги None показываются словом, а не $0',
          cards._usd(None) == 'нет данных')


def t_ignition_counts_wallets_not_trades_and_first_poll_is_silent():
    """ЗАЖИГАНИЕ: считаем РАЗНЫЕ адреса; первый опрос только заводит границу."""
    now = 1800000000

    def trade(tx, who, usd=100000, sym='PEPE', addr='0xtok', mcap=2e8, ts=None):
        return {'transaction_hash': tx, 'trader_address': who, 'trader_address_label': 'Fund ' + who[-1],
                'token_bought_symbol': sym, 'token_bought_address': addr, 'chain': 'ethereum',
                'trade_value_usd': usd, 'token_bought_market_cap': mcap,
                'token_bought_age_days': 400,
                'block_timestamp': _iso(ts or (now - 600))}
    many_one = [trade('0x1', '0xaaa1'), trade('0x2', '0xaaa1'), trade('0x3', '0xaaa1')]
    evs, note = ignition.scan(now=now, fetch=lambda: many_one)
    check('IGN: первый опрос НЕ алертит', not evs and 'первый опрос' in note, note)
    evs, note = ignition.scan(now=now + 60, fetch=lambda: many_one)
    check('IGN: три сделки ОДНОГО адреса - не зажигание', not evs, note)
    three = many_one + [trade('0x4', '0xbbb2'), trade('0x5', '0xccc3')]
    evs, note = ignition.scan(now=now + 120, fetch=lambda: three)
    check('IGN: три РАЗНЫХ адреса - зажигание', len(evs) == 1, note)
    ev = evs[0]
    check('IGN: доля от капитализации посчитана',
          ev['payload']['mcap_bps'] and ev['payload']['mcap_bps'] > 0,
          ev['payload']['mcap_bps'])
    check('IGN: ключ события построен на КОНТРАКТЕ, а не на тикере',
          ev['key'] == detector.key('ignition', 'ethereum:0xtok',
                                    detector._window(now + 120),
                                    ev['payload']['step']),
          'однофамильцы с одним тикером склеились бы в одно «зажигание»')
    check('IGN: повтор той же ленты нового события не даёт',
          not ignition.scan(now=now + 180, fetch=lambda: three)[0])
    # СВАП В СТЕЙБЛ - ЭТО ВЫХОД, А НЕ ВХОД
    outs = [trade('0x%d' % i, '0xddd%d' % i, sym='USDC', addr='0xusdc') for i in range(5)]
    evs2, _ = ignition.scan(now=now + 240, fetch=lambda: outs)
    check('IGN: покупка стейбла не считается заходом', not evs2,
          'массовая фиксация прибыли выглядела бы как приток')
    txt = cards.card(ev)
    check('IGN: карточка ведёт числом адресов и суммой',
          '3 разных адреса' in txt and 'капитализации' in txt, txt[:160])
    check('IGN: и называет сеть с контрактом', '0xtok' in txt and 'ethereum' in txt)


def t_delivery_dedupe_cooldown_cap_and_state():
    """ДОСТАВКА: дедупликация в базе, пауза после успеха, потолок числом, состояние честное."""
    now = int(time.time())
    store.sub_add(UID, 'BTC')
    store.settings_set(UID, alerts_on=1, enrich_on=0)
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 100.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    ev = [e for e in detector.detect(one(mark='104.0', quote_iso=_iso(now)), hot, now=now,
                                     ring=ring) if e['kind'] == 'move_up'][0]
    check('DB: событие записалось', store.event_new(ev) is True)
    check('DB: ПОВТОР того же ключа отбит БАЗОЙ, а не памятью процесса',
          store.event_new(ev) is False,
          'память обнуляется рестартом - после деплоя пришёл бы повтор всех событий')
    n, why = outbox.plan(ev)
    check('PLAN: подписчику поставлена доставка', n == 1, (n, why))
    check('PLAN: повторная постановка не удваивает', outbox.plan(ev)[0] == 0)

    bad = FakeBot(fail=True)
    attach(bad)
    ok, err = asyncio.run(outbox.deliver_due())
    check('SEND: отказ Telegram не считается доставкой', ok == 0 and err == 1, (ok, err))
    st = store.delivery_state(ev['key'], UID)
    check('SEND: «доставлено» НЕ поставлено при сбое', st and st['delivered_at'] is None, st)
    check('SEND: причина сбоя записана словами', st and st['last_err'], st)
    check('SEND: пауза НЕ съедена сбоем',
          store.cooldown_left(UID, 'BTC', 'move_up:1') == 0,
          'иначе человек не получил алерт И не получит следующий')

    good = FakeBot()
    attach(good)
    ok, err = asyncio.run(outbox.deliver_due())
    check('SEND: после ретрая алерт ушёл', ok == 1 and len(good.sent) == 1, (ok, err))
    check('SEND: ушёл ИМЕННО подписчику', good.sent[0][0] == UID, good.sent[0][0])
    check('SEND: в тексте есть величина', '+4.00%' in good.sent[0][1])
    check('SEND: теперь пауза отмечена', store.cooldown_left(UID, 'BTC', 'move_up:1') > 0)
    check('SEND: суточный счётчик считает ДОСТАВЛЕННЫЕ', store.sent_today(UID) == 1)

    # ПАУЗА ПО ПАРЕ (ИНСТРУМЕНТ, ВИД): второе такое же событие в очередь не попадает
    ev2 = dict(ev, key=ev['key'] + 'x', ts=now + 10)
    store.event_new(ev2)
    n2, why2 = outbox.plan(ev2)
    check('COOLDOWN: то же движение в паузе не отправляется', n2 == 0, (n2, why2))
    check('COOLDOWN: и причина называет остаток паузы',
          any('пауза' in w for w in why2), why2)

    # ПОТОЛОК ЧИСЛОМ
    store.settings_set(UID, daily_cap=1)
    ev3 = dict(ev, key=ev['key'] + 'y', ts=now + 20,
               payload=dict(ev['payload'], step=9))
    store.event_new(ev3)
    n3, why3 = outbox.plan(ev3)
    check('CAP: упор в потолок отсекает', n3 == 0, (n3, why3))
    check('CAP: и печатается ВЕЛИЧИНОЙ, а не флагом',
          any('потолок 1/1' in w for w in why3), why3)
    store.settings_set(UID, daily_cap=None)


def t_two_subscribers_each_get_only_their_own():
    """ДВА ПОДПИСЧИКА: доставка — свойство ЧЕЛОВЕКА, а не события."""
    now = int(time.time())
    store.sub_add(UID2, 'ETH')
    store.settings_set(UID2, alerts_on=1, enrich_on=0)
    ring = series(60, now - 60 * 900)
    hot = [(now - 900, 200.0, 8e8, 1000.0, 900.0, 0.05, 1.0, now - 900)]
    ev = [e for e in detector.detect(one(ticker='ETH', name='Ethereum', mark='208.0',
                                         quote_iso=_iso(now)), hot, now=now, ring=ring)
          if e['kind'] == 'move_up'][0]
    store.event_new(ev)
    outbox.plan(ev)
    bot = FakeBot()
    attach(bot)
    asyncio.run(outbox.deliver_due())
    check('ADDR: алерт по ETH ушёл только подписчику ETH',
          [c for c, _t in bot.sent] == [UID2], [c for c, _t in bot.sent])
    check('ADDR: подписчик BTC ничего не получил', UID not in [c for c, _t in bot.sent])


def t_quiet_hours_cross_midnight():
    """ТИХИЕ ЧАСЫ: окно через полночь работает (наивная проверка даёт круглосуточную тишину)."""
    s = {'quiet_from': 22, 'quiet_to': 8}
    mid = 1800000000 - (1800000000 % 86400) + 23 * 3600
    day = 1800000000 - (1800000000 % 86400) + 12 * 3600
    check('QUIET: 23:00 внутри окна 22-8', outbox.quiet_now(s, now=mid) is True)
    check('QUIET: 12:00 вне окна 22-8', outbox.quiet_now(s, now=day) is False)
    check('QUIET: окно не задано - молчания нет', outbox.quiet_now({}) is False)


def t_enrichment_never_blocks_the_numbers():
    """ОБОГАЩЕНИЕ: второе сообщение, только доставленным, провал не трогает первое."""
    now = int(time.time())
    store.settings_set(UID, alerts_on=1, enrich_on=1, daily_cap=None)
    key = 'evtest%d' % now
    store.event_new({'key': key, 'ts': now, 'kind': 'move_up', 'ticker': 'BTC',
                     'severity': 80, 'payload': {'mark': 100.0, 'move_pct': 4.0,
                                                 'penalties': []}})
    store.delivery_plan(key, UID)
    bot = FakeBot()
    attach(bot)
    asyncio.run(outbox.deliver_due())
    check('ENRICH: сводку ждут только доставленные',
          key in store.enrich_pending(limit=10), store.enrich_pending(limit=10))
    check('ENRICH: замок на строке не даёт купить сводку дважды',
          store.enrich_claim(key) is True and store.enrich_claim(key) is False)
    brief = {'lines': ['Покупали за сутки:', '  • Fund A — $48000'],
             'refused': 'X: нет ключа TWITTERAPI_IO_KEY', 'summary': '',
             'cost_line': 'Стоимость сводки: 10 кр'}
    n = asyncio.run(outbox.deliver_enrichment(key, brief))
    check('ENRICH: сводка ушла вторым сообщением', n == 1 and len(bot.sent) == 2, bot.sent)
    txt = bot.sent[1][1]
    check('ENRICH: отказ назван КЛАССОМ, а не «не удалось»', 'нет ключа' in txt, txt)
    check('ENRICH: пересказ модели подписан как пересказ, если он есть',
          'Пересказ моделью' not in txt or 'пересказ данных выше' in txt)
    store.settings_set(UID, enrich_on=0)
    n2 = asyncio.run(outbox.deliver_enrichment(key, brief))
    check('ENRICH: выключенные сводки не шлются, а алерты - шлются', n2 == 0)
    store.settings_set(UID, enrich_on=1)


def t_budget_is_a_quantity_and_stops_spending():
    """БЮДЖЕТ: остаток — ВЕЛИЧИНА, и по её исчерпании ончейн не читается вовсе."""
    left0 = store.budget_left()
    check('BUDGET: остаток - число', isinstance(left0, int) and left0 > 0, left0)
    store.spend_add(credits=config.nansen_day_credits())
    check('BUDGET: исчерпан - ноль, а не флаг', store.budget_left() == 0)
    note = asyncio.run(engine.ignition_tick())
    check('BUDGET: зажигание при пустом бюджете не ходит в сеть и говорит почему',
          'бюджет' in note and 'исчерпан' in note, note)
    store.spend_add(credits=-config.nansen_day_credits())


def t_lease_keeps_one_poller():
    """АРЕНДА: два процесса не опрашивают площадку одновременно."""
    check('LEASE: первый берёт', store.lease('t1', ttl=60, owner='A') is True)
    check('LEASE: второй получает отказ', store.lease('t1', ttl=60, owner='B') is False)
    check('LEASE: владелец продлевает свою', store.lease('t1', ttl=60, owner='A') is True)
    store.lease_release('t1', owner='A')
    check('LEASE: после освобождения берёт другой',
          store.lease('t1', ttl=60, owner='B') is True)
    owner, until = store.lease_owner('t1')
    check('LEASE: владелец и срок видны наружу', owner == 'B' and until > time.time())


def t_rings_and_outcome_are_measured_not_told():
    """ДВА КОЛЬЦА И ИСХОД: холодное живёт в базе, исход мерится нашими же снимками."""
    now = int(time.time())
    x = one(ticker='SOL', name='Solana', mark='150.0')
    n = store.snapshot_put([x], ts=now - 3600)
    check('RING: снимок записался', n == 1)
    hist = store.history('SOL', since_ts=now - 7200)
    check('RING: читается по индексу (PG не даёт доступ по имени)',
          hist and hist[0][1] == 150.0, hist[:1])
    store.snapshot_put([one(ticker='SOL', name='Solana', mark='156.0')], ts=now - 60)
    engine._COLD.pop('SOL', None)
    key = 'outc%d' % now
    store.event_new({'key': key, 'ts': now - 3600, 'kind': 'move_up', 'ticker': 'SOL',
                     'severity': 70, 'payload': {'mark': 150.0, 'penalties': []}})
    due = [k for k, _t, _s in store.outcome_due(60, now=now)]
    check('OUTCOME: событие старше горизонта попало в очередь замера', key in due, due[:3])
    asyncio.run(engine.outcome_tick())
    rows = store.outcomes(kind='move_up', horizon_min=60, since_ts=now - 7200)
    got = [r for r in rows if r[0] == key]
    check('OUTCOME: исход записан и посчитан от НАШИХ снимков',
          got and got[0][1] is not None and abs(got[0][1] - 4.0) < 0.2,
          got[:1])
    check('HITRATE: на малой выборке честно отказывает, а не рисует процент',
          'выборка мала' in engine.hit_rate(kind='move_up', horizon_min=60, min_sample=20),
          engine.hit_rate(kind='move_up', horizon_min=60, min_sample=20))


def t_commands_are_parsed_exactly_and_refuse_with_words():
    """КОМАНДЫ: разбор точный, отказ со словом, «дозор» в теле письма ничего не перехватывает."""
    check('CMD: голое «дозор» - состояние', ui.parse('дозор') == ('status', {}))
    check('CMD: тикер добавляет', ui.parse('дозор btc') == ('add', {'ticker': 'BTC'}))
    check('CMD: «всё» - вся площадка',
          ui.parse('дозор всё') == ('add', {'ticker': store.ALL}))
    check('CMD: убрать', ui.parse('дозор убрать ETH') == ('del', {'ticker': 'ETH'}))
    check('CMD: порог', ui.parse('дозор порог 5,5') == ('minpct', {'pct': 5.5}))
    check('CMD: тихие часы', ui.parse('дозор тихо 22 8') == ('quiet', {'from': 22, 'to': 8}))
    check('CMD: чужая фраза - НЕ наша дверь',
          ui.parse('что там по дозору думаешь') is None,
          'подстрочный матч выхватывал бы слово из тела письма')
    check('CMD: «дозор» с мусором отдаёт помощь, а не молчит',
          ui.parse('дозор абракадабра бывает')[0] == 'help')
    r = ui.route(UID, 'дозор ZZZQQ9')
    check('CMD: подписка на несуществующее отбита СЛОВАМИ',
          r and 'нет инструмента' in r, r)
    st = ui.route(UID, 'дозор')
    check('CMD: состояние ведёт величинами, а не флагами',
          st and 'Сегодня доставлено' in st and 'Пороги сейчас' in st, st)
    check('CMD: в помощи сказано, что дозорный не торгует',
          'НЕ торгует' in ui.HELP or 'НЕ советует' in ui.HELP)


def t_no_import_of_the_trading_contour():
    """ГРАНИЦА: ни один файл дозорного не знает про подписанта и торговые маршруты."""
    import re
    bad = []
    d = os.path.join(BASE, 'sentinel')
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.py'):
            continue
        src = open(os.path.join(d, fn), encoding='utf-8').read()
        # ИЩЕМ ИМПОРТЫ И ВЫЗОВЫ, А НЕ УПОМИНАНИЯ В КОММЕНТАРИЯХ: запрет на слово превратил бы
        # объяснение границы в её нарушение.
        for m in re.finditer(r'^\s*(?:import|from)\s+([\w.]+)', src, re.M):
            mod = m.group(1)
            if 'nansen_signer' in mod or mod.startswith('perp.') or mod == 'trade_session':
                bad.append('%s -> %s' % (fn, mod))
        for call in ('prepare_order', 'execute_order', 'place_order', 'sign_order'):
            if re.search(r'\b%s\s*\(' % call, src):
                bad.append('%s -> %s()' % (fn, call))
    check('ISOLATION: торгового контура в дозорном нет', not bad, bad)
    check('ISOLATION: сцены дозорного есть в закрытом реестре телеметрии',
          _scenes_ok(), 'расход дозорного лёг бы в сводку строкой «? N кр»')


def _scenes_ok():
    import nansen_log as t
    return ({'sentinel_watch', 'sentinel_ignition'} <= set(t.SCENES)
            and 'sentinel' in t.SURFACES)


def t_engine_tick_never_throws_and_always_says_something():
    """ТИК: не бросает ни при какой поломке и ВСЕГДА печатает, что произошло."""
    orig = feed.fetch

    def boom():
        raise feed.FeedError('http', 'HTTP 403', http=403)
    feed.fetch = boom
    note = asyncio.run(engine.ingest_tick())
    feed.fetch = orig
    check('TICK: отказ фида назван классом, а не «не получилось»',
          '403' in note and 'площадка не прочитана' in note, note)

    def kaput():
        raise RuntimeError('что угодно')
    feed.fetch = kaput
    note2 = asyncio.run(engine.ingest_tick())
    feed.fetch = orig
    check('TICK: любая другая поломка тоже не роняет джобу',
          'упал' in note2 or 'не прочитана' in note2, note2)
    check('TICK: строка состояния ведёт величинами',
          'инструментов за час' in outbox.status_line(), outbox.status_line())


def main():
    for fn in (t_parse_is_real_and_names_what_is_missing,
               t_detector_needs_both_percent_and_sigma,
               t_event_key_is_stable_and_step_escalates,
               t_oi_funding_and_spread_have_their_own_reasons,
               t_card_leads_with_magnitude_and_admits_limits,
               t_ignition_counts_wallets_not_trades_and_first_poll_is_silent,
               t_delivery_dedupe_cooldown_cap_and_state,
               t_two_subscribers_each_get_only_their_own,
               t_quiet_hours_cross_midnight,
               t_enrichment_never_blocks_the_numbers,
               t_budget_is_a_quantity_and_stops_spending,
               t_lease_keeps_one_poller,
               t_rings_and_outcome_are_measured_not_told,
               t_commands_are_parsed_exactly_and_refuse_with_words,
               t_no_import_of_the_trading_contour,
               t_engine_tick_never_throws_and_always_says_something):
        print('\n== %s' % fn.__name__)
        try:
            fn()
        except Exception as e:
            global _FAIL
            _FAIL += 1
            import traceback
            traceback.print_exc()
            print('FAIL  %s упал: %s' % (fn.__name__, e))
    print('\n%d PASS / %d FAIL' % (_OK, _FAIL))
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
