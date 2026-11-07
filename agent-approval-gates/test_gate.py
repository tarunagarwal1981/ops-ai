"""Run: python test_gate.py"""
from gate import TOOLS, Tool, run_tool

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

# Blocked verbs never run, even with approval.
trade = Tool("buy_stock", "trade", lambda: "bought", lambda: "BUY")
assert run_tool(trade, always)["status"] == "refused"

print("ALL PASSED")
