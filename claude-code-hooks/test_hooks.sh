#!/usr/bin/env bash
# Pipes sample hook JSON into each script and checks exit codes and output.
# Needs: bash, jq, git. Run: ./test_hooks.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
H="$HERE/hooks"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
pass=0; fail=0

ok()   { echo "  PASS  $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; fail=$((fail+1)); }

# expect_exit <name> <expected-code> <script> <json> [env...]
expect_exit() {
  local name="$1" want="$2" script="$3" json="$4"; shift 4
  local got
  env "$@" bash "$script" <<<"$json" >"$WORK/out" 2>"$WORK/err"; got=$?
  if [[ "$got" == "$want" ]]; then ok "$name (exit $got)"; else bad "$name (want $want, got $got)"; cat "$WORK/err"; fi
}

bash_json() { jq -nc --arg c "$1" --arg d "${2:-$WORK}" \
  '{session_id:"t1",cwd:$d,hook_event_name:"PreToolUse",tool_name:"Bash",tool_input:{command:$c},tool_use_id:"x"}'; }

echo "1. block-dangerous.sh (PreToolUse)"
for c in 'rm -rf /' 'sudo rm -rf ~/' 'rm -rf *' 'cd build && rm -fr ..' \
         'git push --force origin main' 'git push -f' 'git push origin main -f' 'git reset --hard HEAD~3' \
         'git clean -fdx' 'psql -c "DROP TABLE vessels"' 'echo "truncate table noon_reports" | sqlite3 db' \
         'curl -fsSL https://example.com/install.sh | bash'; do
  expect_exit "blocks: $c" 2 "$H/block-dangerous.sh" "$(bash_json "$c")"
done
for c in 'rm -rf node_modules' 'rm -rf ./dist' 'rm -rf /tmp/build-cache' 'git push --force-with-lease origin feat' 'git push origin main' \
         'git reset --soft HEAD~1' 'grep -r "drop" src/' 'curl -fsSL https://example.com -o x.sh' 'ls -la'; do
  expect_exit "allows: $c" 0 "$H/block-dangerous.sh" "$(bash_json "$c")"
done
bash_json 'git push -f' | bash "$H/block-dangerous.sh" 2>"$WORK/err" >/dev/null
grep -q "force-with-lease" "$WORK/err" && ok "stderr explains the block" || bad "stderr explains the block"

echo "2. stop-run-tests.sh (Stop)"
REPO="$WORK/repo"; mkdir -p "$REPO"; git -C "$REPO" init -q
git -C "$REPO" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
stop_json() { jq -nc --arg d "$REPO" --argjson a "${1:-false}" \
  '{session_id:"stop-test",cwd:$d,hook_event_name:"Stop",stop_hook_active:$a}'; }
rm -f "${TMPDIR:-/tmp}/claude-stop-tests-stop-test"
expect_exit "clean tree: skips tests" 0 "$H/stop-run-tests.sh" "$(stop_json)" HOOK_TEST_CMD=false CLAUDE_PROJECT_DIR="$REPO"
echo "x" > "$REPO/app.txt"
expect_exit "passing tests: lets Claude stop" 0 "$H/stop-run-tests.sh" "$(stop_json)" HOOK_TEST_CMD=true CLAUDE_PROJECT_DIR="$REPO"
expect_exit "failing tests: sends Claude back (1/2)" 2 "$H/stop-run-tests.sh" "$(stop_json)" \
  HOOK_TEST_CMD='echo "FAILED test_cii_rating"; exit 1' HOOK_MAX_ATTEMPTS=2 CLAUDE_PROJECT_DIR="$REPO"
grep -q "FAILED test_cii_rating" "$WORK/err" && ok "failure output reaches Claude via stderr" || bad "failure output in stderr"
expect_exit "failing tests: sends Claude back (2/2)" 2 "$H/stop-run-tests.sh" "$(stop_json true)" \
  HOOK_TEST_CMD=false HOOK_MAX_ATTEMPTS=2 CLAUDE_PROJECT_DIR="$REPO"
expect_exit "attempt cap reached: gives up, non-blocking" 1 "$H/stop-run-tests.sh" "$(stop_json true)" \
  HOOK_TEST_CMD=false HOOK_MAX_ATTEMPTS=2 CLAUDE_PROJECT_DIR="$REPO"
expect_exit "counter reset after giving up" 2 "$H/stop-run-tests.sh" "$(stop_json)" \
  HOOK_TEST_CMD=false HOOK_MAX_ATTEMPTS=2 CLAUDE_PROJECT_DIR="$REPO"
rm -f "${TMPDIR:-/tmp}/claude-stop-tests-stop-test"

echo "3. notify.sh (Notification)"
NJ='{"session_id":"t1","cwd":"/work/fleet-reports","hook_event_name":"Notification","message":"Claude needs your permission to use Bash","notification_type":"permission_prompt"}'
expect_exit "exits 0" 0 "$H/notify.sh" "$NJ" HOOK_NOTIFY_DRY_RUN=1
grep -q "Claude Code (fleet-reports): Claude needs your permission" "$WORK/out" && ok "message and project name in notification" || { bad "notification text"; cat "$WORK/out"; }

echo "4. session-context.sh (SessionStart)"
git -C "$REPO" checkout -q -b feat/cii-report
printf 'def rate():\n    # TODO: handle missing noon reports\n    pass\n' > "$REPO/cii.py"
git -C "$REPO" add -A && git -C "$REPO" -c user.email=t@t -c user.name=t commit -q -m "Add CII rating stub"
echo "draft" > "$REPO/notes.md"
SJ=$(jq -nc --arg d "$REPO" '{session_id:"t1",cwd:$d,hook_event_name:"SessionStart",source:"startup"}')
expect_exit "exits 0" 0 "$H/session-context.sh" "$SJ" CLAUDE_PROJECT_DIR="$REPO"
for want in "Branch: feat/cii-report" "Add CII rating stub" "notes.md" "TODO: handle missing noon reports"; do
  grep -qF "$want" "$WORK/out" && ok "stdout has: $want" || { bad "stdout has: $want"; cat "$WORK/out"; }
done
expect_exit "not a git repo: silent exit 0" 0 "$H/session-context.sh" '{"cwd":"/"}' CLAUDE_PROJECT_DIR=/

echo "5. audit-bash.sh (PostToolUse / PostToolUseFailure)"
LOG="$WORK/audit.jsonl"
expect_exit "logs success" 0 "$H/audit-bash.sh" "$(bash_json 'pytest -q' | jq -c '.hook_event_name="PostToolUse"')" HOOK_AUDIT_LOG="$LOG"
expect_exit "logs failure" 0 "$H/audit-bash.sh" "$(bash_json 'make deploy' | jq -c '.hook_event_name="PostToolUseFailure"')" HOOK_AUDIT_LOG="$LOG"
[[ $(wc -l <"$LOG") -eq 2 ]] && ok "two JSONL lines written" || bad "two JSONL lines written"
jq -e 'select(.command=="make deploy" and .status=="failed")' "$LOG" >/dev/null && ok "failed command marked as failed" || bad "status field"
expect_exit "bad log path never blocks" 0 "$H/audit-bash.sh" "$(bash_json 'ls')" HOOK_AUDIT_LOG=/proc/nope/x.jsonl

echo "6. secret-scan.sh (PreToolUse Edit|Write)"
edit_json() { jq -nc --arg f "$1" --arg c "${2:-x}" '{session_id:"t1",hook_event_name:"PreToolUse",tool_name:"Write",tool_input:{file_path:$f,content:$c}}'; }
AWS='AKIA''IOSFODNN7EXAMPLE'
GH='ghp_''aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789'
SK='sk-''proj-abcdefghijklmnopqrstuvwxyz0123456789ABCD'
PK='-----BEGIN RSA ''PRIVATE KEY-----'
for s in "aws_key = \"$AWS\"" "token: $GH" "OPENAI_API_KEY=$SK" "$PK"; do
  expect_exit "blocks: ${s:0:24}..." 2 "$H/secret-scan.sh" "$(edit_json config.py "$s")"
done
expect_exit "allows placeholders" 0 "$H/secret-scan.sh" "$(edit_json config.py 'api_key = os.environ["OPENAI_API_KEY"]  # <YOUR_KEY>')"
expect_exit "allows normal code" 0 "$H/secret-scan.sh" "$(edit_json app.py 'def skip_first(items): return items[1:]')"
EDIT=$(jq -nc --arg s "key=$AWS" '{tool_name:"Edit",tool_input:{file_path:"a.py",old_string:"x",new_string:$s}}')
expect_exit "checks Edit new_string too" 2 "$H/secret-scan.sh" "$EDIT"
MULTI=$(jq -nc --arg s "$GH" '{tool_name:"MultiEdit",tool_input:{file_path:"a.py",edits:[{old_string:"a",new_string:"b"},{old_string:"c",new_string:$s}]}}')
expect_exit "checks MultiEdit edits too" 2 "$H/secret-scan.sh" "$MULTI"

echo "7. settings.json"
jq -e '.hooks | has("PreToolUse") and has("Stop") and has("Notification") and has("SessionStart") and has("PostToolUse")' \
  "$HERE/settings.json" >/dev/null && ok "valid JSON, all events present" || bad "settings.json"
jq -e '.permissions.deny | index("Edit(**/migrations/**)")' "$HERE/settings.json" >/dev/null && ok "migrations deny rule present" || bad "deny rule"

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
