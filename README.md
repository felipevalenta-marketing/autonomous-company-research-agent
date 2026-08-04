# Autonomous Company Research & Report Generation Agent

This project is the foundation for an autonomous company research system that will later gather evidence, reason over it, synthesize findings, and produce executive-ready reports. At this stage it provides a clean Python package structure, local environment loading, a minimal LangGraph workflow foundation, and basic project organization.

## Project Overview

- Selected industry: Market Research & Competitive Intelligence
- Current project status: Foundation setup
- Planned core components: ReAct, LangGraph, Pinecone RAG, external APIs, MCP, N8N, and report generation
- Implemented SEC company resolution uses a configured `SEC_USER_AGENT` and does not require live SEC access for unit tests.
- The SEC integration currently includes deterministic company resolution plus offline submissions and company-facts retrieval.
- The repository also includes an offline-testable NewsAPI provider layer for the `/v2/everything` endpoint.
- The repository also includes an offline-testable Tavily provider layer for the `/search` endpoint.
- The repository also includes an offline-testable OpenAI embeddings layer for vector preparation only.
- The repository also includes an offline-testable Pinecone vector boundary for upsert, query, and controlled delete operations against an already-created index.
- The repository also includes an offline-testable semantic retrieval layer that embeds a query, runs one company-scoped Pinecone lookup, and normalizes matches into `RAGResult` records without answer generation.
- The repository also includes an offline-testable RAG query orchestration service that validates a query, delegates to the retrieval boundary, and returns a `RAGQueryResult` wrapper with the original query plus normalized `RAGResult` values.
- The repository also includes an offline-testable evidence assembly service that deterministically selects traceable evidence from normalized `RAGResult` values without LLM selection or summarization.
- The repository also includes an offline-testable workflow output serialization contract, workflow integration boundary, and executable adapter for self-hosted n8n.
- The repository also includes an offline-testable document chunking service that currently produces deterministic fixed-size chunks with document and source lineage plus character offsets.
- ChunkRecord collections can be embedded through the existing `EmbeddingService`; chunk identity and order are preserved, and Pinecone vector preparation and indexing remain separate later stages.
- Embedded chunks can now be converted into deterministic prepared vector records through the existing vector-preparation boundary; prepared vectors can then flow through the existing vector-indexing boundary before Pinecone.
- The repository also includes an offline-testable RAG ingestion orchestration service that runs document chunking, chunk embedding, vector preparation, and vector indexing in order; retrieval remains a separate service.
- The repository also includes a minimal LangGraph workflow foundation that initializes a research request, resolves the company, validates the result, and routes to completion or failure without connecting provider collection, RAG, evidence assembly, or report generation yet.
- The repository also includes a bounded SEC-to-RAG seed ingestion adapter for one company and one filing type so the Pinecone index can be populated for demo preparation.
- The broader recursive chunking path remains a later-stage RAG concern.

## Current Folder Structure

```text
autonomous-company-research-agent/
|-- app/
|   |-- __init__.py
|   |-- main.py
|   |-- settings.py
|   |-- config/
|   |-- models/
|   |-- utils/
|   |-- clients/
|   |-- services/
|   |-- rag/
|   |-- prompts/
|   |-- exporters/
|   |-- nodes/
|   `-- graph/
|-- agents/
|-- data/
|   |-- raw/
|   |-- cache/
|   `-- processed/
|-- docs/
|-- graph/
|-- n8n/
|-- prompts/
|-- rag/
|-- reports/
|-- outputs/
|-- tests/
|-- tools/
|-- .env
|-- .env.example
|-- .gitignore
|-- README.md
|-- requirements.txt
```

Legacy root-level placeholder packages are preserved for compatibility with earlier scaffolding: `agents/`, `graph/`, `rag/`, `prompts/`, and `tools/`.

## Setup

### 1. Create the virtual environment

```powershell
python -m venv .venv
```

### 2. Activate the virtual environment

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Run the project

```powershell
python -m app.main
```

### 5. Run the tests

```powershell
python -m unittest discover -s tests -v
```

The test suite remains fully offline and uses mocked provider responses.

## Environment Variables

`.env.example` documents the required variable names. Copy it to `.env` for local credentials and keep your values empty until you are ready to configure them. `.env` is for local use only, must never be committed, and API credentials are optional during the foundation stage.

For SEC company resolution, set `SEC_USER_AGENT` to a descriptive header string that includes the application identity and a valid contact channel.
For NewsAPI provider calls, set `NEWS_API_KEY`; the MVP uses only the `/v2/everything` endpoint.
For Tavily provider calls, set `TAVILY_API_KEY`; the MVP uses only the `/search` endpoint and defers `/extract`.
For OpenAI embeddings, set `OPENAI_API_KEY` and optionally override `OPENAI_BASE_URL` or `OPENAI_EMBEDDING_MODEL` if needed; this stage only prepares embeddings and does not include text generation.
For Pinecone vector operations, set `PINECONE_API_KEY`, `PINECONE_INDEX_HOST`, `PINECONE_NAMESPACE_PREFIX`, `PINECONE_VECTOR_DIMENSION`, and optional bounds such as `PINECONE_API_VERSION`, `PINECONE_MAX_UPSERT_BATCH_SIZE`, and `PINECONE_MAX_QUERY_TOP_K`. The index must already exist, namespaces are company-scoped and deterministic, and upsert/delete acknowledgements are eventually consistent rather than immediately query-visible.

## HTTP API

The repository now exposes the existing research workflow through a small ASGI adapter for n8n and other HTTPS callers. It reuses the same application services, workflow output validation, and serialization contract already used by the CLI runner.

Start the API locally with:

```powershell
python -m uvicorn app.api:app --host 0.0.0.0 --port 8000
```

### Health check

```powershell
GET /health
```

Example response:

```json
{
  "status": "ok",
  "service": "autonomous-company-research-agent"
}
```

### Research request

`POST /research` requires the `X-API-Key` header and a JSON body with `company`, `ticker`, `cik`, and `query`.

Example request:

```powershell
POST /research
X-API-Key: $AGENT_API_KEY
Content-Type: application/json

{
  "company": "Apple Inc.",
  "ticker": "AAPL",
  "cik": "0000320193",
  "query": "Analyze the company's recent financial performance and strategic risks"
}
```

The successful response is the approved serialized `WorkflowOutput` contract and keeps the top-level keys:

```json
{
  "research_query": "...",
  "resolved_company": {
    "company_name": "...",
    "ticker": "...",
    "cik": "..."
  },
  "evidence_bundle": {
    "...": "..."
  }
}
```

Safe failure responses are deterministic JSON objects:

```json
{
  "status": "failed",
  "error_code": "INVALID_RESEARCH_REQUEST",
  "message": "Company, ticker, CIK and research query are required."
}
```

```json
{
  "status": "failed",
  "error_code": "UNAUTHORIZED",
  "message": "Invalid API credentials."
}
```

```json
{
  "status": "failed",
  "error_code": "RESEARCH_RETRIEVAL_FAILED",
  "message": "Research retrieval failed."
}
```

```json
{
  "status": "failed",
  "error_code": "INTERNAL_RESEARCH_ERROR",
  "message": "The research workflow could not be completed."
}
```

### How n8n calls it

n8n should send `POST /research` with `X-API-Key` and the same canonical request body used by the API. The workflow should point to this adapter over public HTTPS and treat the 200 response as the final research result.

### Deployment notes

The API is synchronous at the workflow boundary, but the ASGI route safely offloads the synchronous execution path to a worker thread. Deploy it behind a standard ASGI server such as Uvicorn and provide the production `AGENT_API_KEY`, OpenAI, Pinecone, and SEC environment values required by the existing research stack.

## Railway Deployment

1. Push the repository to GitHub.
2. Create a Railway project.
3. Deploy from the GitHub repository.
4. Railway should detect the `Dockerfile` automatically.
5. Add the required environment variables in Railway.
6. Generate a public domain.
7. Verify `GET /health`.
8. Verify authenticated `POST /research`.
9. Connect the public URL to n8n.
10. Never upload `.env`.

Required Railway variables:

- `AGENT_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_EMBEDDING_MODEL`
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `PINECONE_INDEX_HOST`
- `PINECONE_NAMESPACE_PREFIX`
- `PINECONE_VECTOR_DIMENSION`
- `PINECONE_API_VERSION`
- `PINECONE_MAX_UPSERT_BATCH_SIZE`
- `PINECONE_MAX_QUERY_TOP_K`
- `SEC_USER_AGENT`

Example health check:

```bash
curl https://YOUR-DOMAIN/health
```

Example research request:

```bash
curl -X POST https://YOUR-DOMAIN/research \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -d '{"company":"Apple Inc.","ticker":"AAPL","cik":"0000320193","query":"Analyze the company recent financial performance and strategic risks"}'
```

Railway supplies `PORT`, so it should not be added manually.

## Data Directories

- `data/raw/`: original input documents.
- `data/processed/`: transformed data produced during future ingestion.

The LangGraph workflow now orchestrates approved company resolution, RAG query retrieval, and evidence assembly. The n8n integration lives in the workflow source under `n8n/`, while provider collection, ReAct reasoning, and report generation remain outside this backend.

## n8n Adapter

Run the executable adapter with:

```powershell
python -m app.n8n_runner --company "Apple Inc." --query "Analyze the company’s recent financial performance and strategic risks"
```

The command uses the existing environment configuration documented above, writes the JSON payload to stdout on success, and writes safe errors to stderr with a nonzero exit code on failure. A self-hosted n8n workflow can invoke it with the Execute Command node.

### Explicit company override

SEC remains the default company-resolution path. For development or demo runs where a canonical company identity is already known, you can provide both the resolved ticker and CIK explicitly so the workflow skips only the remote SEC ticker lookup.

Both `--resolved-ticker` and `--resolved-cik` must be supplied together. The override does not replace SEC ingestion, retrieval, or evidence assembly.

```powershell
python -m app.n8n_runner --company "Apple Inc." --resolved-ticker "AAPL" --resolved-cik "0000320193" --query "Analyze the company's recent financial performance and strategic risks" --top-k 5 --max-evidence 3
```

## SEC Seed Ingestion

Run the bounded seed-ingestion adapter with:

```powershell
python -m app.rag_ingestion_runner --company "Apple Inc." --filing-type "10-K" --limit 1
```

It uses the configured SEC, OpenAI embeddings, and Pinecone services to seed the existing Pinecone RAG index for demo preparation. The command is intentionally bounded to one company and one filing type, writes a compact JSON summary to stdout on success, and does not generate a report or execute n8n.

## Roadmap

1. Add research workflow orchestration.
2. Introduce ReAct-style reasoning and LangGraph structure.
3. Connect retrieval with Pinecone and supporting data sources.
4. Add external APIs, MCP integrations, and N8N orchestration.
5. Build validation, synthesis, and executive report generation.

## Security Note

Never commit real API keys, secrets, or other private credentials.
