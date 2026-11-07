"""Offline tests: no AWS account, no network.

botocore's Stubber checks every request we build against the real service model
(parameter names, types, required fields) and checks the canned responses against
the response model too. botocore does not check enum values, so enum_errors() below
does that. If a field name or enum in ask.py or retrieve_only.py is wrong, these
tests fail.

The canned responses below are FAKE. They are shaped like real responses so the
parsing code can be exercised; they are not model output.

    python test_offline.py
"""

import json
import os
import sys
import unittest
from pathlib import Path

import boto3
from botocore.exceptions import ParamValidationError
from botocore.stub import Stubber
from botocore.validate import ParamValidator

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "setup"))

import ask  # noqa: E402
import eval_smoke  # noqa: E402
import retrieve_only  # noqa: E402
from rag_common import source_of, vector_search_config  # noqa: E402
from render import render  # noqa: E402

REGION = "us-east-1"
KB_ID = "KBTEST1234"
MODEL_ARN = "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-5-5"
CFG = {"region": REGION, "kb_id": KB_ID, "model_arn": MODEL_ARN, "num_results": 5, "filter": None}
POLICY = "s3://docs-bucket/docs/crew-change-policy.md"
HELPDESK = "s3://docs-bucket/docs/it-helpdesk.md"


def enum_errors(params, shape, path=""):
    """botocore skips enum checks client-side; walk the shape and do them here."""
    errors = []
    if shape.type_name == "structure" and isinstance(params, dict):
        for key, value in params.items():
            if key in shape.members:
                errors += enum_errors(value, shape.members[key], f"{path}.{key}")
    elif shape.type_name == "list" and isinstance(params, list):
        for i, item in enumerate(params):
            errors += enum_errors(item, shape.member, f"{path}[{i}]")
    elif shape.type_name == "string" and shape.enum and params not in shape.enum:
        errors.append(f"{path}={params!r} not in {shape.enum}")
    return errors


def assert_enums_ok(test, service, operation, params):
    model = boto3.client(service, region_name=REGION).meta.service_model
    test.assertEqual(enum_errors(params, model.operation_model(operation).input_shape), [])


def s3_ref(uri, text):
    return {"content": {"type": "TEXT", "text": text},
            "location": {"type": "S3", "s3Location": {"uri": uri}},
            "metadata": {"x-amz-bedrock-kb-source-uri": uri}}


# FAKE RetrieveAndGenerate response, shaped like the API's.
ANSWER = "Officers need 30 days' notice. The fleet manager approves every crew change."
RAG_RESPONSE = {
    "output": {"text": ANSWER},
    "sessionId": "fake-session-0001",
    "citations": [
        {"generatedResponsePart": {"textResponsePart": {
            "text": "Officers need 30 days' notice.", "span": {"start": 0, "end": 29}}},
         "retrievedReferences": [s3_ref(POLICY, "Officers: the crewing team needs 30 days' notice")]},
        {"generatedResponsePart": {"textResponsePart": {
            "text": "The fleet manager approves every crew change.", "span": {"start": 31, "end": 75}}},
         "retrievedReferences": [s3_ref(POLICY, "The fleet manager approves every crew change.")]},
    ],
}

# FAKE Retrieve response.
RETRIEVE_RESPONSE = {"retrievalResults": [
    {**s3_ref(POLICY, "Officers: the crewing team needs 30 days' notice"), "score": 0.71},
    {**s3_ref(HELPDESK, "Priority 1 tickets: response within 1 hour"), "score": 0.32},
]}

# FAKE Converse response.
CONVERSE_RESPONSE = {
    "output": {"message": {"role": "assistant",
                           "content": [{"text": "Officers need 30 days' notice [1]."}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 210, "outputTokens": 12, "totalTokens": 222},
    "metrics": {"latencyMs": 900},
}


class TestRetrieveAndGenerate(unittest.TestCase):
    def test_request_matches_service_model_and_citations_parse(self):
        client = boto3.client("bedrock-agent-runtime", region_name=REGION)
        question = "How much notice for an officer crew change?"
        with Stubber(client) as stub:
            request = ask.build_request(question, KB_ID, MODEL_ARN, 5)
            assert_enums_ok(self, "bedrock-agent-runtime", "RetrieveAndGenerate", request)
            stub.add_response("retrieve_and_generate", RAG_RESPONSE, request)
            response = ask.ask(client, question, CFG)
        text, numbers = ask.annotate(response)
        self.assertEqual(numbers, {POLICY: 1})
        self.assertEqual(text, "Officers need 30 days' notice.[1] "
                               "The fleet manager approves every crew change.[1]")

    def test_filter_and_session_are_sent(self):
        client = boto3.client("bedrock-agent-runtime", region_name=REGION)
        flt = {"andAll": [{"equals": {"key": "team", "value": "crewing"}},
                          {"equals": {"key": "doc_type", "value": "policy"}}]}
        cfg = {**CFG, "filter": flt}
        expected = ask.build_request("q?", KB_ID, MODEL_ARN, 5, flt, "fake-session-0001")
        self.assertEqual(expected["retrieveAndGenerateConfiguration"]["knowledgeBaseConfiguration"]
                         ["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"], flt)
        with Stubber(client) as stub:
            stub.add_response("retrieve_and_generate", RAG_RESPONSE, expected)
            ask.ask(client, "q?", cfg, session_id="fake-session-0001")

    def test_bad_parameter_is_caught(self):
        # Proves the checks are real: a misspelled field and a bad enum must both fail.
        client = boto3.client("bedrock-agent-runtime", region_name=REGION)
        with Stubber(client) as stub:
            stub.add_response("retrieve_and_generate", RAG_RESPONSE)
            with self.assertRaises(ParamValidationError):
                client.retrieve_and_generate(input={"text": "q"}, retrieveAndGenerateConfig={})
        model = client.meta.service_model.operation_model("RetrieveAndGenerate").input_shape
        bad = {"input": {"text": "q"}, "retrieveAndGenerateConfiguration": {"type": "KB"}}
        self.assertEqual(len(enum_errors(bad, model)), 1)

    def test_no_citations(self):
        _, numbers = ask.annotate({"output": {"text": "Not found."}, "sessionId": "s1", "citations": []})
        self.assertEqual(numbers, {})


class TestRetrieveThenConverse(unittest.TestCase):
    def test_retrieve_and_converse(self):
        kb = boto3.client("bedrock-agent-runtime", region_name=REGION)
        llm = boto3.client("bedrock-runtime", region_name=REGION)
        q = "How much notice for an officer crew change?"
        with Stubber(kb) as kb_stub, Stubber(llm) as llm_stub:
            kb_stub.add_response("retrieve", RETRIEVE_RESPONSE, {
                "knowledgeBaseId": KB_ID, "retrievalQuery": {"text": q},
                "retrievalConfiguration": vector_search_config(5)})
            chunks = retrieve_only.retrieve(kb, q, KB_ID, 5)
            llm_stub.add_response("converse", CONVERSE_RESPONSE, {
                "modelId": MODEL_ARN,
                "system": [{"text": retrieve_only.SYSTEM_PROMPT}],
                "messages": retrieve_only.build_messages(q, chunks),
                "inferenceConfig": {"maxTokens": 800, "temperature": 0}})
            answer, usage = retrieve_only.generate(llm, MODEL_ARN, q, chunks)
        self.assertEqual([c["source"] for c in chunks], [POLICY, HELPDESK])
        self.assertEqual(retrieve_only.cited_ids(answer, len(chunks)), ([1], []))
        self.assertEqual(usage["inputTokens"], 210)

    def test_cited_ids_flags_made_up_sources(self):
        self.assertEqual(retrieve_only.cited_ids("a [1] b [7]", 2), ([1], [7]))


class TestEvalChecks(unittest.TestCase):
    def test_cases(self):
        ok = {"question": "q", "expect_source": "crew-change", "expect_in_answer": ["30"]}
        self.assertTrue(eval_smoke.check_case(ok, [POLICY], "30 days")[0])
        self.assertFalse(eval_smoke.check_case(ok, [], "30 days")[0])
        self.assertFalse(eval_smoke.check_case(ok, [HELPDESK], "30 days")[0])
        self.assertFalse(eval_smoke.check_case(ok, [POLICY], "21 days")[0])
        unanswerable = {"question": "q", "expect_source": None}
        self.assertTrue(eval_smoke.check_case(unanswerable, [], "I can't find that")[0])
        self.assertFalse(eval_smoke.check_case(unanswerable, [POLICY], "...")[0])

    def test_shipped_cases_file_is_valid(self):
        cases = json.loads((HERE / "eval_cases.json").read_text())
        self.assertTrue(all("question" in c and "expect_source" in c for c in cases))


class TestHelpers(unittest.TestCase):
    def test_source_of(self):
        self.assertEqual(source_of({"type": "WEB", "webLocation": {"url": "https://x"}}), "https://x")
        self.assertEqual(source_of(None), "(no location)")


class TestSetupPayloads(unittest.TestCase):
    """The JSON files the README's CLI steps send, checked against the service models."""

    ENV = {"AWS_REGION": REGION, "ACCOUNT_ID": "123456789012", "DOCS_BUCKET": "my-docs-bucket",
           "VECTOR_BUCKET": "my-kb-vectors", "INDEX_NAME": "kb-index"}

    def load(self, name):
        return json.loads(render((HERE / "setup" / name).read_text(), self.ENV))

    def validate(self, service, operation, params):
        model = boto3.client(service, region_name=REGION).meta.service_model
        shape = model.operation_model(operation).input_shape
        report = ParamValidator().validate(params, shape)
        self.assertFalse(report.has_errors(), report.generate_report())
        self.assertEqual(enum_errors(params, shape), [])

    def test_create_index(self):
        self.validate("s3vectors", "CreateIndex", {
            "vectorBucketName": self.ENV["VECTOR_BUCKET"], "indexName": self.ENV["INDEX_NAME"],
            "dataType": "float32", "dimension": 1024, "distanceMetric": "cosine",
            "metadataConfiguration": self.load("index-metadata-config.json")})

    def test_create_knowledge_base(self):
        self.validate("bedrock-agent", "CreateKnowledgeBase", {
            "name": "ops-docs-kb", "roleArn": "arn:aws:iam::123456789012:role/BedrockKbRole",
            "knowledgeBaseConfiguration": self.load("kb-config.json"),
            "storageConfiguration": self.load("storage-config.json")})

    def test_create_data_source(self):
        self.validate("bedrock-agent", "CreateDataSource", {
            "knowledgeBaseId": KB_ID, "name": "ops-docs-s3",
            "dataSourceConfiguration": self.load("data-source-config.json"),
            "vectorIngestionConfiguration": self.load("ingestion-config.json")})

    def test_iam_policies_render(self):
        for name in ("kb-trust-policy.json", "kb-permissions-policy.json"):
            self.assertNotIn("${", json.dumps(self.load(name)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
