import logging

import pytest

from graph import factory
from graph.base import NullGraphProvider


@pytest.fixture(autouse=True)
def _fresh_cache():
    factory._provider_cache.clear()
    yield
    factory._provider_cache.clear()


def test_an_unknown_name_falls_back_to_off_and_says_so(monkeypatch, caplog):
    monkeypatch.setenv("GRAPH_RAG_PROVIDER", "semantick")
    with caplog.at_level(logging.WARNING, logger="graph.factory"):
        provider = factory.get_graph_provider()
    assert isinstance(provider, NullGraphProvider)
    assert [r for r in caplog.records if r.message == "graph_provider_unknown"]


def test_off_is_silent(monkeypatch, caplog):
    monkeypatch.setenv("GRAPH_RAG_PROVIDER", "off")
    with caplog.at_level(logging.WARNING, logger="graph.factory"):
        assert isinstance(factory.get_graph_provider(), NullGraphProvider)
    assert not [r for r in caplog.records if r.message == "graph_provider_unknown"]
