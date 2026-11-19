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


def test_a_failed_nightly_run_opens_an_issue() -> None:
    job = _load()["jobs"]["eval-gate"]
    assert job["permissions"]["issues"] == "write"
    step = next(s for s in job["steps"] if "issue" in s.get("name", "").lower())
    assert "schedule" in step["if"] and "failure()" in step["if"]
    assert "gh issue create" in step["run"]
