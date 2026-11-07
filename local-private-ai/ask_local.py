"""Ask a local model a question through Ollama's OpenAI-compatible endpoint.

    python ask_local.py "Summarise this clause in plain English: ..."
    python ask_local.py --json "Extract the parties and the term from: ..."

The model comes from LOCAL_MODEL (default qwen3.5:9b).
"""

import json
import sys

from openai import OpenAI

from local_ai import BASE_URL, CHAT_MODEL, check_local

# Used by --json: the reply must match this schema (Ollama maps it to its `format` field).
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "parties": {"type": "array", "items": {"type": "string"}},
        "dates": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "parties", "dates", "risks"],
}


def client() -> OpenAI:
    check_local(BASE_URL, CHAT_MODEL)
    # The client insists on an API key; Ollama ignores it.
    return OpenAI(base_url=f"{BASE_URL}/v1", api_key="ollama")


def ask(question: str, as_json: bool = False) -> str | dict:
    kwargs = {}
    if as_json:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "extract", "schema": EXTRACT_SCHEMA},
        }
    resp = client().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": "Be brief and precise. If you are unsure, say so."},
            {"role": "user", "content": question},
        ],
        temperature=0,
        **kwargs,
    )
    text = resp.choices[0].message.content or ""
    return json.loads(text) if as_json else text


if __name__ == "__main__":
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if not args:
        sys.exit(__doc__)
    out = ask(" ".join(args), as_json=as_json)
    print(json.dumps(out, indent=2) if as_json else out)
