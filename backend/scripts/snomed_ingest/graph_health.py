"""
Graph health checks and advisory limit reporting for SNOMED CT Neo4j subgraph.

Advisory limits in this module are starting values reported rather than enforced.
Because the clinical subgraph is small, this report exists to detect hubs and
disconnected islands early during ingestion and development without breaking builds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Sequence

try:
    from graph.snomed_neo4j.client import Neo4jClient
except ImportError:  # pragma: no cover
    if TYPE_CHECKING:
        from graph.snomed_neo4j.client import Neo4jClient
    else:
        Neo4jClient = object  # type: ignore

# Read-only Cypher query constants
Q_TOTALS: str = (
    "MATCH (n) "
    "WITH count(n) AS nodes "
    "OPTIONAL MATCH ()-[r]->() "
    "RETURN nodes, count(r) AS relationships"
)

Q_DEGREE: str = (
    "MATCH (n) "
    "WITH COUNT { (n)--() } AS deg "
    "RETURN coalesce(max(deg), 0) AS max_degree, "
    "coalesce(percentileCont(deg, 0.5), 0.0) AS median_degree"
)

Q_MAX_IS_A_IN: str = (
    "MATCH (c:SnomedConcept) "
    "WITH COUNT { ()-[:IS_A]->(c) } AS in_degree "
    "RETURN coalesce(max(in_degree), 0) AS n"
)

Q_MAX_ASKS_IN: str = (
    "MATCH (q:FollowupQuestion) "
    "WITH COUNT { ()-[:ASKS]->(q) } AS in_degree "
    "RETURN coalesce(max(in_degree), 0) AS n"
)

Q_MAX_RED_FLAG_OUT: str = (
    "MATCH (c:SnomedConcept) "
    "WITH COUNT { (c)-[:HAS_RED_FLAG]->() } AS out_degree "
    "RETURN coalesce(max(out_degree), 0) AS n"
)

Q_IS_A_EDGES: str = (
    "MATCH (child:SnomedConcept)-[:IS_A]->(parent:SnomedConcept) "
    "RETURN child.id AS child, parent.id AS parent"
)

Q_ANCHORS_LOADED: str = (
    "MATCH (c:SnomedConcept) "
    "WHERE c.id IN $ids "
    "RETURN count(c) AS n"
)

# Advisory limits: metric display name -> limit value
ADVISORY_LIMITS: dict[str, int | float] = {
    "max/median degree": 50,
    "max IS_A in-degree": 50,
    "max ASKS in-degree": 5,
    "max HAS_RED_FLAG out-degree": 20,
    "nodes": 50_000,
    "relationships": 75_000,
}


@dataclass(frozen=True)
class HealthReport:
    nodes: int
    relationships: int
    max_over_median_degree: float
    max_is_a_in_degree: int
    max_asks_in_degree: int
    max_red_flag_out_degree: int
    component_count: int
    largest_component_share: float
    anchors_loaded: int
    anchors_total: int
    collisions: int


def component_sizes(edges: Iterable[tuple[str, str]]) -> list[int]:
    """Calculate connected component sizes for edges using union-find.

    Returns sizes in descending order.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        root = x
        while root in parent:
            root = parent[root]
        curr = x
        while curr in parent:
            nxt = parent[curr]
            parent[curr] = root
            curr = nxt
        return root

    def union(x: str, y: str) -> None:
        root_x = find(x)
        root_y = find(y)
        if root_x != root_y:
            parent[root_x] = root_y

    all_nodes: set[str] = set()
    for u, v in edges:
        all_nodes.add(u)
        all_nodes.add(v)
        union(u, v)

    if not all_nodes:
        return []

    counts: dict[str, int] = {}
    for node in all_nodes:
        root = find(node)
        counts[root] = counts.get(root, 0) + 1

    return sorted(counts.values(), reverse=True)


def collect(
    client: Neo4jClient,
    anchor_ids: Sequence[str],
    collisions: int = 0,
) -> HealthReport:
    """Collect graph health metrics using client and compute a HealthReport.

    Args:
        client: Neo4jClient instance for executing Cypher queries.
        anchor_ids: Sequence of anchor concept IDs expected to be loaded.
        collisions: Number of concepts reachable from more than one anchor,
            computed in Python at build time.

    Returns:
        HealthReport with summary metrics.
    """
    totals_res = client.run_query(Q_TOTALS, {})
    totals_row = totals_res[0] if totals_res else {"nodes": 0, "relationships": 0}
    nodes: int = int(totals_row.get("nodes", 0))
    relationships: int = int(totals_row.get("relationships", 0))

    deg_res = client.run_query(Q_DEGREE, {})
    deg_row = deg_res[0] if deg_res else {"max_degree": 0, "median_degree": 0.0}
    max_degree: float = float(deg_row.get("max_degree", 0))
    median_degree: float = float(deg_row.get("median_degree", 0.0))
    if median_degree <= 0.0:
        max_over_median_degree: float = max_degree
    else:
        max_over_median_degree = max_degree / median_degree

    max_is_a_res = client.run_query(Q_MAX_IS_A_IN, {})
    max_is_a_in_degree: int = int(max_is_a_res[0]["n"]) if max_is_a_res else 0

    max_asks_res = client.run_query(Q_MAX_ASKS_IN, {})
    max_asks_in_degree: int = int(max_asks_res[0]["n"]) if max_asks_res else 0

    max_red_flag_res = client.run_query(Q_MAX_RED_FLAG_OUT, {})
    max_red_flag_out_degree: int = int(max_red_flag_res[0]["n"]) if max_red_flag_res else 0

    edges_res = client.run_query(Q_IS_A_EDGES, {})
    edges = [(str(row["child"]), str(row["parent"])) for row in edges_res]
    sizes = component_sizes(edges)
    if sizes:
        component_count: int = len(sizes)
        total_size: int = sum(sizes)
        largest_component_share: float = sizes[0] / total_size if total_size > 0 else 0.0
    else:
        component_count = 0
        largest_component_share = 0.0

    anchors_param = anchor_ids if isinstance(anchor_ids, list) else list(anchor_ids)
    anchors_res = client.run_query(Q_ANCHORS_LOADED, {"ids": anchors_param})
    anchors_loaded: int = int(anchors_res[0]["n"]) if anchors_res else 0
    anchors_total: int = len(anchor_ids)

    return HealthReport(
        nodes=nodes,
        relationships=relationships,
        max_over_median_degree=max_over_median_degree,
        max_is_a_in_degree=max_is_a_in_degree,
        max_asks_in_degree=max_asks_in_degree,
        max_red_flag_out_degree=max_red_flag_out_degree,
        component_count=component_count,
        largest_component_share=largest_component_share,
        anchors_loaded=anchors_loaded,
        anchors_total=anchors_total,
        collisions=collisions,
    )


def over_limit(r: HealthReport) -> list[str]:
    """Return display names of limits exceeded, in advisory order."""
    metric_values: dict[str, int | float] = {
        "max/median degree": r.max_over_median_degree,
        "max IS_A in-degree": r.max_is_a_in_degree,
        "max ASKS in-degree": r.max_asks_in_degree,
        "max HAS_RED_FLAG out-degree": r.max_red_flag_out_degree,
        "nodes": r.nodes,
        "relationships": r.relationships,
    }
    return [name for name, limit in ADVISORY_LIMITS.items() if metric_values[name] > limit]


def format_report(r: HealthReport) -> str:
    """Format health report into display lines.

    Limited metrics appear first with limit and ok/over status.
    Informational lines follow without ok/over markers.
    """
    metric_values: dict[str, int | float] = {
        "max/median degree": r.max_over_median_degree,
        "max IS_A in-degree": r.max_is_a_in_degree,
        "max ASKS in-degree": r.max_asks_in_degree,
        "max HAS_RED_FLAG out-degree": r.max_red_flag_out_degree,
        "nodes": r.nodes,
        "relationships": r.relationships,
    }
    lines: list[str] = []
    for name, limit in ADVISORY_LIMITS.items():
        val = metric_values[name]
        status = "over" if val > limit else "ok"
        lines.append(f"{name}: {val} (limit {limit}) {status}")

    lines.append(f"components: {r.component_count} (largest share: {r.largest_component_share})")
    lines.append(f"anchors loaded: {r.anchors_loaded}/{r.anchors_total}")
    lines.append(f"collisions: {r.collisions}")
    return "\n".join(lines)
