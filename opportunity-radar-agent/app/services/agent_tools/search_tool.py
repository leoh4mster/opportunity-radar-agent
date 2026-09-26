from __future__ import annotations

from pydantic import BaseModel

from app.services.agent_tools.base import BaseTool, OpportunityToolContext, ToolOutput


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str = "local"


class SearchProvider:
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError


class LocalSearchProvider(SearchProvider):
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        # Rules cannot produce retrieved evidence or authoritative URLs.
        return []


class TavilySearchProvider(SearchProvider):
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError("TODO: 接入 Tavily Search API")


class SerpAPISearchProvider(SearchProvider):
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError("TODO: 接入 SerpAPI")


class BingSearchProvider(SearchProvider):
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError("TODO: 接入 Bing Search API")


class SearchToolOutput(ToolOutput):
    query: str
    results: list[SearchResult]


class LocalSearchTool(BaseTool):
    name = "local_search"
    description = "围绕单条 opportunity 做本地规则检索。"
    input_model = OpportunityToolContext
    output_model = SearchToolOutput

    def __init__(self, provider: SearchProvider | None = None) -> None:
        self.provider = provider or LocalSearchProvider()

    def run(self, tool_input: OpportunityToolContext) -> SearchToolOutput:
        query = " ".join(
            item
            for item in [tool_input.title, tool_input.organizer, tool_input.link, tool_input.description[:120]]
            if item
        )
        results = self.provider.search(query, max_results=5)
        return SearchToolOutput(
            status="success",
            summary=f"围绕「{tool_input.title}」返回 {len(results)} 条本地规则结果。",
            query=query,
            results=results,
        )
