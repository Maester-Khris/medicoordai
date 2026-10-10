import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from graph.base import GraphContextProvider, GraphContext, NullGraphProvider


class _ExplodingProvider(GraphContextProvider):
    def _lookup(self, user_message, recent_messages):
        raise RuntimeError("boom")


def test_lookup_failure_returns_empty_context_not_raise():
    provider = _ExplodingProvider()
    result = provider.get_symptom_graph_context("chest pain", [])
    assert result == GraphContext(matched=False)


def test_null_provider_always_returns_empty_context():
    provider = NullGraphProvider()
    result = provider.get_symptom_graph_context("chest pain", ["can't breathe"])
    assert result == GraphContext(matched=False)


def test_graph_context_default_red_flags_is_empty_list():
    assert GraphContext(matched=False).red_flags == []


def _graph_count(provider: str, outcome: str) -> float:
    from observability import _registry
    return _registry.get_sample_value(
        "graph_lookup_duration_seconds_count", {"provider": provider, "outcome": outcome}
    ) or 0.0


def test_lookup_is_timed_under_the_configured_provider_name(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_PROVIDER", "Static")
    before = _graph_count("static", "ok")
    NullGraphProvider().get_symptom_graph_context("chest pain", [])
    assert _graph_count("static", "ok") == before + 1


def test_lookup_defaults_to_the_off_label(monkeypatch):
    monkeypatch.delenv("GRAPH_RAG_PROVIDER", raising=False)
    before = _graph_count("off", "ok")
    NullGraphProvider().get_symptom_graph_context("chest pain", [])
    assert _graph_count("off", "ok") == before + 1


def test_failed_lookup_is_timed_as_an_error(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_PROVIDER", "neo4j")
    before = _graph_count("neo4j", "error")
    _ExplodingProvider().get_symptom_graph_context("chest pain", [])
    assert _graph_count("neo4j", "error") == before + 1
