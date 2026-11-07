"""Approval gates for AI agent tools: put the lock in code, not in the prompt.

Companion to "Your AI Agent Can Now Act Without Asking. Lock These Four Words First."

Every tool declares a verb. Gated verbs (send, spend, sign, delete, submit) need a
person to approve the exact action before it runs. Blocked verbs never run, even
with approval. Everything else (read, draft, sort) runs on its own.
"""
from dataclasses import dataclass
from typing import Any, Callable

GATED = {"send", "spend", "sign", "delete", "submit"}
BLOCKED = {"trade", "transfer_between_accounts", "access_other_account"}


@dataclass
class Tool:
    name: str
    verb: str
    run: Callable[..., Any]
    describe: Callable[..., str]   # plain-English preview of exactly what will happen


def run_tool(tool: Tool, approve: Callable[[str], bool], **payload) -> dict:
    """The only path from the model to a side effect. The model never calls tool.run directly."""
    if tool.verb in BLOCKED:
        return {"status": "refused", "reason": f"'{tool.verb}' is never allowed"}
    if tool.verb in GATED:
        preview = tool.describe(**payload)
        if not approve(preview):
            return {"status": "held", "reason": "not approved", "preview": preview}
    return {"status": "done", "result": tool.run(**payload)}


# --- Example: the duplicate-invoice agent ----------------------------------

def _draft_email(to: str, body: str) -> str:
    return f"[draft saved for {to}]"

def _send_email(to: str, body: str) -> str:
    return f"[sent to {to}]"

def _pay_invoice(invoice_id: str, amount: float) -> str:
    return f"[paid {invoice_id}: {amount}]"


TOOLS = {
    "draft_email": Tool("draft_email", "draft", _draft_email,
                        lambda to, body: f"Draft an email to {to}"),
    "send_email":  Tool("send_email", "send", _send_email,
                        lambda to, body: f"SEND email to {to}:\n---\n{body}\n---"),
    "pay_invoice": Tool("pay_invoice", "spend", _pay_invoice,
                        lambda invoice_id, amount: f"PAY invoice {invoice_id} for {amount:,.2f}"),
}


if __name__ == "__main__":
    def ask_human(preview: str) -> bool:
        print(f"\nApproval needed:\n{preview}")
        return input("Approve? [y/N] ").strip().lower() == "y"

    body = "Invoice INV-1043 duplicates INV-0981, paid on 12 Oct. Please cancel it."
    print(run_tool(TOOLS["draft_email"], ask_human, to="billing@vendor.example", body=body))
    print(run_tool(TOOLS["send_email"], ask_human, to="billing@vendor.example", body=body))
    print(run_tool(TOOLS["pay_invoice"], ask_human, invoice_id="INV-1043", amount=1840.0))
