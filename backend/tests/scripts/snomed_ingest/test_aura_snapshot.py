import subprocess

from scripts.snomed_ingest.aura_snapshot import SnapshotResult, take_snapshot


def _done(returncode=0, stdout="", stderr=""):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def test_success_returns_ok():
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "snapshot created", "")

    result = take_snapshot("abc123", run=run)
    assert result.ok is True and "snapshot created" in result.detail
    assert seen == [["aura-cli", "instance", "snapshot", "create", "--instance-id", "abc123"]]


def test_missing_cli_returns_manual_instruction():
    def run(cmd, **kw):
        raise FileNotFoundError("aura-cli")

    result = take_snapshot("abc123", run=run)
    assert result.ok is False and "Take snapshot" in result.detail


def test_nonzero_exit_returns_failure_detail_without_raising():
    result = take_snapshot("abc123", run=_done(returncode=2, stderr="plan does not allow snapshots"))
    assert result.ok is False
    assert "plan does not allow snapshots" in result.detail and "Take snapshot" in result.detail


def test_timeout_is_reported_not_raised():
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    result = take_snapshot("abc123", run=run)
    assert result.ok is False and "Take snapshot" in result.detail
    assert isinstance(result, SnapshotResult)
