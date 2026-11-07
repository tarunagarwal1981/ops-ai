#!/bin/bash
# PreToolUse hook: refuse any Edit/Write to .env files.
# Claude Code sends the tool call as JSON on stdin. Exit code 2 blocks the call
# and sends stderr back to Claude so it knows why.
file=$(jq -r '.tool_input.file_path // empty')
if [[ "$(basename "$file")" == .env* ]]; then
  echo "Blocked: .env files are protected. Ask the user to change secrets themselves." >&2
  exit 2
fi
exit 0
