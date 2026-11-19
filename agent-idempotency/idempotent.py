"""Safe retries for agent tool calls. Stdlib only, Python 3.10+.

The rule: the CODE derives the idempotency key from the tool name and the
payload. The model never invents one. A call is recorded as "started" before
it runs, and "done" (with its result) after it succeeds.

If a call is found "started" but never "done", we are *in doubt*: it may have
run, it may not. We ask a downstream check ("is there already a sent email
with this key?") before ever running it again.
"""
import hashlib
import json
import sqlite3
from typing import Any, Callable, Optional


def make_key(tool: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{tool}:{canonical}".encode()).hexdigest()[:24]


class Ledger:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS calls ("
            "key TEXT PRIMARY KEY, tool TEXT, status TEXT, result TEXT)"
        )
        self.db.commit()

    def begin(self, key: str, tool: str) -> bool:
        """Atomically claim the key. False if someone already has it."""
        try:
            self.db.execute("INSERT INTO calls VALUES (?, ?, 'started', NULL)", (key, tool))
            self.db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get(self, key: str) -> Optional[tuple]:
        return self.db.execute(
            "SELECT status, result FROM calls WHERE key = ?", (key,)
        ).fetchone()

    def finish(self, key: str, result: Any) -> None:
        self.db.execute(
            "UPDATE calls SET status='done', result=? WHERE key=?", (json.dumps(result), key)
        )
        self.db.commit()

    def forget(self, key: str) -> None:
        self.db.execute("DELETE FROM calls WHERE key = ?", (key,))
        self.db.commit()


def call_once(
    ledger: Ledger,
    tool: str,
    fn: Callable[..., Any],
    payload: dict,
    already_happened: Optional[Callable[[str], Any]] = None,
) -> dict:
    """Run fn(**payload) at most once per distinct (tool, payload).

    already_happened(key) asks the outside world whether the effect exists
    (return its result, or None). Without it, an in-doubt call is reported
    and NOT re-run: a person decides.
    """
    key = make_key(tool, payload)
    if not ledger.begin(key, tool):
        status, result = ledger.get(key)
        if status == "done":
            return {"status": "replayed", "key": key, "result": json.loads(result)}
        # started but never finished: in doubt
        if already_happened is None:
            return {"status": "in_doubt", "key": key}
        found = already_happened(key)
        if found is None:
            ledger.forget(key)  # verified it did not happen: safe to run
            return call_once(ledger, tool, fn, payload, already_happened)
        ledger.finish(key, found)
        return {"status": "recovered", "key": key, "result": found}
    try:
        result = fn(**payload, idempotency_key=key)
    except TimeoutError:
        # We do not know if it ran. Leave "started" so the next try checks first.
        return {"status": "in_doubt", "key": key}
    except Exception as e:
        ledger.forget(key)  # failed cleanly, nothing happened: retry is safe
        return {"status": "failed", "key": key, "error": str(e)}
    ledger.finish(key, result)
    return {"status": "done", "key": key, "result": result}
