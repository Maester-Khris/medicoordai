"""
Run manifest: the configuration a checkpoint was produced under, written
beside the checkpoint before the first LLM call and checked on every resume,
so one checkpoint can never mix two models, prompts or checklist sets.

Pure stdlib and pure values — cli.py (Main) reads them off the live adapters
and passes them in, so the manifest cannot drift from what actually ran.
`providers` and `harness_git_commit` are recorded but not enforced on resume:
adding a leg to a checkpoint is not a mixed configuration, and the commit
changes between sessions.
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass

NOT_ENFORCED_ON_RESUME = frozenset({"providers", "harness_git_commit", "started_at"})


class ManifestMismatch(Exception):
    pass


class UnmanifestedCheckpoint(Exception):
    """A checkpoint that already holds results but has no manifest: its configuration is unknown."""


@dataclass(frozen=True)
class RunManifest:
    system_model: str
    system_temperature: float
    system_response_temperature: float
    system_min_turns: int
    system_context_window: int
    simulator_model: str
    simulator_temperature: float
    providers: tuple[str, ...]
    variant: str
    repeats: int
    judges_enabled: bool
    bootstrap_seed: int
    system_prompt_sha256: str
    simulator_prompt_sha256: str
    checklists_sha256: str
    harness_git_commit: str
    retry_max_attempts: int
    retry_base_delay_seconds: float
    conversation_token_cap: int
    breaker_enabled: bool
    breaker_failure_threshold: int
    breaker_cooldown_seconds: float
    capped_reply_sha256: str
    graph_index_manifest_sha256: str  # "" when no semantic leg: the index a neo4j_semantic leg ran against
    semantic_model_id: str
    red_flag_floor_mode: str          # off | shadow | enforce, as the system under test will run them
    groundedness_guard_mode: str
    emergency_mismatch_mode: str
    red_flag_list_sha256: str         # a changed pattern list is a new configuration
    retry_budget_percent: int


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_directory(path: str) -> str:
    """Hash of every non-hidden file's name and bytes, in sorted name order."""
    digest = hashlib.sha256()
    for name in sorted(os.listdir(path)):
        file_path = os.path.join(path, name)
        if name.startswith(".") or not os.path.isfile(file_path):
            continue
        digest.update(name.encode("utf-8") + b"\0")
        with open(file_path, "rb") as f:
            digest.update(f.read() + b"\0")
    return digest.hexdigest()


def manifest_path(checkpoint_path: str) -> str:
    return f"{checkpoint_path}.manifest.json"


def read_manifest(checkpoint_path: str) -> dict | None:
    path = manifest_path(checkpoint_path)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _recorded_lines(checkpoint_path: str) -> int:
    if not os.path.exists(checkpoint_path):
        return 0
    with open(checkpoint_path) as f:
        return sum(1 for line in f if line.strip())


def write_or_verify_manifest(
    checkpoint_path: str, manifest: RunManifest, started_at: str, adopt_legacy: bool = False
) -> None:
    path = manifest_path(checkpoint_path)
    current = json.loads(json.dumps(asdict(manifest)))
    if not os.path.exists(path):
        recorded = _recorded_lines(checkpoint_path)
        if recorded and not adopt_legacy:
            raise UnmanifestedCheckpoint(
                f"{checkpoint_path} already holds {recorded} recorded lines but has no manifest, so the "
                "configuration that produced them is unknown. Use a new --checkpoint path, or pass "
                "--adopt-legacy-checkpoint to certify it with today's configuration."
            )
        with open(path, "w") as f:
            json.dump({**current, "started_at": started_at}, f, indent=2)
        return

    with open(path) as f:
        stored = json.load(f)
    differing = [
        f"{name}: stored {stored.get(name)!r}, now {value!r}"
        for name, value in current.items()
        if name not in NOT_ENFORCED_ON_RESUME and stored.get(name) != value
    ]
    if differing:
        raise ManifestMismatch(
            f"{path} was written under a different configuration — " + "; ".join(differing)
        )
