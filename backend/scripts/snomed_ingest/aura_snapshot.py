"""Aura instance snapshot utility.

Failure to take a snapshot returns a SnapshotResult with ok=False rather than
raising an exception. A snapshot is a safety net taken before a risky rebuild;
the caller decides whether to proceed, and a missing CLI on the Free plan is an
expected case.
"""

from dataclasses import dataclass
import subprocess
from typing import Callable

MANUAL_INSTRUCTION = "Use the Aura console's Take snapshot button for this instance instead."


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    detail: str


def take_snapshot(
    instance_id: str,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> SnapshotResult:
    """Take a snapshot of an Aura instance.

    Failure is returned as a SnapshotResult(ok=False, detail=...) rather than
    raising an exception: a snapshot is a safety net taken before a risky
    rebuild; the caller decides whether to proceed, and a missing CLI on the
    Free plan is an expected case.
    """
    cmd = ["aura-cli", "instance", "snapshot", "create", "--instance-id", instance_id]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        cause = f"Command timed out after {exc.timeout} seconds"
        return SnapshotResult(ok=False, detail=f"{cause}. {MANUAL_INSTRUCTION}")
    except FileNotFoundError as exc:
        cause = f"CLI missing ({exc})"
        return SnapshotResult(ok=False, detail=f"{cause}. {MANUAL_INSTRUCTION}")
    except OSError as exc:
        cause = f"OS error ({exc})"
        return SnapshotResult(ok=False, detail=f"{cause}. {MANUAL_INSTRUCTION}")
    except Exception as exc:
        cause = f"Execution failed ({exc})"
        return SnapshotResult(ok=False, detail=f"{cause}. {MANUAL_INSTRUCTION}")

    if proc.returncode == 0:
        stdout = (proc.stdout or "").strip()
        return SnapshotResult(ok=True, detail=stdout or "snapshot requested")

    stderr = (proc.stderr or "").strip()
    cause = f"aura-cli exited with code {proc.returncode}"
    if stderr:
        cause = f"{cause}: {stderr}"
    return SnapshotResult(ok=False, detail=f"{cause}. {MANUAL_INSTRUCTION}")
