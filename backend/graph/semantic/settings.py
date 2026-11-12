import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class SemanticSettings:
    model_dir: Path
    index_dir: Path
    score_threshold: float
    gap_margin: float
    lay_rule: str
    threads: int = 1
    deadline_ms: int = 250
    top_n: int = 20
    breaker_failures: int = 5
    breaker_cooldown_s: float = 30.0
    model_sha256: str | None = None  # pin of the model file actually loaded; None = unpinned (warns)

    def __post_init__(self) -> None:
        if not isinstance(self.model_dir, Path):
            object.__setattr__(self, "model_dir", Path(self.model_dir))
        if not isinstance(self.index_dir, Path):
            object.__setattr__(self, "index_dir", Path(self.index_dir))


def load_settings(env: Mapping[str, str]) -> SemanticSettings:
    if "SEMANTIC_MODEL_DIR" not in env or not env["SEMANTIC_MODEL_DIR"]:
        raise ValueError("SEMANTIC_MODEL_DIR is required")
    if "SEMANTIC_INDEX_DIR" not in env or not env["SEMANTIC_INDEX_DIR"]:
        raise ValueError("SEMANTIC_INDEX_DIR is required")

    model_dir = Path(env["SEMANTIC_MODEL_DIR"])
    index_dir = Path(env["SEMANTIC_INDEX_DIR"])

    raw_threads = env.get("EMBED_THREADS", "1")
    try:
        threads = int(raw_threads)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid EMBED_THREADS: {raw_threads!r}") from e
    if threads < 1:
        raise ValueError("EMBED_THREADS must be >= 1")

    raw_deadline = env.get("EMBED_DEADLINE_MS", "250")
    try:
        deadline_ms = int(raw_deadline)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid EMBED_DEADLINE_MS: {raw_deadline!r}") from e
    if deadline_ms <= 0:
        raise ValueError("EMBED_DEADLINE_MS must be > 0")

    raw_top_n = env.get("SEMANTIC_TOP_N", "20")
    try:
        top_n = int(raw_top_n)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid SEMANTIC_TOP_N: {raw_top_n!r}") from e
    if top_n <= 0:
        raise ValueError("SEMANTIC_TOP_N must be > 0")

    # SEMANTIC_SCORE_THRESHOLD and SEMANTIC_GAP_MARGIN are UNCALIBRATED PLACEHOLDERS
    # until the calibration task.
    raw_threshold = env.get("SEMANTIC_SCORE_THRESHOLD", "0.5")
    try:
        score_threshold = float(raw_threshold)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid SEMANTIC_SCORE_THRESHOLD: {raw_threshold!r}") from e

    raw_margin = env.get("SEMANTIC_GAP_MARGIN", "0.02")
    try:
        gap_margin = float(raw_margin)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid SEMANTIC_GAP_MARGIN: {raw_margin!r}") from e

    lay_rule = env.get("SEMANTIC_LAY_RULE", "confirmed")
    if lay_rule not in ("all", "confirmed", "approved"):
        raise ValueError(f"SEMANTIC_LAY_RULE must be one of all|confirmed|approved, got {lay_rule!r}")

    raw_failures = env.get("SEMANTIC_BREAKER_FAILURES", "5")
    try:
        breaker_failures = int(raw_failures)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid SEMANTIC_BREAKER_FAILURES: {raw_failures!r}") from e
    if breaker_failures <= 0:
        raise ValueError("SEMANTIC_BREAKER_FAILURES must be > 0")

    raw_cooldown = env.get("SEMANTIC_BREAKER_COOLDOWN_S", "30.0")
    try:
        breaker_cooldown_s = float(raw_cooldown)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid SEMANTIC_BREAKER_COOLDOWN_S: {raw_cooldown!r}") from e
    if breaker_cooldown_s <= 0:
        raise ValueError("SEMANTIC_BREAKER_COOLDOWN_S must be > 0")

    raw_sha = env.get("SEMANTIC_MODEL_SHA256", "").strip().lower()
    if raw_sha and not re.fullmatch(r"[0-9a-f]{64}", raw_sha):
        raise ValueError("SEMANTIC_MODEL_SHA256 must be 64 hex characters (sha256 of the model file)")

    return SemanticSettings(
        model_dir=model_dir,
        index_dir=index_dir,
        score_threshold=score_threshold,
        gap_margin=gap_margin,
        lay_rule=lay_rule,
        threads=threads,
        deadline_ms=deadline_ms,
        top_n=top_n,
        breaker_failures=breaker_failures,
        breaker_cooldown_s=breaker_cooldown_s,
        model_sha256=raw_sha or None,
    )
