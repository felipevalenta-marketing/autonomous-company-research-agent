# Autonomous Company Research & Report Generation Agent

This project is the foundation for an autonomous company research system that will eventually gather evidence, reason over it, synthesize findings, and generate executive-ready reports. The current repository only contains the minimal Python structure needed to support that future work, with no external integrations enabled yet.

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
├── graph/
│   └── __init__.py
├── rag/
│   └── __init__.py
├── tools/
│   └── __init__.py
├── prompts/
│   └── README.md
├── reports/
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   └── test_smoke.py
├── docs/
│   └── .gitkeep
├── n8n/
│   └── .gitkeep
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

### 3. Run the project

```powershell
python run.py
```

### 4. Run the tests

```powershell
python -m unittest discover -s tests
```

## Environment Variables

Copy `.env.example` to `.env` if you need local secrets, then fill in your own values. The `.env` file is ignored by Git, and real credentials must never be committed.

## Roadmap

1. Add the first research workflow and orchestration layer.
2. Introduce ReAct-style reasoning and LangGraph structure.
3. Connect retrieval with Pinecone and supporting data sources.
4. Add external APIs, MCP integrations, and N8N orchestration.
5. Build validation, synthesis, and executive report generation.

## Security Note

Never commit real API keys, secrets, or other private credentials.
