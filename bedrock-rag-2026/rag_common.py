"""Shared helpers: config from env vars, clients, and source/citation formatting.

Every setting comes from an environment variable. Nothing is hard-coded.

Required:
  KB_ID       Knowledge base ID, e.g. ABCDEFGHIJ
  MODEL_ARN   Inference profile ARN (or ID) of the generation model, e.g.
              arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-5-5
Optional:
  AWS_REGION      Region of the knowledge base (default: us-east-1)
  KB_NUM_RESULTS  Chunks to retrieve, 1-100 (default: 5)
  KB_FILTER       Metadata filter as JSON, e.g. '{"equals": {"key": "team", "value": "crewing"}}'
"""

import json
import os
import sys

import boto3


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"Missing environment variable: {name} (see README.md)")
    return value


def load_config():
    num = int(env("KB_NUM_RESULTS", "5"))
    if not 1 <= num <= 100:
        sys.exit("KB_NUM_RESULTS must be between 1 and 100")
    raw_filter = env("KB_FILTER")
    return {
        "region": env("AWS_REGION", "us-east-1"),
        "kb_id": env("KB_ID", required=True),
        "model_arn": env("MODEL_ARN", required=True),
        "num_results": num,
        "filter": json.loads(raw_filter) if raw_filter else None,
    }


def agent_runtime(region):
    """Client for Retrieve / RetrieveAndGenerate (the knowledge base side)."""
    return boto3.client("bedrock-agent-runtime", region_name=region)


def model_runtime(region):
    """Client for Converse (the model side)."""
    return boto3.client("bedrock-runtime", region_name=region)


def vector_search_config(num_results, metadata_filter=None):
    """The retrievalConfiguration block shared by Retrieve and RetrieveAndGenerate."""
    cfg = {"numberOfResults": num_results}
    if metadata_filter:
        cfg["filter"] = metadata_filter
    return {"vectorSearchConfiguration": cfg}


# RetrievalResultLocation has one sub-object per source type, each with a uri/url/id.
_LOCATION_KEYS = {
    "S3": ("s3Location", "uri"),
    "WEB": ("webLocation", "url"),
    "CONFLUENCE": ("confluenceLocation", "url"),
    "SALESFORCE": ("salesforceLocation", "url"),
    "SHAREPOINT": ("sharePointLocation", "url"),
    "ONEDRIVE": ("oneDriveLocation", "url"),
    "GOOGLEDRIVE": ("googleDriveLocation", "url"),
    "KENDRA": ("kendraDocumentLocation", "uri"),
    "CUSTOM": ("customDocumentLocation", "id"),
    "SQL": ("sqlLocation", "query"),
}


def source_of(location):
    """Turn a RetrievalResultLocation dict into one readable string."""
    if not location:
        return "(no location)"
    loc_type = location.get("type", "")
    key, field = _LOCATION_KEYS.get(loc_type, (None, None))
    if key and key in location:
        return location[key].get(field, f"({loc_type})")
    return f"({loc_type or 'unknown'})"


def page_of(metadata):
    """PDF page number, when the knowledge base stored one."""
    page = (metadata or {}).get("x-amz-bedrock-kb-document-page-number")
    return f" p.{int(page)}" if isinstance(page, (int, float)) else ""
