"""Versioned vector index with atomic write and stale detection."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import List, Sequence

import numpy as np


@dataclasses.dataclass(frozen=True)
class IndexRow:
    concept_id: str
    anchor_id: str
    text: str
    kind: str


@dataclasses.dataclass(frozen=True)
class Hit:
    row: IndexRow
    score: float


@dataclasses.dataclass(frozen=True)
class IndexManifest:
    model_id: str
    dim: int
    pooling: str
    prefix: str
    lay_rule: str
    rows: int
    rows_sha256: str
    graph_build_id: str
    model_sha256: str


class StaleIndexError(Exception):
    """Raised when an index is missing, corrupt, or stale."""


def read_manifest(index_dir: Path) -> IndexManifest:
    """Read and parse manifest.json from index_dir.

    Raises StaleIndexError when the directory or file is missing, the JSON is
    unreadable or corrupt, or any required field is absent or of the wrong type.
    """
    index_path = Path(index_dir)
    if not index_path.is_dir():
        raise StaleIndexError(f"Index directory missing: {index_path}")

    manifest_path = index_path / "manifest.json"
    if not manifest_path.is_file():
        raise StaleIndexError(f"Missing manifest file: {manifest_path}")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise StaleIndexError(f"Cannot read manifest: {exc}") from exc

    if not isinstance(data, dict):
        raise StaleIndexError("Manifest is not a JSON object")

    # Validate that all required fields are present and constructible.
    try:
        return IndexManifest(**data)
    except (TypeError, KeyError, ValueError) as exc:
        raise StaleIndexError(f"Manifest has unknown or missing fields: {exc}") from exc


def rows_digest(rows: Sequence[IndexRow]) -> str:
    """Compute sha256 hex digest of canonical JSON of rows in order."""
    data = [dataclasses.asdict(r) for r in rows]
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_index(
    index_dir: Path,
    rows: Sequence[IndexRow],
    matrix: np.ndarray,
    manifest: IndexManifest,
) -> None:
    """Write vector index atomically to index_dir.

    A reader must never see a half-written index: it either gets the old
    complete one or the new complete one.
    """
    if matrix.shape != (len(rows), manifest.dim) or manifest.rows != len(rows):
        raise ValueError(
            f"Shape or count mismatch: matrix.shape={matrix.shape}, "
            f"len(rows)={len(rows)}, manifest.dim={manifest.dim}, "
            f"manifest.rows={manifest.rows}"
        )

    index_path = Path(index_dir)
    tmp_dir = Path(str(index_path) + ".tmp")
    old_dir = Path(str(index_path) + ".old")

    if tmp_dir.is_dir():
        shutil.rmtree(tmp_dir)
    elif tmp_dir.exists():
        tmp_dir.unlink()

    tmp_dir.mkdir(parents=True, exist_ok=True)

    matrix_f32 = np.asarray(matrix, dtype=np.float32)
    matrix_path = tmp_dir / "matrix.npy"
    with open(matrix_path, "wb") as f:
        np.save(f, matrix_f32)
        f.flush()
        os.fsync(f.fileno())

    rows_path = tmp_dir / "rows.json"
    rows_dicts = [dataclasses.asdict(r) for r in rows]
    with open(rows_path, "w", encoding="utf-8") as f:
        json.dump(rows_dicts, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    manifest_path = tmp_dir / "manifest.json"
    manifest_dict = dataclasses.asdict(manifest)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_dict, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    dir_fd = os.open(tmp_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    if index_path.exists():
        if old_dir.is_dir():
            shutil.rmtree(old_dir)
        elif old_dir.exists():
            old_dir.unlink()

        os.rename(index_path, old_dir)
        try:
            os.rename(tmp_dir, index_path)
        except BaseException:
            try:
                os.rename(old_dir, index_path)
            except Exception:
                pass
            raise

        if old_dir.is_dir():
            shutil.rmtree(old_dir)
        elif old_dir.exists():
            old_dir.unlink()
    else:
        os.rename(tmp_dir, index_path)


class SemanticIndex:
    """In-memory semantic vector index for fast similarity search."""

    def __init__(
        self,
        rows: List[IndexRow],
        matrix: np.ndarray,
        manifest: IndexManifest,
    ) -> None:
        self.rows: List[IndexRow] = rows
        self.matrix: np.ndarray = matrix
        self.manifest: IndexManifest = manifest

    @classmethod
    def load(cls, index_dir: Path, expected: IndexManifest) -> SemanticIndex:
        try:
            index_path = Path(index_dir)
            if not index_path.is_dir():
                raise StaleIndexError(f"Index directory missing: {index_path}")

            manifest_path = index_path / "manifest.json"
            rows_path = index_path / "rows.json"
            matrix_path = index_path / "matrix.npy"

            if not manifest_path.is_file():
                raise StaleIndexError(f"Missing manifest file: {manifest_path}")
            if not rows_path.is_file():
                raise StaleIndexError(f"Missing rows file: {rows_path}")
            if not matrix_path.is_file():
                raise StaleIndexError(f"Missing matrix file: {matrix_path}")

            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_dict = json.load(f)
            if not isinstance(manifest_dict, dict):
                raise StaleIndexError("Manifest is not a JSON object")

            manifest = IndexManifest(**manifest_dict)

            if manifest != expected:
                for field in dataclasses.fields(IndexManifest):
                    actual_val = getattr(manifest, field.name)
                    expected_val = getattr(expected, field.name)
                    if actual_val != expected_val:
                        raise StaleIndexError(
                            f"Manifest mismatch on field '{field.name}': "
                            f"expected {expected_val!r}, got {actual_val!r}"
                        )
                raise StaleIndexError("Manifest does not match expected")

            with open(rows_path, "r", encoding="utf-8") as f:
                rows_data = json.load(f)
            if not isinstance(rows_data, list):
                raise StaleIndexError("rows.json must contain a list")

            rows = [IndexRow(**r) for r in rows_data]

            matrix = np.load(matrix_path, allow_pickle=False)
            if matrix.dtype != np.float32:
                matrix = matrix.astype(np.float32)

            if matrix.shape != (manifest.rows, manifest.dim):
                raise StaleIndexError(
                    f"Matrix shape {matrix.shape} does not match manifest "
                    f"({manifest.rows}, {manifest.dim})"
                )

            if len(rows) != manifest.rows:
                raise StaleIndexError(
                    f"Row count {len(rows)} does not match manifest.rows {manifest.rows}"
                )

            return cls(rows=rows, matrix=matrix, manifest=manifest)
        except StaleIndexError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise StaleIndexError(f"Error loading index: {e}") from e

    def search(self, vector: np.ndarray, top_n: int) -> List[Hit]:
        if top_n <= 0 or len(self.rows) == 0:
            return []

        vec = np.asarray(vector, dtype=np.float32)
        scores = self.matrix @ vec

        k = min(top_n, len(self.rows))
        if k < len(self.rows):
            candidate_indices = np.argpartition(scores, -k)[-k:]
        else:
            candidate_indices = np.arange(len(self.rows))

        sorted_indices = candidate_indices[np.argsort(-scores[candidate_indices])]
        return [
            Hit(row=self.rows[int(i)], score=float(scores[i]))
            for i in sorted_indices
        ]
