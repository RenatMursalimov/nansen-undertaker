# Exact sandbox deploy and recording runbook

Use this only after the final PR is merged. The flow is **sandbox → live test bot → production →
recording**. Never test new bot-layer logic first on production.

## 1. Deploy to sandbox from the production server

Canonical command. The tracked script already knows the live stand directory, `<TEST_SERVICE>` unit,
SSH host and identity; do not repeat stale values by hand:

```bash
cd <BOT_DIR> && bash tools/deploytest.sh
```

Expected final line:

```text
ГОТОВО: выложен <HEAD> на СТЕНД, служба <TEST_SERVICE> active
```

The script detects that the current machine is production, connects with
`<SSH_IDENTITY>`, performs `git pull --ff-only`, prints HEAD before/after, runs AST/spec checks
and restarts only a `*test*` service. If any step fails it stops before restart.

There must be one implementation. If the output warns about `<BOT_DIR>/deploytest.sh`,
inspect the current alias before replacing anything:

```bash
type deploytest
```

After this tracked fix is merged and `deploy` has pulled it to production, preserve the old file and
point the convenience alias at the version-controlled script:

```bash
cd <BOT_DIR>
mv deploytest.sh ~/deploytest.sh.legacy_$(date +%s)
unalias deploytest 2>/dev/null || true
printf '%s\n' "alias deploytest='cd <BOT_DIR> && bash tools/deploytest.sh'" >> ~/.bashrc
source ~/.bashrc
type deploytest
```

Independent verification from production (one complete shell line, including the closing quote):

```bash
ssh -i <SSH_IDENTITY> root@5.129.237.130 'cd <STAND_DIR> && echo "HEAD=$(git rev-parse --short HEAD) $(git log -1 --pretty=%s)" && echo "SERVICE=$(systemctl is-active <TEST_SERVICE>)" && { tail -c 200K bot.log 2>/dev/null | grep -a -iE "traceback|dm route err|bad_bot_key|nansen.*(error|failed)" | tail -20 || true; }'
```

Success means:

- HEAD equals merged `origin/main`;
- `SERVICE=active`, not `activating`;
- no fresh traceback/route error.

Untracked files such as screenshots do not automatically break `git pull`; they block it only if an
incoming commit needs the same path. The pull exit code printed by the script is authoritative.

## 2. Sandbox live smoke from the sandbox checkout

These are read-only Nansen calls. Primary and backup have already passed, but repeat once after the
final deploy because this verifies the deployed version, not just the repository:

```bash
ssh -i <SSH_IDENTITY> root@5.129.237.130 '
  cd <STAND_DIR> &&
  ./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 1130012
'

ssh -i <SSH_IDENTITY> root@5.129.237.130 '
  cd <STAND_DIR> &&
  ./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 4323345
'
```

Both must end with:

```text
LIVE PROOF: PASS
known histories: 1 or more
provider failures: 0
```

If the sandbox prints `NANSEN_API_KEY is missing`, add the existing Nansen key to the sandbox's
ignored `.env.test` without printing it into chat/shell history, then rerun. Do not copy the entire
production `.env` onto the sandbox.

## 3. Test the exact Telegram UX on the configured sandbox bot

In a clean private chat:

1. Send `/lang en`.
2. Send `polymarket markets`.
3. Confirm the result is English and ends with `Source: Nansen, data just now` (or a factual cache
   age).
4. Find the row whose printed market id is `1130012`; tap its `🎭 N` button.
5. Verify:
   - the returned header still says `1130012` — not a different market at the same rank;
   - `Of $… examined` appears;
   - holder rows show side, entry→current, win rate, PnL;
   - unexamined holders are described as `not examined because of the lookup cap`, not as having
     no history;
   - footer says `Source: Nansen` and factual freshness.
6. Also send direct English fallback: `market reputation 1130012`. It must open the same market.
7. Repeat direct fallback for backup: `market reputation 4323345`.

If primary is no longer present in the top-five market list, that is not a failure. Use the direct
English command for the recording. Do not tap a different numbered market and present it as the
pretested one.

## 4. Production deploy — only after sandbox passes

The production machine already has the canonical `deploy` command, which performs pull, AST check,
restart, active-state check and fresh-log scan. Keep the backup step explicit:

```bash
cd <BOT_DIR>
cp bot.py bot.py.bak_$(date +%s)
deploy
```

The command must finish with both:

```text
✅ <BOT_SERVICE> active
✅ чисто (нет dm route err / traceback)
```

`deploy` is a machine convenience command, not repository code. If its output ever stops showing
all five stages (pull → AST → restart → active → fresh-log scan), stop using the alias and run the
reviewable equivalent explicitly:

```bash
cd <BOT_DIR>
cp bot.py bot.py.bak_$(date +%s)
git pull --ff-only && \
./venv/bin/python3 -c "import ast
for p in ('bot.py','nansen_api.py','nansen_log.py','onchain/oc_dm.py','onchain/oc_callbacks.py'):
    ast.parse(open(p, encoding='utf-8').read())
print('ast OK')" && \
rm -rf __pycache__ onchain/__pycache__ && \
systemctl restart <BOT_SERVICE> && \
sleep 20 && \
test "$(systemctl is-active <BOT_SERVICE>)" = active
```

Then independently verify the live process and main log:

```bash
cd <BOT_DIR>
systemctl is-active <BOT_SERVICE>
tail -c 300K bot.log | grep -a -iE "traceback|dm route err|bad_bot_key|nansen.*(error|failed)" | tail -30 || true
```

Success is exactly `active`, not `activating`, and no fresh traceback. A successful `git pull` alone
is not a deploy: the restart inside `deploy` is what makes all lazily imported modules the same
version.

## 5. Prepare the recording

1. Download/open `assets/social-preview.png`; it is also the 0–3 second title card.
2. Use Telegram Desktop or Web in a **clean private chat** with the production bot.
3. Hide notification previews, bookmarks bar, wallet extensions/balances and unrelated chats.
4. Use 100% display zoom and a window wide enough that holder rows do not wrap excessively.
5. Send `/lang en` before recording; remove/scroll past the language confirmation.
6. Immediately before recording, run primary live smoke once in SSH. If it fails or resolves,
   switch to backup. Do not rerun the 1,050-call corpus.

Primary preflight:

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 1130012
```

Backup:

```bash
./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id 4323345
```

## 6. Record exactly 52 seconds

### Preferred one-tap take

Use this only if primary `1130012` is still among the top five rows.

| Time | Screen action |
|---:|---|
| 0–3s | full-screen `assets/social-preview.png` |
| 3–8s | switch to Telegram; send `polymarket markets` |
| 8–12s | briefly show probability/volume/id and `Source: Nansen`; tap the `🎭 N` belonging to `1130012` |
| 12–26s | wait visibly for live result; highlight `Of $X examined, $Y (Z%)…` |
| 26–36s | show side totals and two holder rows (entry→current, win rate, PnL) |
| 36–43s | show the separate `not examined due to lookup cap` line |
| 43–48s | show `Source: Nansen, data just now` and request count |
| 48–52s | return to title/end card with public repo URL |

### Stable direct-command take

If primary is not in the list, use:

```text
market reputation 1130012
```

This sacrifices one menu tap but guarantees the pretested market identity. Keep the title card,
result highlights and end card unchanged.

### Backup take

Use:

```text
market reputation 4323345
```

The backup is technically strong but has a less dramatic headline (`0% below 40%`), so publish it
only if primary fails/resolves.

## 7. Validate the video before posting

- Duration: 30–60 seconds; target 52.
- Understandable with sound muted.
- Live loading is visible; no fixture.
- `market_id` in result equals selected/pretyped id.
- No participant handles, private wallet addresses, server paths, API keys, wallet balances,
  notification text or browser bookmarks.
- Nansen source and freshness are visible.
- Public repo URL is readable for at least three seconds.
- Do not show tests, forced failures, Agent, trading, telemetry dashboard or all workflows.

The ready thread is `X_THREAD.md`. The first post must contain the video, `@nansen_ai` and the public
repo link.
