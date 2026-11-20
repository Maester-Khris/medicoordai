from scripts.snomed_ingest import graph_health as gh
from scripts.snomed_ingest.graph_health import HealthReport, collect, component_sizes, format_report, over_limit


def test_component_sizes_on_two_islands():
    edges = [("a", "b"), ("b", "c"), ("x", "y")]
    assert component_sizes(edges) == [3, 2]
    assert component_sizes([]) == []


class FakeClient:
    """Answers by the exact query text, so a changed or missing query fails loudly."""

    def __init__(self, answers):
        self.answers = answers
        self.seen = []

    def run_query(self, query, params):
        self.seen.append((query, params))
        return self.answers[query]


def test_collect_maps_cypher_rows_into_the_report():
    client = FakeClient({
        gh.Q_TOTALS: [{"nodes": 1000, "relationships": 2000}],
        gh.Q_DEGREE: [{"max_degree": 40, "median_degree": 4.0}],
        gh.Q_MAX_IS_A_IN: [{"n": 12}],
        gh.Q_MAX_ASKS_IN: [{"n": 2}],
        gh.Q_MAX_RED_FLAG_OUT: [{"n": 7}],
        gh.Q_IS_A_EDGES: [{"child": "a", "parent": "b"}, {"child": "c", "parent": "b"}, {"child": "x", "parent": "y"}],
        gh.Q_ANCHORS_LOADED: [{"n": 2}],
    })
    r = collect(client, ["a", "b", "z"], collisions=5)
    assert r == HealthReport(nodes=1000, relationships=2000, max_over_median_degree=10.0, max_is_a_in_degree=12,
                             max_asks_in_degree=2, max_red_flag_out_degree=7, component_count=2,
                             largest_component_share=0.6, anchors_loaded=2, anchors_total=3, collisions=5)
    anchors_query = next(p for q, p in client.seen if q == gh.Q_ANCHORS_LOADED)
    assert anchors_query == {"ids": ["a", "b", "z"]}


def _report(**overrides):
    base = dict(nodes=1000, relationships=2000, max_over_median_degree=10.0, max_is_a_in_degree=12, max_asks_in_degree=2,
                max_red_flag_out_degree=7, component_count=1, largest_component_share=1.0, anchors_loaded=3, anchors_total=3,
                collisions=0)
    base.update(overrides)
    return HealthReport(**base)


def test_format_report_flags_values_over_limit():
    ok = format_report(_report())
    assert "over" not in ok and over_limit(_report()) == []
    bad_report = _report(max_asks_in_degree=9, nodes=60000, max_over_median_degree=80.0)
    bad = format_report(bad_report)
    assert "max ASKS in-degree" in bad and "9" in bad
    assert sum(line.rstrip().endswith("over") for line in bad.splitlines()) == 3
    assert sorted(over_limit(bad_report)) == ["max ASKS in-degree", "max/median degree", "nodes"]
