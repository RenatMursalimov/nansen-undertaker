#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Human-gated diagnostics for the four Nansen spot-trading endpoints.

Trading endpoints consume zero Nansen plan credits, so they are not a way to raise contest credit
usage. Quote and bridge status are read-only. Prepare creates a signable transaction and therefore
requires an explicit human flag. Execute broadcasts real money, has no dry mode, and is intentionally
unavailable in this generic server probe until the repository has a user-bound confirmation broker,
strict signer verification and unknown-timeout reconciliation.

Examples (default is always a zero-call plan):

    ./venv/bin/python3 tools/nansen_trade_probe.py quote --wallet 0x...
    ./venv/bin/python3 tools/nansen_trade_probe.py quote --wallet 0x... --run
    ./venv/bin/python3 tools/nansen_trade_probe.py prepare --wallet 0x... --run
    ./venv/bin/python3 tools/nansen_trade_probe.py prepare --wallet 0x... --run --yes-create-signable
    ./venv/bin/python3 tools/nansen_trade_probe.py bridge-status --tx-hash 0x... --run
    ./venv/bin/python3 tools/nansen_trade_probe.py execute

No key, quote, transaction body or signed payload is written to disk or printed.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import nansen_api as N  # noqa: E402
import nansen_log as T  # noqa: E402


def _parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('quote', 'prepare', 'bridge-status', 'execute'))
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--yes-create-signable', action='store_true',
                    help='human accepts creation of an unsigned, signable transaction')
    ap.add_argument('--wallet', default=os.getenv('NANSEN_SWEEP_TRADE_WALLET'))
    ap.add_argument('--chain', choices=N.TRADE_CHAINS, default='base')
    ap.add_argument('--amount', default='1', help='human USDC amount (default 1)')
    ap.add_argument('--slippage-bps', type=int, default=50)
    ap.add_argument('--tx-hash', default=os.getenv('NANSEN_SWEEP_BRIDGE_TX_HASH'))
    return ap


def _quote(args):
    if not args.wallet:
        return [], 'wallet is required (--wallet or NANSEN_SWEEP_TRADE_WALLET)'
    try:
        from decimal import Decimal
        human_amount = Decimal(str(args.amount))
        amount = N.base_units(human_amount, N.DECIMALS['usdc'])
    except Exception as e:
        return [], 'invalid amount: %s' % str(e)[:80]
    if human_amount <= 0:
        return [], 'amount must be positive'
    if human_amount > Decimal(str(N.trade_cap_usd())):
        return [], 'amount exceeds configured trade cap $%s' % N.trade_cap_usd()
    if not (1 <= int(args.slippage_bps) <= 500):
        return [], 'slippage must be 1..500 bps'
    # Fixed USDC -> native leg satisfies the provider's route contract on both supported chains.
    return N.trade_quote(args.chain, N.USDC[args.chain], N.NATIVE[args.chain], amount,
                         args.wallet, slippage_bps=args.slippage_bps)


def _human_prepare_confirmation():
    """An ordinary CLI flag is cron-compatible; require a live terminal and typed phrase too."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        return input('Type PREPARE SIGNABLE to create an unsigned transaction: ').strip() == \
            'PREPARE SIGNABLE'
    except (EOFError, KeyboardInterrupt):
        return False


def main(argv=None):
    args = _parser().parse_args(argv)
    print('PLAN: action=%s · chain=%s · amount=%s USDC · Nansen credits=0'
          % (args.action, args.chain, args.amount))
    if args.action == 'execute':
        print('BLOCKED BY DESIGN: trade/execute broadcasts a signed transaction and has no dry mode.')
        print('This generic probe never accepts a signed payload and can never broadcast money.')
        return 3
    if args.action in ('quote', 'prepare') and not args.wallet:
        print('Need --wallet or NANSEN_SWEEP_TRADE_WALLET. Nothing sent.')
        return 2
    if args.action == 'bridge-status' and not args.tx_hash:
        print('Need --tx-hash or NANSEN_SWEEP_BRIDGE_TX_HASH. Nothing sent.')
        return 2
    if args.action == 'prepare' and args.run:
        if not args.yes_create_signable:
            print('STOP: only a human may add --yes-create-signable. Nothing prepared.')
            return 3
        if not _human_prepare_confirmation():
            print('STOP: prepare requires an interactive terminal and the exact typed phrase. '
                  'Cron/pipes cannot prepare.')
            return 3
    if not args.run:
        extra = (' Add --run --yes-create-signable only if you want an unsigned transaction.'
                 if args.action == 'prepare' else ' Add --run to send this read-only request.')
        print('Nothing sent.' + extra)
        return 0
    if not N._key():
        print('NANSEN_API_KEY is missing. Nothing sent.')
        return 2

    with T.scene('trade_probe'):
        if args.action == 'quote':
            quotes, why = _quote(args)
            print('RESULT: trade/quote · outcome=%s · quotes=%d' % (why, len(quotes or [])))
            if quotes:
                print(N.quote_card(quotes[0], args.chain, 'USDC',
                                   'ETH' if args.chain == 'base' else 'SOL'))
            return 0 if quotes else 1
        if args.action == 'bridge-status':
            got, why = N.trade_bridge_status(args.chain, args.tx_hash)
            # Schema keys are useful; values may contain transaction/wallet details and stay hidden.
            print('RESULT: trade/bridge-status · outcome=%s · fields=%s'
                  % (why, ','.join(sorted(got.keys())[:20]) if isinstance(got, dict) else ''))
            return 0 if got else 1
        quotes, why = _quote(args)
        if not quotes:
            print('STOP: quote failed (%s); prepare was not called.' % why)
            return 1
        prepared, why = N.trade_prepare(args.chain, args.wallet, quotes[0], skip_simulation=False)
        fields = ','.join(sorted(prepared.keys())[:20]) if isinstance(prepared, dict) else ''
        simulation = prepared.get('simulationPassed') if isinstance(prepared, dict) else None
        print('RESULT: trade/prepare · outcome=%s · simulationPassed=%s · fields=%s'
              % (why, simulation, fields))
        print('Unsigned transaction body intentionally not printed or saved. No signing/execution occurred.')
        return 0 if prepared else 1


if __name__ == '__main__':
    sys.exit(main())
