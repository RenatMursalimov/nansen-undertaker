#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fresh server-side sweep of every Nansen client route that is safe to schedule.

The client currently contains 53 network routes. This tool keeps a declarative entry for every
one and fails if the client and registry drift apart. It sends fresh requests through the normal
telemetry throat (never through response cache), but it does NOT pretend every route is schedulable:

* 47 structural read routes can run in ``complete``;
* ``trade/quote`` is a zero-credit read and joins routine/complete;
* two Agent routes require ``--include-agents`` because they cost 200 + 750 credits;
* ``trade/bridge-status`` requires a real tx hash supplied outside source control;
* ``trade/prepare`` and ``trade/execute`` are represented but categorically excluded from any
  scheduled sweep. Prepare creates signable intent; execute broadcasts real money and has no dry
  mode. Use ``nansen_trade_probe.py`` for human-gated quote/prepare/status commands.

Default is a PLAN and makes zero calls. Typical one-run commands:

    ./venv/bin/python3 tools/nansen_endpoint_sweep.py --profile complete
    ./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --profile complete
    ./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --profile agents --include-agents
    ./venv/bin/python3 tools/nansen_endpoint_sweep.py --run --only prediction-market/orderbook

Every call is fresh, sequential and telemetry-visible. A hard wire cap, conservative planning
budget and recent remaining-credit reserve guard are enforced from an aggregate state file. No response body, wallet result or
API key is persisted.
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import nansen_api as N  # noqa: E402
import nansen_log as T  # noqa: E402

TOKEN = '0x4200000000000000000000000000000000000006'      # public WETH contract on Base
USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'       # public USDC contract on Base
WALLET = '0x1f9090aaE28b8a3dCeaDf281B0F12828e676c326'     # public Ethereum builder
MARKET = os.getenv('NANSEN_SWEEP_MARKET_ID') or '1130012'
STATE = os.getenv('NANSEN_SWEEP_STATE') or os.path.join(ROOT, 'nansen_endpoint_sweep_state.json')
LOCK = os.getenv('NANSEN_SWEEP_LOCK') or '/tmp/nansen_endpoint_sweep.lock'


def _utc_day(delta=0):
    return (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=delta)).isoformat()


def _dr(days):
    return N._date_range(days)


def _pg(n=5):
    return {'page': 1, 'per_page': n}


def _case(path, body=None, base='v1', estimate=5, tier='routine', kind='post'):
    return {'path': path, 'body': body, 'base': base, 'estimate': int(estimate),
            'tier': tier, 'kind': kind}


def registry():
    """One executable/safety declaration for every route in nansen_api.py."""
    yesterday = _utc_day(-1)
    hist_to = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=N.HIST_LAG_DAYS)
    hist_from = hist_to - dt.timedelta(days=30)
    base = [
        _case('smart-money/netflow',
              {'chains': ['ethereum', 'solana', 'base'],
               'filters': {'include_stablecoins': False}, 'pagination': _pg(),
               'order_by': [{'field': 'net_flow_24h_usd', 'direction': 'DESC'}]}, estimate=5),
        _case('token-screener',
              {'chains': ['ethereum', 'solana', 'base'], 'timeframe': '24h',
               'filters': {'only_smart_money': True},
               'order_by': [{'field': 'netflow', 'direction': 'DESC'}],
               'pagination': _pg()}, estimate=1),
        _case('smart-money/holdings',
              {'chains': ['ethereum', 'solana', 'base'],
               'filters': {'value_usd': {'min': 1000}, 'include_stablecoins': False},
               'pagination': _pg(),
               'order_by': [{'field': 'value_usd', 'direction': 'DESC'}]}, estimate=3),
        _case('smart-money/dex-trades',
              {'chains': ['ethereum', 'solana', 'base'], 'pagination': _pg(),
               'order_by': [{'field': 'block_timestamp', 'direction': 'DESC'}]}),
        _case('smart-money/perp-trades',
              {'pagination': _pg(),
               'order_by': [{'field': 'block_timestamp', 'direction': 'DESC'}]}),

        _case('tgm/flow-intelligence',
              {'chain': 'base', 'token_address': TOKEN, 'timeframe': '1d'}, estimate=1),
        _case('tgm/holders',
              {'chain': 'base', 'token_address': TOKEN, 'label_type': 'all_holders',
               'aggregate_by_entity': False, 'pagination': _pg(), 'premium_labels': False,
               'order_by': [{'field': 'value_usd', 'direction': 'DESC'}]}),
        _case('tgm/pnl-leaderboard',
              {'chain': 'base', 'token_address': TOKEN, 'date': _dr(30),
               'pagination': _pg(), 'premium_labels': False,
               'order_by': [{'field': 'pnl_usd_realised', 'direction': 'DESC'}]}),
        _case('tgm/who-bought-sold',
              {'chain': 'base', 'token_address': TOKEN, 'buy_or_sell': 'BUY',
               'date': _dr(1), 'pagination': _pg(),
               'order_by': [{'field': 'bought_volume_usd', 'direction': 'DESC'}]}, estimate=1),
        _case('tgm/token-information',
              {'chain': 'base', 'token_address': TOKEN, 'timeframe': '1d'}, estimate=1),
        _case('tgm/indicators', {'chain': 'base', 'token_address': TOKEN}),
        _case('tgm/flows',
              {'chain': 'base', 'token_address': TOKEN, 'date': _dr(1),
               'pagination': _pg()}),
        _case('tgm/dex-trades',
              {'chain': 'base', 'token_address': TOKEN, 'date': _dr(1),
               'pagination': _pg()}),
        _case('tgm/token-transfers',
              {'chain': 'base', 'token_address': TOKEN, 'date': _dr(1),
               'pagination': _pg()}),
        _case('tgm/price-ohlcv',
              {'chain': 'base', 'token_address': TOKEN, 'timeframe': '1d',
               'date': _dr(30)}),
        _case('perp-leaderboard',
              {'date': {'from': _dr(7)['from'][:10], 'to': _dr(7)['to'][:10]},
               'pagination': _pg(), 'filters': {'account_value': {'min': 10000}},
               'premium_labels': False,
               'order_by': [{'field': 'total_pnl', 'direction': 'DESC'}]}),
        _case('perp-screener',
              {'date': _dr(1), 'pagination': _pg(),
               'order_by': [{'field': 'volume_24h', 'direction': 'DESC'}]}),
        _case('tgm/perp-positions',
              {'token_symbol': 'BTC', 'pagination': _pg(),
               'order_by': [{'field': 'position_value_usd', 'direction': 'DESC'}]}),
        _case('tgm/perp-pnl-leaderboard',
              {'token': 'BTC', 'date': _dr(7), 'pagination': _pg(),
               'order_by': [{'field': 'total_pnl', 'direction': 'DESC'}]}),

        _case('profiler/address/labels',
              {'address': WALLET, 'chain': 'ethereum', 'pagination': _pg(100)}),
        _case('profiler/address/premium-labels',
              {'address': WALLET, 'chain': 'ethereum', 'pagination': _pg(100)},
              estimate=150, tier='expensive'),
        _case('profiler/address/pnl-summary',
              {'address': WALLET, 'chain': 'ethereum', 'date': _dr(30)}),
        _case('profiler/address/related-wallets',
              {'address': WALLET, 'chain': 'ethereum', 'pagination': _pg(),
               'order_by': [{'field': 'order', 'direction': 'ASC'}]}),
        _case('profiler/address/counterparties',
              {'address': WALLET, 'chain': 'ethereum', 'date': _dr(30),
               'group_by': 'wallet', 'source_input': 'Combined', 'pagination': _pg(),
               'order_by': [{'field': 'total_volume_usd', 'direction': 'DESC'}]}),
        _case('profiler/address/current-balance',
              {'address': WALLET, 'chain': 'ethereum', 'hide_spam_token': True,
               'pagination': _pg(),
               'order_by': [{'field': 'value_usd', 'direction': 'DESC'}]}),
        _case('profiler/perp-positions', {'address': WALLET}),
        _case('profiler/address/transactions',
              {'address': WALLET, 'chain': 'ethereum', 'date': _dr(30),
               'pagination': _pg()}),
        _case('profiler/dex-trades',
              {'address': WALLET, 'chain': 'ethereum', 'date': _dr(30),
               'pagination': _pg()}),
        _case('profiler/address/perp-trades',
              {'address': WALLET, 'date': _dr(30), 'pagination': _pg()}),
        _case('profiler/address/historical-token-balances',
              {'address': WALLET, 'chain': 'ethereum', 'date': _dr(30),
               'pagination': _pg()}),

        _case('prediction-market/categories', {}),
        _case('prediction-market/events',
              {'query': '', 'pagination': _pg(),
               'order_by': [{'field': 'volume_24hr', 'direction': 'DESC'}]}),
        _case('prediction-market/market-screener',
              {'order_by': [{'direction': 'DESC', 'field': 'volume_24hr'}], 'query': '',
               'status': 'active', 'pagination': _pg()}),
        _case('prediction-market/orderbook', {'market_id': MARKET}),
        _case('prediction-market/ohlcv', {'market_id': MARKET}),
        _case('prediction-market/trades', {'market_id': MARKET, 'pagination': _pg()}),
        _case('prediction-market/wallet-trades', {'address': WALLET, 'pagination': _pg()}),
        _case('prediction-market/top-holders',
              {'market_id': MARKET, 'pagination': _pg(),
               'order_by': [{'field': 'position_size', 'direction': 'DESC'}]}),
        _case('prediction-market/address-summary',
              {'address': WALLET, 'pagination': _pg(10)}),
        _case('prediction-market/pnl-by-address',
              {'address': WALLET, 'pagination': _pg(),
               'order_by': [{'direction': 'DESC', 'field': 'total_pnl_usd'}]}),
        _case('prediction-market/pnl-by-market',
              {'market_id': MARKET, 'pagination': _pg(),
               'order_by': [{'direction': 'DESC', 'field': 'total_pnl_usd'}]}),

        _case('tgm/historical-who-bought-sold',
              {'chain': 'base', 'token_address': TOKEN, 'buy_or_sell': 'BUY',
               'date_range': {'from': yesterday, 'to': yesterday}, 'pagination': _pg()},
              base='beta'),
        _case('tgm/historical-top-holders',
              {'chain': 'base', 'token_address': TOKEN, 'as_of_date': yesterday,
               'pagination': _pg()}, base='beta', estimate=25, tier='expensive'),
        _case('tgm/historical-token-quant-scores',
              {'chain': 'base', 'token_address': TOKEN, 'as_of_date': yesterday},
              base='beta', estimate=25, tier='expensive'),
        _case('token-screener/historical',
              {'chains': ['ethereum', 'solana', 'base'], 'as_of_date': yesterday,
               'pagination': _pg()}, base='beta'),
        _case('tgm/historical-token-ohlcv',
              {'chain': 'base', 'token_address': TOKEN,
               'date_from': hist_from.isoformat(), 'as_of_date': hist_to.isoformat(),
               'timeframe': '1d'}, base='beta'),
        _case('tgm/historical-token-flow-summary',
              {'chain': 'base', 'token_address': TOKEN,
               'date_range': {'from': hist_from.isoformat(), 'to': hist_to.isoformat()}},
              base='beta'),

        _case('trade/quote', estimate=0, kind='quote'),
        _case('trade/bridge-status', estimate=0, tier='conditional', kind='bridge'),
        _case('agent/fast', estimate=200, tier='agent', kind='agent'),
        _case('agent/expert', estimate=750, tier='agent', kind='agent'),
        _case('trade/prepare', estimate=0, tier='manual', kind='blocked'),
        _case('trade/execute', estimate=0, tier='forbidden', kind='blocked'),
    ]
    return base


def _client_routes():
    from tools.nansen_catalog import _endpoints_in
    src = open(os.path.join(ROOT, 'nansen_api.py'), encoding='utf-8').read()
    return _endpoints_in(src)


def coverage_errors(cases=None):
    cases = cases or registry()
    paths = [c['path'] for c in cases]
    declared, client = set(paths), set(_client_routes())
    out = []
    if len(paths) != len(declared):
        out.append('duplicate registry route(s)')
    if declared - client:
        out.append('registry only: %s' % ', '.join(sorted(declared - client)))
    if client - declared:
        out.append('client only: %s' % ', '.join(sorted(client - declared)))
    return out


def _load_state():
    fresh = {'day': _utc_day(), 'runs': 0, 'wire': 0, 'planned_credits': 0,
             'outcomes': {}}
    if not os.path.exists(STATE):
        return fresh
    try:
        d = json.load(open(STATE, encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise RuntimeError('daily state is unreadable: %s' % str(e)[:100])
    if not isinstance(d, dict):
        raise RuntimeError('daily state is not an object')
    if d.get('day') != _utc_day():
        return fresh
    for key in ('runs', 'wire', 'planned_credits'):
        try:
            d[key] = int(d.get(key) or 0)
        except (TypeError, ValueError):
            raise RuntimeError('daily state field %s is invalid' % key)
        if d[key] < 0:
            raise RuntimeError('daily state field %s is negative' % key)
    if not isinstance(d.get('outcomes'), dict):
        raise RuntimeError('daily state outcomes is invalid')
    return d


def _save_state(d):
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def _select(args, cases):
    if args.only:
        return [c for c in cases if c['path'] == args.only]
    if args.profile == 'routine':
        selected = [c for c in cases if c['tier'] == 'routine' or c['kind'] == 'quote']
    elif args.profile == 'complete':
        selected = [c for c in cases if c['kind'] == 'post' or c['kind'] == 'quote']
    elif args.profile == 'agents':
        selected = [c for c in cases if c['kind'] == 'agent']
    elif args.profile == 'trade-read':
        selected = [c for c in cases if c['kind'] in ('quote', 'bridge')]
    else:
        selected = []
    if args.include_agents and args.profile != 'agents':
        selected += [c for c in cases if c['kind'] == 'agent']
    seen = set()
    return [c for c in selected if not (c['path'] in seen or seen.add(c['path']))]


def _shape(j):
    rows = N._rows(j)
    if isinstance(rows, list):
        first = rows[0] if rows and isinstance(rows[0], dict) else None
        return len(rows), sorted(first.keys())[:12] if first else []
    if isinstance(j, dict):
        return 1 if j else 0, sorted(j.keys())[:12]
    return 0, []


def _run_case(case, args):
    path, kind = case['path'], case['kind']
    T.clear()
    with T.scene('endpoint_sweep'):
        if kind == 'post':
            base = N._BETA if case['base'] == 'beta' else N._BASE
            body = (N._schema_apply(path, case['body'])
                    if case['base'] == 'v1' else dict(case['body'] or {}))
            j, http = N._http_post(base, path, body, args.timeout,
                                   ' beta' if case['base'] == 'beta' else ' sweep')
            count, keys = _shape(j)
            return {'http': http, 'out': T.outcome() or 'http', 'rows': count, 'keys': keys}
        if kind == 'agent':
            if not args.include_agents:
                return {'skip': 'requires --include-agents (200/750 credits)'}
            expert = path.endswith('/expert')
            question = ('Using current Nansen data only, identify three measurable onchain '
                        'signals worth monitoring today. Return concise facts, not advice.'
                        if not expert else
                        'Using current Nansen data only, deeply compare smart-money flows, token '
                        'holder quality and perp positioning today. Cite measurable facts and '
                        'state missing coverage; do not give financial advice.')
            text, tools = N.ask_agent(question, expert=expert, use_cache=False,
                                      timeout=max(args.timeout, 120))
            return {'http': int((T.box() or {}).get('http') or (200 if text else 0)),
                    'out': T.outcome() or ('ok' if text else 'http'),
                    'rows': 1 if text else 0, 'keys': sorted(set(tools or []))[:12]}
        if kind == 'quote':
            wallet = os.getenv('NANSEN_SWEEP_TRADE_WALLET') or WALLET
            quotes, why = N.trade_quote('base', N.USDC['base'], N.NATIVE['base'],
                                        N.base_units('1', 6), wallet, timeout=args.timeout)
            return {'http': int((T.box() or {}).get('http') or (200 if quotes else 0)),
                    'out': T.outcome() or why, 'rows': len(quotes or []), 'keys': []}
        if kind == 'bridge':
            tx_hash = (os.getenv('NANSEN_SWEEP_BRIDGE_TX_HASH') or '').strip()
            if not tx_hash:
                return {'skip': 'set NANSEN_SWEEP_BRIDGE_TX_HASH to a real existing source tx'}
            got, why = N.trade_bridge_status('base', tx_hash, timeout=args.timeout)
            return {'http': int((T.box() or {}).get('http') or (200 if got else 0)),
                    'out': T.outcome() or why, 'rows': 1 if got else 0,
                    'keys': sorted(got.keys())[:12] if isinstance(got, dict) else []}
        return {'skip': 'never scheduled; use nansen_trade_probe.py with a human gate'}


def _parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', action='store_true', help='send fresh calls; default is plan only')
    ap.add_argument('--list', action='store_true', help='list all 53 route declarations')
    ap.add_argument('--profile', choices=('routine', 'complete', 'agents', 'trade-read'),
                    default='routine')
    ap.add_argument('--only', help='run/plan one exact route from --list')
    ap.add_argument('--include-agents', action='store_true',
                    help='allow 200/750-credit Agent calls; never implied by complete')
    ap.add_argument('--max-wire', type=int, default=60, help='hard calls in this process')
    ap.add_argument('--daily-wire-cap', type=int, default=700)
    ap.add_argument('--daily-credit-cap', type=int, default=6000,
                    help='hard daily planning budget; conservative route estimates')
    ap.add_argument('--reserve-credits', type=int, default=15000,
                    help='stop while at least this many credits remain')
    ap.add_argument('--balance-max-age', type=int, default=21600,
                    help='require remaining-credit snapshot no older than this many seconds')
    ap.add_argument('--timeout', type=int, default=60)
    ap.add_argument('--pause', type=float, default=0.4)
    return ap


def main(argv=None):
    args = _parser().parse_args(argv)
    cases = registry()
    errors = coverage_errors(cases)
    if errors:
        print('REGISTRY DRIFT: ' + '; '.join(errors))
        return 2
    if len(cases) != 53:
        print('REGISTRY DRIFT: expected 53 routes, got %d' % len(cases))
        return 2
    if args.max_wire < 1 or args.daily_wire_cap < 1 or args.daily_credit_cap < 1:
        print('Caps must be positive. Nothing sent.')
        return 2
    if args.only and not any(c['path'] == args.only for c in cases):
        print('Unknown route %r. Use --list. Nothing sent.' % args.only)
        return 2
    if args.list:
        for c in cases:
            print('%-49s %-11s %-11s budget≈%d'
                  % (c['path'], c['kind'], c['tier'], c['estimate']))
        print('\n53 declared: 47 structural reads + 2 Agent + 4 trade.')
        return 0

    selected = _select(args, cases)
    blocked = [c for c in selected if c['kind'] == 'blocked']
    if blocked:
        print('BLOCKED: %s is not a schedulable probe. Nothing sent.' % blocked[0]['path'])
        print('Prepare creates signable intent; execute broadcasts real money and has no dry mode.')
        return 3
    planned = sum(c['estimate'] for c in selected)
    print('PLAN: profile=%s · fresh cases=%d · conservative budget≈%d credits · max-wire=%d'
          % (args.profile, len(selected), planned, args.max_wire))
    for c in selected:
        suffix = ''
        if c['kind'] == 'agent' and not args.include_agents:
            suffix = ' [SKIP without --include-agents]'
        if c['kind'] == 'bridge' and not os.getenv('NANSEN_SWEEP_BRIDGE_TX_HASH'):
            suffix = ' [SKIP without bridge tx hash]'
        print('  %-49s %s%s' % (c['path'], c['tier'], suffix))
    if not args.run:
        print('Nothing sent. Human runs the shown plan by adding --run.')
        return 0
    if any(c['kind'] == 'agent' for c in selected) and not args.include_agents:
        print('Agent gate: add --include-agents after reviewing the 200 + 750 credit plan. '
              'Nothing sent.')
        return 3
    if not N._key():
        print('NANSEN_API_KEY is missing. Nothing sent.')
        return 2

    os.makedirs(os.path.dirname(STATE) or '.', exist_ok=True)
    lock_fh = open(LOCK, 'a+')
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('Another endpoint sweep is running. Nothing sent.')
        return 4

    try:
        state = _load_state()
        # Prove the checkpoint is writable before spending the first call. A broken state file
        # must stop the job, not silently reset a hard daily cap.
        _save_state(state)
    except (OSError, RuntimeError) as e:
        print('State gate: %s. Nothing sent.' % str(e))
        return 4
    before_rows = len(T.read_day(T._day()) or [])
    before_credits = N.credits_left()
    balance_ts = float(N._CREDITS.get('ts') or 0)
    balance_age = max(0, int(time.time() - balance_ts)) if balance_ts else None
    if not isinstance(before_credits, int) or balance_age is None \
            or balance_age > args.balance_max_age:
        print('Balance gate: remaining-credit snapshot is missing/stale (remaining=%s, age=%s). '
              'Nothing sent.' % (before_credits, balance_age))
        print('Run one normal Nansen screen/live smoke to refresh response headers, then retry.')
        return 5
    runnable = [c for c in selected
                if not (c['kind'] == 'bridge' and
                        not os.getenv('NANSEN_SWEEP_BRIDGE_TX_HASH'))]
    run_planned = sum(c['estimate'] for c in runnable)
    if len(runnable) > args.max_wire:
        print('Cap gate: profile needs %d calls but max-wire=%d. Nothing sent.'
              % (len(runnable), args.max_wire))
        return 5
    if state['wire'] + len(runnable) > args.daily_wire_cap:
        print('Cap gate: profile would exceed daily wire cap (%d + %d > %d). Nothing sent.'
              % (state['wire'], len(runnable), args.daily_wire_cap))
        return 5
    if state['planned_credits'] + run_planned > args.daily_credit_cap:
        print('Cap gate: profile would exceed daily planning budget (%d + %d > %d). Nothing sent.'
              % (state['planned_credits'], run_planned, args.daily_credit_cap))
        return 5
    if before_credits - run_planned < args.reserve_credits:
        print('Reserve gate: %d available - ≈%d planned < %d reserve. Nothing sent.'
              % (before_credits, run_planned, args.reserve_credits))
        return 5
    attempted, completed, skipped = 0, 0, 0
    outcomes, unhealthy = {}, []
    incomplete = None
    print('RUN: day state wire=%d/%d · planned=%d/%d · remaining=%s (age %ss)'
          % (state['wire'], args.daily_wire_cap, state['planned_credits'],
             args.daily_credit_cap, before_credits, balance_age))
    for c in selected:
        if _utc_day() != state['day']:
            incomplete = 'UTC day changed during the run'
            print('STOP: %s; next invocation starts a new daily state.' % incomplete)
            break
        if c['kind'] == 'agent' and not args.include_agents:
            skipped += 1
            continue
        if c['kind'] == 'bridge' and not os.getenv('NANSEN_SWEEP_BRIDGE_TX_HASH'):
            print('SKIP %-49s set NANSEN_SWEEP_BRIDGE_TX_HASH to a real existing source tx'
                  % c['path'])
            skipped += 1
            continue
        if attempted >= args.max_wire:
            incomplete = 'process max-wire=%d reached' % args.max_wire
            print('STOP: %s.' % incomplete)
            break
        if state['wire'] >= args.daily_wire_cap:
            incomplete = 'daily wire cap=%d reached' % args.daily_wire_cap
            print('STOP: %s.' % incomplete)
            break
        if state['planned_credits'] + c['estimate'] > args.daily_credit_cap:
            incomplete = 'daily planning budget=%d reached before %s' % (args.daily_credit_cap,
                                                                          c['path'])
            print('STOP: %s.' % incomplete)
            break
        remaining = N.credits_left()
        current_ts = float(N._CREDITS.get('ts') or 0)
        current_age = max(0, int(time.time() - current_ts)) if current_ts else None
        if not isinstance(remaining, int) or current_age is None \
                or current_age > args.balance_max_age:
            incomplete = 'remaining-credit snapshot became missing/stale before %s' % c['path']
            print('STOP: %s.' % incomplete)
            break
        if remaining - c['estimate'] < args.reserve_credits:
            incomplete = 'remaining-credit reserve %d reached before %s' % (args.reserve_credits,
                                                                             c['path'])
            print('STOP: %s.' % incomplete)
            break
        credit_ts_before = current_ts
        # Reserve the wire/budget slot BEFORE the request. If the process dies after sending,
        # tomorrow's cron cannot silently reuse that slot and exceed the hard daily cap.
        state['wire'] += 1
        state['planned_credits'] += c['estimate']
        _save_state(state)
        attempted += 1
        try:
            result = _run_case(c, args)
        except Exception as e:
            result = {'http': 0, 'out': 'tool_error', 'rows': 0,
                      'keys': [type(e).__name__]}
        outcome = str(result.get('out') or 'http')
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        state['outcomes'][outcome] = state['outcomes'].get(outcome, 0) + 1
        if outcome not in ('ok', 'empty', 'unsupported'):
            unhealthy.append('%s=%s' % (c['path'], outcome))
        _save_state(state)
        completed += 1
        balance_error = None
        if c['estimate'] > 0:
            after_remaining = N._CREDITS.get('remaining')
            after_ts = float(N._CREDITS.get('ts') or 0)
            if not isinstance(after_remaining, int) or after_ts <= credit_ts_before:
                balance_error = '%s did not return a fresh valid remaining-credit header' % c['path']
                unhealthy.append('%s=balance_header' % c['path'])
                incomplete = balance_error
        print('%-53s http=%-3s out=%-12s rows=%-4s fields=%s'
              % (c['path'], result.get('http') or 0, outcome, result.get('rows') or 0,
                 ','.join(result.get('keys') or [])[:100]))
        if balance_error:
            print('STOP: %s.' % balance_error)
            break
        if outcome in ('nocredits', 'no_credits', 'ratelimit', 'rate_limited'):
            incomplete = 'provider-wide outcome %s' % outcome
            print('STOP: %s; do not hammer the next routes.' % incomplete)
            break
        if args.pause > 0:
            time.sleep(min(args.pause, 10))
    state['runs'] += 1
    _save_state(state)

    run_rows = (T.read_day(T._day()) or [])[before_rows:]
    sweep_rows = [r for r in run_rows if r.get('scene') == 'endpoint_sweep']
    net = sum(1 for r in sweep_rows if not int(r.get('cache') or 0))
    cached = sum(1 for r in sweep_rows if int(r.get('cache') or 0))
    after_credits = N.credits_left()
    print('\nRESULT: logical=%d · telemetry network=%d · cache=%d · skipped=%d · outcomes=%s'
          % (completed, net, cached, skipped, json.dumps(outcomes, sort_keys=True)))
    print('CREDITS: before=%s · after=%s · reserve=%d · daily planned=%d/%d'
          % (before_credits, after_credits, args.reserve_credits,
             state['planned_credits'], args.daily_credit_cap))
    if cached or net != attempted:
        print('NO VERDICT: fresh-call reconciliation failed (attempted=%d, network=%d, cache=%d).'
              % (attempted, net, cached))
        return 6
    if incomplete or unhealthy:
        print('UNHEALTHY: %s%s'
              % ((incomplete or 'provider/schema failures'),
                 (' · ' + ', '.join(unhealthy[:12])) if unhealthy else ''))
        return 7
    return 0


if __name__ == '__main__':
    sys.exit(main())
