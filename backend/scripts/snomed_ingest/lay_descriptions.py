"""Lay description loading and selection for semantic search indexing.

The lay descriptions data file is designed as a reviewable dataset where human
reviewers can audit, approve, or reject patient-facing lay phrases that feed the
SNOMED semantic index. Each phrase transitions through statuses (generated ->
confirmed -> approved / rejected), and downstream consumers use selection rules
("all", "confirmed", "approved") to control index strictness.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


VALID_STATUSES: frozenset[str] = frozenset(
    {"generated", "confirmed", "rejected", "approved"}
)


@dataclass(frozen=True)
class LayPhrase:
    anchor_id: str
    text: str
    source: str
    status: str

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"Unknown status '{self.status}'. Must be one of: {sorted(VALID_STATUSES)}"
            )


def load_lay_descriptions(
    path: Path, valid_anchor_ids: Collection[str]
) -> list[LayPhrase]:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Invalid lay descriptions file: version must be 1")

    phrases_raw = data.get("phrases")
    if not isinstance(phrases_raw, list):
        raise ValueError("Invalid lay descriptions file: 'phrases' must be a list")

    seen: set[tuple[str, str]] = set()
    result: list[LayPhrase] = []

    for item in phrases_raw:
        if not isinstance(item, dict):
            raise ValueError("Each phrase entry must be a dictionary")

        if "anchor_id" not in item:
            raise ValueError("Missing 'anchor_id' in phrase entry")
        anchor_id = str(item["anchor_id"])
        if anchor_id not in valid_anchor_ids:
            raise ValueError(f"Unknown anchor_id: {anchor_id}")

        if "status" not in item:
            raise ValueError("Missing 'status' in phrase entry")
        status = str(item["status"])
        if status not in VALID_STATUSES:
            raise ValueError(f"Unknown status: {status}")

        if "text" not in item:
            raise ValueError("Missing 'text' in phrase entry")
        text = str(item["text"]).strip()
        words = text.split()
        if len(words) < 2:
            continue

        dedup_key = (anchor_id, text.lower())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        result.append(
            LayPhrase(
                anchor_id=anchor_id,
                text=text,
                source=str(item.get("source", "")),
                status=status,
            )
        )

    return result


def select_for_index(phrases: Sequence[LayPhrase], rule: str) -> list[LayPhrase]:
    if rule == "all":
        return [p for p in phrases if p.status != "rejected"]
    elif rule == "confirmed":
        return [p for p in phrases if p.status in {"confirmed", "approved"}]
    elif rule == "approved":
        return [p for p in phrases if p.status == "approved"]
    else:
        raise ValueError(f"Unknown selection rule: {rule}")


def lay_description_id(anchor_id: str, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"lay:{anchor_id}:{digest}"
