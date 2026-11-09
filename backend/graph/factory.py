"""
Factory. Reads GRAPH_RAG_PROVIDER env var. Mirrors get_llm_client()
(backend/services/llm_agent.py) — deferred imports so unused provider
packages don't cause ImportError.

Providers are cached per provider-name value (not a single unconditional
singleton) — this fixes C1 (a fresh Neo4j driver/connection pool was opened
on every LLMAgent() construction, i.e. every chat request, and never closed)
while preserving the existing eval-script pattern of setting
GRAPH_RAG_PROVIDER at runtime mid-process and expecting a fresh provider for
the new value (backend/scripts/graphrag_eval/run_track_a_retrieval.py's
build_provider()). See plan: 2026-08-03-sprint19-postreview-critical-important-fixes.md, C1.

Supported provider names: off (NullGraphProvider), static (StaticLookupProvider),
neo4j (Neo4jSnomedProvider), neo4j_semantic (Neo4jSemanticProvider).
"""
import os

from graph.base import GraphContextProvider, NullGraphProvider

_provider_cache: dict[str, GraphContextProvider] = {}


def _build_provider(provider_name: str) -> GraphContextProvider:
    if provider_name == "static":
        from graph.static_provider import StaticLookupProvider
        return StaticLookupProvider()
    if provider_name == "neo4j":
        from graph.snomed_neo4j.provider import Neo4jSnomedProvider
        return Neo4jSnomedProvider()
    if provider_name == "neo4j_semantic":
        from graph.snomed_neo4j.semantic_provider import Neo4jSemanticProvider
        return Neo4jSemanticProvider()
    return NullGraphProvider()


def get_graph_provider() -> GraphContextProvider:
    provider_name = os.environ.get("GRAPH_RAG_PROVIDER", "off").lower()
    if provider_name not in _provider_cache:
        _provider_cache[provider_name] = _build_provider(provider_name)
    return _provider_cache[provider_name]


def close_graph_provider() -> None:
    """Closes every cached provider that exposes close() (today, only
    Neo4jSnomedProvider does) and clears the cache. Call once from FastAPI
    lifespan teardown (backend/main.py) — the shutdown half cache.py's
    startup-warm pattern doesn't otherwise have."""
    for provider in _provider_cache.values():
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    _provider_cache.clear()
