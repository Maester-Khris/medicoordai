from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "eval-gate.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_the_gate_runs_nightly_on_demand_and_on_labelled_pull_requests() -> None:
    triggers = _load()[True]  # YAML reads the bare key `on` as True
    assert triggers["schedule"] == [{"cron": "17 6 * * *"}]
    assert "workflow_dispatch" in triggers and "pull_request" in triggers


def test_a_failed_first_pass_still_lets_the_retry_pass_run() -> None:
    steps = _load()["jobs"]["eval-gate"]["steps"]
    script = next(s["run"] for s in steps if s.get("name") == "Run the sentinel conversations")
    assert "for attempt in 1 2" in script and "|| true" in script
