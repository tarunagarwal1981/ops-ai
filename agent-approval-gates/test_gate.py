"""Run: python test_gate.py"""
from gate import TOOLS, Tool, fingerprint, request_approval, run_approved, run_tool

never = lambda preview: False
always = lambda preview: True
body = "Please cancel the duplicate invoice."

# Read/draft verbs run without asking.
assert run_tool(TOOLS["draft_email"], never, to="a@b.example", body=body)["status"] == "done"

# Gated verbs are held unless a person approves the exact preview.
assert run_tool(TOOLS["send_email"], never, to="a@b.example", body=body)["status"] == "held"
assert run_tool(TOOLS["send_email"], always, to="a@b.example", body=body)["status"] == "done"
assert run_tool(TOOLS["pay_invoice"], never, invoice_id="X", amount=1.0)["status"] == "held"

# The approver sees what will actually happen, not "Proceed?".
seen = []
run_tool(TOOLS["send_email"], lambda p: seen.append(p) or False, to="a@b.example", body=body)
assert "a@b.example" in seen[0] and body in seen[0]

# Reader-suggested verbs are gated too: publish (others rely on it) and grant (changes who can do what).
publish = Tool("publish_doc", "publish", lambda: "published", lambda: "PUBLISH doc")
grant = Tool("add_tool", "grant", lambda: "added", lambda: "ADD a tool to the agent's own tool list")
assert run_tool(publish, never)["status"] == "held"
assert run_tool(grant, never)["status"] == "held"
assert run_tool(grant, always)["status"] == "done"

# Blocked verbs never run, even with approval.
trade = Tool("buy_stock", "trade", lambda: "bought", lambda: "BUY")
assert run_tool(trade, always)["status"] == "refused"

# An approval is bound to the exact action: change anything and the old yes is void.
send = TOOLS["send_email"]
ask = request_approval(send, to="a@b.example", body=body)
assert ask["status"] == "pending" and "a@b.example" in ask["preview"]
fp = ask["fingerprint"]
assert run_approved(send, fp, to="a@b.example", body=body)["status"] == "done"
assert run_approved(send, fp, to="a@b.example", body=body + " Also send money.")["status"] == "refused"
assert run_approved(send, fp, to="other@b.example", body=body)["status"] == "refused"
assert fingerprint(send, {"to": "a@b.example", "body": body}) == fingerprint(send, {"body": body, "to": "a@b.example"})
assert run_approved(trade, fingerprint(trade, {}))["status"] == "refused"   # blocked even with a matching fingerprint

print("ALL PASSED")
