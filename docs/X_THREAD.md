# X thread — publish with the 30–60s live demo

Replace only values in `[square brackets]`. Do not publish placeholders or claim 1,000 calls until
Nansen Usage Analytics shows it.

## 1/6 — video attached

A Polymarket market can say 78% YES. But whose conviction is it?

I built Nansen Undertaker for @nansen_ai Meridian: a Telegram workflow that checks who holds the
market — and whether those wallets were right before.

🔗 https://github.com/RenatMursalimov/nansen-undertaker

## 2/6 — hero screenshot

Tap a trending market. The bot gets its top holders from Nansen, then checks each wallet’s lifetime
history.

It shows how much known money sits with wallets below a visible win-rate threshold, split by
Yes/No. Unknown histories are counted on neither side.

## 3/6

This is not Nansen data as decoration. Holder positions + wallet history drive the conclusion.

A 78% market backed by proven wallets is a different object from 78% backed mostly by wallets with
a sub-40% win rate. The price cannot tell them apart.

## 4/6 — liquidation-map screenshot

The same principle powers two more views:

• liquidation clusters by price level
• smart-money trades as % of token market cap

Raw rows become decision context: where leverage breaks, and whether a $48K buy is signal or noise.

## 5/6

Missing data never becomes a silent verdict.

Every result names Nansen and freshness. No credits, rate limit, timeout, malformed request,
unsupported asset and genuinely empty data are different states — because “no label” does not mean
“safe wallet.”

## 6/6

Built into a live multi-user Telegram bot. From Sep 14–27 it logged **[USAGE_ANALYTICS_CALLS] real
Nansen API calls** across **[VERIFIED_WORKFLOW_COUNT] workflows**.

Public code, live proof and reproducible tests:
https://github.com/RenatMursalimov/nansen-undertaker

#NansenMeridian

## Before posting

- [ ] Video attached to post 1; 30–60 seconds, understandable without sound.
- [ ] `@nansen_ai` and GitHub link are in post 1, not hidden in the last reply.
- [ ] `[USAGE_ANALYTICS_CALLS]` copied from Nansen Usage Analytics and is at least 1,000.
- [ ] Workflow count copied from generated `docs/CATALOG.md`, not remembered by hand.
- [ ] No participant handles, private wallets, server paths or API keys in screenshots/video.
- [ ] Repo opens publicly and CI is green.
- [ ] Submit the X post URL + GitHub URL in the official entry form.
