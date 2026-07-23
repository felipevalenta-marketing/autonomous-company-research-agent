# Autonomous Company Research & Report Generation Agent

This project is the foundation for an autonomous company research system that will later gather evidence, reason over it, synthesize findings, and produce executive-ready reports. At this stage it only provides a clean Python package structure, local environment loading, and basic project organization.

## Project Overview

- Selected industry: Market Research & Competitive Intelligence
- Current project status: Foundation setup
- Planned core components: ReAct, LangGraph, Pinecone RAG, external APIs, MCP, N8N, and report generation
- Implemented SEC company resolution uses a configured `SEC_USER_AGENT` and does not require live SEC access for unit tests.
- The SEC integration currently includes deterministic company resolution plus offline submissions and company-facts retrieval.

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

The test suite remains fully offline and uses mocked SEC responses.

## Environment Variables

`.env.example` documents the required variable names. Copy it to `.env` for local credentials and keep your values empty until you are ready to configure them. `.env` is for local use only, must never be committed, and API credentials are optional during the foundation stage.

For SEC company resolution, set `SEC_USER_AGENT` to a descriptive header string that includes the application identity and a valid contact channel.

## Data Directories

- `data/raw/`: original input documents.
- `data/processed/`: transformed data produced during future ingestion.

No RAG, API, LangGraph, or autonomous-agent functionality has been implemented yet.

## Roadmap

1. Add research workflow orchestration.
2. Introduce ReAct-style reasoning and LangGraph structure.
3. Connect retrieval with Pinecone and supporting data sources.
4. Add external APIs, MCP integrations, and N8N orchestration.
5. Build validation, synthesis, and executive report generation.

## Security Note

Never commit real API keys, secrets, or other private credentials.
