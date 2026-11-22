"""Runs a scripted day for the example org and prints every decision.   python demo.py"""
import json, os, tempfile, threading, urllib.request
from client import AgentOrg, Denied, NeedsApproval
import server

HERE = os.path.dirname(os.path.abspath(__file__))
httpd, token = server.make_server(os.path.join(HERE, "org.example.json"),
                                  os.path.join(tempfile.mkdtemp(), "demo.db"), port=0)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{httpd.server_address[1]}"

refund, triage, invoice = (AgentOrg(url, a) for a in ("refund-bot", "triage-bot", "invoice-bot"))


def show(who, what, d):
    mark = {"allow": "ALLOW", "deny": "DENY ", "needs_approval": "WAIT "}[d.status]
    print(f"  {mark}  {who:<12} {what:<34} {d.reason}")


print("A day at Acme Support\n")
show("refund-bot", "spend $12 (refund)", refund.check("spend", "payment", "p1", amount_usd=12))
show("refund-bot", "spend $35 (refund)", d := refund.check("spend", "payment", "p2", amount_usd=35))
print("             ...a person opens the panel and approves it...")
req = urllib.request.Request(f"{url}/api/approvals/{d.approval_id}/approve", b"{}",
                             {"X-Admin-Token": token, "Content-Type": "application/json"})
urllib.request.urlopen(req)
show("refund-bot", "spend $35 again (approved)", refund.check("spend", "payment", "p2", amount_usd=35))
show("refund-bot", "spend $35 again (one-time!)", refund.check("spend", "payment", "p2", amount_usd=35))
show("refund-bot", "spend $80 (over its $50 cap)", refund.check("spend", "payment", "p3", amount_usd=80))
show("refund-bot", "email amy@acme.com", refund.check("send", "email", "m1", recipient="amy@acme.com"))
show("refund-bot", "email boss@competitor.com", refund.check("send", "email", "m2", recipient="boss@competitor.com"))
show("refund-bot", "email x@unknown.io", refund.check("send", "email", "m3", recipient="x@unknown.io"))
show("refund-bot", "read crm", refund.check("read", "crm", "customers"))
show("refund-bot", "write crm", refund.check("write", "crm", "customers"))
show("refund-bot", "delete tickets", refund.check("delete", "tickets", "t1"))
show("triage-bot", "refund payments", triage.check("refund", "payments", "p9"))
show("triage-bot", "label tickets", triage.check("label", "tickets", "t1"))
show("invoice-bot", "spend $90", invoice.check("spend", "invoice", "i1", amount_usd=90))
show("invoice-bot", "spend $90", invoice.check("spend", "invoice", "i2", amount_usd=90))
show("invoice-bot", "spend $90 (team budget is $200)", invoice.check("spend", "invoice", "i3", amount_usd=90))

print("\nAs a decorator, inside your agent code:\n")


@refund.guard("spend", "payment", amount_arg="amount")
def issue_refund(payment_id, amount):
    return f"refunded ${amount} on {payment_id}"


for amt in (10, 70, 30):
    try:
        print("  ", issue_refund("p7", amt))
    except NeedsApproval as e:
        print(f"   waiting for a person: {e}")
    except Denied as e:
        print(f"   blocked: {e}")

print("\nIf the policy server is down, nothing is allowed:")
print("  ", AgentOrg("http://127.0.0.1:1", "refund-bot", timeout=1).check("spend", "payment", "p", amount_usd=1).reason)
httpd.shutdown()
