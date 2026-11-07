#!/bin/bash
# PostToolUse hook: format the file Claude just edited.
# Picks a formatter by file type and skips quietly if it isn't installed.
file=$(jq -r '.tool_input.file_path // empty')
[[ -z "$file" || ! -f "$file" ]] && exit 0

case "$file" in
  *.py)
    command -v ruff >/dev/null && ruff format --quiet "$file" ;;
  *.js|*.jsx|*.ts|*.tsx|*.json|*.css|*.md|*.yml|*.yaml)
    command -v npx >/dev/null && npx --no-install prettier --write --log-level silent "$file" 2>/dev/null ;;
esac
exit 0
