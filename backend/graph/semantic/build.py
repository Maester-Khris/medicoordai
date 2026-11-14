"""Index builder for the semantic vector index.

Fetches rows from Neo4j, embeds them, and writes the index atomically.
Supports a non-blocking ``ensure`` entry-point so the API starts immediately
while a low-priority background process handles the (potentially slow) build.
"""

from __future__ import annotations

import argparse
import dataclasses
import fcntl
import json
import logging
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Generator, Sequence

import numpy as np

from graph.semantic.embedder import Embedder, OnnxEmbedder
from graph.semantic.index import (
    IndexManifest,
    IndexRow,
    SemanticIndex,
    StaleIndexError,
    rows_digest,
    write_index,
)
from graph.semantic.settings import SemanticSettings, load_settings
from graph.snomed_neo4j.client import Neo4jClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cypher constants (the tests key a fake client on exact string identity)
# ---------------------------------------------------------------------------

Q_ENGLISH_ROWS = (
    'MATCH (c:SnomedConcept)-[:HAS_DESCRIPTION]->(d:Description) '
    'WHERE c.primary_anchor_id IS NOT NULL '
    'AND d.language_code = "en" '
    'AND coalesce(d.kind, "snomed") <> "lay" '
    'RETURN c.id AS concept_id, c.primary_anchor_id AS anchor_id, '
    'd.term AS text, d.is_fsn AS is_fsn'
)

Q_LAY_ROWS = (
    'MATCH (c:SnomedConcept)-[:HAS_DESCRIPTION]->(d:Description {kind: "lay"}) '
    'WHERE d.status IN $statuses '
    'RETURN c.id AS concept_id, c.id AS anchor_id, d.term AS text'
)

Q_GRAPH_BUILD = (
    'MATCH (c:SnomedConcept) '
    'RETURN max(c.source_release) AS release, count(c) AS concepts'
)

# ---------------------------------------------------------------------------
# Lay-rule status sets
# ---------------------------------------------------------------------------

LAY_STATUSES: dict[str, list[str]] = {
    "all": ["generated", "confirmed", "approved"],
    "confirmed": ["confirmed", "approved"],
    "approved": ["approved"],
}


# ---------------------------------------------------------------------------
# ModelCard
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class ModelCard:
    model_id: str
    pooling: str
    prefix: str
    max_len: int
    model_sha256: str


def load_model_card(model_dir: Path) -> ModelCard:
    """Read model metadata from model_dir/export.json.

    Raises FileNotFoundError if the file is absent.
    """
    export_path = model_dir / "export.json"
    if not export_path.exists():
        raise FileNotFoundError(f"export.json not found in {model_dir}")
    with open(export_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ModelCard(
        model_id=data["model_key"],
        pooling=data["pooling"],
        prefix=data["prefix"],
        max_len=data["max_len"],
        model_sha256=data["model_sha256"],
    )


def read_model_dim(model_dir: Path) -> int:
    """Read the embedding dimension from model_dir/export.json."""
    export_path = model_dir / "export.json"
    if not export_path.exists():
        raise FileNotFoundError(f"export.json not found in {model_dir}")
    with open(export_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return int(data["dim"])


# ---------------------------------------------------------------------------
# Row fetching
# ---------------------------------------------------------------------------

def fetch_index_rows(client: Neo4jClient, lay_rule: str) -> list[IndexRow]:
    """Fetch all index rows from Neo4j for the given lay_rule.

    English descriptions get kind "english"; FSN terms have their trailing
    semantic tag stripped (matching offline evaluation).  Lay descriptions
    get kind "lay".  Empty texts are dropped; duplicates on
    (concept_id, text.lower(), kind) are collapsed keeping first occurrence.
    Result is sorted by (concept_id, kind, text.lower()) for a deterministic digest.

    Raises ValueError for an unknown lay_rule.
    """
    if lay_rule not in LAY_STATUSES:
        raise ValueError(
            f"Unknown lay_rule {lay_rule!r}. Must be one of: {sorted(LAY_STATUSES)}"
        )

    statuses = LAY_STATUSES[lay_rule]

    english_raw = client.run_query(Q_ENGLISH_ROWS, {})
    lay_raw = client.run_query(Q_LAY_ROWS, {"statuses": statuses})

    rows: list[IndexRow] = []

    for rec in english_raw:
        text: str = rec["text"] or ""
        is_fsn: bool = bool(rec.get("is_fsn", False))
        if is_fsn:
            # Strip trailing semantic tag e.g. " (finding)" – matches offline eval
            text = re.sub(r"\s*\([^()]*\)$", "", text).strip()
        if not text:
            continue
        rows.append(IndexRow(
            concept_id=str(rec["concept_id"]),
            anchor_id=str(rec["anchor_id"]),
            text=text,
            kind="english",
        ))

    for rec in lay_raw:
        text = rec["text"] or ""
        if not text:
            continue
        rows.append(IndexRow(
            concept_id=str(rec["concept_id"]),
            anchor_id=str(rec["anchor_id"]),
            text=text,
            kind="lay",
        ))

    # Deduplicate on (concept_id, text.lower(), kind), keeping first occurrence
    seen: set[tuple[str, str, str]] = set()
    deduped: list[IndexRow] = []
    for row in rows:
        key = (row.concept_id, row.text.lower(), row.kind)
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    deduped.sort(key=lambda r: (r.concept_id, r.kind, r.text.lower()))
    return deduped


# ---------------------------------------------------------------------------
# Graph build identifier
# ---------------------------------------------------------------------------

def graph_build_id(client: Neo4jClient) -> str:
    """Return a string identifying the current graph snapshot.

    Format: "{release}:{concepts}".  Falls back to "none:0" when the query
    returns no rows or the release is None.
    """
    rows = client.run_query(Q_GRAPH_BUILD, {})
    if not rows:
        return "none:0"
    row = rows[0]
    release = row.get("release")
    concepts = row.get("concepts", 0)
    if release is None:
        return f"none:{concepts}"
    return f"{release}:{concepts}"


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def expected_manifest(
    rows: list[IndexRow],
    card: ModelCard,
    dim: int,
    settings: SemanticSettings,
    build_id: str,
) -> IndexManifest:
    """Construct the manifest that a freshly built index should carry."""
    return IndexManifest(
        model_id=card.model_id,
        pooling=card.pooling,
        prefix=card.prefix,
        lay_rule=settings.lay_rule,
        rows=len(rows),
        rows_sha256=rows_digest(rows),
        graph_build_id=build_id,
        model_sha256=card.model_sha256,
        dim=dim,
    )


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

def build_index(
    client: Neo4jClient,
    embedder: Embedder,
    settings: SemanticSettings,
    out_dir: Path,
    *,
    card: ModelCard | None = None,
) -> IndexManifest:
    """Embed all rows and write the index atomically.

    Zero rows raises ValueError.  An embedding failure leaves nothing behind
    because write_index is atomic (uses a tmp directory).
    """
    if card is None:
        card = load_model_card(settings.model_dir)

    rows = fetch_index_rows(client, settings.lay_rule)
    if not rows:
        raise ValueError("no rows to index")

    build_id = graph_build_id(client)

    # Embed each row exactly once, in order
    vectors: list[np.ndarray] = []
    dim: int | None = None
    for row in rows:
        vec = embedder.embed(row.text)
        if dim is None:
            dim = int(vec.shape[0])
        vectors.append(vec)

    assert dim is not None  # guaranteed by len(rows) > 0
    matrix = np.stack(vectors, axis=0).astype(np.float32)

    manifest = expected_manifest(rows, card, dim, settings, build_id)
    write_index(out_dir, rows, matrix, manifest)
    return manifest


# ---------------------------------------------------------------------------
# Index state
# ---------------------------------------------------------------------------

def index_state(
    settings: SemanticSettings,
    client: Neo4jClient,
    card: ModelCard,
    dim: int,
) -> str:
    """Return "missing", "ready", or "stale".  Client errors propagate."""
    if not settings.index_dir.exists():
        return "missing"

    rows = fetch_index_rows(client, settings.lay_rule)
    build_id = graph_build_id(client)
    manifest = expected_manifest(rows, card, dim, settings, build_id)

    try:
        SemanticIndex.load(settings.index_dir, manifest)
        return "ready"
    except StaleIndexError:
        return "stale"


# ---------------------------------------------------------------------------
# Build lock (non-blocking flock)
# ---------------------------------------------------------------------------

@contextmanager
def build_lock(index_dir: Path) -> Generator[bool, None, None]:
    """Exclusive, non-blocking lock around a build.

    Two replicas or a quick redeploy must not both spend minutes of CPU
    building the same index.  Yields True when the lock was acquired, False
    when another process already holds it.  Always releases and closes on exit.
    """
    lock_path = index_dir.parent / (index_dir.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "w")  # noqa: WPS515
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


# ---------------------------------------------------------------------------
# Background build spawning
# ---------------------------------------------------------------------------

def spawn_background_build(cmd: list[str]) -> None:
    """Launch a detached subprocess that runs the build command.

    stdout/stderr are inherited so the platform log shows build progress.
    """
    subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# ensure – called at API startup; ALWAYS returns 0
# ---------------------------------------------------------------------------

def ensure(
    settings: SemanticSettings,
    make_client: Callable[[], Neo4jClient],
    make_info: Callable[[], tuple[ModelCard, int]],
    spawn: Callable[[list[str]], None] = spawn_background_build,
) -> int:
    """Check index state and spawn a background build if needed.

    Always returns 0 – the API must start even when this fails.
    The start command uses ``;`` so a failure here never blocks the server.

    A low-priority detached child is spawned so the API and its health check
    start at once; the build can take minutes on a shared CPU.
    """
    client = None
    try:
        client = make_client()
        card, dim = make_info()
        state = index_state(settings, client, card, dim)
    except Exception as exc:
        logger.exception("ensure: failed to check index state (%s: %s)", type(exc).__name__, exc)
        return 0
    finally:
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass
    if state == "ready":
        return 0

    # Spawn a low-priority detached child so the API starts immediately.
    # ``nice -n 19`` keeps CPU impact minimal on shared infrastructure.
    try:
        spawn([
            "nice", "-n", "19",
            sys.executable, "-m", "graph.semantic.build", "run",
        ])
    except Exception as exc:
        logger.exception("ensure: failed to spawn background build (%s: %s)", type(exc).__name__, exc)

    return 0


# ---------------------------------------------------------------------------
# run – the actual build (called from the background child)
# ---------------------------------------------------------------------------

def run(
    settings: SemanticSettings,
    make_client: Callable[[], Neo4jClient],
    make_info: Callable[[], tuple[ModelCard, int]],
    make_embedder: Callable[[ModelCard], Embedder],
) -> int:
    """Build the index under a non-blocking lock.

    Returns 0 on success or when another build already holds the lock.
    Returns 1 on any exception (never raises).
    """
    with build_lock(settings.index_dir) as got_lock:
        if not got_lock:
            logger.info("another build is running")
            return 0
        try:
            client = make_client()
            card, dim = make_info()
            embedder = make_embedder(card)
            if hasattr(embedder, "warm_up"):
                embedder.warm_up()
            manifest = build_index(client, embedder, settings, settings.index_dir, card=card)
            logger.info(
                "build complete: %d rows, model=%s", manifest.rows, manifest.model_id
            )
            return 0
        except Exception as exc:
            logger.exception("build failed (%s: %s)", type(exc).__name__, exc)
            return 1


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ``python -m graph.semantic.build ensure|run``."""
    parser = argparse.ArgumentParser(prog="graph.semantic.build")
    parser.add_argument("command", choices=["ensure", "run"])
    args = parser.parse_args(argv)

    # Settings loading may fail (missing env vars); catch for ensure only.
    if args.command == "ensure":
        try:
            settings = load_settings(os.environ)
        except Exception as exc:
            logger.exception("ensure: failed to load settings (%s: %s)", type(exc).__name__, exc)
            return 0

        def make_client() -> Neo4jClient:
            return Neo4jClient(
                os.environ["NEO4J_URI"],
                (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            )

        d = settings.model_dir

        def make_info() -> tuple[ModelCard, int]:
            return load_model_card(d), read_model_dim(d)

        return ensure(settings, make_client, make_info)

    # command == "run"
    settings = load_settings(os.environ)

    def make_client() -> Neo4jClient:
        return Neo4jClient(
            os.environ["NEO4J_URI"],
            (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )

    d = settings.model_dir

    def make_info() -> tuple[ModelCard, int]:
        return load_model_card(d), read_model_dim(d)

    def make_embedder(card: ModelCard) -> Embedder:
        return OnnxEmbedder(
            settings.model_dir,
            settings,
            card.pooling,
            card.prefix,
            card.max_len,
        )

    return run(settings, make_client, make_info, make_embedder)


if __name__ == "__main__":
    raise SystemExit(main())
