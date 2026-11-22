#!/usr/bin/env python3
"""agent-org server: an AuthZEN-style decision endpoint plus a small control panel.

    python server.py                      # uses org.example.json, listens on 127.0.0.1:8787
    python server.py --policy my-org.json --db agent-org.db --port 8787

Agents ask:   POST /access/v1/evaluation   {subject, action, resource, context}
Panel + API:  open the URL printed at start (needs the admin token, which agents never get)
"""
import argparse
import hmac
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine import Engine, Policy, PolicyError

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_BODY = 64 * 1024


def make_server(policy_path, db_path, port=8787, host="127.0.0.1", admin_token=None):
    with open(policy_path) as f:
        engine = Engine(Policy(json.load(f)), db_path)
    token = admin_token or secrets.token_urlsafe(18)

    class H(BaseHTTPRequestHandler):
        server_version = "agent-org"

        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, raw=None, ctype="application/json"):
            body = raw if raw is not None else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _admin(self):
            ok = hmac.compare_digest(self.headers.get("X-Admin-Token", ""), token)
            if not ok:
                self._send(401, {"error": "admin token required"})
            return ok

        def _json(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                self._send(413, {"error": "body too large"})
                return None
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"error": "body must be JSON"})
                return None

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                with open(os.path.join(HERE, "ui.html"), "rb") as f:
                    return self._send(200, raw=f.read(), ctype="text/html; charset=utf-8")
            if path == "/.well-known/authzen-configuration":
                base = f"http://{self.headers.get('Host', 'localhost')}"
                return self._send(200, {"policy_decision_point": base,
                                        "access_evaluation_endpoint": base + "/access/v1/evaluation"})
            if path == "/api/tree" and self._admin():
                return self._send(200, engine.tree())
            if path == "/api/decisions" and self._admin():
                return self._send(200, engine.decisions(200))
            if path == "/api/approvals" and self._admin():
                return self._send(200, engine.approvals())
            if not path.startswith("/api/"):
                return self._send(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/access/v1/evaluation":
                body = self._json()
                if body is None:
                    return
                auth = self.headers.get("Authorization", "")
                cred = auth[7:] if auth.lower().startswith("bearer ") else None
                return self._send(200, engine.evaluate(body, credential=cred))
            m = re.fullmatch(r"/api/approvals/([\w-]+)/(approve|deny)", path)
            if m and self._admin():
                if self._json() is None:
                    return
                ok = engine.resolve_approval(m.group(1), m.group(2) == "approve", who="admin")
                return self._send(200 if ok else 409, {"ok": ok})
            if not m:
                return self._send(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), H), token


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", default=os.path.join(HERE, "org.example.json"))
    ap.add_argument("--db", default="agent-org.db")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1", help="keep this local unless you put auth in front")
    a = ap.parse_args()
    try:
        httpd, token = make_server(a.policy, a.db, a.port, a.host, os.environ.get("AGENT_ORG_ADMIN_TOKEN"))
    except (PolicyError, OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"could not start: {e}")
    print(f"agent-org control panel:  http://{a.host}:{httpd.server_address[1]}/#token={token}")
    print(f"agents call:              POST http://{a.host}:{httpd.server_address[1]}/access/v1/evaluation")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
