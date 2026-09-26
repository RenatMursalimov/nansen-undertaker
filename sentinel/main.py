# -*- coding: utf-8 -*-
"""sentinel/main.py — ОТДЕЛЬНЫЙ ПРОЦЕСС дозорного: тот же домен, свой цикл и свой юнит.

ЗАЧЕМ ОТДЕЛЬНЫЙ ПРОЦЕСС, ЕСЛИ ДЖОБЫ В БОТЕ УЖЕ РАБОТАЮТ. Три измеренные причины, ни одна не
про эстетику:
  1. ДЕПЛОЙ. Обновление бота = рестарт службы, а горячее кольцо живёт в памяти: после каждого
     `git pull` дозорный терял бы 90 минут истории и молчал бы, пока не наберёт заново.
  2. ОБЩИЙ ЦИКЛ. В боте живут Telethon, PTB и несколько десятков джоб; пропуски там уже
     случались (сторож `jobs_registry` для этого и заведён). Опрос раз в 15 секунд к такому
     соседству не подходит.
  3. ОТВЕТСТВЕННОСТЬ. Упавший дозорный не должен ронять бота, а упавший бот не должен
     прекращать наблюдение за рынком.

ДОМЕН НЕ ДУБЛИРУЕТСЯ: этот файл зовёт ТЕ ЖЕ функции `engine.*`, что и планировщик бота.
Единственное, что здесь есть своего, — расписание и корректное завершение.

АРЕНДА ДЕЛАЕТ ПЕРЕЕЗД БЕЗОПАСНЫМ. В момент переключения живы оба (бот со своими джобами и
этот юнит), и без аренды они удвоили бы запросы к площадке (лимит 10/10с с адреса) и записали
бы кольцо вразнобой. `store.lease` отдаёт опрос ровно одному; второй честно печатает, у кого
аренда, и ничего не делает.

Запуск вручную:
    ./venv/bin/python3 -m sentinel.main               # цикл
    ./venv/bin/python3 -m sentinel.main --once        # один круг всего и выход
    ./venv/bin/python3 -m sentinel.main --status      # строка состояния и выход
Юнит: см. nansen/SENTINEL_SPEC.md (раздел «Как это ставится на сервер»).
"""

import asyncio
import os
import signal
import sys
import time

# ЗАКОН №6: окружение одним резолвером, своих путей к .env не заводим.
try:
    import env_load
    env_load.load()
except Exception as _e:
    print('[sentinel] env_load недоступен (%s) - работаю на экспортированном окружении'
          % str(_e)[:80])

from . import config, engine, outbox, store   # noqa: E402

_STOP = False


def _bye(signum, frame):
    """Сигнал -> мягкое завершение. Аренду отдаём САМИ, чтобы следующий владелец не ждал её
    истечения: пауза в опросе после штатного рестарта — потерянные данные без причины."""
    global _STOP
    _STOP = True
    print('[sentinel] получен сигнал %s - завершаюсь' % signum)


#: ═══ СТОРОЖ ПРОЦЕССА (этап 5, ТЗ 5.1) ═══
#: Отдельный ПОТОК, а не проверка в цикле: зависший сетевой вызов держит и сам цикл, и
#: проверка внутри него не выполнилась бы никогда - ровно тот случай, ради которого сторож и
#: нужен. Поток раз в poll_sec сверяет пульс (`engine.HEARTBEAT`) и при вердикте
#: `engine.watchdog_verdict` завершает процесс кодом 3; `Restart=always` в юните поднимает его.
#: `os._exit`, а не `sys.exit`: из потока `sys.exit` завершил бы только поток.
WATCHDOG_EXIT_CODE = 3


def _watchdog(started):
    import threading

    def _run():
        while not _STOP:
            time.sleep(max(5, config.poll_sec()))
            why = engine.watchdog_verdict(time.time(), started)
            if why and not _STOP:
                print('[sentinel] СТОРОЖ: %s - завершаюсь с кодом %d, юнит поднимет заново'
                      % (why, WATCHDOG_EXIT_CODE), flush=True)
                os._exit(WATCHDOG_EXIT_CODE)
    t = threading.Thread(target=_run, name='sentinel-watchdog', daemon=True)
    t.start()
    return t


#: ПОТОЛОК НА ОДИН ТИК ЦИКЛА, секунды: зависший тик не держит остальные (этап 5).
TICK_TIMEOUT_S = int(os.getenv('SENTINEL_TICK_TIMEOUT_SEC') or 240)


async def _tick(name, fn):
    try:
        return await asyncio.wait_for(fn(), timeout=TICK_TIMEOUT_S)
    except asyncio.TimeoutError:
        return '%s: не уложился в %d с - пропущен' % (name, TICK_TIMEOUT_S)


async def loop():
    last = {'ignition': 0, 'enrich': 0, 'outcome': 0, 'prune': 0, 'health': 0, 'digest': 0}
    #: ТЕМПЫ РАЗНЫЕ, И КАЖДЫЙ ОБОСНОВАН. Площадка — 15с (её лимит 10/10с, наш запрос один).
    #: Зажигание — 3 минуты: оно стоит кредитов, и чаще смысла нет (лента Nansen трейлинговая
    #: и обновляется не мгновенно). Сводки — минута. Исходы и уборка — раз в час.
    every = {'ignition': int(os.getenv('SENTINEL_IGN_SEC') or 180),
             'enrich': 60, 'outcome': 900, 'prune': 3600, 'health': 600,
             # СВОДКА - РАЗ В МИНУТУ, А НЕ РАЗ В ПЕРИОД (этап 4): период теперь личный (10-60
             # мин по пресету), и кому пора, решает `store.digest_due` по каждому человеку.
             'digest': 60}
    # СТРОКА СТАРТА НЕ ВРЁТ ПРО БЮДЖЕТ. Ноль капа значит «потолка нет» (решение владельца на
    # время хакатона), и печатать «бюджет 0 кр/сутки» означало бы сообщить человеку прямо
    # противоположное - что дозорный в Nansen не пойдёт вовсе.
    _cap = config.nansen_day_credits()
    print('[sentinel] старт: опрос каждые %dс, зажигание каждые %dс, бюджет Nansen %s, '
          'предохранитель %d сообщений / %d мин, порог звонка %d/100'
          % (config.poll_sec(), every['ignition'],
             ('без потолка' if _cap <= 0 else '%d кр/сутки' % _cap),
             config.burst_max(), config.burst_window_sec() // 60, config.min_severity()))
    if not config.deliver_on():
        # АВАРИЙНЫЙ РУБИЛЬНИК ОБЪЯВЛЯЕТСЯ ГРОМКО. Молчащая отправка при живом наблюдении
        # выглядит как поломка, и первым, кто будет это отлаживать, станет человек, который сам
        # её и выключил месяц назад.
        print('[sentinel] ВНИМАНИЕ: SENTINEL_DELIVER=0 - наблюдаю и пишу очередь, НЕ ОТПРАВЛЯЮ')
    _watchdog(time.time())
    while not _STOP:
        t0 = time.time()
        print('[sentinel] %s' % await _tick('ingest', engine.ingest_tick))
        print('[sentinel] %s' % await _tick('deliver', engine.deliver_tick))
        now = time.time()
        for name, fn in (('ignition', engine.ignition_tick), ('enrich', engine.enrich_tick),
                         ('digest', engine.digest_tick),
                         ('outcome', engine.outcome_tick), ('prune', engine.prune_tick)):
            if now - last[name] >= every[name]:
                last[name] = now
                print('[sentinel] %s: %s' % (name, await _tick(name, fn)))
        if now - last['health'] >= every['health']:
            last['health'] = now
            print('[sentinel] %s' % outbox.status_line())
        # СПИМ ОСТАТОК, А НЕ ФИКСИРОВАННЫЙ ИНТЕРВАЛ: иначе медленный круг складывался бы с
        # паузой, и реальный темп опроса уезжал бы вдвое от заявленного.
        await asyncio.sleep(max(1.0, config.poll_sec() - (time.time() - t0)))
    store.lease_release('variational')
    print('[sentinel] аренда отдана, выход')


async def once():
    for name, fn in (('ingest', engine.ingest_tick), ('ignition', engine.ignition_tick),
                     ('deliver', engine.deliver_tick), ('enrich', engine.enrich_tick),
                     ('digest', engine.digest_tick), ('outcome', engine.outcome_tick)):
        print('[sentinel] %s: %s' % (name, await fn()))
    print('[sentinel] %s' % outbox.status_line())


def main(argv=None):
    # ЮНИТ САМ ОБЪЯВЛЯЕТ СЕБЯ ОПРАШИВАЮЩИМ. Строка в `.env` может отсутствовать
    # (человек забыл), и тогда опрос вели бы двое: один из них постоянно
    # проигрывал бы аренду и писал об этом в лог. Здесь переменная ставится в
    # СВОЁМ процессе - на бота это не влияет, он читает свою.
    # РОЛЬ - ГЛАВНАЯ ИЗ ДВУХ СТРОК. Именно её читает `engine._ingest`; прежний `SENTINEL_IN_BOT`
    # отвечал на вопрос «где идёт опрос», и юнит, честно ответив «не в боте», исключал сам себя
    # (разбор в `config.role`). Флаг оставлен ради совместимости с `.env` на проде.
    os.environ.setdefault('SENTINEL_ROLE', config.ROLE_POLLER)
    os.environ.setdefault('SENTINEL_IN_BOT', '0')
    argv = list(argv if argv is not None else sys.argv[1:])
    tok = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('BOT_TOKEN')
    if tok:
        outbox.configure(tok)
    else:
        # ГОВОРИМ ВСЛУХ, А НЕ ПАДАЕМ И НЕ МОЛЧИМ: без токена наблюдение работает, а отправка
        # нет, и очередь будет копиться. Это рабочий режим для стенда, но человек обязан знать.
        print('[sentinel] токена бота нет: наблюдаю и пишу очередь, отправлять не смогу')
    if '--status' in argv:
        print(outbox.status_line())
        return 0
    signal.signal(signal.SIGTERM, _bye)
    signal.signal(signal.SIGINT, _bye)
    asyncio.run(once() if '--once' in argv else loop())
    return 0


if __name__ == '__main__':
    sys.exit(main())
