"""A flaky 'send email' tool: it sends, then the reply times out. Run: python demo.py"""
from idempotent import Ledger, call_once

outbox = []          # the "real world": what the vendor actually received
timeouts = {"left": 1}


def send_email(to, body, idempotency_key=None):
    outbox.append({"to": to, "body": body, "key": idempotency_key})
    if timeouts["left"] > 0:          # sent, but the confirmation is lost
        timeouts["left"] -= 1
        raise TimeoutError("no reply from mail server")
    return f"sent to {to}"


def sent_with_key(key):
    return next((f"sent to {m['to']}" for m in outbox if m["key"] == key), None)


payload = {"to": "billing@vendor.example", "body": "Please cancel the duplicate invoice."}

print("Naive retry:")
for _ in range(2):
    try:
        send_email(**payload)
    except TimeoutError:
        pass
print(f"  vendor received {len(outbox)} emails\n")

outbox.clear(); timeouts["left"] = 1
ledger = Ledger()
print("With call_once:")
for attempt in (1, 2, 3):
    r = call_once(ledger, "send_email", send_email, payload, already_happened=sent_with_key)
    print(f"  attempt {attempt}: {r['status']}")
print(f"  vendor received {len(outbox)} email")

print("\nMore like this: https://github.com/tarunagarwal1981/ops-ai")
print("If this saved you a duplicate email, a star helps others find it.")
