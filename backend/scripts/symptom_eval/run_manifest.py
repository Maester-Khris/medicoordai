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


@dataclass(frozen=True)
class RunManifest:
    system_model: str
    system_temperature: float
    system_response_temperature: float
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


def write_or_verify_manifest(checkpoint_path: str, manifest: RunManifest, started_at: str) -> None:
    path = manifest_path(checkpoint_path)
    current = json.loads(json.dumps(asdict(manifest)))
    if not os.path.exists(path):
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
