"""Bounded graph traversal with nearest-anchor primary assignment for SNOMED concepts.

Traverses a bounded graph of SNOMED concepts starting from curated anchors,
performing nearest-anchor primary assignment via breadth-first search.
Concepts are assigned to the closest anchor within the anchor's configured depth;
ties break toward the earlier anchor in input order.
"""

from collections import deque
from dataclasses import dataclass
from typing import Mapping, Sequence

BLOCKED_ROOTS: frozenset[str] = frozenset({"404684003", "95320005", "66091009"})
DEFAULT_INDEX_DEPTH: int = 1
BROAD_CONCEPT_THRESHOLD: int = 200
CATCH_ALL_NAMES: tuple[str, ...] = (
    "Other skin conditions",
    "Congenital problem in children",
    "Post-operative complications",
)


@dataclass(frozen=True)
class AnchorSpec:
    anchor_id: str
    name: str
    depth: int


@dataclass(frozen=True)
class Assignment:
    concept_anchor: dict[str, str]
    concept_depth: dict[str, int]
    ties: dict[str, tuple[str, ...]]
    broad: tuple[str, ...]


def resolve_index_depth(
    name: str, anchor_id: str, overrides: Mapping[str, int]
) -> int:
    """Resolve indexing depth with override precedence, catch-all default 0, or default depth."""
    if anchor_id in overrides:
        return overrides[anchor_id]
    if name in CATCH_ALL_NAMES:
        return 0
    return DEFAULT_INDEX_DEPTH


def assign_concepts(
    children: Mapping[str, Sequence[str]], anchors: Sequence[AnchorSpec]
) -> Assignment:
    """Assign concepts to nearest anchors within bounded BFS depth."""
    broad: list[str] = []
    for anchor in anchors:
        if anchor.anchor_id in BLOCKED_ROOTS:
            continue
        visited_closure: set[str] = {anchor.anchor_id}
        closure_queue: deque[tuple[str, int]] = deque([(anchor.anchor_id, 0)])
        while closure_queue:
            curr, d = closure_queue.popleft()
            if d < 2:
                for child in children.get(curr) or ():
                    if child not in BLOCKED_ROOTS and child not in visited_closure:
                        visited_closure.add(child)
                        closure_queue.append((child, d + 1))
        if len(visited_closure) > BROAD_CONCEPT_THRESHOLD:
            if anchor.anchor_id not in broad:
                broad.append(anchor.anchor_id)

    min_depth: dict[str, int] = {}
    tied_anchors: dict[str, list[str]] = {}

    for anchor in anchors:
        if anchor.anchor_id in BLOCKED_ROOTS:
            continue

        seen_for_anchor: set[str] = {anchor.anchor_id}
        queue: deque[tuple[str, int]] = deque([(anchor.anchor_id, 0)])

        while queue:
            curr, d = queue.popleft()

            if curr not in min_depth or d < min_depth[curr]:
                min_depth[curr] = d
                tied_anchors[curr] = [anchor.anchor_id]
            elif d == min_depth[curr]:
                if anchor.anchor_id not in tied_anchors[curr]:
                    tied_anchors[curr].append(anchor.anchor_id)

            if d < anchor.depth:
                for child in children.get(curr) or ():
                    if child not in BLOCKED_ROOTS and child not in seen_for_anchor:
                        seen_for_anchor.add(child)
                        queue.append((child, d + 1))

    concept_anchor: dict[str, str] = {}
    concept_depth: dict[str, int] = {}
    ties: dict[str, tuple[str, ...]] = {}

    for concept, anchor_ids in tied_anchors.items():
        concept_anchor[concept] = anchor_ids[0]
        concept_depth[concept] = min_depth[concept]
        if len(anchor_ids) > 1:
            ties[concept] = tuple(anchor_ids)

    return Assignment(
        concept_anchor=concept_anchor,
        concept_depth=concept_depth,
        ties=ties,
        broad=tuple(broad),
    )
