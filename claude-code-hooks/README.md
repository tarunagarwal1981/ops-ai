# Claude Code hooks: six worth adding today

Six small hook scripts for Claude Code, a deny rule, a `settings.json` that wires them up and a test script. Started as companion code for *5 Claude Code Hooks Worth Adding Today*; the secret scan and the deny rule came later.

They build on the two hooks in [`claude-code-starter/`](../claude-code-starter/) (formatter, `.env` blocker). None of these repeat those.

```
claude-code-hooks/
├── settings.json                 wires all six hooks, plus a deny rule for migration files
├── test_hooks.sh                 pipes sample JSON into each script, checks the result
└── hooks/
    ├── block-dangerous.sh        PreToolUse (Bash): blocks rm -rf /, force push, reset --hard, DROP TABLE, curl | sh
    ├── secret-scan.sh            PreToolUse (Edit|Write): blocks text that looks like an AWS key, API token or private key
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
52 passed, 0 failed
```

## How the exit codes work

From the hook descriptions in Claude Code 2.1.319:

- **PreToolUse**, exit 2: blocks the tool call and shows stderr to Claude
- **Stop**, exit 2: shows stderr to Claude and continues the conversation (Claude keeps working)
- **PostToolUse**, exit 2: shows stderr to Claude, but the tool has already run
- **SessionStart**, exit 0: stdout is added to Claude's context
- **Notification**: can't block anything; non-zero exits only show stderr to you
- Any other non-zero exit: stderr shown to you, nothing blocked

## Protecting a folder: deny rule first, hook second, CI last

A hook only watches the tool it's attached to. I had a hook that stopped Claude editing migration files, and Claude made the same change with `echo >> db/migrations/004.sql` through Bash.

Claude Code's own deny rules go further than you might expect. `settings.json` here has:

```json
"permissions": { "deny": ["Edit(**/migrations/**)"] }
```

Claude Code checks shell commands that write files against `Edit` rules too. I tested it in Claude Code 2.1.327, with each command explicitly allowed (`--allowedTools "Bash(echo *)"` and so on) so only the deny rule could stop it:

| Command Claude ran | Result |
| --- | --- |
| `echo "-- x" >> db/migrations/001.sql` | denied |
| `echo "-- t" \| tee -a db/migrations/001.sql` | denied |
| `cp new.sql db/migrations/001.sql` | denied |
| `sed -i "s/int/bigint/" db/migrations/001.sql` | denied |
| `python3 -c "open('db/migrations/001.sql','a').write('-- p')"` | **ran, file changed** |
| `f=db/migrations/004.sql; echo "-- x" >> $f` | **ran, file created** (the path only exists after the variable expands) |
| `cd db/migrations && echo "-- y" >> 004.sql` | denied |

(Variable and `cd` cases added after a reader pointed them out; same version, same setup.)

So the deny rule closes most doors, but any script, or a path built from a variable, can still write the file. Anything that matches on the command is one interpreter away from a bypass.

### Push the lock below the agent: file permissions

A reader suggested the stronger fix: stop matching commands and make the file itself unwritable, so every program fails the same way. I tested two versions on Linux, running as a normal (non-root) user, since root ignores file permissions.

**Applied migrations owned by a different user, in a sticky directory** (`chown root` on the files, `chmod 1777 db/migrations`, files `644`). New files can still be created, since the agent has to be able to add migration 004:

| Attempt, as the agent's user | Result |
| --- | --- |
| create `004.sql` | allowed |
| `echo >>` onto `001.sql` | denied |
| `python3 -c "open('001.sql','a')..."` | denied |
| `sed -i` on `001.sql` | denied |
| `mv` or `rm` on `001.sql` | denied |
| `cp` over `001.sql` | denied |
| `os.replace(004.sql, 001.sql)` | denied |
| `chmod u+w 001.sql`, or `os.chmod` in Python | denied (not the owner) |

The same attempts with a variable-built path, or after a `cd`, were denied too, because the check happens on the file and not the command text.

**Files owned by the agent's own user with `chmod -w`** is weaker. `echo >>` and a plain Python `open()` fail, but `os.chmod(path, 0o666)` followed by a write **succeeds**, because the owner may change their own permissions. Blocking `chmod` in a hook only blocks the command `chmod`, not the Python call. If you go this way, the owner has to be someone other than the agent.

The catch is setup: the agent has to run as a different user than the file owner, and something else (you, or a deploy step) has to take ownership of a migration once it's applied. Tested only on Linux; macOS, Windows and containers behave differently, and anything running as root bypasses all of it. So the layers are: file permissions where you can, the deny rule for the route Claude usually takes, a hook for the readable error message, and CI as the check nobody can talk around.

The last layer is a check that doesn't care how the file changed. For migrations the real rule is "new files are fine, never edit an applied one", so in CI:

```bash
! git diff --name-status origin/main...HEAD -- db/migrations/ | grep -v '^A'
```

It fails the build if anything in `db/migrations/` was modified, renamed or deleted. (The `!` matters: `grep` exits 0 when it finds a line, which is the case you want to fail.)

Deny rule for most routes, hook for the error message Claude sees, CI for the part nobody can talk around. Thanks to the r/ClaudeCode thread where this came up.

## Limits

- `block-dangerous.sh` is a seatbelt, not a sandbox. It matches text. `rm -rf /tmp/x`, a script file that does the deleting, or a command built from variables will get past it. Pair it with `permissions.deny` rules and a sandbox for anything that matters.
- `stop-run-tests.sh` runs on every stop while the working tree has uncommitted changes, including after a quick question. Slow test suite? Point `HOOK_TEST_CMD` at a fast subset.
- Claude Code also has its own cap: after 8 consecutive Stop-hook blocks it ends the turn anyway (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`). The script's own limit of 3 kicks in first.
- Hooks run with your user's permissions. Read any hook before you install it, these included.

---

Want this set up in one command? The [Claude Code Starter Kit](https://tarunagarwal.gumroad.com/l/claude-code-starter-kit) adds four more hooks (protected paths, `.env` blocker, no commits on main, formatter), five subagents, five CLAUDE.md templates and an installer that picks your test command. Everything in this folder stays free.
