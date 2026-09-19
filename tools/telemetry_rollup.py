#!/usr/bin/env python3
"""Дневная сводка телеметрии Nansen. Реализует раздел «Сводка» из telemetry_spec.md.

Читает JSON Lines из nansen_telemetry.log (+ ротированные nansen_telemetry.log.YYYY-MM-DD)
и печатает счётчики. uid_hash используется ТОЛЬКО для подсчёта разных людей и повторов
и НИКОГДА не печатается — ни в тексте, ни в --json, ни в --export.

Использование:
    python3 nansen/telemetry_rollup.py                      сводка за сегодня
    python3 nansen/telemetry_rollup.py --day 2026-09-18
    python3 nansen/telemetry_rollup.py --since 2026-09-15 --until 2026-09-27
    python3 nansen/telemetry_rollup.py --json               машинный вывод
    python3 nansen/telemetry_rollup.py --export FILE.md     таблица по дням для заявки
    python3 nansen/telemetry_rollup.py --self-test          прогон на синтетике, без лога

Битую строку пропускаем и считаем в 'skipped': сводка не имеет права падать из-за
одной обрезанной записи, но и молчать о ней не должна.
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG = os.path.join(os.path.dirname(BASE), 'nansen_telemetry.log')

# Отказы, которые мы называем человеку прямо (требование B2). Считаются отдельно от
# сбоев: «кредиты кончились» и «упёрся в суточный лимит» — не ошибки бота, а честные
# отказы, и в сводке они отдельная строка, иначе не обосновать докупку кредитов.
HONEST = ('no_credits', 'quota_user', 'rate_limited', 'nokey')
FAILURES = ('http_error', 'timeout')

COMMUNITY = ('sm_netflow', 'sm_holdings', 'wallet_dossier', 'token_breakdown',
             'perp_leaders', 'pm_markets', 'pm_wallet', 'pm_market_leaders')


def _p(vals, pct):
    """Персентиль по отсортированной выборке. -> float | None."""
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return float(s[k])


def read_rows(log_path, since=None, until=None):
    """Прочитать все строки из лога и ротированных файлов. -> (rows, skipped)."""
    rows, skipped = [], 0
    paths = [log_path] + sorted(glob.glob(log_path + '.*'))
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    skipped += 1
                    continue
                if not isinstance(r, dict) or 'ts' not in r:
                    skipped += 1
                    continue
                day = str(r.get('ts'))[:10]
                if since and day < since:
                    continue
                if until and day > until:
                    continue
                rows.append(r)
    return rows, skipped


def summarize(rows):
    """Счётчики по набору строк. -> dict. uid_hash в результат НЕ попадает."""
    out = {
        'requests': len(rows),
        'credits': 0,
        'unpriced_calls': 0,
        'people': 0,
        'by_scenario': {},
        'by_endpoint': {},
        'by_outcome': {},
        'by_trigger': {},
        'honest_refusals': 0,
        'failures': 0,
        'empty': 0,
        'cache_hits': 0,
        'latency_avg_ms': None,
        'latency_p95_ms': None,
        'top_scenario': None,
        'costliest_request': None,
        'credits_remaining_last': None,
        'repeat_users': 0,
        'community_requests': 0,
    }
    if not rows:
        return out

    uids, lat = set(), []
    sc, ep, oc, tr = Counter(), Counter(), Counter(), Counter()
    cost_by_scenario = Counter()
    best = None

    for r in rows:
        scen = str(r.get('scenario') or '?')
        sc[scen] += 1
        ep[str(r.get('endpoint') or '?')] += 1
        outcome = str(r.get('outcome') or '?')
        oc[outcome] += 1
        tr[str(r.get('trigger') or '?')] += 1

        if scen in COMMUNITY:
            out['community_requests'] += 1

        c = r.get('credits_est')
        c = int(c) if isinstance(c, (int, float)) else 0
        out['credits'] += c
        cost_by_scenario[scen] += c
        # неоценённый вызов: цена эндпоинта неизвестна, а не равна нулю. Кэш при этом
        # честно стоит 0 и неоценённым не считается.
        if c == 0 and not r.get('cache_hit') and outcome in ('ok', 'empty'):
            out['unpriced_calls'] += 1

        if best is None or c > best[0]:
            best = (c, scen, str(r.get('endpoint') or '?'))

        if outcome in HONEST:
            out['honest_refusals'] += 1
        if outcome in FAILURES:
            out['failures'] += 1
        if r.get('empty'):
            out['empty'] += 1
        if r.get('cache_hit'):
            out['cache_hits'] += 1

        if r.get('uid_hash'):
            uids.add(r['uid_hash'])
        try:
            if r.get('repeat_n') and int(r['repeat_n']) > 1:
                out['repeat_users'] += 1
        except (TypeError, ValueError):
            pass

        v = r.get('latency_ms')
        if isinstance(v, (int, float)):
            lat.append(float(v))

        cr = r.get('credits_remaining')
        if isinstance(cr, (int, float)):
            out['credits_remaining_last'] = int(cr)

    out['people'] = len(uids)
    out['by_scenario'] = dict(sc.most_common())
    out['by_endpoint'] = dict(ep.most_common())
    out['by_outcome'] = dict(oc.most_common())
    out['by_trigger'] = dict(tr.most_common())
    out['credits_by_scenario'] = dict(cost_by_scenario.most_common())
    if lat:
        out['latency_avg_ms'] = round(sum(lat) / len(lat), 1)
        out['latency_p95_ms'] = _p(lat, 95)
    if sc:
        out['top_scenario'] = sc.most_common(1)[0][0]
    if best:
        out['costliest_request'] = {'credits': best[0], 'scenario': best[1], 'endpoint': best[2]}
    return out


def render(s, title):
    """Человекочитаемая сводка. -> str."""
    n = s['requests']
    if not n:
        return '🧠 Nansen · %s\nЗапросов нет.' % title

    def pc(x):
        return '%.0f%%' % (100.0 * x / n)

    L = ['🧠 Nansen · %s' % title, '']
    L.append('Запросов: %d (из них комьюнити-сценарии: %d)' % (n, s['community_requests']))
    L.append('Разных людей: %d · повторных запросов: %d' % (s['people'], s['repeat_users']))
    L.append('Кредитов сожжено: %d' % s['credits'])
    if s['unpriced_calls']:
        L.append('  ⚠ вызовов с НЕИЗВЕСТНОЙ ценой: %d (в сумму не вошли)' % s['unpriced_calls'])
    if s['credits_remaining_last'] is not None:
        L.append('Остаток кредитов: %d' % s['credits_remaining_last'])
    L.append('')
    L.append('Пустых ответов: %d (%s) · попаданий в кэш: %d (%s)'
             % (s['empty'], pc(s['empty']), s['cache_hits'], pc(s['cache_hits'])))
    L.append('Честных отказов: %d · сбоев: %d' % (s['honest_refusals'], s['failures']))
    if s['latency_avg_ms'] is not None:
        L.append('Латентность: средняя %.0f мс · p95 %.0f мс'
                 % (s['latency_avg_ms'], s['latency_p95_ms']))
    L.append('')
    L.append('Сценарий дня: %s' % (s['top_scenario'] or '—'))
    cr = s.get('costliest_request')
    if cr:
        L.append('Самый дорогой запрос: %s (%s) — %d кр.'
                 % (cr['scenario'], cr['endpoint'], cr['credits']))
    L.append('')
    L.append('По сценариям:')
    for k, v in s['by_scenario'].items():
        cost = s.get('credits_by_scenario', {}).get(k, 0)
        L.append('  %-22s %4d  %6d кр.' % (k, v, cost))
    L.append('')
    L.append('По исходам:')
    for k, v in s['by_outcome'].items():
        mark = ' ←честный отказ' if k in HONEST else (' ←сбой' if k in FAILURES else '')
        L.append('  %-14s %4d%s' % (k, v, mark))
    L.append('')
    L.append('По способу вызова:')
    for k, v in s['by_trigger'].items():
        L.append('  %-8s %4d' % (k, v))
    return '\n'.join(L)


def render_export(rows):
    """Таблица по дням для заявки и статьи. Без uid_hash и без адресов. -> str."""
    by_day = defaultdict(list)
    for r in rows:
        by_day[str(r.get('ts'))[:10]].append(r)

    L = ['# Телеметрия Nansen за период конкурса', '']
    L.append('Только счётчики. Идентификаторов людей, адресов кошельков и текстов')
    L.append('вопросов в этой таблице нет по построению.')
    L.append('')
    L.append('| День | Запросов | Людей | Кредитов | Пустых | Честных отказов | Сбоев | Ср. латентность, мс | Сценарий дня |')
    L.append('|---|---|---|---|---|---|---|---|---|')
    tot = Counter()
    for day in sorted(by_day):
        s = summarize(by_day[day])
        L.append('| %s | %d | %d | %d | %d | %d | %d | %s | %s |' % (
            day, s['requests'], s['people'], s['credits'], s['empty'],
            s['honest_refusals'], s['failures'],
            '%.0f' % s['latency_avg_ms'] if s['latency_avg_ms'] is not None else '—',
            s['top_scenario'] or '—'))
        for k in ('requests', 'credits', 'empty', 'honest_refusals', 'failures'):
            tot[k] += s[k]
    total = summarize(rows)
    L.append('')
    L.append('**Итого за период:** запросов %d · разных людей %d · кредитов %d · '
             'пустых %d · честных отказов %d · сбоев %d'
             % (tot['requests'], total['people'], tot['credits'],
                tot['empty'], tot['honest_refusals'], tot['failures']))
    if total['unpriced_calls']:
        L.append('')
        L.append('**Вызовов с неизвестной ценой эндпоинта: %d.** В сумму кредитов они '
                 'не вошли; цена появится, когда будет снята из Usage Analytics.'
                 % total['unpriced_calls'])
    L.append('')
    L.append('Сценарии за период:')
    L.append('')
    L.append('| Сценарий | Запросов | Кредитов |')
    L.append('|---|---|---|')
    for k, v in total['by_scenario'].items():
        L.append('| %s | %d | %d |' % (k, v, total.get('credits_by_scenario', {}).get(k, 0)))
    return '\n'.join(L)


SELF_TEST_ROWS = [
    {"ts": "2026-09-18T14:03:11+03:00", "scenario": "sm_netflow", "endpoint": "smart-money/netflow",
     "trigger": "btn", "surface": "dm", "latency_ms": 612, "credits_est": 0,
     "credits_remaining": 71204, "outcome": "ok", "http_code": 200, "cache_hit": False,
     "empty": False, "uid_hash": "9f2a1c7b4e08", "repeat_n": 1},
    {"ts": "2026-09-18T14:05:00+03:00", "scenario": "token_breakdown", "endpoint": "tgm/indicators",
     "trigger": "btn", "surface": "public", "latency_ms": 1900, "credits_est": 25,
     "credits_remaining": 71179, "outcome": "ok", "http_code": 200, "cache_hit": False,
     "empty": False, "uid_hash": "3c81de55a920", "repeat_n": 1},
    {"ts": "2026-09-18T14:05:01+03:00", "scenario": "token_breakdown", "endpoint": "tgm/holders",
     "trigger": "btn", "surface": "public", "latency_ms": 700, "credits_est": 5,
     "credits_remaining": 71174, "outcome": "ok", "http_code": 200, "cache_hit": False,
     "empty": False, "uid_hash": "3c81de55a920", "repeat_n": 1},
    {"ts": "2026-09-18T15:00:00+03:00", "scenario": "sm_netflow", "endpoint": "smart-money/netflow",
     "trigger": "btn", "surface": "dm", "latency_ms": 3, "credits_est": 0,
     "credits_remaining": None, "outcome": "cache", "http_code": None, "cache_hit": True,
     "empty": False, "uid_hash": "9f2a1c7b4e08", "repeat_n": 2},
    {"ts": "2026-09-19T19:41:02+03:00", "scenario": "token_breakdown", "endpoint": "tgm/indicators",
     "trigger": "btn", "surface": "public", "latency_ms": 344, "credits_est": 0,
     "credits_remaining": 0, "outcome": "no_credits", "http_code": 402, "cache_hit": False,
     "empty": True, "uid_hash": "3c81de55a920", "repeat_n": 2},
    {"ts": "2026-09-19T19:42:00+03:00", "scenario": "agent_ask", "endpoint": "agent/fast",
     "trigger": "tool", "surface": "dm", "latency_ms": 0, "credits_est": 0,
     "credits_remaining": None, "outcome": "quota_user", "http_code": None, "cache_hit": False,
     "empty": False, "uid_hash": "aa11bb22cc33", "repeat_n": 4},
]


def self_test():
    """Прогон на синтетике: проверяем, что сводка считается и что uid_hash не утекает."""
    s = summarize(SELF_TEST_ROWS)
    txt = render(s, 'самопроверка')
    exp = render_export(SELF_TEST_ROWS)

    checks = [
        ('запросов 6', s['requests'] == 6),
        ('разных людей 3', s['people'] == 3),
        ('кредитов 30 (25+5)', s['credits'] == 30),
        ('неоценённых вызовов 1 (netflow ok)', s['unpriced_calls'] == 1),
        ('честных отказов 2 (no_credits+quota_user)', s['honest_refusals'] == 2),
        ('пустых 1', s['empty'] == 1),
        ('кэш-попаданий 1', s['cache_hits'] == 1),
        ('повторных 3', s['repeat_users'] == 3),
        ('сценарий дня token_breakdown', s['top_scenario'] == 'token_breakdown'),
        ('дорогой запрос 25 кр', s['costliest_request']['credits'] == 25),
        ('комьюнити-запросов 5', s['community_requests'] == 5),
        ('uid_hash НЕ в сводке', 'uid_hash' not in json.dumps(s)),
        ('uid_hash НЕ в тексте', '9f2a1c7b4e08' not in txt),
        ('uid_hash НЕ в экспорте', '9f2a1c7b4e08' not in exp and '3c81de55a920' not in exp),
    ]
    print(txt)
    print()
    print('--- экспорт ---')
    print(exp)
    print()
    bad = 0
    for name, ok in checks:
        print('%s %s' % ('OK  ' if ok else 'ФЕЙЛ', name))
        bad += 0 if ok else 1
    print()
    print('самопроверка: %d из %d' % (len(checks) - bad, len(checks)))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description='Дневная сводка телеметрии Nansen.')
    ap.add_argument('--log', default=DEFAULT_LOG, help='путь к nansen_telemetry.log')
    ap.add_argument('--day', help='один день YYYY-MM-DD (по умолчанию сегодня)')
    ap.add_argument('--since', help='начало периода YYYY-MM-DD')
    ap.add_argument('--until', help='конец периода YYYY-MM-DD')
    ap.add_argument('--json', action='store_true', help='машинный вывод')
    ap.add_argument('--export', metavar='FILE', help='таблица по дням в файл')
    ap.add_argument('--self-test', action='store_true', help='прогон на синтетике, лог не нужен')
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    if a.since or a.until:
        since, until = a.since, a.until
        title = 'период %s — %s' % (since or '…', until or '…')
    else:
        day = a.day or datetime.now().strftime('%Y-%m-%d')
        since = until = day
        title = 'за %s' % day

    if not os.path.exists(a.log) and not glob.glob(a.log + '.*'):
        print('Лога нет: %s' % a.log, file=sys.stderr)
        # УТВЕРЖДЕНИЕ «ТЕЛЕМЕТРИЯ НЕ ВКЛЮЧЕНА» БЫВАЕТ ЛОЖНЫМ, И ЭТО ХУЖЕ МОЛЧАНИЯ. Реализация
        # ТЗ B (PR #843) пишет телеметрию В ДРУГОМ ФОРМАТЕ и в другое место -
        # `nansen_tele/YYYY-MM-DD.log`, строки `k=v`, читатель `tools/nansen_daily.py`. Наш
        # файл при этом не пишет никто, поэтому «не включена» здесь означало бы «я смотрю не
        # туда», а человек прочитал бы это как «чисел нет вовсе» и пошёл включать включённое.
        # Расхождение двух контрактов и три варианта его примирения - в nansen/DIVERGENCE.md,
        # решение за владельцем; до решения прибор обязан хотя бы показывать, где числа есть.
        _alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'nansen_tele')
        _alt_files = sorted(glob.glob(os.path.join(_alt, '*.log'))) if os.path.isdir(_alt) else []
        if _alt_files:
            print('НО ТЕЛЕМЕТРИЯ ПИШЕТСЯ, просто в другом формате: %d файлов в %s '
                  '(формат k=v, ТЗ B / PR #843).' % (len(_alt_files), _alt),
                  file=sys.stderr)
            print('Сводка по ним: ./venv/bin/python3 tools/nansen_daily.py'
                  ' [дата|--range A B] [--csv]', file=sys.stderr)
            print('Какой из двух приборов остаётся - решение владельца, '
                  'см. nansen/DIVERGENCE.md.', file=sys.stderr)
        else:
            print('Телеметрия ещё не включена (ТЗ B3) либо путь другой — задай --log.',
                  file=sys.stderr)
        return 2

    rows, skipped = read_rows(a.log, since, until)
    s = summarize(rows)
    s['skipped_lines'] = skipped

    if a.export:
        os.makedirs(os.path.dirname(os.path.abspath(a.export)), exist_ok=True)
        with open(a.export, 'w', encoding='utf-8') as f:
            f.write(render_export(rows) + '\n')
        print('Экспорт записан: %s (строк в выборке: %d)' % (a.export, len(rows)))
        return 0

    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print(render(s, title))
        if skipped:
            print()
            print('⚠ пропущено битых строк: %d' % skipped)
    return 0


if __name__ == '__main__':
    sys.exit(main())
