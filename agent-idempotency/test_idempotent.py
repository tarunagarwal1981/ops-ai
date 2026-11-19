"""Run: python test_idempotent.py"""
from idempotent import AckedThenFailed, Ledger, call_once, make_key

P = {"to": "a@b.example", "body": "hi"}


def world():
    sent, flaky = [], {"n": 0}

    def send(to, body, idempotency_key=None):
        sent.append(idempotency_key)
        if flaky["n"] > 0:
            flaky["n"] -= 1
            raise TimeoutError()
        return "ok"

    return sent, flaky, send


# Same payload -> same key; key order does not matter; different payload differs.
assert make_key("t", {"a": 1, "b": 2}) == make_key("t", {"b": 2, "a": 1})
assert make_key("t", {"a": 1}) != make_key("t", {"a": 2})

# A finished call is replayed, not re-run.
sent, _, send = world()
l = Ledger()
assert call_once(l, "send", send, P)["status"] == "done"
assert call_once(l, "send", send, P)["status"] == "replayed"
assert len(sent) == 1

# Timeout after the effect happened: verified via the check, not re-sent.
sent, flaky, send = world(); flaky["n"] = 1
l = Ledger()
check = lambda key: "ok" if key in sent else None
assert call_once(l, "send", send, P, check)["status"] == "in_doubt"
assert call_once(l, "send", send, P, check)["status"] == "recovered"
assert len(sent) == 1

# Timeout where the effect did NOT happen: check says no, so it runs once more.
l = Ledger()
n = {"calls": 0}
def lost(to, body, idempotency_key=None):
    n["calls"] += 1
    if n["calls"] == 1:
        raise TimeoutError()      # never reached the world
    return "ok"
assert call_once(l, "send", lost, P, lambda k: None)["status"] == "in_doubt"
assert call_once(l, "send", lost, P, lambda k: None)["status"] == "done"

# No check available: in-doubt is never silently re-run.
sent, flaky, send = world(); flaky["n"] = 1
l = Ledger()
call_once(l, "send", send, P)
assert call_once(l, "send", send, P)["status"] == "in_doubt"
assert len(sent) == 1

# Clean failure frees the key so a retry can run.
l = Ledger()
def boom(to, body, idempotency_key=None): raise ValueError("bad address")
assert call_once(l, "send", boom, P)["status"] == "failed"
sent, _, send = world()
assert call_once(l, "send", send, P)["status"] == "done"

# Vendor answered but our read failed: their id is stored, no check lookup needed, never re-sent.
sent = []
def acked(to, body, idempotency_key=None):
    sent.append(idempotency_key)
    raise AckedThenFailed("msg_123")
l = Ledger()
r = call_once(l, "send", acked, P, already_happened=None)
assert r["status"] == "recovered" and r["result"] == {"vendor_id": "msg_123"}
assert call_once(l, "send", acked, P)["status"] == "replayed"
assert len(sent) == 1

print("ALL PASSED")
