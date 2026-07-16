# Autonomous Company Research & Report Generation Agent

This project is the foundation for an autonomous company research system that will later gather evidence, reason over it, synthesize findings, and produce executive-ready reports. At this stage it only provides a clean Python package structure, local environment loading, and basic project organization.

## Project Overview

- Selected industry: Market Research & Competitive Intelligence
- Current project status: Foundation setup
- Planned core components: ReAct, LangGraph, Pinecone RAG, external APIs, MCP, N8N, and report generation

## Current Folder Structure

```text
autonomous-company-research-agent/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── settings.py
│   └── state.py
├── agents/
│   └── __init__.py
├── data/
│   ├── raw/
│   │   └── .gitkeep
│   └── processed/
│       └── .gitkeep
├── docs/
│   └── .gitkeep
├── graph/
│   └── __init__.py
├── n8n/
│   └── .gitkeep
├── prompts/
│   └── README.md
├── rag/
│   └── __init__.py
├── reports/
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   └── test_smoke.py
├── tools/
│   └── __init__.py
├── .env
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── run.py
```

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
python run.py
```

### 5. Run the tests

```powershell
python -m unittest discover -s tests -v
```

## Environment Variables

`.env.example` documents the required variable names. Copy it to `.env` for local credentials and keep your values empty until you are ready to configure them. `.env` is for local use only, must never be committed, and API credentials are optional during the foundation stage.

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
