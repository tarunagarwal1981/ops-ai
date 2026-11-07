# Claude Code starter folder

A starting `.claude/` setup: the six pieces from *The Claude Code Setup I Wish I Had on Day One*, ready to copy into a repo.

```
claude-code-starter/
├── CLAUDE.md                        1. project memory (template, fill it in)
└── .claude/
    ├── settings.json                5. hooks + 6. permissions
    ├── hooks/
    │   ├── block-env.sh             PreToolUse: refuses edits to .env files
    │   └── format.sh                PostToolUse: formats the edited file
    ├── agents/
    │   └── code-reviewer.md         4. read-only reviewer subagent
    └── skills/
        └── new-endpoint/SKILL.md    3. example team procedure
```

Plan mode (2) needs no file: press Shift+Tab.

## Use it

```bash
cp -r claude-code-starter/.claude  your-repo/
cp    claude-code-starter/CLAUDE.md your-repo/     # or run /init and merge
chmod +x your-repo/.claude/hooks/*.sh
```

Then edit before you rely on it:

- **CLAUDE.md**: replace every `<placeholder>`. Delete rules that don't apply. Keep it short.
- **settings.json**: the allowlist assumes `pnpm`. Swap in your own test and lint commands.
- **skills/new-endpoint**: an example. Replace it with a procedure your team really repeats.

The hooks need `jq`. `format.sh` uses `ruff` for Python and `prettier` for JS/TS/JSON/Markdown if they're installed, and skips silently if not.

## Check it's working

- `/permissions` lists every rule and which file it came from
- `/context` shows what's filling the context window
- Ask Claude to edit `.env`: the hook should block it with a message

## The rule of thumb

Annoying if it's broken? Write it in CLAUDE.md. Expensive if it's broken? Make it a hook or a deny rule. Instructions can slip on a long task; hooks and permissions are enforced by Claude Code itself.
