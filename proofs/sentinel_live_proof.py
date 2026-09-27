"""ЖИВОЕ ДОКАЗАТЕЛЬСТВО ДОЗОРНОГО: настоящий ответ Variational -> настоящая карточка алерта.

ЗАЧЕМ ЭТОТ ФАЙЛ ОТДЕЛЬНО ОТ ТЕСТОВ. Тесты кормят детектор синтетическим рядом, где правильный
ответ известен заранее, — это правильно для инварианта и НЕ доказывает, что живой ответ
площадки вообще разбирается. Здесь наоборот: сеть настоящая, разбор настоящий, карточка
настоящая. Единственное, что подставлено, — САМО ДВИЖЕНИЕ: ждать реального выброса по
конкретному тикеру ради демонстрации бессмысленно, поэтому цена одного инструмента сдвигается
на заданный процент, а всё остальное (объём, открытый интерес, спред, ёмкость на $100k,
возраст котировки) берётся из живого ответа как есть.

ЧТО ЭТО ДОКАЗЫВАЕТ:
  1. публичная ручка отвечает и её форма нам понятна (553 инструмента одним запросом);
  2. кольцо, детектор и карточка сходятся на живых числах, а не только на фикстуре;
  3. карточка называет свежесть котировки и ёмкость — то есть то, что определяет, можно ли
     по этому алерту вообще зайти руками.

Запуск:  python3 proofs/sentinel_live_proof.py [ТИКЕР] [ПРОЦЕНТ]   (в боте: nansen/proofs/...)
Пример:  python3 proofs/sentinel_live_proof.py BTC 4.5

ПЛЮС ЧИСЛО ИНСТРУМЕНТОВ НА КАЖДОЙ ПЛОЩАДКЕ, ЖИВЬЁМ. В README стояли «553 / 234 / 210», и
только у первого числа был механизм (датированная фикстура). Число, которое нельзя повторить,
хуже отсутствия числа (закон №22), поэтому здесь его печатает тот же `venues.fetch_all`, по
которому работает дозорный: ровно те инструменты, что попадают в кольцо (у Lighter - активные
и не замороженные).
Сеть нужна (только Variational, без ключей и без Nansen — кредиты не тратятся).
"""
import os
import sys
import time

# КОРЕНЬ - ТАМ, ГДЕ ЛЕЖИТ ПАКЕТ `sentinel`, а не на фиксированной глубине. В боте файл лежит в
# `nansen/proofs/` (корень тремя уровнями выше), в публичной выжимке - в `proofs/` (двумя), и
# фиксированная глубина роняла выжимку `ModuleNotFoundError: sentinel` (аудит 27.09, A3).
BASE = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(BASE, 'sentinel')) and os.path.dirname(BASE) != BASE:
    BASE = os.path.dirname(BASE)
sys.path.insert(0, BASE)

from sentinel import cards, detector                      # noqa: E402
from sentinel import variational_feed as feed             # noqa: E402
from sentinel import venues                               # noqa: E402

TICKER = (sys.argv[1] if len(sys.argv) > 1 else 'BTC').upper()
SHIFT = float(sys.argv[2]) if len(sys.argv) > 2 else 4.5


def venue_counts():
    """Сколько инструментов дозорный видит на каждой площадке сейчас. -> {площадка: int|отказ}."""
    import asyncio
    # ВСЕ ПЛОЩАДКИ С ЧТЕНИЕМ ИЗ РЕЕСТРА, а не `enabled()`: доказательство меряет площадки, а не
    # то, что включено в окружении этой машины.
    _all = tuple(v for v, d in venues.VENUES.items() if d.get('fetch'))
    rows, notes = asyncio.run(venues.fetch_all(_all))
    out = {}
    for v in _all:
        n = notes.get(v)
        out[v] = (sum(1 for r in rows if getattr(r, 'venue', None) == v)
                  if not isinstance(n, Exception) else 'не прочитана: %s' % n)
    return out


def main():
    t0 = time.time()
    print('ПЛОЩАДКИ СЕЙЧАС (%s UTC):' % time.strftime('%Y-%m-%d %H:%M', time.gmtime()))
    for v, n in venue_counts().items():
        print('  %-12s %s' % (venues.title(v), ('%d инструментов в дозоре' % n)
                                                 if isinstance(n, int) else n))
    try:
        rows, meta = feed.fetch()
    except feed.FeedError as e:
        # БЕЗ СЕТИ - ПРИЧИНА СЛОВАМИ, А НЕ ТРЕЙСБЕК: «площадка не ответила» и «доказательство
        # сломано» - разные новости.
        print('\nVariational не ответила (%s): живую карточку собрать не из чего.' % e)
        return 2
    print('ЖИВОЙ ОТВЕТ: %d инструментов, %d байт, %d мс' %
          (len(rows), meta.get('bytes') or 0, meta.get('latency_ms') or 0))
    print('Площадка целиком: объём 24ч $%.2fB · открытый интерес $%.2fB · TVL $%.0fM' %
          ((meta.get('total_volume_24h') or 0) / 1e9, (meta.get('open_interest') or 0) / 1e9,
           (meta.get('tvl') or 0) / 1e6))
    by = {r.ticker: r for r in rows}
    if TICKER not in by:
        print('На площадке нет %s. Есть, например: %s'
              % (TICKER, ', '.join(sorted(by)[:12])))
        return 1
    x = by[TICKER]
    print('\n%s (%s): марк %s · оборот $%.1fM · спред %s б.п. · котировке %s с · класс %s'
          % (x.ticker, x.name, x.mark, (x.volume_24h or 0) / 1e6, x.spread_bps,
             int(x.quote_age() or -1), feed.asset_class(x)))

    now = int(time.time())
    # ХОЛОДНОЕ КОЛЬЦО СОБИРАЕМ ИЗ ЖИВОЙ ЦЕНЫ С НЕБОЛЬШИМ ДРОЖАНИЕМ: сигма должна быть не
    # нулевой, иначе доказательство показало бы путь «сигма неприменима», а не обычный.
    ring = []
    for i in range(60):
        jitter = 1.0 + ((i % 5) - 2) * 0.0008
        ring.append((now - (60 - i) * detector.W15, x.mark * jitter, x.volume_24h,
                     x.oi_long, x.oi_short, x.funding_raw, x.spread_bps, now))
    hot = [(now - detector.W15, x.mark, x.volume_24h, x.oi_long, x.oi_short,
            x.funding_raw, x.spread_bps, now)]

    moved = feed.Listing(ticker=x.ticker, name=x.name, mark=x.mark * (1 + SHIFT / 100.0),
                         volume_24h=x.volume_24h, oi_long=x.oi_long, oi_short=x.oi_short,
                         funding_raw=x.funding_raw,
                         funding_interval_s=x.funding_interval_s, spread_bps=x.spread_bps,
                         quote_ts=x.quote_ts, quotes=x.quotes, missing=x.missing)
    evs = detector.detect(moved, hot, now=now, ring=ring)
    if not evs:
        print('\nДвижение %.2f%% порога не прошло (порог 15м: %.1f%%). Это тоже результат.'
              % (SHIFT, __import__('sentinel.config', fromlist=['x']).move_pct_15m()))
        return 0
    for ev in evs:
        print('\n' + '─' * 72)
        print(cards.card(ev))
    print('\n' + '─' * 72)
    print('Всё вместе заняло %.2f с. Кредитов Nansen сожжено: 0 (ручка площадки бесплатна).'
          % (time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
