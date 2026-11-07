#!/usr/bin/env bash
# Notification (matcher: permission_prompt|idle_prompt)
# Pops a desktop notification when Claude is waiting on you.
set -uo pipefail

input=$(cat)
msg=$(jq -r '.message // "Claude Code needs your attention"' <<<"$input")
title=$(jq -r '.title // "Claude Code"' <<<"$input")
project=$(basename "$(jq -r '.cwd // empty' <<<"$input")")
[[ -n "$project" ]] && title="$title ($project)"

if [[ -n "${HOOK_NOTIFY_DRY_RUN:-}" ]]; then
  echo "$title: $msg"; exit 0              # used by the tests
elif command -v osascript >/dev/null; then  # macOS
  osascript -e 'on run argv' \
            -e 'display notification (item 1 of argv) with title (item 2 of argv)' \
            -e 'end run' "$msg" "$title"
elif command -v notify-send >/dev/null; then  # Linux
  notify-send "$title" "$msg"
else
  printf '\a' > /dev/tty 2>/dev/null || true # terminal bell as a last resort
fi
exit 0
