"""Smoke test against a live knowledge base: does every answer cite the right source?

Not a quality eval. It catches the failures that matter first: an empty index after a
bad sync, a broken filter, a prompt change that drops citations, a model that stops
citing, a question answered from the wrong document.

    python eval_smoke.py                       # uses eval_cases.json, RetrieveAndGenerate
    python eval_smoke.py --mode retrieve       # same cases through retrieve_only.py
    python eval_smoke.py --cases my_cases.json

Exit code 0 if every case passes, 1 otherwise, so it can gate a deploy.
"""

import argparse
import json
import sys
from pathlib import Path

from rag_common import agent_runtime, load_config, model_runtime


def check_case(case, sources, answer):
    """Return (passed, reason). `sources` is the list of cited source strings."""
    expect = case.get("expect_source")
    if expect is None:  # a question the documents can't answer: we want no citations
        return (not sources, "no citations, as expected" if not sources else f"cited {sources}")
    if not sources:
        return False, "answer has no citations"
    if not any(expect in s for s in sources):
        return False, f"expected a source containing {expect!r}, got {sources}"
    for phrase in case.get("expect_in_answer", []):
        if phrase.lower() not in answer.lower():
            return False, f"answer is missing {phrase!r}"
    return True, "cited " + ", ".join(sources)


def run_rag(cfg, question):
    from ask import annotate, ask
    response = ask(agent_runtime(cfg["region"]), question, cfg)
    _, numbers = annotate(response)
    return response["output"]["text"], list(numbers)


def run_retrieve(cfg, question):
    from retrieve_only import cited_ids, generate, retrieve
    chunks = retrieve(agent_runtime(cfg["region"]), question, cfg["kb_id"],
                      cfg["num_results"], cfg["filter"])
    if not chunks:
        return "", []
    answer, _ = generate(model_runtime(cfg["region"]), cfg["model_arn"], question, chunks)
    valid, _ = cited_ids(answer, len(chunks))
    return answer, sorted({chunks[i - 1]["source"] for i in valid})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(Path(__file__).with_name("eval_cases.json")))
    parser.add_argument("--mode", choices=["rag", "retrieve"], default="rag")
    args = parser.parse_args()

    cfg = load_config()
    runner = run_rag if args.mode == "rag" else run_retrieve
    cases = json.loads(Path(args.cases).read_text())

    failures = 0
    for case in cases:
        answer, sources = runner(cfg, case["question"])
        passed, reason = check_case(case, sources, answer)
        failures += not passed
        print(f"{'PASS' if passed else 'FAIL'}  {case['question']}\n      {reason}")
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
