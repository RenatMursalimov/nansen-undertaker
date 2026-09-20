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
    ./venv/bin/python3 tools/nansen_daily.py --submission 2026-09-15 2026-09-27  # блок в заявку
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


def _submission(days):
    """ГОТОВЫЙ БЛОК ЧИСЕЛ ДЛЯ ЗАЯВКИ, собранный из ТОГО ЖЕ лога, что и суточные сводки.

    ЗАЧЕМ ОТДЕЛЬНЫЙ РЕЖИМ, ЕСЛИ ЕСТЬ `--range`. `--range` печатает ленту суток для ЧЕЛОВЕКА,
    который разбирается; в заявку нужен короткий блок, который можно вставить и который
    ПРОВЕРЯЕМ: каждое число здесь пересчитывается из файлов телеметрии одной командой. Это и
    есть главное отличие от «мы активно пользовались API» - утверждение против таблицы.

    ЧИСЛА, КОТОРЫХ МЫ НЕ ИЗМЕРИЛИ, НЕ ПОДСТАВЛЯЮТСЯ. Цена части эндпоинтов в официальном
    списке не названа, и такие вызовы идут ОТДЕЛЬНОЙ строкой «с неизвестной ценой», а не
    подмешиваются в сумму кредитов. Красивая сумма, собранная из догадок, - ровно то, чего
    этот прибор не должен делать (закон №22).

    НИ ОДНОГО ИДЕНТИФИКАТОРА ЧЕЛОВЕКА: только счётчики и места. Блок уезжает наружу.
    """
    got = [s for s in (T.summary(d) for d in days) if s]
    if not got:
        print('ВЕРДИКТА НЕТ: ни одного файла телеметрии за %s..%s (каталог %s). '
              'Это НЕ «ноль запросов» - это несобравшийся прибор.'
              % (days[0], days[-1], T.TELE_DIR), file=sys.stderr)
        return 2
    _calls = sum(s['calls'] for s in got)
    _net = sum(s['net'] for s in got)
    _cr = sum(s['credits'] for s in got)
    _fail = sum(s['fail'] for s in got)
    _empty = sum(s['empty'] for s in got)
    _nos = sum(s['noscene'] for s in got)
    # КЛЮЧ `unpriced`, А НЕ ПРИДУМАННЫЙ: сводка называет его так, и `.get` с чужим именем
    # молча отдавал бы ноль - то есть строка «вызовов с неизвестной ценой» ВСЕГДА была бы
    # нулевой, и мы бы решили, что цена известна вся. Тихая ложь в самом проверяемом месте.
    _unk = sum(s.get('unpriced', 0) for s in got)
    _honest = sum(s.get('honest_refusals', 0) for s in got)
    _rem = [s.get('rem_last') for s in got if s.get('rem_last') is not None]
    tot = T.contrib_totals(len(days))
    # ═══ ДВА ИСТОЧНИКА ЧИСЕЛ, И ИХ НАДО РАЗДЕЛИТЬ ЯВНО ═══
    # Живой прогон 20.09 напечатал в одном блоке «кредитов 3044» и тут же таблицу сцен, где
    # сумма 3628. Оба числа верные и оба про разное: телеметрия считает ВСЕ вызовы (включая
    # фоновые джобы и вызовы без человека), а зачёт вклада - только те, у которых есть человек
    # и которые прошли антинакрутку. Но стоя рядом без подписи, они выглядят как арифметическая
    # ошибка - и человек перестаёт верить ОБОИМ. Это хуже, чем одно неверное число.
    #
    # Поэтому таблица по сценам берётся ИЗ ТЕХ ЖЕ СУТОЧНЫХ СВОДОК, что и итог сверху (закон
    # №48: итог собирается из напечатанных чисел), а числа зачёта уезжают в свой раздел со
    # своей подписью.
    per_scene = {}
    for sc_map in (s.get('per_scene') or {} for s in got):
        for sc, v in sc_map.items():
            acc = per_scene.setdefault(sc, {'calls': 0, 'credits': 0, 'unpriced': 0})
            acc['calls'] += v.get('calls', 0)
            acc['credits'] += int(v.get('credits', 0))
            acc['unpriced'] += v.get('unpriced', 0)
    print('=== БЛОК В ЗАЯВКУ (пересчитывается этой же командой) ===')
    print('Окно: %s..%s (суток с данными %d из %d)' % (days[0], days[-1], len(got), len(days)))
    print('')
    print('Запросов к Nansen:        %d' % _calls)
    print('  из них по сети:         %d' % _net)
    print('  из них из кэша:         %d' % (_calls - _net))
    print('Кредитов (измерено):      %d' % _cr)
    if _unk:
        # ОТДЕЛЬНОЙ СТРОКОЙ, А НЕ В СУММЕ: «184 вызова с неизвестной ценой» полезнее
        # красивого итога, собранного из догадок.
        print('  вызовов с НЕизвестной ценой (в сумму не вошли): %d' % _unk)
    print('Сбоев всего:              %d' % _fail)
    print('  из них с НАЗВАННОЙ причиной: %d' % _honest)
    print('Пустых ответов (200, данных нет): %d' % _empty)
    print('Вызовов без сцены:        %d' % _nos)
    if _rem:
        print('Остаток кредитов на конце окна: %s' % _rem[-1])
    print('')
    print('По сценариям — ВСЕ вызовы, из тех же сводок, что итог выше')
    print('(сцена = вопрос человека, а не имя эндпоинта):')
    _sum_calls = _sum_cr = 0
    for sc, v in sorted(per_scene.items(), key=lambda kv: -kv[1]['calls']):
        _nm = sc if sc != '?' else '? (без сцены)'
        _tail = (' · без цены %d' % v['unpriced']) if v['unpriced'] else ''
        print('  %-24s вызовов %-6d кредитов %-6d%s' % (_nm, v['calls'], v['credits'], _tail))
        _sum_calls += v['calls']
        _sum_cr += v['credits']
    # СВЕРКА ПЕЧАТАЕТСЯ, А НЕ ПОДРАЗУМЕВАЕТСЯ: если таблица и итог разойдутся, это будет видно
    # В САМОМ БЛОКЕ, а не обнаружится тем, кто станет складывать столбик руками.
    if (_sum_calls, _sum_cr) != (_calls, _cr):
        print('  ⚠️ СВЕРКА НЕ СОШЛАСЬ: по сценам %d вызовов / %d кредитов против %d / %d '
              'в итоге. Числу верить нельзя, пока это не объяснено.'
              % (_sum_calls, _sum_cr, _calls, _cr))
    else:
        print('  сходится с итогом: %d вызовов, %d кредитов' % (_sum_calls, _sum_cr))
    print('')
    print('--- ЗАЧЁТ ВКЛАДА (другой счёт: ТОЛЬКО вызовы людей, прошедшие антинакрутку) ---')
    print('Людей в зачёте:           %d' % tot['people'])
    print('Вызовов в зачёт:          %d' % tot['calls'])
    print('Кредитов в зачёте:        %d' % int(tot['credits']))
    print('Не в зачёт (антинакрутка, повтор чаще %d мин): %d' % (T.REPEAT_MIN, tot['skipped']))
    print('Эти числа МЕНЬШЕ итога сверху и должны быть меньше: фоновые джобы и вызовы без')
    print('человека в зачёт не идут вовсе.')
    print('')
    print('Проверить: ./venv/bin/python3 tools/nansen_daily.py --range %s %s --csv'
          % (days[0], days[-1]))
    print('В выгрузке нет ни одного идентификатора человека - только числа и места.')
    return 0


def main(argv):
    args = [a for a in argv[1:]]
    as_csv = '--csv' in args
    contrib = '--contrib' in args
    submission = '--submission' in args
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

    if submission:
        return _submission(days)

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
