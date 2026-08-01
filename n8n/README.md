# Autonomous Company Research Agent n8n Workflow

This directory contains the SDK source for the draft n8n workflow that wraps the existing Python research agent.

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

The HTTP Request node uses this placeholder until a real Python API is available:

- `Public HTTPS /research endpoint for the Python agent`

## Required Credential

The HTTP Request node expects this n8n credential name:

- `Autonomous Research Agent API`

The workflow does not contain the secret value.

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

- `status`
- `company`
- `ticker`
- `cik`
- `research_query`
- `evidence_count`
- `source_count`
- `document_count`
- `summary`
- `evidence_bundle`

## Controlled Error Output

The failure branch emits a deterministic error payload with:

- `status`
- `stage`
- `http_status`
- `error_code`
- `message`

## Regenerating or Updating Through MCP

When the connected n8n MCP server is available, use it to:

1. list workflows;
2. inspect the draft workflow named `Autonomous Company Research Agent`;
3. update the workflow rather than creating a duplicate;
4. validate node schemas, branches, and credential references before activation.

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
3. the placeholder URL is replaced with the real endpoint.
