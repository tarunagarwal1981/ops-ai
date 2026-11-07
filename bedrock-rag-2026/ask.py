"""Ask a question. Bedrock retrieves, generates, and returns citations in one call.

    python ask.py "How much notice does a crew change need?"
    python ask.py --session <id> "And for officers?"   # follow-up in the same session
"""

import argparse

from rag_common import agent_runtime, load_config, page_of, source_of, vector_search_config


def build_request(question, kb_id, model_arn, num_results=5, metadata_filter=None, session_id=None):
    request = {
        "input": {"text": question},
        "retrieveAndGenerateConfiguration": {
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": kb_id,
                "modelArn": model_arn,
                "retrievalConfiguration": vector_search_config(num_results, metadata_filter),
            },
        },
    }
    if session_id:  # Bedrock creates the session on the first call; you only reuse it.
        request["sessionId"] = session_id
    return request


def ask(client, question, cfg, session_id=None):
    return client.retrieve_and_generate(
        **build_request(question, cfg["kb_id"], cfg["model_arn"],
                        cfg["num_results"], cfg["filter"], session_id)
    )


def sources_from(response):
    """Unique sources in the order they are first cited -> {source: number}."""
    numbers = {}
    for citation in response.get("citations", []):
        for ref in citation.get("retrievedReferences", []):
            src = source_of(ref.get("location")) + page_of(ref.get("metadata"))
            numbers.setdefault(src, len(numbers) + 1)
    return numbers


def annotate(response):
    """Insert [n] markers into the answer at the end of each cited span."""
    text = response["output"]["text"]
    numbers = sources_from(response)
    inserts = []
    for citation in response.get("citations", []):
        part = citation.get("generatedResponsePart", {}).get("textResponsePart", {})
        refs = citation.get("retrievedReferences", [])
        if not part or not refs:
            continue
        # Place the marker right after the cited text. Searching for the text
        # (from the span start) avoids depending on whether span.end is inclusive.
        start = part.get("span", {}).get("start", 0)
        found = text.find(part.get("text", ""), max(0, start - 1)) if part.get("text") else -1
        pos = found + len(part["text"]) if found >= 0 else part.get("span", {}).get("end", len(text))
        ids = sorted({numbers[source_of(r.get("location")) + page_of(r.get("metadata"))] for r in refs})
        inserts.append((pos, "".join(f"[{i}]" for i in ids)))
    # Insert from the back so earlier offsets stay valid.
    for pos, marker in sorted(inserts, reverse=True):
        pos = min(pos, len(text))
        text = text[:pos] + marker + text[pos:]
    return text, numbers


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--session", help="sessionId from a previous answer, for follow-ups")
    args = parser.parse_args()

    cfg = load_config()
    response = ask(agent_runtime(cfg["region"]), args.question, cfg, args.session)

    text, numbers = annotate(response)
    print(text, "\n")
    if not numbers:
        print("WARNING: no citations. Treat this answer as unsupported.")
    for src, n in numbers.items():
        print(f"[{n}] {src}")
    if response.get("guardrailAction") == "INTERVENED":
        print("(a guardrail intervened)")
    print(f"\nsession: {response['sessionId']}")


if __name__ == "__main__":
    main()
