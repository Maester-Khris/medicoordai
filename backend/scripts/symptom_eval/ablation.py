"""
RunBaselineAblation (Metric 4) — runs the full vignette pool through the
conversation loop once per GRAPH_RAG_PROVIDER leg, diffing Metrics 1-3
between legs. No new scoring logic — Metrics 1-3 called once per leg
(backend/graph/factory.py:12 defines the provider values), per design §6.

Takes system_factory rather than constructing LiveLLMAgentAdapter directly —
per this plan's Dependency Rule, only cli.py (Main) may reference that
concrete adapter; this file only sees SystemUnderTestPort.

CheckpointStore persists each vignette-leg's scored result to a JSONL file
as soon as it's computed, not just after a full leg completes — added after
Task 13's first live run crashed on a Groq daily-quota 429 partway through
the `off` leg and lost every already-completed vignette's work, since
nothing was written to disk until both legs finished. Only stdlib file I/O
here (json/os), not a vendor SDK, so it stays in this use-case file rather
than needing a cli.py-only adapter.
"""
import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Callable

from scripts.symptom_eval import confusion_matrix, elicitation_coverage, information_gain
from scripts.symptom_eval.confusion_matrix import ConfusionMatrixRow
from scripts.symptom_eval.conversation_runner import run_vignette_conversation
from scripts.symptom_eval.domain import Vignette
from scripts.symptom_eval.elicitation_coverage import ElicitationCoverageResult, FeaturePresenceJudgePort
from scripts.symptom_eval.information_gain import InformationGainResult, RubricJudgePort
from scripts.symptom_eval.patient_simulator import PatientSimulatorPort
from scripts.symptom_eval.system_under_test import SystemUnderTestPort


@dataclass
class AblationLegResult:
    provider: str
    confusion_matrix: dict
    elicitation_coverage: list[ElicitationCoverageResult | None]
    information_gain: list[InformationGainResult | None]


class CheckpointStore:
    """Append-only JSONL checkpoint, one line per completed vignette-leg-repeat.

    A line is keyed by (variant, provider, case_id, repeat). Lines written
    before variants and repeats existed carry neither field and load as
    variant "original", repeat 0. Loading an existing file reconstructs what's
    already done; rerunning run_leg against the same path skips those keys and
    resumes where a crash (e.g. a Groq 429) left off.

    A line that is not valid JSON or lacks provider/case_id stops the load with
    its line number: silently skipping it would let a corrupt checkpoint pass
    for a complete one.
    """

    def __init__(self, path: str):
        self._path = path
        self.entries: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.done: set[tuple[str, str, str, int]] = set()
        if os.path.exists(path):
            with open(path) as f:
                for line_number, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    self._record(self._parse_line(line, line_number))

    def _parse_line(self, line: str, line_number: int) -> dict:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{self._path}: line {line_number} is not valid JSON ({error})") from error
        if "provider" not in entry or "case_id" not in entry:
            raise ValueError(f"{self._path}: line {line_number} has no provider/case_id")
        entry.setdefault("variant", "original")
        entry.setdefault("repeat", 0)
        return entry

    def _record(self, entry: dict) -> None:
        self.entries[(entry["variant"], entry["provider"])].append(entry)
        self.done.add((entry["variant"], entry["provider"], entry["case_id"], entry["repeat"]))

    def has(self, variant: str, provider: str, case_id: str, repeat: int) -> bool:
        return (variant, provider, case_id, repeat) in self.done

    def append(
        self,
        variant: str,
        provider: str,
        repeat: int,
        confusion_row: ConfusionMatrixRow,
        coverage: ElicitationCoverageResult | None,
        gain: InformationGainResult | None,
        graph_context_matched: list[bool],
        transcript: list[dict] | None = None,
    ) -> None:
        entry = {
            "variant": variant,
            "provider": provider,
            "case_id": confusion_row.case_id,
            "repeat": repeat,
            "confusion_row": asdict(confusion_row),
            "coverage": asdict(coverage) if coverage is not None else None,
            "gain": asdict(gain) if gain is not None else None,
            "graph_context_matched": graph_context_matched,
        }
        if transcript is not None:
            entry["transcript"] = transcript
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self._record(entry)

    def entries_for(self, variant: str, provider: str) -> list[dict]:
        return list(self.entries[(variant, provider)])

    def rows_for(
        self, variant: str, provider: str
    ) -> tuple[
        list[ConfusionMatrixRow],
        list[ElicitationCoverageResult | None],
        list[InformationGainResult | None],
    ]:
        entries = self.entries[(variant, provider)]
        confusion_rows = [ConfusionMatrixRow(**e["confusion_row"]) for e in entries]
        coverages = [ElicitationCoverageResult(**e["coverage"]) if e["coverage"] else None for e in entries]
        gains = [InformationGainResult(**e["gain"]) if e["gain"] else None for e in entries]
        return confusion_rows, coverages, gains


def run_leg(
    provider: str,
    vignettes: list[Vignette],
    system_factory: Callable[[str], SystemUnderTestPort],
    simulator: PatientSimulatorPort,
    feature_judge: FeaturePresenceJudgePort | None,
    rubric_judge: RubricJudgePort | None,
    checkpoint: CheckpointStore | None = None,
    variant: str = "original",
    repeats: int = 1,
) -> AblationLegResult:
    system = system_factory(provider)
    if checkpoint is not None:
        confusion_rows, coverage_results, gain_results = checkpoint.rows_for(variant, provider)
    else:
        confusion_rows, coverage_results, gain_results = [], [], []

    for vignette in vignettes:
        for repeat in range(repeats):
            if checkpoint is not None and checkpoint.has(variant, provider, vignette.case_id, repeat):
                continue

            transcript = run_vignette_conversation(
                vignette, simulator, system,
                conversation_id=f"{variant}:{provider}:{vignette.case_id}:{repeat}",
            )
            row = confusion_matrix.score_vignette(vignette, transcript)
            coverage = (
                elicitation_coverage.score_vignette(vignette, transcript, feature_judge)
                if feature_judge is not None else None
            )
            gain = (
                information_gain.score_vignette(transcript, rubric_judge)
                if rubric_judge is not None else None
            )

            confusion_rows.append(row)
            coverage_results.append(coverage)
            gain_results.append(gain)
            if checkpoint is not None:
                checkpoint.append(
                    variant, provider, repeat, row, coverage, gain,
                    [turn.graph_context_matched for turn in transcript.turns],
                    transcript=[
                        {
                            "turn_index": turn.turn_index,
                            "patient_message": turn.patient_message,
                            "system_response": turn.system_response,
                            "graph_context_matched": turn.graph_context_matched,
                            "cap_reached": turn.cap_reached,
                        }
                        for turn in transcript.turns
                    ],
                )

    return AblationLegResult(
        provider=provider,
        confusion_matrix=confusion_matrix.summarize(confusion_rows),
        elicitation_coverage=coverage_results,
        information_gain=gain_results,
    )


def run_ablation(
    vignettes: list[Vignette],
    system_factory: Callable[[str], SystemUnderTestPort],
    simulator: PatientSimulatorPort,
    feature_judge: FeaturePresenceJudgePort | None,
    rubric_judge: RubricJudgePort | None,
    providers: tuple[str, ...] = ("off", "neo4j"),
    checkpoint: CheckpointStore | None = None,
    variant: str = "original",
    repeats: int = 1,
) -> list[AblationLegResult]:
    return [
        run_leg(
            provider, vignettes, system_factory, simulator, feature_judge, rubric_judge,
            checkpoint=checkpoint, variant=variant, repeats=repeats,
        )
        for provider in providers
    ]
