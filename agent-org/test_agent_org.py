"""Tests for agent-org. Run: python test_agent_org.py"""
import hashlib, json, os, sys, tempfile, threading, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as e

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print("FAIL:", name)

POLICY = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "org.example.json")))
T0 = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)

def mk(policy=None):
    return e.Engine(json.loads(json.dumps(policy or POLICY)))

def req(agent, action, rtype="x", rid="1", dry=False, **props):
    r = {"subject": {"type": "agent", "id": agent}, "action": {"name": action},
         "resource": {"type": rtype, "id": rid, "properties": props}}
    if dry: r["context"] = {"dry_run": True}
    return r

def ev(eng, r, now=T0, cred=None):
    return eng.evaluate(r, credential=cred, now=now)

# ---- policy validation
for bad, why in [({}, "empty"), ({"nodes": []}, "no nodes"),
                 ({"nodes": [{"id": "a", "type": "org"}, {"id": "b", "type": "org"}]}, "two roots"),
                 ({"nodes": [{"id": "a", "type": "org"}, {"id": "a", "type": "team", "parent": "a"}]}, "dup id"),
                 ({"nodes": [{"id": "a", "type": "org"}, {"id": "b", "type": "team", "parent": "zzz"}]}, "bad parent"),
                 ({"nodes": [{"id": "a", "type": "org"}, {"id": "b", "type": "robot", "parent": "a"}]}, "bad type"),
                 ({"nodes": [{"id": "a", "type": "org"}, {"id": "b", "type": "agent", "parent": "a"},
                             {"id": "c", "type": "agent", "parent": "b"}]}, "agent with child")]:
    try: e.Policy(bad); check("policy rejects " + why, False)
    except e.PolicyError: check("policy rejects " + why, True)
check("policy version is stable", e.Policy(POLICY).version == e.Policy(json.loads(json.dumps(POLICY))).version)

# ---- fail closed
g = mk()
for name, r in [("not a dict", "hi"), ("empty", {}), ("unknown agent", req("ghost", "spend", amount_usd=1)),
                ("a team is not an agent", req("support", "read", "crm")),
                ("no action", {"subject": {"id": "refund-bot"}})]:
    check("deny: " + name, ev(g, r)["decision"] is False)

# ---- access
r = ev(g, req("refund-bot", "read", "crm"));           check("allow crm:read", r["decision"] is True)
r = ev(g, req("refund-bot", "refund", "payments"));    check("allow payments:refund", r["decision"] is True)
r = ev(g, req("refund-bot", "write", "crm"));          check("deny crm:write (not in allow)", not r["decision"] and "allow list" in r["context"]["reason"])
r = ev(g, req("refund-bot", "delete", "tickets"));     check("org deny *:delete beats agent allow tickets:*", not r["decision"] and r["context"]["rule"] == "acme.access.deny")
r = ev(g, req("triage-bot", "refund", "payments"));    check("triage-bot cannot refund", not r["decision"])
r = ev(g, req("refund-bot", "read", "db"));            check("org denies db:*", not r["decision"] and r["context"]["rule"] == "acme.access.deny")
r = ev(g, req("invoice-bot", "read", "crm"));          check("invoice-bot cannot read crm", not r["decision"])
r = ev(g, {"subject": {"id": "refund-bot"}, "action": {"name": "read"}, "resource": {"id": "1"}}); check("access needs resource.type", not r["decision"])
solo = mk({"nodes": [{"id": "o", "type": "org"}, {"id": "a", "type": "agent", "parent": "o"}]})
check("no allow list anywhere = deny", not ev(solo, req("a", "read", "crm"))["decision"])

# ---- spend: per action, approval, daily, shared budgets
check("spend under threshold allowed", ev(mk(), req("refund-bot", "spend", amount_usd=10))["decision"])
r = ev(mk(), req("refund-bot", "spend", amount_usd=60))
check("over per-action limit denied", not r["decision"] and r["context"]["rule"] == "refund-bot.spend.per_action_usd")
for bad in [-5, "10", None, float("nan"), True]:
    check(f"bad amount {bad!r} denied", not ev(mk(), req("refund-bot", "spend", amount_usd=bad))["decision"])
check("missing amount denied", not ev(mk(), req("refund-bot", "spend"))["decision"])
r = ev(mk(), req("triage-bot", "spend", amount_usd=1))
check("agent with no budget of its own inherits parents' budgets", r["decision"] is True)
r = ev(solo, req("a", "spend", amount_usd=1))
check("no budget anywhere = deny", not r["decision"] and r["context"]["rule"] == "spend.default")
r = ev(solo, req("a", "send", "email", "m", recipient="a@b.com"))
check("no send rules anywhere = deny", not r["decision"] and r["context"]["rule"] == "send.default")

g = mk()
for i in range(4): check(f"refund {i} (20) ok", ev(g, req("refund-bot", "spend", amount_usd=20), now=T0 + timedelta(minutes=i))["decision"])
r = ev(g, req("refund-bot", "spend", amount_usd=20), now=T0 + timedelta(minutes=5))
check("5th 20 ok (100 total)", r["decision"] is True)
r = ev(g, req("refund-bot", "spend", amount_usd=1), now=T0 + timedelta(minutes=6))
check("daily agent budget stops at 100", not r["decision"] and r["context"]["rule"] == "refund-bot.spend.daily_usd")
check("budget resets next day", ev(g, req("refund-bot", "spend", amount_usd=20), now=T0 + timedelta(days=1))["decision"])

# shared budget: finance team has 200; invoice-bot spends 140 twice? per-action 150, approval >100
g = mk()
check("invoice 90 ok", ev(g, req("invoice-bot", "spend", amount_usd=90))["decision"])
check("invoice 90 ok again", ev(g, req("invoice-bot", "spend", amount_usd=90))["decision"])
r = ev(g, req("invoice-bot", "spend", amount_usd=90))
check("finance team budget (200) is shared and stops it", not r["decision"] and r["context"]["rule"] == "finance.spend.daily_usd")
check("tree shows spend rolled up", g.tree(T0)["root"]["spent_today"] == 180.0)

# org-wide budget counts every agent
tiny = json.loads(json.dumps(POLICY)); tiny["nodes"][0]["limits"]["spend"]["daily_usd"] = 25
g = mk(tiny)
check("org budget first spend", ev(g, req("refund-bot", "spend", amount_usd=15))["decision"])
r = ev(g, req("invoice-bot", "spend", amount_usd=15))
check("org budget is shared across teams", not r["decision"] and r["context"]["rule"] == "acme.spend.daily_usd")

# monthly
mon = json.loads(json.dumps(POLICY)); mon["nodes"][2]["limits"]["spend"]["monthly_usd"] = 30
g = mk(mon)
ev(g, req("refund-bot", "spend", amount_usd=15), now=T0)
ev(g, req("refund-bot", "spend", amount_usd=15), now=T0 + timedelta(days=2))
r = ev(g, req("refund-bot", "spend", amount_usd=1), now=T0 + timedelta(days=3))
check("monthly budget", not r["decision"] and r["context"]["rule"] == "refund-bot.spend.monthly_usd")

# ---- approvals
g = mk()
r = ev(g, req("refund-bot", "spend", "payment", "p1", amount_usd=35))
check("over threshold waits", not r["decision"] and r["context"]["status"] == "needs_approval")
aid = r["context"]["approval_id"]
r2 = ev(g, req("refund-bot", "spend", "payment", "p1", amount_usd=35))
check("same request reuses the pending approval", r2["context"]["approval_id"] == aid and len(g.approvals("pending")) == 1)
check("still blocked while pending", not r2["decision"])
check("approve works", g.resolve_approval(aid, True, "tarun"))
check("approve only once", not g.resolve_approval(aid, False))
r3 = ev(g, req("refund-bot", "spend", "payment", "p1", amount_usd=35))
check("approved request now allowed", r3["decision"] and "tarun" in r3["context"]["reason"])
r4 = ev(g, req("refund-bot", "spend", "payment", "p1", amount_usd=35))
check("approval is one-time", not r4["decision"] and r4["context"]["status"] == "needs_approval")
ev(g, req("refund-bot", "spend", "payment", "p2", amount_usd=35))
other = [a for a in g.approvals("pending") if a["resource"] == "payment:p2"][0]["id"]
check("different request needs its own approval", other != aid)
g.resolve_approval(other, False, "tarun")
r = ev(g, req("refund-bot", "spend", "payment", "p2", amount_usd=35))
check("denied approval stays denied, no new queue entry", not r["decision"] and r["context"]["status"] == "deny"
      and not [a for a in g.approvals("pending") if a["resource"] == "payment:p2"])
g2 = mk(); a = ev(g2, req("refund-bot", "spend", "payment", "p1", amount_usd=35))["context"]["approval_id"]; g2.resolve_approval(a, True)
check("approval for 35 does not cover 36", not ev(g2, req("refund-bot", "spend", "payment", "p1", amount_usd=36))["decision"])
check("approval for p1 does not cover p9", not ev(g2, req("refund-bot", "spend", "payment", "p9", amount_usd=35))["decision"])
g3 = mk()
r = ev(g3, req("refund-bot", "spend", "payment", "z", dry=True, amount_usd=35))
check("dry run creates no approval", r["context"]["status"] == "needs_approval" and not g3.approvals())
ev(g3, req("refund-bot", "spend", dry=True, amount_usd=10))
check("dry run does not use budget", g3.spent("refund-bot", T0) == 0)

# ---- send
g = mk()
check("send to acme.com ok", ev(g, req("refund-bot", "send", "email", "m1", recipient="amy@acme.com"))["decision"])
check("send to sub.acme.com ok (wildcard)", ev(g, req("refund-bot", "send", "email", "m1", recipient="a@eu.acme.com"))["decision"])
r = ev(g, req("refund-bot", "send", "email", "m1", recipient="x@evil.io"))
check("send to unknown domain denied", not r["decision"] and r["context"]["rule"] == "support.send.allow_domains")
r = ev(g, req("refund-bot", "send", "email", "m1", recipient="x@Competitor.com"))
check("deny_domains wins (case-insensitive)", not r["decision"] and r["context"]["rule"] == "acme.send.deny_domains")
r = ev(g, req("triage-bot", "send", "email", "m1", recipient="x@gmail.com"))
check("agent allow list narrows team list", not r["decision"] and r["context"]["rule"] == "triage-bot.send.allow_domains")
for bad in ["nope", "a@b@c.com", "a@", None, 5]:
    check(f"bad recipient {bad!r} denied", not ev(g, req("refund-bot", "send", "email", "m", recipient=bad))["decision"])
check("invoice-bot has no send rights", not ev(g, req("invoice-bot", "send", "email", "m", recipient="a@acme.com"))["decision"])
cap = json.loads(json.dumps(POLICY)); cap["nodes"][2]["limits"]["send"]["max_per_day"] = 3
g = mk(cap)
for i in range(3): ev(g, req("refund-bot", "send", "email", f"m{i}", recipient="a@acme.com"))
r = ev(g, req("refund-bot", "send", "email", "m9", recipient="a@acme.com"))
check("send cap per day", not r["decision"] and r["context"]["rule"] == "refund-bot.send.max_per_day")
check("denied sends do not count", g.sent("refund-bot", T0) == 3)

# ---- identity keys
keyed = json.loads(json.dumps(POLICY)); keyed["nodes"][2]["api_key_sha256"] = hashlib.sha256(b"s3cret").hexdigest()
g = mk(keyed)
check("keyed agent: no credential denied", not ev(g, req("refund-bot", "read", "crm"))["decision"])
check("keyed agent: wrong credential denied", not ev(g, req("refund-bot", "read", "crm"), cred="nope")["decision"])
check("keyed agent: right credential allowed", ev(g, req("refund-bot", "read", "crm"), cred="s3cret")["decision"])
check("other agents unaffected", ev(g, req("triage-bot", "read", "tickets"))["decision"])

# ---- audit trail
g = mk(); ev(g, req("refund-bot", "read", "crm")); ev(g, req("refund-bot", "write", "crm"))
d = g.decisions()
check("every decision logged", len(d) == 2 and d[0]["allowed"] == 0 and d[1]["allowed"] == 1)
check("log carries policy version + rule", d[0]["policy_version"] == g.policy.version and d[0]["rule"])
check("response has decision_id", "decision_id" in ev(g, req("refund-bot", "read", "crm"))["context"])

# ---- HTTP server
import server as s
tmp = tempfile.mkdtemp()
httpd, token = s.make_server(os.path.join(os.path.dirname(os.path.abspath(__file__)), "org.example.json"),
                             os.path.join(tmp, "t.db"), port=0, admin_token="tok")
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
def call(path, body=None, headers=None):
    rq = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(rq, timeout=5) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as ex: return ex.code, json.loads(ex.read() or b"{}")
st, body = call("/access/v1/evaluation", req("refund-bot", "read", "crm"))
check("http evaluation allow", st == 200 and body["decision"] is True)
st, body = call("/access/v1/evaluation", req("refund-bot", "write", "crm"))
check("http evaluation deny", st == 200 and body["decision"] is False)
rq = urllib.request.Request(base + "/access/v1/evaluation", data=b"{not json", headers={"Content-Type": "application/json"})
try: urllib.request.urlopen(rq, timeout=5); code = 200
except urllib.error.HTTPError as ex: code = ex.code
check("http bad json is 400", code == 400)
check("admin api needs token", call("/api/tree")[0] == 401)
check("admin api wrong token", call("/api/tree", headers={"X-Admin-Token": "x"})[0] == 401)
st, body = call("/api/tree", headers={"X-Admin-Token": "tok"})
check("admin api tree", st == 200 and body["root"]["id"] == "acme")
st, body = call("/access/v1/evaluation", req("refund-bot", "spend", "payment", "h1", amount_usd=35))
aid = body["context"]["approval_id"]
check("agent cannot approve (no token)", call(f"/api/approvals/{aid}/approve", {})[0] == 401)
st, _ = call(f"/api/approvals/{aid}/approve", {}, {"X-Admin-Token": "tok"})
check("admin approves", st == 200)
st, body = call("/access/v1/evaluation", req("refund-bot", "spend", "payment", "h1", amount_usd=35))
check("retry after approval allowed", body["decision"] is True)
st, body = call("/api/decisions", headers={"X-Admin-Token": "tok"})
check("decision log over http", st == 200 and len(body) >= 3)
rq = urllib.request.Request(base + "/"); html = urllib.request.urlopen(rq, timeout=5).read().decode()
check("ui html served", "agent-org" in html)
httpd.shutdown()

print(f"{PASS} passed, {FAIL} failed")
print("ALL PASSED" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
