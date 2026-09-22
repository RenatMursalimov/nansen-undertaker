# Mini-app: the decisions, including the one to not ship a screen

## Part C: the fourth screen is NOT added. Branch 3 — now by measurement.

**Two live probes on 2026-09-22 settled it, and the record is a fact rather than a shortage of
hours.**

Probe 1 — `422`, not `404`, with a machine-readable instruction:

```
Required field 'body -> date' is missing.
Expected format: {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
```

So the path exists and the body is parsed. Probe 2 sent the window and learned the decisive part:
the platform **does not know the fields `chain` and `token_address`**. Repair-by-the-provider's-words
removed both and the request returned `200 {"data": []}`.

**That 200 is the trap, and it is worth naming.** Repair strips fields the platform rejects — which
here meant stripping the very fields that carry the question *“which token?”*. What came back was a
syntactically valid query with no meaning, and its empty answer reads like *“there are no posts”*
when the truth is *“we never asked properly”*. This is the project's own ban on “emptiness passed off
as a measurement”, arriving from an unexpected direction: the repair mechanism itself.

General rule extracted: **repair is right when the platform says “a field is missing” (we can supply
it) and harmful when it says “I do not know your field” (it throws the question away).** For
discovering a field *name*, repair must be off — the raw refusal is the answer. The `ra` group was
therefore removed from `FIX_DEFAULT`.

So the open question is exactly one: **what is the token field called?** Until it is answered there
can be no screen — “posts by token” that cannot select a token is not a screen. The probe now
measures that instead of guessing it: one candidate name per request, repair off, so the platform
answers either “unknown field” (the name is wrong — a fact) or `200` with rows (the name is right).
A control case re-sends the already-rejected `token_address`, and a baseline case sends no token
filter at all — because if the unfiltered query is empty too, then “empty” means “no coverage on our
plan”, and iterating over names is pointless. Without that baseline we would mistake missing coverage
for a wrong schema.

```bash
./venv/bin/python3 tools/nansen_probe.py --only ra          # plan, zero calls
./venv/bin/python3 tools/nansen_probe.py --run --only ra     # 7 read-only requests
```

Credits spent so far: 5 of ~58,300 remaining. The decision stands as branch 3 until a name answers.

## Why branch 3 was the right call even before the probe

The plan allowed three branches for one extra scene, to be chosen **by the result of a probe**:

1. `ra-agent/posts-by-token` answers and carries the post language → build “what they say vs what
   they do” (narrative next to money flow);
2. it does not → build “route price” on `trade/quote` (0 credits);
3. neither is assembled in time → **do not add the scene.**

**Chosen: branch 3, and the reason is a fact, not a shortage of hours.** The probe cannot be run
where this work was done: there is no live Nansen key in the build environment, and
`ra-agent/posts-by-token` is not in the client at all — its very existence is the open question.
Adding a screen on an unprobed endpoint would break the project's oldest rule: do not promise what
was not measured. A screen that renders an endpoint nobody called is exactly the “door into a wall”
defect the integration already paid for once (four dead clients, then `profiler/address/perp-positions`
buried on a single 404 and resurrected a day later).

The probe itself is shipped, so the decision can be revisited in thirty minutes with one command:

```bash
./venv/bin/python3 tools/nansen_probe.py --only ra          # plan, zero calls
./venv/bin/python3 tools/nansen_probe.py --run --only ra     # two read-only requests
```

Read three things off the raw answer: the status code (200 alive / 404 no such path / 422 path
exists but our body is wrong), whether a language field is present (`lang`/`language`/`locale`), and
whether Chinese posts appear at all. Without a language field the hybrid with our Chinese slice
cannot be built, and then the screen is not worth having.

Branch 2 was not taken either, and deliberately: `trade/quote` is read-only and free, but putting any
trading route into the mini-app gateway would put the trading contour on a public surface for the
sake of a screen nobody asked for. `trade/prepare` and `trade/execute` are unreachable through the
gateway **by absence** — they are not in the scene list, so a request for them returns the same
“unknown screen” as a typo, without confirming such a handle exists.

## The gateway is a mailbox, not a route, and that is not a shortcut

The plan asked for `GET /nansen/<scene>`. That shape is impossible here, and the reason is
architectural rather than stylistic: **the bot has no inbound port.** The mini-app stack is a
Cloudflare Worker (signature check + mailbox) plus a bot that *polls* that mailbox. The Nansen key,
the per-user limits and the telemetry all live in the bot.

A real `/nansen/<scene>` route on the Worker could only answer from the Worker's own storage — which
means a second source of numbers, and Law 0 dead on the first screen. So the gateway is a new signal
kind (`nsn`) in the existing mailbox: the browser asks, the bot computes, the answer comes back. The
browser never sees the key, and the numbers have exactly one origin.

## Two leaks the scrubber caught before production

Both were found by `tools/record_fixture.py` re-reading what it had just written, not by review:

1. `payload.rows[].addr` — a **token contract** address. Not personal data, but the screen does not
   draw it, so it is no longer sent. “Do not send what you do not show” is cheaper than loosening a
   scrubber rule.
2. `payload.first_row` — the **raw provider row**, kept for schema diagnostics and carrying every
   field Nansen returned, including fields that do not exist there yet.

Both are stripped in `nansen_gate._strip_private`, on the same path the live screen uses. A second
implementation of the stripping would have diverged silently.

## A limit bug caught on our own test

The first version of the gateway called the shared `nansen_limits.check(uid, …)`, which includes the
**agent** question counter (3/day). On the third run it refused a liquidation map with “your
questions for today are used up”. In the bot that limit applies to the agent only — structural
screens at 1–5 credits are not capped. Applying it in the mini-app would have introduced a rule the
bot does not have: free in chat, refused in the app. The gateway now checks the shared daily credit
cap only, knows the price of the pending screen before allowing it, and never touches the agent
counter. Spend is counted where it always was — one telemetry row per network call.

## Telemetry: a new surface, not a new scene

The mini-app writes `surface=miniapp` on the **same** scene names. Giving it its own scene names
would have split “market reputation” into two rows of the daily summary, and neither row would
answer “what did this screen cost in total”. The column is appended at the end of the log line, so
files written before this change still parse.
