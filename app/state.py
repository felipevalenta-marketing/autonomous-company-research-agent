"""Shared application state contract."""

from typing import TypedDict


class ResearchState(TypedDict):
    """Initial state for company research workflows."""

    company_name: str
    research_goal: str
    research_plan: list[str]
    web_results: list[dict]
    news_results: list[dict]
    financial_results: list[dict]
    rag_context: list[str]
    analysis: str
    report: str
    errors: list[str]
