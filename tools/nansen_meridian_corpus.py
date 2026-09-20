#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a meaningful 7-day Smart Money corpus — and satisfy the 1,000-call eligibility rule.

Official Meridian rules require **1,000+ API calls between Sep 14–27**. Local telemetry currently
shows far fewer network calls, so eligibility is a P0 blocker, not a bonus. This tool does not spam
the same endpoint: it builds a resumable research corpus for the low-cap discovery workflow.

Method:
  1. discover tokens from current Smart Money netflow and both sides of live DEX trades;
  2. for each public token contract and each of the last 7 completed UTC days, request the exact
     historical top-100 buyers and sellers (`tgm/historical-who-bought-sold`); cells that
     return 100 rows are marked partial rather than presented as complete;
  3. store only aggregate counts/volumes — no buyer wallet addresses — and rank tokens by how
     persistently buying exceeded selling across days.

Default is a PLAN with zero calls. A human must add --run because calls spend credits:

    ./venv/bin/python3 tools/nansen_meridian_corpus.py --max-calls 1050
    ./venv/bin/python3 tools/nansen_meridian_corpus.py --run --max-calls 1050

At 5 credits per historical request, the stated upper bound is about 5,250 credits. The tool stops
at the hard call cap, checkpoints every result, resumes without repeating completed work and never
places a trade. A second run normally makes only missing calls. Verify final eligibility in the
Nansen Usage dashboard: local telemetry started mid-window and is evidence, not the authority.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import nansen_api as N       # noqa: E402
import nansen_log as T       # noqa: E402

OUT = os.getenv('NANSEN_CORPUS_PATH') or os.path.join(ROOT, 'nansen_meridian_corpus.jsonl')
DAYS = 7
SIDES = ('BUY', 'SELL')


def _day_list():
    today = dt.datetime.utcnow().date()
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(1, DAYS + 1)]


def _pick(row, names):
    for n in names:
        if isinstance(row, dict) and row.get(n) not in (None, ''):
            return row[n]
    return None


def _tokens(rows):
    """Discovery rows -> unique public token coordinates. No wallet addresses.

    `smart-money/dex-trades` carries bought AND sold tokens in one row; token-screener carries
    one generic token. Reading both sides roughly doubles the useful corpus without another API
    call and avoids mistaking trader_address for a token address.
    """
    out, seen = [], set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        chain = str(_pick(r, ('chain', 'network', 'blockchain')) or '').lower()
        candidates = [
            (_pick(r, ('token_bought_address',)), _pick(r, ('token_bought_symbol',))),
            (_pick(r, ('token_sold_address',)), _pick(r, ('token_sold_symbol',))),
            (_pick(r, ('token_address', 'contract_address')),
             _pick(r, ('token_symbol', 'symbol', 'ticker'))),
        ]
        for addr, sym in candidates:
            addr = str(addr or '')
            if not chain or not addr or (chain, addr.lower()) in seen:
                continue
            seen.add((chain, addr.lower()))
            out.append({'chain': chain, 'token': addr, 'symbol': str(sym or '?')[:16]})
    return out


def _done():
    keys = set()
    try:
        for line in open(OUT, encoding='utf-8'):
            try:
                r = json.loads(line)
                # Только завершённые состояния закрывают cell. Временный 402/429/timeout/http
                # сохраняется для аудита, но следующий run обязан его повторить; прежний код
                # считал любой checkpoint «done» и навсегда превращал сбой в нулевой volume.
                if r.get('reason') in ('ok', 'empty', 'unsupported'):
                    keys.add((r['day'], r['chain'], r['token'].lower(), r['side']))
            except Exception:
                continue
    except OSError:
        pass
    return keys


def _attempts():
    """Сколько раз cell уже пытались получить. Временные сбои ретраятся, но не бесконечно."""
    out = {}
    try:
        for line in open(OUT, encoding='utf-8'):
            try:
                r = json.loads(line)
                k = (r['day'], r['chain'], r['token'].lower(), r['side'])
                out[k] = out.get(k, 0) + 1
            except Exception:
                continue
    except OSError:
        pass
    return out


def _append(row):
    with open(OUT, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')


def _aggregate(rows):
    """Response rows -> counts and USD volume only. Wallet addresses are deliberately dropped."""
    count, volume, labeled = 0, 0.0, 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        count += 1
        if _pick(r, ('address_label', 'trader_address_label', 'label')):
            labeled += 1
        value, _field = N._usd_any(r, ('bought_volume_usd', 'sold_volume_usd',
                                       'volume_usd', 'value_usd', 'trade_value_usd'))
        try:
            volume += float(value or 0)
        except (TypeError, ValueError):
            pass
    # Один page по 100 строк. Не называем это «все покупатели»: если ровно 100, возможно
    # продолжение, и cell маркируется partial. Для eligibility это остаётся meaningful read,
    # но ranking не притворяется полным.
    return {'rows': count, 'labeled': labeled, 'volume_usd': round(volume, 2),
            'partial_top100': 1 if count >= 100 else 0}


def _report():
    data = []
    try:
        data = [json.loads(x) for x in open(OUT, encoding='utf-8') if x.strip()]
    except OSError:
        return 'no corpus yet'
    # Повтор временного сбоя создаёт новую строку; в ranking участвует только ПОСЛЕДНЯЯ
    # попытка каждой cell, иначе один token-day-side считался бы дважды.
    latest = {}
    for r in data:
        try:
            latest[(r['day'], r['chain'], r['token'].lower(), r['side'])] = r
        except Exception:
            continue
    data = list(latest.values())
    by = {}
    for r in data:
        k = (r.get('chain'), r.get('token'), r.get('symbol'))
        day = by.setdefault(k, {}).setdefault(r.get('day'), {})
        day[r.get('side')] = float(r.get('volume_usd') or 0)
    scored = []
    for k, days in by.items():
        positive = sum(1 for v in days.values() if v.get('BUY', 0) > v.get('SELL', 0))
        buy = sum(v.get('BUY', 0) for v in days.values())
        sell = sum(v.get('SELL', 0) for v in days.values())
        scored.append((positive, buy - sell, k, len(days)))
    scored.sort(reverse=True)
    partial = sum(1 for r in data if r.get('partial_top100'))
    unresolved = sum(1 for r in data if r.get('reason') not in ('ok', 'empty', 'unsupported'))
    L = ['Corpus cells: %d · tokens: %d · top-100 partial cells: %d · unresolved failures: %d'
         % (len(data), len(by), partial, unresolved),
         'Top persistent Smart Money accumulation (BUY > SELL days; partial cells marked '
         'in JSONL, ranking is exploratory):']
    for positive, net, (chain, _token, symbol), n_days in scored[:20]:
        L.append('  %-12s %-10s %d/%d days · net $%s'
                 % (symbol, chain, positive, n_days, N._usd(net)))
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', action='store_true', help='spend calls and write the corpus')
    ap.add_argument('--max-calls', type=int, default=1050,
                    help='hard network-call attempt cap including discovery (default 1050)')
    ap.add_argument('--per-page', type=int, default=100)
    args = ap.parse_args(argv)
    if args.max_calls < 2 or args.max_calls > 2000:
        print('--max-calls must be 2..2000 (the two discovery calls are inside the cap)')
        return 1
    est = max(0, args.max_calls - 2) * 5
    print('PLAN: up to %d API calls, read-only; historical upper-bound ≈%d credits.'
          % (args.max_calls, est))
    print('Dataset: %s' % OUT)
    print('Method: current Smart Money tokens × 7 completed UTC days × BUY/SELL; aggregates only.')
    print('Existing checkpoint rows: %d (will not be repeated).' % len(_done()))
    if not args.run:
        print('Nothing sent. Run by a human with: --run --max-calls %d' % args.max_calls)
        return 0
    if not N._key():
        print('NANSEN_API_KEY is missing. Nothing sent.')
        return 2

    attempted = 0
    tele_start = len(T.read_day(T._day()) or [])
    # ДВА РАЗНЫХ discovery-источника: netflow даёт текущих лидеров, dex-trades — обе стороны
    # реальных сделок. Оба endpoint уже сняты живой пробой; вместе дают достаточно уникальных
    # публичных контрактов для 1,000-cell корпуса.
    with T.scene('admin_backfill'):
        netflow = N.smart_money_netflow(per_page=args.per_page)
        why_net = None if netflow else N.fail_reason('empty')
    attempted += 1
    with T.scene('admin_backfill'):
        trades = N.sm_dex_trades(None, args.per_page)
        why_trades = None if trades else N.fail_reason('empty')
    attempted += 1
    tokens = _tokens((netflow or []) + (trades or []))
    if not tokens:
        why = why_trades if why_trades not in (None, 'empty') else why_net
        print(N.refusal(why, 'en', what='tokens receiving Smart Money activity'))
        return 2
    done = _done()
    attempts = _attempts()
    tasks = [(d, t, side, attempts.get((d, t['chain'], t['token'].lower(), side), 0) + 1)
             for t in tokens for d in _day_list() for side in SIDES
             if (d, t['chain'], t['token'].lower(), side) not in done
             and attempts.get((d, t['chain'], t['token'].lower(), side), 0) < 3]
    print('Discovered %d tokens; pending unique token-day-side cells: %d.' % (len(tokens), len(tasks)))
    if attempted + len(tasks) < args.max_calls:
        print('WARNING: this corpus can attempt only %d calls with the tokens returned today, '
              'below the requested cap %d. Do not claim eligibility from the cap; verify the '
              'actual Usage Analytics count.' % (attempted + len(tasks), args.max_calls))

    for day, tok, side, attempt in tasks:
        if attempted >= args.max_calls:
            break
        t0 = time.time()
        with T.scene('admin_backfill'):
            got = N.hist_who_bought_sold(tok['chain'], tok['token'], day, side, per_page=100)
            reason = None if got else N.fail_reason('empty')
        attempted += 1
        agg = _aggregate(got)
        _append({'day': day, 'chain': tok['chain'], 'token': tok['token'],
                 'symbol': tok['symbol'], 'side': side, 'reason': reason or 'ok',
                 'attempt': attempt, 'elapsed_ms': int((time.time() - t0) * 1000), **agg})
        if attempted % 25 == 0:
            print('  attempted %d/%d · checkpoint rows %d'
                  % (attempted, args.max_calls, len(_done())))

    print('')
    print(_report())
    print('')
    run_rows = (T.read_day(T._day()) or [])[tele_start:]
    network = sum(1 for r in run_rows if not int((r or {}).get('cache') or 0))
    cached = sum(1 for r in run_rows if int((r or {}).get('cache') or 0))
    print('Client invocations this run: %d (hard cap %d).' % (attempted, args.max_calls))
    print('Telemetry: network calls %d · cache hits %d.' % (network, cached))
    print('VERIFY ELIGIBILITY IN NANSEN USAGE ANALYTICS. Required: 1,000+ calls Sep 14–27.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
