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
- The repository also includes an offline-testable document chunking service that currently produces deterministic fixed-size chunks with document and source lineage plus character offsets.
- ChunkRecord collections can be embedded through the existing `EmbeddingService`; chunk identity and order are preserved, and Pinecone vector preparation and indexing remain separate later stages.
- Embedded chunks can now be converted into deterministic prepared vector records through the existing vector-preparation boundary; prepared vectors can then flow through the existing vector-indexing boundary before Pinecone.
- The repository also includes an offline-testable RAG ingestion orchestration service that runs document chunking, chunk embedding, vector preparation, and vector indexing in order; retrieval remains a separate service.
- The repository also includes a minimal LangGraph workflow foundation that initializes a research request, resolves the company, validates the result, and routes to completion or failure without connecting provider collection, RAG, evidence assembly, or report generation yet.
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

## Data Directories

- `data/raw/`: original input documents.
- `data/processed/`: transformed data produced during future ingestion.

No autonomous-agent reasoning, provider collection, RAG execution, evidence assembly, or answer-generation layer has been connected to the LangGraph foundation yet.

## Roadmap

1. Add research workflow orchestration.
2. Introduce ReAct-style reasoning and LangGraph structure.
3. Connect retrieval with Pinecone and supporting data sources.
4. Add external APIs, MCP integrations, and N8N orchestration.
5. Build validation, synthesis, and executive report generation.

## Security Note

Never commit real API keys, secrets, or other private credentials.
