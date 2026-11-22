"""agent-org engine: decides what each AI agent may spend, send and access.

Agents sit in a tree (org > team > agent). Each node can set limits. A child can only be
stricter than its parents: every node on the path from the agent up to the root must agree.

Rules in one place:
  * deny always wins; anything not clearly allowed is denied (fail closed)
  * spend:  per_action_usd, daily_usd, monthly_usd, approval_over_usd
  * send:   allow_domains, deny_domains, max_per_day
  * access: allow / deny patterns on "<resource type>:<action>", e.g. "crm:read", "payments:refund"
  * budgets are shared: a team's daily_usd counts what ALL agents under it spent today
  * an over-threshold request waits for a human; the approval is tied to that exact request
    and works once

Standard library only. The request and answer shapes follow the OpenID AuthZEN
"access evaluation" API: {subject, action, resource, context} -> {decision, context}.
"""
import fnmatch
import hashlib
import json
import math
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

NODE_TYPES = {"org", "team", "agent"}


class PolicyError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _day(t):
    return t.strftime("%Y-%m-%d")


def _month(t):
    return t.strftime("%Y-%m")


class Policy:
    def __init__(self, obj):
        if not isinstance(obj, dict) or not isinstance(obj.get("nodes"), list) or not obj["nodes"]:
            raise PolicyError("policy needs a non-empty 'nodes' list")
        self.name = str(obj.get("name", "org"))
        self.nodes = {}
        for n in obj["nodes"]:
            if not isinstance(n, dict) or not n.get("id"):
                raise PolicyError("every node needs an id")
            if n["id"] in self.nodes:
                raise PolicyError(f"duplicate node id {n['id']!r}")
            if n.get("type") not in NODE_TYPES:
                raise PolicyError(f"node {n['id']!r}: type must be one of {sorted(NODE_TYPES)}")
            self.nodes[n["id"]] = n
        roots = [n for n in self.nodes.values() if not n.get("parent")]
        if len(roots) != 1:
            raise PolicyError("exactly one node must have no parent (the root)")
        for n in self.nodes.values():
            p = n.get("parent")
            if p and p not in self.nodes:
                raise PolicyError(f"node {n['id']!r}: unknown parent {p!r}")
            if p and self.nodes[p]["type"] == "agent":
                raise PolicyError(f"node {n['id']!r}: an agent cannot have children")
            seen, cur = set(), n["id"]
            while cur:
                if cur in seen:
                    raise PolicyError("the tree has a cycle")
                seen.add(cur)
                cur = self.nodes[cur].get("parent")
        self.root = roots[0]["id"]
        self.children = {i: [] for i in self.nodes}
        for n in self.nodes.values():
            if n.get("parent"):
                self.children[n["parent"]].append(n["id"])
        canon = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        self.version = hashlib.sha256(canon.encode()).hexdigest()[:12]

    def chain(self, node_id):
        """The node, then its parents up to the root."""
        out, cur = [], node_id
        while cur:
            out.append(self.nodes[cur])
            cur = self.nodes[cur].get("parent")
        return out

    def agents_under(self, node_id):
        out, stack = [], [node_id]
        while stack:
            i = stack.pop()
            if self.nodes[i]["type"] == "agent":
                out.append(i)
            stack.extend(self.children[i])
        return out


def _limits(node, section):
    sec = (node.get("limits") or {}).get(section)
    return sec if isinstance(sec, dict) else {}


def _match(patterns, value):
    return any(fnmatch.fnmatchcase(value, p) for p in patterns)


class Engine:
    def __init__(self, policy, db_path=":memory:"):
        self.policy = policy if isinstance(policy, Policy) else Policy(policy)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS decisions(
          id TEXT PRIMARY KEY, ts TEXT, agent TEXT, action TEXT, resource TEXT,
          amount REAL, recipient TEXT, allowed INTEGER, status TEXT, reason TEXT, rule TEXT,
          policy_version TEXT, dry_run INTEGER);
        CREATE TABLE IF NOT EXISTS approvals(
          id TEXT PRIMARY KEY, ts TEXT, fingerprint TEXT, agent TEXT, action TEXT, resource TEXT,
          amount REAL, recipient TEXT, status TEXT, resolved_by TEXT, resolved_ts TEXT, consumed INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS d_agent_ts ON decisions(agent, ts);
        """)

    # ---------------------------------------------------------------- usage
    def _sum(self, node_id, action, prefix, field):
        agents = self.policy.agents_under(node_id)
        if not agents:
            return 0.0
        q = ",".join("?" * len(agents))
        col = "COALESCE(SUM(amount),0)" if field == "amount" else "COUNT(*)"
        row = self.db.execute(
            f"SELECT {col} FROM decisions WHERE allowed=1 AND dry_run=0 AND action=? AND ts LIKE ? "
            f"AND agent IN ({q})", [action, prefix + "%", *agents]).fetchone()
        return float(row[0])

    def spent(self, node_id, t=None, month=False):
        t = t or _now()
        return self._sum(node_id, "spend", _month(t) if month else _day(t), "amount")

    def sent(self, node_id, t=None):
        return self._sum(node_id, "send", _day(t or _now()), "count")

    # ---------------------------------------------------------------- decide
    def evaluate(self, req, credential=None, now=None):
        """AuthZEN-style access evaluation. Never raises; anything odd is a deny."""
        now = now or _now()
        with self.lock:
            try:
                out = self._evaluate(req, credential, now)
            except Exception as e:  # fail closed
                out = self._result(False, "deny", f"internal error, denied for safety: {type(e).__name__}", "engine")
            return self._record(req, out, now)

    def _result(self, allowed, status, reason, rule, approval_id=None):
        return {"decision": allowed, "context": {"status": status, "reason": reason, "rule": rule,
                                                 "policy_version": self.policy.version,
                                                 **({"approval_id": approval_id} if approval_id else {})}}

    def _deny(self, reason, rule):
        return self._result(False, "deny", reason, rule)

    def _evaluate(self, req, credential, now):
        if not isinstance(req, dict):
            return self._deny("request must be a JSON object", "request")
        subject = req.get("subject") or {}
        action = (req.get("action") or {}).get("name")
        resource = req.get("resource") or {}
        ctx = req.get("context") or {}
        props = resource.get("properties") or {}
        agent_id = subject.get("id")
        if not isinstance(agent_id, str) or not isinstance(action, str) or not action:
            return self._deny("request needs subject.id and action.name", "request")
        node = self.policy.nodes.get(agent_id)
        if not node or node["type"] != "agent":
            return self._deny(f"unknown agent {agent_id!r}", "identity")
        want = node.get("api_key_sha256")
        if want and hashlib.sha256((credential or "").encode()).hexdigest() != want:
            return self._deny("missing or wrong credential for this agent", f"{agent_id}.identity")
        chain = self.policy.chain(agent_id)
        dry = bool(ctx.get("dry_run"))

        if action == "spend":
            return self._spend(agent_id, chain, resource, props, now, dry)
        if action == "send":
            return self._send(agent_id, chain, resource, props, now)
        return self._access(chain, str(resource.get("type", "")), action)

    # access -------------------------------------------------------------
    def _access(self, chain, rtype, action):
        if not rtype:
            return self._deny("resource.type is required for an access check", "request")
        cap = f"{rtype}:{action}"
        for n in chain:
            if _match(_limits(n, "access").get("deny", []), cap):
                return self._deny(f"{cap} is denied at {n['id']}", f"{n['id']}.access.deny")
        granted = False
        for n in chain:
            allow = _limits(n, "access").get("allow")
            if allow is not None:
                granted = True
                if not _match(allow, cap):
                    return self._deny(f"{cap} is not in the allow list of {n['id']}", f"{n['id']}.access.allow")
        if not granted:
            return self._deny(f"nothing grants {cap}", "access.default")
        return self._result(True, "allow", f"{cap} is allowed", "access.allow")

    # spend --------------------------------------------------------------
    def _spend(self, agent_id, chain, resource, props, now, dry):
        amt = props.get("amount_usd")
        if isinstance(amt, bool) or not isinstance(amt, (int, float)) or not math.isfinite(amt) or amt < 0:
            return self._deny("spend needs resource.properties.amount_usd as a number >= 0", "request")
        amt = float(amt)
        has_budget, thresholds = False, []
        for n in chain:
            lim = _limits(n, "spend")
            if not lim:
                continue
            has_budget = True
            if "per_action_usd" in lim and amt > lim["per_action_usd"]:
                return self._deny(f"${amt:g} is over the ${lim['per_action_usd']:g} per-action limit at {n['id']}",
                                  f"{n['id']}.spend.per_action_usd")
            if "daily_usd" in lim:
                used = self.spent(n["id"], now)
                if used + amt > lim["daily_usd"]:
                    return self._deny(f"{n['id']} daily budget: ${used:g} spent of ${lim['daily_usd']:g}, "
                                      f"this ${amt:g} would go over", f"{n['id']}.spend.daily_usd")
            if "monthly_usd" in lim:
                used = self.spent(n["id"], now, month=True)
                if used + amt > lim["monthly_usd"]:
                    return self._deny(f"{n['id']} monthly budget: ${used:g} spent of ${lim['monthly_usd']:g}, "
                                      f"this ${amt:g} would go over", f"{n['id']}.spend.monthly_usd")
            if "approval_over_usd" in lim:
                thresholds.append((lim["approval_over_usd"], n["id"]))
        if not has_budget:
            return self._deny("no spend budget is set for this agent or its parents", "spend.default")
        over = [(t, nid) for t, nid in thresholds if amt > t]
        if over:
            t, nid = min(over)
            return self._needs_approval(agent_id, "spend", resource, amt, None, dry,
                                        f"${amt:g} is over the ${t:g} approval threshold at {nid}",
                                        f"{nid}.spend.approval_over_usd", now)
        return self._result(True, "allow", f"${amt:g} is within every budget on the path", "spend.allow")

    # send ---------------------------------------------------------------
    def _send(self, agent_id, chain, resource, props, now):
        rcpt = props.get("recipient")
        if not isinstance(rcpt, str) or rcpt.count("@") != 1 or not rcpt.split("@")[1]:
            return self._deny("send needs resource.properties.recipient as an email address", "request")
        domain = rcpt.split("@")[1].lower()
        for n in chain:
            if _match(_limits(n, "send").get("deny_domains", []), domain):
                return self._deny(f"{domain} is blocked at {n['id']}", f"{n['id']}.send.deny_domains")
        granted = False
        for n in chain:
            allow = _limits(n, "send").get("allow_domains")
            if allow is not None:
                granted = True
                if not _match(allow, domain):
                    return self._deny(f"{domain} is not in the allowed domains of {n['id']}",
                                      f"{n['id']}.send.allow_domains")
        if not granted:
            return self._deny("no allowed recipient domains are set for this agent or its parents", "send.default")
        for n in chain:
            mx = _limits(n, "send").get("max_per_day")
            if mx is not None and self.sent(n["id"], now) + 1 > mx:
                return self._deny(f"{n['id']} has reached its limit of {mx} messages today", f"{n['id']}.send.max_per_day")
        return self._result(True, "allow", f"{domain} is allowed and under the daily limits", "send.allow")

    # approvals ----------------------------------------------------------
    @staticmethod
    def _fingerprint(agent, action, resource, amount, recipient):
        blob = json.dumps([agent, action, resource.get("type"), resource.get("id"), amount, recipient])
        return hashlib.sha256(blob.encode()).hexdigest()

    def _needs_approval(self, agent, action, resource, amount, recipient, dry, reason, rule, now):
        fp = self._fingerprint(agent, action, resource, amount, recipient)
        row = self.db.execute("SELECT * FROM approvals WHERE fingerprint=? AND status='approved' AND consumed=0 "
                              "ORDER BY ts LIMIT 1", [fp]).fetchone()
        if row:
            if not dry:
                self.db.execute("UPDATE approvals SET consumed=1 WHERE id=?", [row["id"]])
            return self._result(True, "allow", f"approved by {row['resolved_by']} (one-time)", rule, row["id"])
        den = self.db.execute("SELECT resolved_by FROM approvals WHERE fingerprint=? AND status='denied' LIMIT 1",
                              [fp]).fetchone()
        if den:
            return self._result(False, "deny", f"{den['resolved_by']} already denied this exact request", rule)
        pend = self.db.execute("SELECT id FROM approvals WHERE fingerprint=? AND status='pending'", [fp]).fetchone()
        if pend:
            return self._result(False, "needs_approval", reason + " (waiting for a person)", rule, pend["id"])
        if dry:
            return self._result(False, "needs_approval", reason + " (a real request would ask a person)", rule)
        aid = "apr_" + uuid.uuid4().hex[:10]
        self.db.execute("INSERT INTO approvals(id,ts,fingerprint,agent,action,resource,amount,recipient,status) "
                        "VALUES(?,?,?,?,?,?,?,?,'pending')",
                        [aid, now.isoformat(), fp, agent, action,
                         f"{resource.get('type','')}:{resource.get('id','')}", amount, recipient])
        self.db.commit()
        return self._result(False, "needs_approval", reason, rule, aid)

    def resolve_approval(self, approval_id, approve, who="admin", now=None):
        with self.lock:
            cur = self.db.execute("UPDATE approvals SET status=?, resolved_by=?, resolved_ts=? "
                                  "WHERE id=? AND status='pending'",
                                  ["approved" if approve else "denied", who, (now or _now()).isoformat(), approval_id])
            self.db.commit()
            return cur.rowcount == 1

    # records + views ------------------------------------------------------
    def _record(self, req, out, now):
        try:
            subject = (req or {}).get("subject") or {}
            res = (req or {}).get("resource") or {}
            props = res.get("properties") or {}
            ctx = (req or {}).get("context") or {}
            c = out["context"]
            did = "dec_" + uuid.uuid4().hex[:12]
            amt = props.get("amount_usd") if isinstance(props.get("amount_usd"), (int, float)) else None
            rcpt = props.get("recipient") if isinstance(props.get("recipient"), str) else None
            action = str(((req or {}).get("action") or {}).get("name", ""))
            self.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [did, now.isoformat(), str(subject.get("id", "")), action,
                             f"{res.get('type','')}:{res.get('id','')}", amt, rcpt, int(out["decision"]),
                             c["status"], c["reason"], c["rule"], c["policy_version"], int(bool(ctx.get("dry_run")))])
            self.db.commit()
            out["context"]["decision_id"] = did
        except Exception:
            pass
        return out

    def decisions(self, limit=100):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM decisions ORDER BY ts DESC, rowid DESC LIMIT ?", [limit])]

    def approvals(self, status=None):
        q = "SELECT * FROM approvals" + (" WHERE status=?" if status else "") + " ORDER BY ts DESC LIMIT 200"
        with self.lock:
            return [dict(r) for r in self.db.execute(q, [status] if status else [])]

    def tree(self, now=None):
        with self.lock:
            return self._tree(now or _now())

    def _tree(self, now):
        def build(i):
            n = self.policy.nodes[i]
            lim = n.get("limits") or {}
            return {"id": i, "type": n["type"], "limits": lim,
                    "spent_today": round(self.spent(i, now), 2), "spent_month": round(self.spent(i, now, True), 2),
                    "sent_today": int(self.sent(i, now)),
                    "children": [build(c) for c in self.policy.children[i]]}
        return {"name": self.policy.name, "version": self.policy.version, "root": build(self.policy.root)}
