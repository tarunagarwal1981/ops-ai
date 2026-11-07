#!/usr/bin/env bash
# PreToolUse (matcher: Bash)
# Blocks a short list of commands that are expensive to undo.
# Exit 2 = Claude Code cancels the tool call and shows stderr to Claude.
set -uo pipefail

cmd=$(jq -r '.tool_input.command // empty')
[[ -z "$cmd" ]] && exit 0

S='[[:space:]]'
rules=(
  # rm -rf aimed at /, ~, $HOME, *, . or ..
  "rm${S}+(-[a-zA-Z]*${S}+)*-[a-zA-Z]*(rf|fr)[a-zA-Z]*${S}+((/|~/?|\\\$HOME/?|\\.\\.?/?)\\*?|\\*)(${S}|$)|rm -rf on a root, home or wildcard path"
  # force push (--force-with-lease is allowed)
  "git${S}+push(${S}.*)?${S}(--force|-f)(${S}|$)|git push --force (use --force-with-lease, or ask the user)"
  "git${S}+reset${S}+--hard|git reset --hard throws away uncommitted work"
  "git${S}+clean${S}+-[a-zA-Z]*f|git clean -f deletes untracked files"
  "(drop${S}+(table|database|schema)|truncate${S}+(table${S}+)?[a-z_\"\`])|destructive SQL (DROP / TRUNCATE)"
  "(curl|wget)${S}[^|]*\\|${S}*(sudo${S}+)?(ba|z)?sh|piping a download straight into a shell"
)

for rule in "${rules[@]}"; do
  pattern="${rule%|*}"
  reason="${rule##*|}"
  if grep -Eiq -- "$pattern" <<<"$cmd"; then
    echo "Blocked by block-dangerous.sh: $reason." >&2
    echo "If this is really needed, stop and ask the user to run it themselves." >&2
    exit 2
  fi
done
exit 0
