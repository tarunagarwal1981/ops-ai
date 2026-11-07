"""Offline test: runs every code path against a tiny fake Ollama on 127.0.0.1.

No model, no Ollama install, no internet. The fake server returns canned chat
replies and simple word-count embeddings, so this checks the plumbing (requests,
parsing, ranking, the privacy guard), not the quality of any real model.

    python test_offline.py      # or: pytest test_offline.py
"""

import hashlib
import json
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
REQUESTS: list[dict] = []  # everything the fake server received


def fake_embedding(text: str, dim: int = 256) -> list[float]:
    """Hashed bag of words. Deliberately NOT unit length, to test our normalisation."""
    text = re.sub(r"^search_(query|document): ", "", text)
    v = np.zeros(dim)
    stop = {"the", "what", "and", "for", "how", "many", "must", "when", "before", "with", "this", "any"}
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) > 2 and w not in stop:
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    return (v * 3.0).tolist()


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append({"path": self.path, "body": body})
        if self.path == "/api/embed":
            texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
            return self._send({"model": body["model"], "embeddings": [fake_embedding(t) for t in texts]})
        if self.path == "/v1/chat/completions":
            if body.get("response_format", {}).get("type") == "json_schema":
                content = json.dumps({"summary": "stub", "parties": ["A", "B"], "dates": [], "risks": []})
            else:
                content = "STUB REPLY"
            return self._send({
                "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
        self.send_error(404)


# --- start the fake server and point the scripts at it, before importing them ---
server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["LOCAL_AI_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
os.environ["LOCAL_MODEL"] = "test-chat:latest"
os.environ["LOCAL_EMBED_MODEL"] = "nomic-embed-text"
os.environ.pop("ALLOW_REMOTE", None)

# Block any outbound connection that isn't loopback, so a leak fails loudly.
_real_connect = socket.socket.connect


def _loopback_only(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise AssertionError(f"tried to connect to {address}")
    return _real_connect(self, address)


socket.socket.connect = _loopback_only

import ask_local  # noqa: E402
import chat_with_files as cwf  # noqa: E402
from local_ai import NotLocalError, check_local  # noqa: E402


def test_ask_plain():
    REQUESTS.clear()
    assert ask_local.ask("Say hi") == "STUB REPLY"
    req = REQUESTS[-1]
    assert req["path"] == "/v1/chat/completions"
    assert req["body"]["model"] == "test-chat:latest"


def test_ask_json_schema():
    REQUESTS.clear()
    out = ask_local.ask("Extract parties", as_json=True)
    assert out["parties"] == ["A", "B"]
    rf = REQUESTS[-1]["body"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"]["required"]


def test_guard_blocks_remote_and_cloud():
    for url, model in [("https://api.example.com", "qwen3.5:9b"),
                       ("http://192.168.1.20:11434", "qwen3.5:9b"),
                       ("http://localhost:11434", "gemma4:cloud"),
                       ("http://localhost:11434", "gpt-oss:120b-cloud")]:
        try:
            check_local(url, model)
        except NotLocalError:
            continue
        raise AssertionError(f"guard let through {url} / {model}")
    check_local("http://localhost:11434", "qwen3.5:9b")  # fine
    check_local("http://127.0.0.1:11434", "nomic-embed-text")  # no tag is fine


def test_chunking():
    chunks = cwf.load_chunks(HERE / "sample_docs")
    files = {c["file"] for c in chunks}
    assert files == {"acme-services-agreement.txt", "travel-expense-policy.md", "drydock-planning-notes.md"}
    assert all(len(c["text"]) <= cwf.CHUNK_CHARS + 400 for c in chunks)


def test_retrieval_and_answer():
    REQUESTS.clear()
    chunks = cwf.load_chunks(HERE / "sample_docs")
    vecs = cwf.embed([cwf.DOC_PREFIX + c["text"] for c in chunks])
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)
    assert REQUESTS[-1]["body"]["input"][0].startswith("search_document: ")

    cases = {
        "How many days notice to terminate the agreement?": "acme-services-agreement.txt",
        "What is the hotel limit in Singapore?": "travel-expense-policy.md",
        "When must the paint be on site before the yard?": "drydock-planning-notes.md",
    }
    for q, expected in cases.items():
        hits = cwf.top_chunks(q, chunks, vecs, k=2)
        assert hits[0]["file"] == expected, (q, hits[0]["file"])
        assert hits[0]["score"] >= hits[1]["score"]

    hits = cwf.top_chunks("notice period to terminate", chunks, vecs)
    assert cwf.answer("notice period to terminate", hits) == "STUB REPLY"
    prompt = REQUESTS[-1]["body"]["messages"][1]["content"]
    assert "[acme-services-agreement.txt]" in prompt and "90 days" in prompt


def test_every_request_stayed_local():
    paths = {r["path"] for r in REQUESTS}
    assert paths <= {"/api/embed", "/v1/chat/completions"}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    order = ["test_ask_plain", "test_ask_json_schema", "test_guard_blocks_remote_and_cloud",
             "test_chunking", "test_retrieval_and_answer", "test_every_request_stayed_local"]
    for name in order:
        globals()[name]()
        print(f"PASS  {name}")
    print("ALL PASSED")
    server.shutdown()
