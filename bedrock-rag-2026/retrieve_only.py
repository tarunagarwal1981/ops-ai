"""Retrieve chunks from the knowledge base, then write the prompt yourself (Converse API).

Use this instead of ask.py when you need control that RetrieveAndGenerate doesn't give:
your own prompt and citation format, extra context (a database row, a user profile),
your own reranking or dropping of chunks, or a Managed Knowledge Base (which supports
Retrieve but not RetrieveAndGenerate; for one, swap vectorSearchConfiguration for
managedSearchConfiguration in rag_common.vector_search_config. Not tested here).

    python retrieve_only.py "How much notice does a crew change need?"
"""

import argparse
import re

from rag_common import (agent_runtime, load_config, model_runtime, page_of, source_of,
                        vector_search_config)

SYSTEM_PROMPT = (
    "Answer only from the numbered sources provided. "
    "After every sentence that uses a source, cite it like [1] or [2][3]. "
    "If the sources do not contain the answer, reply exactly: "
    "\"I can't find that in the documents.\""
)


def retrieve(client, query, kb_id, num_results=5, metadata_filter=None):
    """Return a list of {"text", "source", "score"} dicts, best first."""
    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration=vector_search_config(num_results, metadata_filter),
    )
    chunks = []
    for r in response["retrievalResults"]:
        chunks.append({
            "text": r["content"].get("text", ""),
            "source": source_of(r.get("location")) + page_of(r.get("metadata")),
            "score": r.get("score"),
        })
    return chunks


def build_messages(question, chunks):
    sources = "\n\n".join(
        f'<source id="{i}" from="{c["source"]}">\n{c["text"]}\n</source>'
        for i, c in enumerate(chunks, start=1)
    )
    user = f"<sources>\n{sources}\n</sources>\n\nQuestion: {question}"
    return [{"role": "user", "content": [{"text": user}]}]


def generate(client, model_id, question, chunks, max_tokens=800):
    response = client.converse(
        modelId=model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=build_messages(question, chunks),
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    text = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
    return text, response["usage"]


def cited_ids(answer, n_chunks):
    """Which [n] markers the model used, and which of those point at nothing."""
    ids = {int(m) for m in re.findall(r"\[(\d+)\]", answer)}
    return sorted(i for i in ids if 1 <= i <= n_chunks), sorted(i for i in ids if not 1 <= i <= n_chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--min-score", type=float, default=None,
                        help="drop chunks scoring below this before prompting")
    args = parser.parse_args()

    cfg = load_config()
    chunks = retrieve(agent_runtime(cfg["region"]), args.question, cfg["kb_id"],
                      cfg["num_results"], cfg["filter"])
    if args.min_score is not None:
        chunks = [c for c in chunks if c["score"] is None or c["score"] >= args.min_score]
    if not chunks:
        print("No chunks retrieved. Nothing to answer from.")
        return

    answer, usage = generate(model_runtime(cfg["region"]), cfg["model_arn"], args.question, chunks)
    valid, invalid = cited_ids(answer, len(chunks))

    print(answer, "\n")
    for i in valid:
        print(f"[{i}] {chunks[i - 1]['source']}")
    if not valid:
        print("WARNING: no citations. Treat this answer as unsupported.")
    if invalid:
        print(f"WARNING: cited sources that don't exist: {invalid}")
    print(f"\ntokens in/out: {usage['inputTokens']}/{usage['outputTokens']}"
          f"  cache read: {usage.get('cacheReadInputTokens', 0)}")


if __name__ == "__main__":
    main()
