# Claude Code hooks: five worth adding today

Five small hook scripts for Claude Code, plus a `settings.json` that wires them up and a test script. Companion code for *5 Claude Code Hooks Worth Adding Today*.

They build on the two hooks in [`claude-code-starter/`](../claude-code-starter/) (formatter, `.env` blocker). None of these repeat those.

```
claude-code-hooks/
├── settings.json                 wires all five hooks
├── test_hooks.sh                 pipes sample JSON into each script, checks the result
└── hooks/
    ├── block-dangerous.sh        PreToolUse (Bash): blocks rm -rf /, force push, reset --hard, DROP TABLE, curl | sh
    ├── stop-run-tests.sh         Stop: runs your tests when Claude says "done"; failures send it back (max 3 tries)
    ├── notify.sh                 Notification: desktop alert when Claude is waiting on you
    ├── session-context.sh        SessionStart: puts branch, last commits, uncommitted files, TODOs into context
    └── audit-bash.sh             PostToolUse + PostToolUseFailure (Bash): logs every command to JSON Lines
```

## Use it

```bash
mkdir -p your-repo/.claude/hooks
cp claude-code-hooks/hooks/*.sh your-repo/.claude/hooks/
chmod +x your-repo/.claude/hooks/*.sh
# merge claude-code-hooks/settings.json into your-repo/.claude/settings.json
```

Requirements: `bash`, `jq`, `git`. `notify.sh` uses `osascript` on macOS, `notify-send` on Linux, and a terminal bell otherwise.

Set your test command for the Stop hook. Either export it, or put it in the hook command in `settings.json`:

```json
{ "type": "command", "command": "HOOK_TEST_CMD=\"pytest -q\" \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop-run-tests.sh", "timeout": 300 }
```

Config, all optional:

- `HOOK_TEST_CMD`: test command for `stop-run-tests.sh` (default `npm test --silent`)
- `HOOK_MAX_ATTEMPTS`: how many times in a row the Stop hook can send Claude back (default `3`)
- `HOOK_AUDIT_LOG`: where `audit-bash.sh` writes (default `.claude/bash-audit.jsonl`; add it to `.gitignore`)

Run `/hooks` inside Claude Code to check they're loaded.

## Test it

```bash
./test_hooks.sh
```

Expected last line:

```
43 passed, 0 failed
```

## How the exit codes work

From the hook descriptions in Claude Code 2.1.319:

- **PreToolUse**, exit 2: blocks the tool call and shows stderr to Claude
- **Stop**, exit 2: shows stderr to Claude and continues the conversation (Claude keeps working)
- **PostToolUse**, exit 2: shows stderr to Claude, but the tool has already run
- **SessionStart**, exit 0: stdout is added to Claude's context
- **Notification**: can't block anything; non-zero exits only show stderr to you
- Any other non-zero exit: stderr shown to you, nothing blocked

## Limits

- `block-dangerous.sh` is a seatbelt, not a sandbox. It matches text. `rm -rf /tmp/x`, a script file that does the deleting, or a command built from variables will get past it. Pair it with `permissions.deny` rules and a sandbox for anything that matters.
- `stop-run-tests.sh` runs on every stop while the working tree has uncommitted changes, including after a quick question. Slow test suite? Point `HOOK_TEST_CMD` at a fast subset.
- Claude Code also has its own cap: after 8 consecutive Stop-hook blocks it ends the turn anyway (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`). The script's own limit of 3 kicks in first.
- Hooks run with your user's permissions. Read any hook before you install it, these included.
