"""
backend/graph/snomed_neo4j/semantic_provider.py

Neo4jSemanticProvider — augments Neo4jSnomedProvider with a vector-based
candidate-generation step.

Why a subclass: only the candidate-generation step differs.  Every other
part of the request path (anchor traversal, red-flag filtering, severity
sorting, the never-raises contract) is inherited unchanged.  The override
point is _gather_candidates(): the base class runs a lexical Cypher query;
this class merges those hits with semantic (embedding + ANN) candidates from
a SemanticCandidateSource so that short or paraphrased messages that miss
exact lexical matches can still reach the graph traversal.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from graph.semantic.abstention import anchor_scores, decide
from graph.semantic.candidates import CandidateResult, SemanticCandidateSource
from graph.semantic.settings import SemanticSettings, load_settings
from graph.snomed_neo4j.provider import Neo4jSnomedProvider

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Long exact lexical matches are unambiguous; short ones are weak evidence.
# Read once at import so the constant is stable across requests.
LEXICAL_PRECEDENCE_MIN_LEN: int = int(os.environ.get("LEXICAL_PRECEDENCE_MIN_LEN", "12"))


class Neo4jSemanticProvider(Neo4jSnomedProvider):
    """Neo4jSnomedProvider extended with a semantic candidate-generation step.

    The only difference from the base class is _gather_candidates(): instead
    of relying solely on the lexical Cypher lookup, this provider merges those
    hits with semantic (embedding + ANN) candidates from a
    SemanticCandidateSource.  Ranking rule:

    - Exact lexical hits with matched_length >= LEXICAL_PRECEDENCE_MIN_LEN
      get score 1000 + length (always outrank semantic hits).
    - Short lexical hits (length < LEXICAL_PRECEDENCE_MIN_LEN) get
      score length / 1000 (weak evidence; a confident semantic hit beats them).
    - Accepted semantic candidates are merged at their raw similarity score.

    The base class's never-raises contract is preserved: any exception inside
    the semantic stage falls back to the lexical dict only.
    """

    def __init__(
        self,
        source: SemanticCandidateSource | None = None,
        settings: SemanticSettings | None = None,
    ) -> None:
        super().__init__()  # reads NEO4J_* env vars, opens driver

        if settings is None:
            try:
                settings = load_settings(os.environ)
            except ValueError:
                # Settings are optional — missing SEMANTIC_MODEL_DIR /
                # SEMANTIC_INDEX_DIR is expected during the disabled state.
                # Do NOT log the ValueError text: it may echo env-var values.
                logger.warning("semantic_settings_missing")
                settings = None

        self._settings: SemanticSettings | None = settings

        # Atomically store the semantic state as a single tuple so a request
        # thread never observes a half-updated state.
        self._semantic: tuple[SemanticCandidateSource | None, str, str, int] = (
            source,
            "ready" if source is not None else "disabled",
            "",
            0,
        )

    def attach_semantic(
        self,
        source: SemanticCandidateSource | None,
        state: str,
        model: str = "",
        rows: int = 0,
    ) -> None:
        """Swap the semantic source and status atomically.

        A single tuple assignment is atomic in CPython (the GIL guarantees
        no request thread can read a partially-updated state).  Called by the
        background loader task once the model and index are ready.
        """
        self._semantic = (source, state, model, rows)

    def semantic_status(self) -> dict:
        """Return the current semantic-layer status.

        Returns a dict with keys ``state``, ``model``, ``rows``.
        ``state`` is one of: ready | warming | building | stale | disabled.
        """
        _, state, model, rows = self._semantic
        return {"state": state, "model": model, "rows": rows}

    def _gather_candidates(self, user_message: str, all_text: str) -> dict[str, float]:
        """Merge lexical and semantic candidates into a single specificity dict.

        Lexical hits come from the base-class implementation (Cypher lookup on
        all_text).  Long hits are ranked above any semantic score; short hits
        are down-weighted.  Semantic hits are added only when the
        SemanticCandidateSource returns an accepted decision.

        Only the top-scoring anchor's candidates are merged (the runner-up and
        below are ignored) so that weak runner-up anchors do not distort the
        traversal.

        Any exception in the semantic stage is caught and logged; the lexical
        dict is always returned as a safe fallback (base-class contract: lookups
        never raise).
        """
        # Lexical pass — always runs.
        lexical = super()._gather_candidates(user_message, all_text)

        # Re-weight lexical hits: long = strong, short = weak evidence.
        scores: dict[str, float] = {}
        for concept_id, length in lexical.items():
            if length >= LEXICAL_PRECEDENCE_MIN_LEN:
                scores[concept_id] = 1000.0 + length
            else:
                scores[concept_id] = length / 1000.0

        # Semantic pass — only when a source and settings are attached.
        source, _, _, _ = self._semantic
        if source is None or self._settings is None:
            return scores

        try:
            # Query the semantic source with the CURRENT message only —
            # history is never passed to the embedder.
            result: CandidateResult = source.candidates(user_message)

            if result.skipped is None and result.candidates:
                sem_scores = anchor_scores(result.candidates)
                decision = decide(
                    sem_scores,
                    self._settings.score_threshold,
                    self._settings.gap_margin,
                )
                if decision.accepted:
                    # Find the top-scoring anchor and merge ONLY its candidates.
                    top_anchor = max(sem_scores, key=lambda a: sem_scores[a])
                    for c in result.candidates:
                        if c.anchor_id == top_anchor:
                            existing = scores.get(c.concept_id, 0.0)
                            scores[c.concept_id] = max(existing, c.score)
        except Exception:
            logger.exception("semantic_candidates_failed")
            # Degrade gracefully: return whatever lexical scores we built.

        return scores
