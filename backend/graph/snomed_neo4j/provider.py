"""
backend/graph/snomed_neo4j/provider.py

Neo4jSnomedProvider — v2 GraphContextProvider backed by the live Neo4j graph
(Layer 1 SNOMED CT terminology + Layer 2 CTAS red-flag overlay).

This is the only file in the request path that knows about the graph's schema.
It implements _lookup() only — the public get_symptom_graph_context() entry
point is inherited from GraphContextProvider and must NOT be overridden: the
base class's try/except is what guarantees a Neo4j outage (including AuraDB
Free's 72h auto-pause) degrades to GraphContext(matched=False) rather than
breaking triage.

neo4j.Record objects never leave client.py — this module works only with the
plain dicts run_query() returns. GraphContext/RedFlagMatch are assembled here
and nowhere else in the request path.

Global constraints (binding, same as every prior task in this pipeline):
- LLMAgent / prompts.py import only graph.base.GraphContextProvider/GraphContext
  — never graph.snomed_neo4j.* directly.
- Severity classification is the LLM's job, unconditionally.
"""
import logging
import os
import re
from collections import defaultdict

from graph.base import GraphContext, GraphContextProvider, RedFlagMatch
from graph.snomed_neo4j.client import Neo4jClient
from graph.snomed_neo4j.queries import (
    build_concept_lookup_query,
    build_red_flag_traversal_query_batch,
)
from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS

logger = logging.getLogger(__name__)

# I-3: ~25 of 86 canonical indicator strings in symptom_triage_data.json are
# corrupted PDF-extraction fragments. These two patterns catch 15 of them
# (7 level-prefixed + 8 bare VS-abbreviation stubs), verified directly
# against current data (2026-08-03) and confirmed to correctly NOT flag the
# other 3 "VS, ... dehydration" entries, which are real descriptive phrases,
# not stubs. The remainder of the estimated ~25 are free-text sentence
# fragments needing manual clinical review, not a regex; this is a
# defensive filter, not a claim of full data cleanup. v1
# (static_provider.py) shares this exposure and is not touched here.
_LEVEL_PREFIX_RE = re.compile(r"^\d+\s")
_VS_STUB_RE = re.compile(r"^VS,?\s*(?:[A-Z]{2,4},?\s*)*$")


def is_corrupted_indicator(indicator: str) -> bool:
    """True when `indicator` is a known PDF-extraction artifact that must not
    reach the LLM prompt (see the pattern notes above)."""
    if _LEVEL_PREFIX_RE.match(indicator):
        return True
    if _VS_STUB_RE.match(indicator):
        return True
    return False

class Neo4jSnomedProvider(GraphContextProvider):
    """v2 provider — reads the live Neo4j KG built by Phases 0-3.

    __init__ establishes the driver once; _lookup() is called per request.
    Credentials come from NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD env vars
    (injected via Doppler per repo convention — never hardcoded).
    """

    def __init__(self) -> None:
        missing = [v for v in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD") if not os.environ.get(v)]
        if missing:
            raise ValueError(
                f"Neo4jSnomedProvider requires env vars: {', '.join(missing)}. "
                "Inject via Doppler or set before constructing the provider."
            )
        uri = os.environ["NEO4J_URI"]
        username = os.environ["NEO4J_USERNAME"]
        password = os.environ["NEO4J_PASSWORD"]
        self._client = Neo4jClient(uri, (username, password))

    def close(self) -> None:
        """Release the underlying Neo4j driver. Call at application shutdown
        (e.g. FastAPI lifespan teardown). The base class 'never-raises' contract
        applies only to _lookup(); the driver itself is not auto-closed."""
        self._client.close()

    def ping(self) -> None:
        """Ops-only connectivity check for /health (backend/main.py) — keeps
        AuraDB's free-tier instance from hitting the 72h auto-pause window
        mentioned in this class's docstring. Raises on failure; never called
        from the triage request path."""
        self._client.ping()

    def _gather_candidates(self, user_message: str, all_text: str) -> dict[str, float]:
        """Run the concept lookup query against `all_text` and return a
        specificity dict ``{concept_id: matched_length}`` for every hit.
        This is the seam that Neo4jSemanticProvider overrides to merge in
        semantic candidates before the traversal step."""
        lookup_query, lookup_params = build_concept_lookup_query()
        concept_rows = self._client.run_query(lookup_query, {**lookup_params, "text": all_text})
        return {row["concept_id"]: row["matched_length"] for row in concept_rows}

    def _resolve_surviving_mappings(
        self, all_text: str, user_message: str | None = None
    ) -> list[tuple]:
        """Shared by _lookup() and debug_all_matches(): every
        ANCHOR_MAPPINGS entry with surviving (non-corrupted) red-flag
        rows, each paired with its specificity score (the longest matched
        Description.term length among the candidate concepts that
        traversed to it) and its rows. Iteration follows ANCHOR_MAPPINGS
        order, which also becomes the tie-break when two anchors share the
        same specificity score (fixed 2026-08-05 — see docs/superpowers/
        plans/2026-08-05-v1-v2-retrieval-eval-fairness.md Task 2;
        previously this picked the first anchor in list order regardless
        of specificity)."""
        candidates = self._gather_candidates(
            user_message if user_message is not None else all_text, all_text
        )
        if not candidates:
            return []

        candidate_ids = list(candidates)
        candidate_specificity = candidates
        rows_by_anchor = self._traverse_all_anchors(candidate_ids)
        self._log_cross_symptom_clusters(rows_by_anchor)

        surviving = []
        for mapping in ANCHOR_MAPPINGS:
            rows = rows_by_anchor.get(mapping.anchor_concept_id, [])
            rows = [row for row in rows if not is_corrupted_indicator(row["indicator"])]
            if not rows:
                continue
            specificity = max(candidate_specificity.get(row["candidate_id"], 0) for row in rows)
            surviving.append((mapping, specificity, rows))
        return surviving

    def _lookup(self, user_message: str, recent_messages: list[str]) -> GraphContext:
        all_text = " ".join([user_message, *recent_messages]).strip()
        surviving = self._resolve_surviving_mappings(all_text, user_message=user_message)
        if not surviving:
            return GraphContext(matched=False)

        # Task 2 fix: most specific (longest matched term) anchor wins,
        # not whichever comes first in ANCHOR_MAPPINGS's static order.
        # max() with key= returns the first maximal element while
        # iterating in order, so ties still preserve the original
        # ANCHOR_MAPPINGS-order tie-break.
        best_mapping, _, _ = max(surviving, key=lambda triple: triple[1])
        complaint_name = best_mapping.ctas_alias

        red_flags: list[RedFlagMatch] = []
        seen_indicators: set[str] = set()
        for _, _, rows in surviving:
            for row in rows:
                indicator = row["indicator"]
                if indicator not in seen_indicators:
                    seen_indicators.add(indicator)
                    red_flags.append(
                        RedFlagMatch(
                            indicator=indicator,
                            ctas_level=row["ctas_level"],
                            app_severity=row["app_severity"],
                            followup_question=row["followup_question"],
                        )
                    )

        if not red_flags:
            return GraphContext(matched=False)

        # Design §4 point 4 / §8 — precedence rule, explicit not learned:
        # most severe (lowest ctas_level) first, regardless of traversal order.
        red_flags.sort(key=lambda rf: rf.ctas_level)
        return GraphContext(matched=True, complaint_name=complaint_name, red_flags=red_flags)

    def debug_all_matches(self, text: str) -> list[str]:
        """Eval-only introspection for Track A's Recall@k metric (backend/
        scripts/graphrag_eval/run_track_a_retrieval.py): every complaint
        (ctas_alias) with any surviving red-flag rows, not just the one
        _lookup() selects as most specific. Never called from the request
        path — LLMAgent only calls get_symptom_graph_context()."""
        surviving = self._resolve_surviving_mappings(text)
        return [mapping.ctas_alias for mapping, _, _ in surviving]

    def _traverse_all_anchors(self, candidate_ids: list[str]) -> dict[str, list[dict]]:
        """Groups ANCHOR_MAPPINGS by max_depth and issues one batched query per
        distinct depth (C2 fix) instead of one query per anchor. Returns rows
        keyed by anchor_id so _lookup() can reassemble them in ANCHOR_MAPPINGS's
        own order."""
        anchors_by_depth: dict[int, list[str]] = defaultdict(list)
        for mapping in ANCHOR_MAPPINGS:
            anchors_by_depth[mapping.max_depth].append(mapping.anchor_concept_id)

        rows_by_anchor: dict[str, list[dict]] = defaultdict(list)
        for max_depth, anchor_ids in anchors_by_depth.items():
            query, params = build_red_flag_traversal_query_batch(
                candidate_ids, anchor_ids, max_depth
            )
            for row in self._client.run_query(query, params):
                rows_by_anchor[row["anchor_id"]].append(row)
        return rows_by_anchor

    def _log_cross_symptom_clusters(self, rows_by_anchor: dict[str, list[dict]]) -> None:
        """Design §4 point 3 (disclosed deviation: single-pass, not a second
        query — see plan I9). Detection/logging only — does not affect
        severity classification, per the same restraint as I3."""
        anchors_by_cluster: dict[str, set[str]] = defaultdict(set)
        for anchor_id, rows in rows_by_anchor.items():
            for row in rows:
                cluster_name = row.get("cluster_name")
                if cluster_name:
                    anchors_by_cluster[cluster_name].add(anchor_id)

        for cluster_name, anchor_ids in anchors_by_cluster.items():
            if len(anchor_ids) >= 2:
                logger.info(
                    "cross_symptom_cluster_matched",
                    extra={"cluster_name": cluster_name, "anchor_count": len(anchor_ids)},
                )
