#!/usr/bin/env bash
# PreToolUse (matcher: Edit|Write|MultiEdit)
# Looks at the text Claude is about to write and blocks it if it contains
# something that looks like a real secret (cloud keys, API tokens, private keys).
set -uo pipefail

input=$(cat)
text=$(jq -r '[.tool_input.content, .tool_input.new_string, (.tool_input.edits // [] | .[].new_string)] | map(select(. != null)) | join("\n")' <<<"$input")
[[ -z "$text" ]] && exit 0

rules=(
  'AKIA[0-9A-Z]{16}|an AWS access key ID'
  '-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|a private key'
  'gh[pousr]_[A-Za-z0-9]{36,}|a GitHub token'
  'xox[baprs]-[A-Za-z0-9-]{10,}|a Slack token'
  'sk-(proj-|ant-)?[A-Za-z0-9_-]{32,}|an OpenAI/Anthropic-style API key'
  'AIza[0-9A-Za-z_-]{35}|a Google API key'
)
for rule in "${rules[@]}"; do
  pattern="${rule%|*}"; what="${rule##*|}"
  if grep -Eq -- "$pattern" <<<"$text"; then
    echo "Blocked by secret-scan.sh: the text looks like it contains $what." >&2
    echo "Read secrets from environment variables instead, and put placeholders like <YOUR_KEY> in examples." >&2
    exit 2
  fi
done
exit 0
