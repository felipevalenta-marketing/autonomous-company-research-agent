# Autonomous Company Research Agent API Reference

## 1. Overview

The public API exposes the company research workflow over HTTP. It is hosted on Railway and is consumed by n8n, but it can also be called directly by other authenticated clients. In this repository, the API is an adapter over the Python and LangGraph research workflow. The backend owns company resolution, embeddings, Pinecone retrieval, normalization, evidence assembly, workflow completion, and serialization.

The service name defined in source is `autonomous-company-research-agent`.

## 2. Base URL

Current deployed base URL:

`https://autonomous-company-research-agent-production.up.railway.app`

Local development may use a different host.

## 3. Authentication

`POST /research` requires the `X-API-Key` header. The expected value is sourced from `AGENT_API_KEY`.

Authentication is not required for `GET /health` or `GET /deployment-info`.

If the API key is missing or invalid, the API returns:

- HTTP `401`
- `error_code`: `UNAUTHORIZED`
- `message`: `Invalid API credentials.`

Sanitized header example:

```http
X-API-Key: <AGENT_API_KEY>
```

## 4. Endpoint Summary

| Method | Endpoint | Authentication | Purpose |
|---|---|---|---|
| GET | `/health` | Not required | Health check for Railway and local use |
| GET | `/deployment-info` | Not required | Safe deployment identity metadata |
| POST | `/research` | Required | Run the company research workflow |

## 5. GET /health

Purpose: return a minimal health indicator without constructing provider clients.

Authentication: not required.

Status code: HTTP `200`.

Response body:

```json
{
  "status": "ok",
  "service": "autonomous-company-research-agent"
}
```

The health route is safe for Railway health checks because it does not call SEC, OpenAI, Pinecone, or build workflow dependencies.

Example request:

```http
GET /health
```

PowerShell:

```powershell
$baseUrl = "https://autonomous-company-research-agent-production.up.railway.app"
Invoke-RestMethod -Method Get -Uri "$baseUrl/health"
```

curl:

```bash
curl https://autonomous-company-research-agent-production.up.railway.app/health
```

## 6. GET /deployment-info

Purpose: return safe deployment identity metadata for comparing the running Railway deployment with the active service.

Authentication: not required.

Status code: HTTP `200`.

Response shape:

```json
{
  "status": "ok",
  "service": "autonomous-company-research-agent",
  "deployment": {
    "service_name": "local",
    "environment": "local",
    "commit": "unknown"
  }
}
```

Behavior:

- `service_name` comes from `RAILWAY_SERVICE_NAME` or falls back to `local`.
- `environment` comes from `RAILWAY_ENVIRONMENT_NAME` or falls back to `local`.
- `commit` is the first 8 characters of `RAILWAY_GIT_COMMIT_SHA` or `unknown` when unavailable.

Example request:

```http
GET /deployment-info
```

PowerShell:

```powershell
$baseUrl = "https://autonomous-company-research-agent-production.up.railway.app"
Invoke-RestMethod -Method Get -Uri "$baseUrl/deployment-info"
```

curl:

```bash
curl https://autonomous-company-research-agent-production.up.railway.app/deployment-info
```

To compare with Railway, match the returned `commit` prefix against the active deployment commit shown in Railway.

## 7. POST /research

Purpose: run the full company research workflow through the public Python service.

Authentication: required via `X-API-Key`.

Content type: `application/json`.

The request processing order in `app/api.py` is:

1. request received;
2. authentication;
3. JSON parsing;
4. request normalization;
5. dependency construction;
6. workflow invocation;
7. workflow-state retrieval-failure inspection;
8. workflow output construction;
9. serialization;
10. cleanup;
11. response.

If the JSON body is malformed, the API returns a safe `400` validation response.

## 8. Research Request Contract

Request body:

```json
{
  "company": "Apple Inc.",
  "ticker": "AAPL",
  "cik": "0000320193",
  "query": "Analyze the company's recent financial performance and strategic risks."
}
```

| Field | Type | Required | Normalization | Validation |
|---|---|---|---|---|
| company | string | Yes | Trimmed | Must be non-empty |
| ticker | string | Yes | Trimmed and uppercased | Must be non-empty |
| cik | string | Yes | Trimmed, validated as positive numeric string, padded to 10 digits | Must be numeric and positive |
| query | string | Yes | Trimmed | Must be non-empty |

The payload must be a JSON object. Invalid JSON also returns the safe `400` validation response.

## 9. Successful Response Contract

The public API returns the serialized backend workflow output. The top-level response contains exactly:

- `research_query`
- `resolved_company`
- `evidence_bundle`

Example success response:

```json
{
  "research_query": "Analyze the company's recent financial performance and strategic risks",
  "resolved_company": {
    "company_name": "Apple Inc.",
    "ticker": "AAPL",
    "cik": "0000320193",
    "exchange": null,
    "country": null,
    "security_type": null,
    "company_id": null,
    "website_url": null
  },
  "evidence_bundle": {
    "query": "Analyze the company's recent financial performance and strategic risks",
    "evidence_count": 1,
    "evidence": [
      {
        "result_id": "result-1",
        "query": "Analyze the company's recent financial performance and strategic risks",
        "company_name": "Apple Inc.",
        "source_id": "source-1",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "text": "Retrieved SEC evidence excerpt.",
        "similarity_score": 0.482,
        "retrieval_scope": "company:cik:0000320193",
        "source_url": "https://www.sec.gov/Archives/..."
      }
    ],
    "source_count": 1,
    "document_count": 1
  }
}
```

Inside `resolved_company`, the serializer currently includes:

- `company_name`
- `ticker`
- `cik`
- `exchange`
- `country`
- `security_type`
- `company_id`
- `website_url`

Inside `evidence_bundle`, the serializer includes:

- `query`
- `evidence_count`
- `evidence`
- `source_count`
- `document_count`

Inside each evidence item, the serializer includes:

- `result_id`
- `query`
- `company_name`
- `source_id`
- `document_id`
- `chunk_id`
- `text`
- `similarity_score`
- `retrieval_scope`
- `source_url`

## 10. Empty Evidence Success

A valid completed workflow may return zero evidence while still succeeding with HTTP `200`.

Example:

```json
{
  "research_query": "Analyze the company's recent financial performance and strategic risks",
  "resolved_company": {
    "company_name": "Apple Inc.",
    "ticker": "AAPL",
    "cik": "0000320193",
    "exchange": null,
    "country": null,
    "security_type": null,
    "company_id": null,
    "website_url": null
  },
  "evidence_bundle": {
    "query": "Analyze the company's recent financial performance and strategic risks",
    "evidence_count": 0,
    "evidence": [],
    "source_count": 0,
    "document_count": 0
  }
}
```

This is a valid completed response, not an error.

## 11. Error Responses

| HTTP Status | error_code | message | Meaning |
|---|---|---|---|
| 400 | `INVALID_RESEARCH_REQUEST` | `Company, ticker, CIK and research query are required.` | The request body is malformed or missing required fields |
| 401 | `UNAUTHORIZED` | `Invalid API credentials.` | The `X-API-Key` header is missing or invalid |
| 502 | `RESEARCH_RETRIEVAL_FAILED` | `Research retrieval failed.` | The workflow failed during retrieval or a retrieval-related failure was detected |
| 500 | `INTERNAL_RESEARCH_ERROR` | `The research workflow could not be completed.` | The workflow failed outside the retrieval path or during output/integration handling |

The public API does not return provider payloads, vectors, embeddings, filing text, or raw exception messages.

## 12. Retrieval Failure Classification

`app/api.py` maps retrieval-related failures to HTTP `502` in two ways:

- it catches provider/retrieval exceptions directly; and
- it inspects failed workflow state for retrieval-related error codes.

The workflow-state inspection path recognizes retrieval-oriented errors, including concrete consistency subclasses, and returns the safe `RESEARCH_RETRIEVAL_FAILED` response.

## 13. Safe Diagnostics and Logging

Current safe log markers in source include:

- `research_request_received`
- `retrieval_exception_origin`
- `research_request_failed`

`research_request_received` includes only:

- route
- service name
- environment
- commit prefix

`retrieval_exception_origin` includes only:

- exception type
- exception module
- origin file
- origin function
- origin line
- immediate cause type

`research_request_failed` includes only:

- stage
- error type
- cause type
- response status

These markers do not expose API keys, request bodies, headers, vectors, embeddings, Pinecone payloads, SEC filing text, provider response bodies, exception messages, stack traces, or absolute paths.

## 14. PowerShell Examples

### Health check

```powershell
$baseUrl = "https://autonomous-company-research-agent-production.up.railway.app"
Invoke-RestMethod -Method Get -Uri "$baseUrl/health" | ConvertTo-Json -Depth 20
```

### Deployment info

```powershell
$baseUrl = "https://autonomous-company-research-agent-production.up.railway.app"
Invoke-RestMethod -Method Get -Uri "$baseUrl/deployment-info" | ConvertTo-Json -Depth 20
```

### Authenticated research request

```powershell
$baseUrl = "https://autonomous-company-research-agent-production.up.railway.app"
$agentKey = "<AGENT_API_KEY>"
$headers = @{
  "X-API-Key" = $agentKey
}
$body = @{
  company = "Apple Inc."
  ticker  = "AAPL"
  cik     = "0000320193"
  query   = "Analyze the company's recent financial performance and strategic risks."
}

Invoke-RestMethod -Method Post -Uri "$baseUrl/research" -Headers $headers -ContentType "application/json" -Body ($body | ConvertTo-Json -Depth 20) | ConvertTo-Json -Depth 20
```

## 15. curl Examples

### GET /health

```bash
curl https://autonomous-company-research-agent-production.up.railway.app/health
```

### GET /deployment-info

```bash
curl https://autonomous-company-research-agent-production.up.railway.app/deployment-info
```

### POST /research

```bash
curl -X POST https://autonomous-company-research-agent-production.up.railway.app/research \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <AGENT_API_KEY>" \
  -d "{\"company\":\"Apple Inc.\",\"ticker\":\"AAPL\",\"cik\":\"0000320193\",\"query\":\"Analyze the company's recent financial performance and strategic risks.\"}"
```

## 16. n8n Integration

The n8n workflow uses an HTTP Request node named `Run Autonomous Research Agent` in `n8n/workflows/autonomous_company_research_agent.workflow.json`.

Current configuration in source:

- method: `POST`
- URL: `https://autonomous-company-research-agent-production.up.railway.app/research`
- authentication: `X-API-Key` through the `Autonomous Research Agent API` Header Auth credential
- body: `company`, `ticker`, `cik` from the normalized CIK field, and `query`
- timeout: `120000`
- success response handling: full response enabled, response code ignored for branching
- error response handling: the workflow routes validation, timeout, Python error, and unexpected cases separately

Secrets remain in n8n credentials; they are not embedded in the exported workflow source.

## 17. Provider and Backend Dependencies

| Dependency | Purpose |
|---|---|
| SEC EDGAR | Source documents and company metadata for ingestion |
| OpenAI embeddings | Vector embeddings for query and document retrieval |
| Pinecone | Company-scoped vector storage and query |
| LangGraph | Stateful research workflow execution |
| Railway | HTTPS hosting and environment-variable management |
| n8n | Orchestration, validation, routing, and presentation |

Transport success from these dependencies does not guarantee successful local parsing, normalization, or evidence assembly. The API still validates the workflow state before producing a public response.

## 18. Operational Verification

- `GET /health` returns HTTP `200`
- `GET /deployment-info` returns a safe deployment identity payload
- authenticated `POST /research` returns HTTP `200` for Apple
- authenticated `POST /research` returns HTTP `200` for Microsoft
- `evidence_count` is nonzero for indexed companies
- `source_url` points to SEC sources in successful evidence
- `retrieval_exception_origin` does not appear on successful requests
- `research_request_failed` does not appear on successful requests
- Railway logs show OpenAI and Pinecone HTTP `200` when applicable

## 19. Security Considerations

- `AGENT_API_KEY` remains in Railway environment variables
- n8n stores `X-API-Key` in credentials
- the exported workflow contains only credential references
- provider secrets remain environment variables
- public error responses are intentionally generic
- `GET /deployment-info` exposes only safe metadata
- no secret should be committed to Git

## 20. Known Limitations

- only companies with indexed Pinecone data return nonzero evidence
- the API returns retrieved evidence, not a fully generative executive report
- supported filing coverage depends on ingestion configuration
- empty evidence is a valid completed response
- the API currently uses API-key authentication
- there is no built-in pagination contract for evidence results
- there is no built-in namespace management endpoint

## 21. Related Files

- `app/api.py`
- `app/n8n_runner.py`
- `app/settings.py`
- `app/graph/workflow.py`
- `app/rag/retrieval_service.py`
- `app/rag/normalization.py`
- `app/services/evidence_assembly_service.py`
- `app/services/workflow_output_service.py`
- `app/services/workflow_serialization_service.py`
- `app/services/workflow_integration_service.py`
- `n8n/workflows/autonomous_company_research_agent.workflow.json`
- `docs/workflow_architecture.md`
- `tests/unit/test_api.py`
- `tests/unit/test_n8n_runner.py`
