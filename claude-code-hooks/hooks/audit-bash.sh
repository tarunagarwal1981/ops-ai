#!/usr/bin/env bash
# PostToolUse + PostToolUseFailure (matcher: Bash)
# Appends every Bash command Claude ran to a JSON Lines file.
# Never blocks: always exits 0.
set -uo pipefail

input=$(cat)
dir=$(jq -r '.cwd // empty' <<<"$input")
log="${HOOK_AUDIT_LOG:-${CLAUDE_PROJECT_DIR:-${dir:-.}}/.claude/bash-audit.jsonl}"
mkdir -p "$(dirname "$log")"

jq -c --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{
  ts: $ts,
  session: .session_id,
  status: (if .hook_event_name == "PostToolUseFailure" then "failed" else "ok" end),
  cwd: .cwd,
  command: .tool_input.command
}' <<<"$input" >> "$log" 2>/dev/null || true
exit 0
