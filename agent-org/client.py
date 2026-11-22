"""Tiny client for agent-org. Standard library only; copy this file into your agent project.

    from client import AgentOrg, Denied, NeedsApproval
    org = AgentOrg("http://127.0.0.1:8787", agent="refund-bot", key=None)

    d = org.check("spend", "payment", "pay_123", amount_usd=35)   # -> Decision
    if d.allowed: ...do it...

    @org.guard("spend", "payment", amount_arg="amount")           # raises Denied / NeedsApproval
    def refund(payment_id, amount): ...

Fails closed: if the server cannot be reached, nothing is allowed.
"""
import functools
import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class Denied(Exception):
    pass


class NeedsApproval(Denied):
    def __init__(self, msg, approval_id=None):
        super().__init__(msg)
        self.approval_id = approval_id


@dataclass
class Decision:
    allowed: bool
    status: str       # allow | deny | needs_approval
    reason: str
    approval_id: str = ""
    raw: dict = None


class AgentOrg:
    def __init__(self, url, agent, key=None, timeout=5):
        self.url, self.agent, self.key, self.timeout = url.rstrip("/"), agent, key, timeout

    def check(self, action, rtype="", rid="", dry_run=False, **props):
        body = {"subject": {"type": "agent", "id": self.agent}, "action": {"name": action},
                "resource": {"type": rtype, "id": rid, "properties": props}, "context": {"dry_run": dry_run}}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        try:
            rq = urllib.request.Request(self.url + "/access/v1/evaluation", json.dumps(body).encode(), headers)
            with urllib.request.urlopen(rq, timeout=self.timeout) as r:
                out = json.loads(r.read())
            c = out["context"]
            return Decision(bool(out["decision"]), c["status"], c["reason"], c.get("approval_id", ""), out)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            return Decision(False, "deny", f"policy server unreachable, denied for safety ({type(e).__name__})")

    def guard(self, action, rtype="", amount_arg=None, recipient_arg=None):
        def wrap(fn):
            import inspect
            sig = inspect.signature(fn)

            @functools.wraps(fn)
            def inner(*a, **kw):
                bound = sig.bind(*a, **kw)
                bound.apply_defaults()
                props = {}
                if amount_arg:
                    props["amount_usd"] = bound.arguments[amount_arg]
                if recipient_arg:
                    props["recipient"] = bound.arguments[recipient_arg]
                d = self.check(action, rtype, fn.__name__, **props)
                if d.status == "needs_approval":
                    raise NeedsApproval(d.reason, d.approval_id)
                if not d.allowed:
                    raise Denied(d.reason)
                return fn(*a, **kw)
            return inner
        return wrap
