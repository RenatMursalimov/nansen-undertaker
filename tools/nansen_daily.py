#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/nansen_daily.py — суточная сводка расхода Nansen и выгрузка за период.

ЗАЧЕМ ОТДЕЛЬНЫЙ ПРИБОР. Числа за конкурс собираются каждый день, и собрать их постфактум
неоткуда: строка `[nansen]` в bot.log печаталась ТОЛЬКО при ошибке, то есть у нас был
знаменатель без числителя. Телеметрия пишет строку на КАЖДЫЙ вызов (nansen_log), а этот
скрипт её читает.

ПРИБОР, КОТОРЫЙ ПИШЕТ НОЛЬ СТРОК, И ПРИБОР, КОТОРЫЙ ВИДИТ НОЛЬ ВЫЗОВОВ, СНАРУЖИ ОДИНАКОВЫ.
Поэтому файла нет - печатаем «ВЕРДИКТА НЕТ» с причиной и выходим КОДОМ 2, а не рисуем нули:
ноль запросов и несобравшаяся телеметрия требуют противоположных действий.

В `--csv` не идёт ни одного идентификатора человека - только числа. Это и есть та выгрузка,
которая уезжает в сабмишен и в статью.

Запуск:
    ./venv/bin/python3 tools/nansen_daily.py                          # за вчера
    ./venv/bin/python3 tools/nansen_daily.py 2026-09-20               # за дату
    ./venv/bin/python3 tools/nansen_daily.py --range 2026-09-15 2026-09-27
    ./venv/bin/python3 tools/nansen_daily.py --range 2026-09-15 2026-09-27 --csv
    ./venv/bin/python3 tools/nansen_daily.py --contrib                # вклад людей, агрегаты
"""

import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nansen_log as T          # noqa: E402


def _days(a, b):
    d0 = dt.date.fromisoformat(a)
    d1 = dt.date.fromisoformat(b)
    if d1 < d0:
        d0, d1 = d1, d0
    out = []
    while d0 <= d1:
        out.append(d0.isoformat())
        d0 += dt.timedelta(days=1)
    return out


def main(argv):
    args = [a for a in argv[1:]]
    as_csv = '--csv' in args
    contrib = '--contrib' in args
    args = [a for a in args if not a.startswith('--') or a == '--range']

    if '--range' in args:
        i = args.index('--range')
        try:
            days = _days(args[i + 1], args[i + 2])
        except (IndexError, ValueError) as e:
            print('нужны две даты: --range 2026-09-15 2026-09-27 (%s)' % e)
            return 1
    elif args:
        try:
            dt.date.fromisoformat(args[0])
        except ValueError:
            print('дата в формате YYYY-MM-DD, а не %r' % args[0])
            return 1
        days = [args[0]]
    else:
        days = [T._day(__import__('time').time() - 86400)]      # по умолчанию за вчера

    if as_csv:
        rows = T.csv_rows(days)
        if len(rows) <= 1:
            print('ВЕРДИКТА НЕТ: ни одного файла телеметрии за %s..%s (каталог %s)'
                  % (days[0], days[-1], T.TELE_DIR), file=sys.stderr)
            return 2
        w = csv.writer(sys.stdout)
        for r in rows:
            w.writerow(r)
        return 0

    if contrib:
        tot = T.contrib_totals(T.CONTEST_DAYS)
        print('Вклад людей за %d дней (ни одного идентификатора, только счётчики):'
              % T.CONTEST_DAYS)
        print('  человек: %d' % tot['people'])
        print('  вызовов в зачёт: %d' % tot['calls'])
        print('  кредитов: %d' % int(tot['credits']))
        print('  не в зачёт (повторы одного запроса чаще %d мин): %d'
              % (T.REPEAT_MIN, tot['skipped']))
        if tot['by_scene']:
            print('  по сценариям:')
            for sc, (n, cr) in sorted(tot['by_scene'].items(), key=lambda kv: -kv[1][0]):
                print('    %-22s вызовов %-6d кредитов %d' % (sc, n, int(cr)))
        else:
            print('  по сценариям: ни одного вызова с человеком за окно')
        print('\nМеста (без имён и без ID):')
        board = T.leaderboard(T.CONTEST_DAYS, top=20)
        for place, calls, cr, sc in board:
            print('  %2d. кредитов %-7d сценариев %-3d вызовов %d'
                  % (place, int(cr), sc, calls))
        if not board:
            print('  пусто')
        return 0

    missing = 0
    for d in days:
        txt = T.daily_text(d)
        print(txt)
        print('')
        if 'ВЕРДИКТА НЕТ' in txt:
            missing += 1
    # СУММА ЗА ПЕРИОД СОБИРАЕТСЯ ИЗ НАПЕЧАТАННЫХ СУТОК, а не отдельным счётчиком: оба вранья
    # `transport_probe` пришли ровно оттуда - вердикт считался мимо выведенной ленты.
    if len(days) > 1:
        got = [T.summary(d) for d in days]
        got = [s for s in got if s]
        if got:
            print('ЗА ПЕРИОД %s..%s (суток с данными %d из %d):'
                  % (days[0], days[-1], len(got), len(days)))
            print('  запросов %d, по сети %d, кредитов %d'
                  % (sum(s['calls'] for s in got), sum(s['net'] for s in got),
                     sum(s['credits'] for s in got)))
            print('  сбоев %d, пустых ответов %d, вызовов без сцены %d'
                  % (sum(s['fail'] for s in got), sum(s['empty'] for s in got),
                     sum(s['noscene'] for s in got)))
    return 2 if missing == len(days) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
