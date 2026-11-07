#!/usr/bin/env bash
# Stop
# Runs the test suite when Claude says it's done. If tests fail, exit 2:
# Claude Code keeps the turn going and shows Claude the failure output.
#
# Config (env vars):
#   HOOK_TEST_CMD       test command (default: "npm test --silent")
#   HOOK_MAX_ATTEMPTS   how many times in a row we may send Claude back (default: 3)
set -uo pipefail

input=$(cat)
session=$(jq -r '.session_id // "nosession"' <<<"$input")
dir=$(jq -r '.cwd // empty' <<<"$input")
cd "${CLAUDE_PROJECT_DIR:-${dir:-.}}" || exit 0

test_cmd="${HOOK_TEST_CMD:-npm test --silent}"
max="${HOOK_MAX_ATTEMPTS:-3}"
counter="${TMPDIR:-/tmp}/claude-stop-tests-${session}"

# Nothing changed in the working tree? Then there's nothing to test.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
   && [[ -z "$(git status --porcelain 2>/dev/null)" ]]; then
  rm -f "$counter"; exit 0
fi

if output=$(bash -c "$test_cmd" 2>&1); then
  rm -f "$counter"; exit 0
fi

attempts=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$attempts" > "$counter"

if (( attempts > max )); then
  rm -f "$counter"
  echo "Tests still failing after $max attempts. Letting Claude stop; over to you." >&2
  exit 1   # non-blocking: the user sees this, Claude stops
fi

{
  echo "Tests are failing, so the task is not done (attempt $attempts of $max)."
  echo "Command: $test_cmd"
  echo "Last 40 lines of output:"
  tail -n 40 <<<"$output"
  echo "Fix the cause. Do not skip, delete or weaken tests to make them pass."
} >&2
exit 2
