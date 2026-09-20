#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live proof for the hero workflow: “A market says YES — but whose conviction is it?”

Default is a plan with ZERO calls. A real run needs an explicit flag because it spends API calls:

    python3 tools/nansen_live_smoke.py                 # plan, no calls
    python3 tools/nansen_live_smoke.py --run           # fresh active market, up to 5 calls
    python3 tools/nansen_live_smoke.py --run --market-id 1130012

Why this exists when offline tests are green: the public suite substitutes the wire. That proves
parsing, calculations, telemetry and refusal semantics, but it cannot prove that today's live API
still returns the documented fields. Buildathon judges require a live-data demo and another builder
must be able to run it in under ten minutes. This is the smallest reproducible live proof.

It does NOT trade, sign, write to an exchange or bypass any limit. It reads one market list (unless
a market id is supplied), one holder list and up to three public wallet summaries. The exact upper
bound is printed before the flag is removed by a human.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import nansen_api as N       # noqa: E402
import nansen_log as T       # noqa: E402

TOP = 3


def _plain(text):
    return re.sub(r'<[^>]+>', '', str(text or '')).replace('&lt;', '<').replace('&gt;', '>')


def main(argv):
    run = '--run' in argv
    market_id = None
    if '--market-id' in argv:
        try:
            market_id = argv[argv.index('--market-id') + 1]
        except IndexError:
            print('--market-id needs a value')
            return 1

    calls = TOP + 1 + (0 if market_id else 1)
    if not run:
        print('PLAN — nothing was sent.')
        print('Hero workflow: active market → top holders → lifetime history for top %d.' % TOP)
        print('Maximum network calls: %d. Read-only. No trades or signatures.' % calls)
        print('Run: python3 tools/nansen_live_smoke.py --run%s'
              % ((' --market-id ' + market_id) if market_id else ''))
        return 0
    if not N._key():
        print('NANSEN_API_KEY is missing. No request was sent; this is configuration, not a verdict.')
        return 2

    if not market_id:
        with T.scene('pm_markets'):
            rows = N.pm_market_screener(per_page=5)
            why = None if rows else N.fail_reason('empty')
        if not rows:
            print(_plain(N.refusal(why, 'en', what='active Polymarket markets')))
            return 2
        market_id = N.pm_market_id(rows[0])
        question = rows[0].get('question') or rows[0].get('event_title') or ''
        print('Market: %s' % question[:120])
        if not market_id:
            print('LIVE PROOF: FAIL — market-screener returned rows but no recognized market_id.')
            print('Fields: %s' % sorted(rows[0].keys())[:30])
            print('No holder request was sent; this is schema drift, not an empty market.')
            return 3
        print('market_id: %s' % market_id)
    else:
        print('market_id: %s' % market_id)

    with T.scene('pm_reputation'):
        rep = N.pm_reputation(market_id, top=TOP)
        why = None if rep else N.fail_reason('empty')
    if not rep:
        print(_plain(N.refusal(why, 'en', what='holders and their lifetime history')))
        return 2
    block = N.pm_reputation_block(rep, market_id, 'en', top=TOP)
    print('')
    print(_plain(block))
    print('')
    print('LIVE PROOF: PASS' if rep.get('known', 0) else 'LIVE PROOF: PARTIAL — no measurable win rate')
    print('Requests: %d · known histories: %d · provider failures: %d'
          % (rep.get('calls', 0), rep.get('known', 0), rep.get('failed', 0)))
    # Functionality criterion: the hero conclusion needs at least one real history. A pretty
    # holder list with zero histories is not the promised build.
    return 0 if rep.get('known', 0) > 0 else 3


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
