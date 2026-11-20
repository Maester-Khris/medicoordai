from pathlib import Path
from unittest.mock import patch

import pytest

from graph import factory
from graph.base import GraphContext
from graph.semantic.candidates import Candidate, CandidateResult
from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS
from graph.snomed_neo4j.provider import Neo4jSnomedProvider
from graph.snomed_neo4j.semantic_provider import Neo4jSemanticProvider

A, B = ANCHOR_MAPPINGS[0], ANCHOR_MAPPINGS[2]  # two different complaints
assert A.anchor_concept_id != B.anchor_concept_id and A.max_depth == B.max_depth


class FakeClient:
    """Lexical rows for the text lookup; one red flag per anchor for the traversal, keyed by candidate -> anchor."""

    def __init__(self, lexical=None):
        self.lexical = lexical or []
        self.candidate_anchor = {"lex": A.anchor_concept_id, "sem": B.anchor_concept_id}
        self.queries = []

    def run_query(self, query, params):
        self.queries.append((query, params))
        if "$text" in query:
            return self.lexical
        rows = []
        for cand in params["candidate_concept_ids"]:
            anchor = self.candidate_anchor.get(cand, cand)
            if anchor in params["anchor_concept_ids"]:
                rows.append({"candidate_id": cand, "anchor_id": anchor, "indicator": f"flag for {anchor}", "ctas_level": 2,
                             "app_severity": "urgent", "followup_question": f"question for {anchor}?", "cluster_name": None})
        return rows

    def close(self):
        pass


class FakeSource:
    def __init__(self, result):
        self.result, self.messages = result, []

    def candidates(self, message):
        self.messages.append(message)
        return self.result


def _semantic_result(score_b=0.9, score_other=0.2):
    return CandidateResult((Candidate("sem", B.anchor_concept_id, score_b, "phrase b"),
                            Candidate("other-concept", "unrelated-anchor", score_other, "phrase c")), None)


def _provider(monkeypatch, client, source, **settings_kw):
    monkeypatch.setenv("NEO4J_URI", "bolt://x")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    from graph.semantic.settings import SemanticSettings
    settings = SemanticSettings(model_dir=Path("/m"), index_dir=Path("/i"), score_threshold=settings_kw.get("threshold", 0.5),
                                gap_margin=settings_kw.get("margin", 0.1), lay_rule="confirmed")
    with patch("graph.snomed_neo4j.provider.Neo4jClient", return_value=client):
        return Neo4jSemanticProvider(source=source, settings=settings)


def test_lexical_exact_hit_outranks_semantic_candidates(monkeypatch):
    client = FakeClient([{"concept_id": "lex", "matched_length": 20}])
    ctx = _provider(monkeypatch, client, FakeSource(_semantic_result())).get_symptom_graph_context("a long exact phrase here", [])
    assert ctx.matched and ctx.complaint_name == A.ctas_alias
    assert {rf.indicator for rf in ctx.red_flags} == {f"flag for {A.anchor_concept_id}", f"flag for {B.anchor_concept_id}"}


def test_short_lexical_hit_does_not_outrank_a_semantic_hit(monkeypatch):
    client = FakeClient([{"concept_id": "lex", "matched_length": 5}])
    ctx = _provider(monkeypatch, client, FakeSource(_semantic_result())).get_symptom_graph_context("my head is pounding", [])
    assert ctx.complaint_name == B.ctas_alias


def test_semantic_timeout_falls_back_to_lexical_result(monkeypatch):
    client = FakeClient([{"concept_id": "lex", "matched_length": 5}])
    ctx = _provider(monkeypatch, client, FakeSource(CandidateResult((), "timeout"))).get_symptom_graph_context("sore", [])
    assert ctx.matched and ctx.complaint_name == A.ctas_alias


def test_abstained_semantic_part_is_dropped_but_lexical_kept(monkeypatch):
    client = FakeClient([{"concept_id": "lex", "matched_length": 5}])
    low = _semantic_result(score_b=0.3)  # below the 0.5 threshold
    ctx = _provider(monkeypatch, client, FakeSource(low)).get_symptom_graph_context("sore", [])
    assert ctx.complaint_name == A.ctas_alias
    assert {rf.indicator for rf in ctx.red_flags} == {f"flag for {A.anchor_concept_id}"}


def test_semantic_only_uses_the_accepted_top_anchor_candidates(monkeypatch):
    client = FakeClient()
    provider = _provider(monkeypatch, client, FakeSource(_semantic_result(score_b=0.9, score_other=0.2)))
    ctx = provider.get_symptom_graph_context("my head is pounding", [])
    assert ctx.complaint_name == B.ctas_alias
    candidate_ids = [p["candidate_concept_ids"] for q, p in client.queries if "$text" not in q][0]
    assert candidate_ids == ["sem"]  # the runner-up anchor's candidate is not sent to the traversal


def test_the_semantic_source_sees_only_the_current_message(monkeypatch):
    source = FakeSource(CandidateResult((), "empty"))
    _provider(monkeypatch, FakeClient(), source).get_symptom_graph_context("current message", ["an earlier one"])
    assert source.messages == ["current message"]


def test_stale_index_serves_lexical_only_and_reports_stale(monkeypatch):
    client = FakeClient([{"concept_id": "lex", "matched_length": 20}])
    provider = _provider(monkeypatch, client, None)
    assert provider.semantic_status()["state"] == "disabled"
    provider.attach_semantic(None, "stale")
    assert provider.semantic_status()["state"] == "stale"
    ctx = provider.get_symptom_graph_context("a long exact phrase here", [])
    assert ctx.matched and ctx.complaint_name == A.ctas_alias


def test_empty_message_returns_matched_false_without_error(monkeypatch):
    provider = _provider(monkeypatch, FakeClient(), FakeSource(CandidateResult((), "empty")))
    assert provider.get_symptom_graph_context("😀", []) == GraphContext(matched=False)


def test_factory_builds_semantic_provider_for_the_new_value_and_leaves_neo4j_alone(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://x")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    for var in ("SEMANTIC_MODEL_DIR", "SEMANTIC_INDEX_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(factory, "_provider_cache", {})
    with patch("graph.snomed_neo4j.provider.Neo4jClient", return_value=FakeClient()):
        monkeypatch.setenv("GRAPH_RAG_PROVIDER", "neo4j_semantic")
        semantic = factory.get_graph_provider()
        monkeypatch.setenv("GRAPH_RAG_PROVIDER", "neo4j")
        v2 = factory.get_graph_provider()
    assert type(semantic) is Neo4jSemanticProvider and semantic.semantic_status()["state"] == "disabled"
    assert type(v2) is Neo4jSnomedProvider
