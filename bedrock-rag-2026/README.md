# RAG on AWS Bedrock, 2026 edition

A Bedrock Knowledge Base on S3 + Amazon S3 Vectors, queried three ways:

- `ask.py`: one `RetrieveAndGenerate` call. Bedrock retrieves, generates, and returns citations. The answer is printed with `[n]` markers and a source list.
- `retrieve_only.py`: `Retrieve` for the chunks, then your own prompt to the Converse API. Use it when you need control (your own prompt, extra context, your own filtering of chunks, a Managed Knowledge Base).
- `eval_smoke.py`: asks a few known questions and fails if an answer doesn't cite the expected source.

Companion code for the Medium post *Build a RAG Pipeline on AWS Bedrock: the 2026 Edition*.

> **How this was tested.** All request and response shapes were validated offline against the boto3 1.43.126 service models, with botocore's `Stubber` (see `test_offline.py`). The CLI commands below were checked against AWS CLI 1.46.3's parameter validation without credentials. None of it has been run against a live AWS account by the author of this folder. Run `eval_smoke.py` against your own knowledge base before you trust it.

## Files

```
rag_common.py        env config, clients, source formatting
ask.py               RetrieveAndGenerate with citations
retrieve_only.py     Retrieve + Converse with your own prompt
eval_smoke.py        citation smoke test (exit code 1 on failure)
eval_cases.json      the questions eval_smoke.py asks
test_offline.py      offline tests (Stubber + service-model validation)
sample_docs/         two made-up documents + .metadata.json files
setup/*.json         payloads for the CLI setup path (templated with ${VARS})
setup/render.py      fills the templates into build/
```

## Run the offline tests (no AWS account needed)

```bash
pip install -r requirements.txt
python test_offline.py
```

Expected last lines:

```
Ran 13 tests in 0.0XXs

OK
```

## Create the knowledge base: console (recommended for a first run)

Pick a Region where both Bedrock Knowledge Bases and S3 Vectors are available (this README uses `us-east-1`).

1. Create a general purpose S3 bucket and upload `sample_docs/` (both `.md` files and both `.metadata.json` files) under a `docs/` prefix.
2. Open the Amazon Bedrock console → **Knowledge bases** → create a knowledge base **with a vector store**. (The console now also offers **Managed Knowledge Base**. It's simpler, but `ask.py` won't work with it, because `RetrieveAndGenerate` doesn't support managed knowledge bases. See the post.)
3. Let Bedrock create the service role.
4. Data source: **Amazon S3**, your bucket, inclusion prefix `docs/`. Under **Content parsing and chunking**, leave the default parser and pick a chunking strategy. You can't change the chunking strategy later.
5. Embeddings model: **Titan Text Embeddings V2**, float32, 1024 dimensions.
6. Vector database: **Quick create a new vector store** → **Amazon S3 Vectors**.
7. Create, then press **Sync** on the data source. Note the knowledge base ID.

## Create the knowledge base: CLI

Same result, fully scripted. Uses bash/zsh and the AWS CLI.

```bash
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=$AWS_REGION        # AWS CLI v1 reads this one, not AWS_REGION
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export DOCS_BUCKET=kb-docs-$ACCOUNT_ID
export VECTOR_BUCKET=kb-vectors-$ACCOUNT_ID
export INDEX_NAME=kb-index
export KB_ROLE_NAME=BedrockKbRole-ops-docs

python setup/render.py                       # writes build/*.json with your values

# 1. Documents
aws s3 mb s3://$DOCS_BUCKET
aws s3 cp sample_docs/ s3://$DOCS_BUCKET/docs/ --recursive

# 2. Vector bucket + index. AWS docs say to mark AMAZON_BEDROCK_TEXT and
#    AMAZON_BEDROCK_METADATA as non-filterable; otherwise the chunk text counts
#    against the 2 KB filterable-metadata limit and ingestion can fail.
aws s3vectors create-vector-bucket --vector-bucket-name $VECTOR_BUCKET
aws s3vectors create-index --vector-bucket-name $VECTOR_BUCKET --index-name $INDEX_NAME \
  --data-type float32 --dimension 1024 --distance-metric cosine \
  --metadata-configuration file://build/index-metadata-config.json

# 3. Service role the knowledge base assumes (embedding model, docs bucket, vector index)
aws iam create-role --role-name $KB_ROLE_NAME \
  --assume-role-policy-document file://build/kb-trust-policy.json
aws iam put-role-policy --role-name $KB_ROLE_NAME --policy-name kb-access \
  --policy-document file://build/kb-permissions-policy.json
sleep 15   # give IAM a moment to propagate

# 4. Knowledge base
export KB_ID=$(aws bedrock-agent create-knowledge-base --name ops-docs-kb \
  --role-arn arn:aws:iam::$ACCOUNT_ID:role/$KB_ROLE_NAME \
  --knowledge-base-configuration file://build/kb-config.json \
  --storage-configuration file://build/storage-config.json \
  --query knowledgeBase.knowledgeBaseId --output text)
aws bedrock-agent get-knowledge-base --knowledge-base-id $KB_ID \
  --query knowledgeBase.status --output text          # wait for ACTIVE

# 5. Data source (fixed-size chunks: 300 tokens, 20% overlap)
export DS_ID=$(aws bedrock-agent create-data-source --knowledge-base-id $KB_ID \
  --name ops-docs-s3 \
  --data-source-configuration file://build/data-source-config.json \
  --vector-ingestion-configuration file://build/ingestion-config.json \
  --query dataSource.dataSourceId --output text)

# 6. Sync (re-run whenever the documents change)
export JOB_ID=$(aws bedrock-agent start-ingestion-job --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID --query ingestionJob.ingestionJobId --output text)
aws bedrock-agent get-ingestion-job --knowledge-base-id $KB_ID --data-source-id $DS_ID \
  --ingestion-job-id $JOB_ID --query 'ingestionJob.[status,statistics]'   # wait for COMPLETE
```

## Pick the generation model

Newer Claude models on Bedrock are served through inference profiles. List the ones your Region offers, then get the ARN of the one you want:

```bash
aws bedrock list-inference-profiles --type-equals SYSTEM_DEFINED \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude')].inferenceProfileId"

export MODEL_ARN=$(aws bedrock get-inference-profile \
  --inference-profile-identifier us.anthropic.claude-sonnet-5-5 \
  --query inferenceProfileArn --output text)
```

Profile IDs confirmed in the Bedrock model cards at the time of writing: `us.anthropic.claude-sonnet-5-5`, `us.anthropic.claude-haiku-5-5` (also `eu.`, `au.`, `global.` variants). A `us.`/`eu.` profile can route to other Regions in that geography; `global.` can route to any commercial Region. If you have data residency rules, check where yours routes with `get-inference-profile`.

Your own IAM identity needs `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate` (see the knowledge base permissions page), plus access to the model.

## Ask questions

```bash
export KB_ID=...          # from step 4
export MODEL_ARN=...      # from above
export AWS_REGION=us-east-1
# optional:
export KB_NUM_RESULTS=5
export KB_FILTER='{"equals": {"key": "team", "value": "crewing"}}'

python ask.py "How many days' notice does an officer crew change need?"
python ask.py --session <sessionId-from-last-answer> "And for ratings?"
python retrieve_only.py "How fast is a Priority 1 IT ticket answered?"
python eval_smoke.py
python eval_smoke.py --mode retrieve
```

What you get back:

- `ask.py` prints the answer with `[n]` after each cited sentence, the list of cited S3 URIs, and the `sessionId` for a follow-up. If there are no citations it says so.
- `retrieve_only.py` prints the answer, the sources it cited, a warning if it cited a source number that doesn't exist, and token usage including `cacheReadInputTokens`.
- `eval_smoke.py` prints PASS/FAIL per question and exits 1 if any fail. The last case in `eval_cases.json` is a question the documents can't answer: it passes only if the answer cites nothing.

## Clean up

```bash
aws bedrock-agent delete-data-source --knowledge-base-id $KB_ID --data-source-id $DS_ID
aws bedrock-agent delete-knowledge-base --knowledge-base-id $KB_ID
aws s3vectors delete-index --vector-bucket-name $VECTOR_BUCKET --index-name $INDEX_NAME
aws s3vectors delete-vector-bucket --vector-bucket-name $VECTOR_BUCKET
aws s3 rb s3://$DOCS_BUCKET --force
aws iam delete-role-policy --role-name $KB_ROLE_NAME --policy-name kb-access
aws iam delete-role --role-name $KB_ROLE_NAME
```

## Known limits (from the AWS docs)

- S3 Vectors as a knowledge base store: semantic search only (no hybrid), float32 only, 1 KB of custom metadata and 35 metadata keys per vector.
- Hierarchical chunking is not recommended with S3 Vectors (parent chunk context is stored as metadata and can hit the size limit).
- Metadata files must be named `<file>.metadata.json`, sit next to the file, and stay under 10 KB.
- `RetrieveAndGenerate` doesn't work with Managed Knowledge Bases. Use `Retrieve` (or `AgenticRetrieveStream`) there.

MIT licensed.
