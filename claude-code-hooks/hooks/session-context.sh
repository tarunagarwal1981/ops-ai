#!/usr/bin/env bash
# SessionStart (matcher: startup|clear|compact)
# Whatever this prints on stdout (exit 0) is added to Claude's context.
set -uo pipefail

dir=$(jq -r '.cwd // empty')
cd "${CLAUDE_PROJECT_DIR:-${dir:-.}}" || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

echo "## Repo state at session start"
echo "Branch: $(git branch --show-current 2>/dev/null || echo detached)"
echo
echo "Last 5 commits:"
git log --oneline -5 2>/dev/null | sed 's/^/- /'
echo
changed=$(git status --porcelain 2>/dev/null)
if [[ -n "$changed" ]]; then
  echo "Uncommitted changes ($(wc -l <<<"$changed" | tr -d ' ') files):"
  head -n 15 <<<"$changed" | sed 's/^/- /'
else
  echo "Working tree is clean."
fi
echo
todos=$(git grep -nE '\b(TODO|FIXME)\b' -- ':!*.lock' ':!*.min.js' 2>/dev/null | head -n 10)
if [[ -n "$todos" ]]; then
  echo "Open TODO/FIXME (first 10):"
  sed 's/^/- /' <<<"$todos"
fi
exit 0
