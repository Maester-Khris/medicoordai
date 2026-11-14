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
import threading
import time
from typing import TYPE_CHECKING, Callable

from graph.semantic.abstention import anchor_scores, decide
from graph.semantic.build import ModelCard, OnnxEmbedder, load_model_card
from graph.semantic.candidates import CandidateResult, SemanticCandidateSource
from graph.semantic.index import SemanticIndex, StaleIndexError, read_manifest
from graph.semantic.settings import SemanticSettings, load_settings
from graph.snomed_neo4j.provider import Neo4jSnomedProvider

if TYPE_CHECKING:
    from graph.semantic.embedder import Embedder

logger = logging.getLogger(__name__)

# Long exact lexical matches are unambiguous; short ones are weak evidence.
# Read once at import so the constant is stable across requests.
LEXICAL_PRECEDENCE_MIN_LEN: int = int(os.environ.get("LEXICAL_PRECEDENCE_MIN_LEN", "12"))


def _default_embedder_factory(settings: SemanticSettings, card: ModelCard) -> "Embedder":
    """Build an OnnxEmbedder from settings and model card."""
    return OnnxEmbedder(
        settings.model_dir,
        settings,
        card.pooling,
        card.prefix,
        card.max_len,
    )


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
        *,
        autoload: bool = False,
        embedder_factory: Callable[[SemanticSettings, ModelCard], "Embedder"] | None = None,
        clock: Callable[[], float] = time.monotonic,
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

        # Embedder factory — defaults to building OnnxEmbedder.
        self._embedder_factory: Callable[[SemanticSettings, ModelCard], "Embedder"] = (
            embedder_factory if embedder_factory is not None else _default_embedder_factory
        )

        # Embedder instance (set by initialise()).
        self._embedder: "Embedder | None" = None

        # Last successfully loaded manifest (used to detect changes).
        self._loaded_manifest: object = None  # IndexManifest | None

        # Timestamp of the last reload compatibility check (injected clock).
        self._last_reload_check: float | None = None

        # How many seconds between reload checks (env-configurable, never logged).
        self._reload_s: float = float(os.environ.get("SEMANTIC_RELOAD_S", "60"))

        # Lock that serialises reload attempts; acquire(blocking=False) so
        # a health poll never blocks a concurrent reload thread.
        self._reload_lock: threading.Lock = threading.Lock()

        # Keep the model card after initialise() for compatibility checks.
        self._card: ModelCard | None = None

        # Injected clock for reload rate-limiting.
        self._clock: Callable[[], float] = clock

        # If autoload is requested and we have settings but no source, start a
        # daemon thread to run initialise() without blocking the constructor.
        if autoload and source is None and settings is not None:
            # Mark as warming before the thread starts so callers see a
            # consistent state immediately.
            self._semantic = (None, "warming", "", 0)
            t = threading.Thread(target=self.initialise, name="semantic-init", daemon=True)
            t.start()

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

    def initialise(self) -> None:
        """Load the embedder and perform an initial index reload.

        Public, synchronous, NEVER raises.  Leaves the provider lexical-only
        (state "disabled") on any failure.  On success without an index the
        state is "building"; once an index is loaded the state becomes "ready".
        """
        if self._settings is None:
            logger.warning("semantic_init_skipped: no settings")
            self._semantic = (None, "disabled", "", 0)
            return

        try:
            card = load_model_card(self._settings.model_dir)
            self._card = card
            embedder = self._embedder_factory(self._settings, card)
            embedder.warm_up()
            self._embedder = embedder

            # No index attached yet — announce building state.
            source, _, _, _ = self._semantic
            if source is None:
                self.attach_semantic(None, "building", card.model_id, 0)

            # Try to load an existing index immediately.
            self.maybe_reload(force=True)
        except Exception:
            logger.exception("semantic_init_failed")
            # Leave the provider lexical-only; wipe any warming/building state.
            self._semantic = (None, "disabled", "", 0)

    def maybe_reload(self, force: bool = False) -> bool:
        """Check whether a newer compatible index is available and load it.

        NEVER raises.  Returns True when a new index was swapped in.

        Why only cheap checks here: the staleness of the index against the
        graph is handled when the index is built/ensured; here only manifest
        compatibility and shape integrity are checked so a health poll stays
        fast.
        """
        try:
            embedder = self._embedder
            # Cannot reload without a warmed embedder.
            if embedder is None or not getattr(embedder, "ready", False):
                return False

            if self._settings is None:
                return False

            now = self._clock()

            # Rate-limit checks unless forced.
            if not force:
                if (
                    self._last_reload_check is not None
                    and (now - self._last_reload_check) < self._reload_s
                ):
                    return False

            # Record the check timestamp before we do any real work so that a
            # long load doesn't create an artificially short gap to the next
            # check.
            self._last_reload_check = now

            # Non-blocking lock — if another thread is already reloading, skip.
            if not self._reload_lock.acquire(blocking=False):
                return False

            try:
                return self._do_reload(embedder)
            finally:
                self._reload_lock.release()
        except Exception:
            logger.exception("maybe_reload_failed")
            return False

    def _do_reload(self, embedder: "Embedder") -> bool:
        """Inner reload logic executed under the reload lock."""
        try:
            manifest = read_manifest(self._settings.index_dir)
        except StaleIndexError:
            # Index directory absent or corrupt — keep whatever we have now.
            return False

        # Nothing changed since last load.
        if manifest == self._loaded_manifest:
            return False

        # Cheap compatibility check: the index must have been built for this
        # exact model configuration.  Any mismatch means the on-disk index is
        # for a different model/settings combination.
        # Logged at warning WITHOUT values to avoid leaking env-sourced data.
        card = self._card
        if card is None:
            return False

        compatible = (
            manifest.model_id == card.model_id
            and manifest.pooling == card.pooling
            and manifest.prefix == card.prefix
            and manifest.model_sha256 == card.model_sha256
            and manifest.dim == getattr(embedder, "dim", None)
            and manifest.lay_rule == self._settings.lay_rule
        )
        if not compatible:
            logger.warning("semantic_reload_skipped: index built for different model/settings")
            return False

        # Load and validate shape/row counts.
        try:
            index = SemanticIndex.load(self._settings.index_dir, manifest)
        except StaleIndexError:
            # Keep the old index.
            return False

        # Swap atomically: remember the old source so we can close it after.
        old_source, _, _, _ = self._semantic
        new_source = SemanticCandidateSource(embedder, index, self._settings)
        self.attach_semantic(new_source, "ready", card.model_id, manifest.rows)
        self._loaded_manifest = manifest

        # Close the old source after the swap so no request thread holds a
        # reference to it after this point.
        if old_source is not None:
            try:
                old_source.close()
            except Exception:
                pass

        return True

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
