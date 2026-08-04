# Autonomous Company Research Agent n8n Workflow

This directory contains the SDK source for the production-ready n8n workflow that wraps the existing Python research agent.

## Purpose

The workflow provides two entry paths:

- a manual demo trigger for presentation use;
- a webhook trigger for external HTTP execution.

It does not reimplement SEC, OpenAI, Pinecone, LangGraph, or evidence assembly. Those remain inside the Python agent.

## Architecture

1. Start Research Demo
2. Prepare Demo Request
3. Research API
4. Normalize Webhook Request
5. Validate Research Input
6. Input Valid and Complete?
7. Run Autonomous Research Agent
8. Normalize Agent Response
9. Research Successful?
10. Build Research Summary
11. Research Result
12. Invalid Request
13. Controlled Research Error

## Required API Endpoint

The HTTP Request node calls the Railway deployment directly:

- `https://autonomous-company-research-agent-production.up.railway.app/research`

## Required Credential

Create an HTTP Header Auth credential named:

- `Autonomous Research Agent API`

Configure the credential to send the `X-API-Key` header. Store the secret value in n8n, not in the workflow export.

## Manual Demo Execution

Use the manual trigger to run the prepared Apple demo request:

- company: `Apple Inc.`
- ticker: `AAPL`
- cik: `0000320193`
- query: `Analyze the company's recent financial performance and strategic risks`

## Webhook Request Example

```json
{
  "company": "Apple Inc.",
  "ticker": "AAPL",
  "cik": "0000320193",
  "query": "Analyze the company's recent financial performance and strategic risks"
}
```

The webhook also accepts the same fields inside `body`.

## Success Output

The presentation branch emits a deterministic result with:

- `status` set to `completed`
- `company` with `name`, `ticker`, and `cik`
- `research_query`
- `summary` with `evidence_count`, `source_count`, and `document_count`
- `key_evidence`, sorted by similarity score and capped at three items
- `markdown`, a readable demo view with SEC source URLs

An empty but valid evidence bundle remains a completed result with zero counts.

## Controlled Error Output

The failure branches emit deterministic safe error payloads with:

- `status`
- `stage`
- `http_status`
- `error_code`
- `message`

The workflow keeps separate branches for validation, Python, timeout, and unexpected failures.

## Regenerating or Updating Through MCP

When the connected n8n MCP server is available, use it to:

1. list workflows;
2. inspect the draft workflow named `Autonomous Company Research Agent`;
3. update the workflow rather than creating a duplicate;
4. validate node schemas, branches, and credential references before activation.

## Import Checklist

1. Import the SDK source from this directory into n8n.
2. Create the `Autonomous Research Agent API` credential with the `X-API-Key` header.
3. Replace the URL only if the Railway deployment changes.
4. Keep the workflow import free of secrets.
5. Verify the manual trigger and webhook trigger both reach the shared validation chain.

## Why Provider Integrations Stay in Python

The Python agent remains the owner of:

- SEC resolution;
- OpenAI embeddings;
- Pinecone retrieval;
- RAG normalization;
- evidence assembly;
- workflow output generation.

n8n only prepares the request, calls the Python API, and routes the final response for presentation.

## Notes

The workflow cannot execute successfully until:

1. the Python agent is exposed through a public HTTPS `/research` endpoint;
2. the n8n credential is created;
3. the workflow is imported into a clean n8n instance.

## Demo Checklist

1. Run `Start Research Demo`.
2. Confirm the Apple input is normalized and validated.
3. Confirm `Run Autonomous Research Agent` sends the authenticated POST request.
4. Confirm the success branch renders `key_evidence` and `markdown`.
5. Confirm empty evidence still produces a completed output, not an error.
6. Confirm failure branches return safe normalized errors.

## Screenshot Checklist

Capture these screenshots for the project submission:

1. The full workflow canvas with the manual trigger, webhook trigger, validation chain, agent call, and presentation branch visible.
2. The `Autonomous Research Agent API` credential configuration showing the `X-API-Key` header name only.
3. A successful Apple manual trigger execution with the final `key_evidence` and `markdown` fields visible.
4. A webhook execution showing validation or controlled error routing.
5. The workflow settings or notes panel showing the endpoint and demo purpose.
