"""Ask questions about a folder of .txt and .md files. Everything stays on this machine.

    python chat_with_files.py ./sample_docs "What is the notice period in the Acme agreement?"

How it works:
1. Split every file into chunks of roughly 800 characters.
2. Embed the chunks with a local embedding model (Ollama /api/embed).
3. Embed the question, rank chunks by cosine similarity (numpy, no vector DB).
4. Send the top chunks plus the question to the local chat model.
"""

import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

from ask_local import client
from local_ai import BASE_URL, CHAT_MODEL, EMBED_MODEL, check_local

CHUNK_CHARS = 800
TOP_K = 4

# nomic-embed-text expects task prefixes on its inputs (see its model card).
NOMIC = EMBED_MODEL.startswith("nomic-embed")
DOC_PREFIX = "search_document: " if NOMIC else ""
QUERY_PREFIX = "search_query: " if NOMIC else ""


def load_chunks(folder: Path) -> list[dict]:
    """Split each file on blank lines, then pack paragraphs into ~CHUNK_CHARS chunks."""
    chunks = []
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in {".txt", ".md"} or not path.is_file():
            continue
        paras = [p.strip() for p in path.read_text(encoding="utf-8", errors="ignore").split("\n\n")]
        buf = ""
        for p in filter(None, paras):
            if buf and len(buf) + len(p) > CHUNK_CHARS:
                chunks.append({"file": path.name, "text": buf})
                buf = ""
            buf = f"{buf}\n\n{p}" if buf else p
        if buf:
            chunks.append({"file": path.name, "text": buf})
    return chunks


def embed(texts: list[str]) -> np.ndarray:
    """Call Ollama's native embedding endpoint. It returns unit-length vectors."""
    check_local(BASE_URL, EMBED_MODEL)
    body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/embed", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        vecs = np.array(json.load(r)["embeddings"], dtype=np.float32)
    # Normalise anyway, so cosine similarity is a plain dot product whatever the server does.
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def top_chunks(question: str, chunks: list[dict], vecs: np.ndarray, k: int = TOP_K) -> list[dict]:
    q = embed([QUERY_PREFIX + question])[0]
    scores = vecs @ q
    best = np.argsort(-scores)[:k]
    return [{**chunks[i], "score": float(scores[i])} for i in best]


def answer(question: str, hits: list[dict]) -> str:
    context = "\n\n---\n\n".join(f"[{h['file']}]\n{h['text']}" for h in hits)
    resp = client().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "Answer only from the context. Name the file you used in [brackets]. "
                "If the answer is not in the context, say you don't know.",
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
    )
    return resp.choices[0].message.content or ""


def main(folder: str, question: str) -> None:
    chunks = load_chunks(Path(folder))
    if not chunks:
        sys.exit(f"No .txt or .md files found in {folder}")
    vecs = embed([DOC_PREFIX + c["text"] for c in chunks])
    hits = top_chunks(question, chunks, vecs)
    print(answer(question, hits))
    print("\nSources:")
    for h in hits:
        print(f"  {h['score']:.3f}  {h['file']}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], " ".join(sys.argv[2:]))
