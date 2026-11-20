"""
Rescore saved conversations with the elicitation-coverage judge, with no system or
simulator calls: the transcripts and the checklists are already on disk.

Three choices keep it cheap and its numbers readable:
- A fact in the opening exchange is judged first, once per vignette (the opening is the
  same in every leg and repeat; the VerdictCache makes that automatic). Only the facts not
  in the opening are judged against the full transcript.
- Coverage is reported over all facts and over patient-answerable facts only. Vitals (blood
  pressure, pulse) are in the checklists but a chat patient cannot read them out.
- A second judge can re-judge a random sample of the verdicts; Cohen's kappa says how far
  the first judge can be trusted.
"""
import hashlib
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from scripts.symptom_eval.domain import ConversationTurn, DisclosureItem, Vignette, VignetteTranscript
from scripts.symptom_eval.elicitation_coverage import FeaturePresenceJudgePort
from scripts.symptom_eval.paired_stats import BootstrapResult, paired_bootstrap_diff

PATIENT_ANSWERABLE = ("chief_complaint", "history", "exam")  # vitals are left out of the primary metric


class VerdictCache:
    """Judge verdicts by (fact wording, text). One cache per judge model: `salt` names it, so a
    cache file written by one model is never read as another's verdicts."""

    def __init__(self, path: str | None = None, salt: str = "") -> None:
        self._items: dict[str, tuple[str, str, bool]] = {}
        self._lock = threading.Lock()
        self._path = path
        self._salt = salt
        if path:
            try:
                with open(path) as f:
                    for line in f:
                        if line.strip():
                            key, phrasing, text, verdict = json.loads(line)
                            self._items[key] = (phrasing, text, verdict)
            except FileNotFoundError:
                pass

    def _key(self, phrasing: str, text: str) -> str:
        return hashlib.sha256(f"{self._salt}\x00{phrasing}\x00{text}".encode()).hexdigest()

    def judge(self, judge: FeaturePresenceJudgePort, feature: DisclosureItem, text: str) -> bool:
        key = self._key(feature.first_person_phrasing, text)
        with self._lock:
            if key in self._items:
                return self._items[key][2]
        verdict = bool(judge.was_surfaced(feature, text))  # outside the lock so workers overlap
        with self._lock:
            self._items[key] = (feature.first_person_phrasing, text, verdict)
            if self._path:
                with open(self._path, "a") as f:
                    f.write(json.dumps([key, feature.first_person_phrasing, text, verdict]) + "\n")
        return verdict

    def items(self) -> list[tuple[str, str, bool]]:
        with self._lock:
            return list(self._items.values())


@dataclass(frozen=True)
class FeatureVerdict:
    feature_id: str
    category: str
    in_opening: bool
    surfaced: bool

    @property
    def elicited(self) -> bool:
        return self.surfaced and not self.in_opening


@dataclass(frozen=True)
class EntryScore:
    provider: str
    case_id: str
    repeat: int
    verdicts: list[FeatureVerdict]

    @staticmethod
    def _coverage(verdicts: Sequence[FeatureVerdict]) -> float:
        return sum(v.elicited for v in verdicts) / len(verdicts) if verdicts else 0.0

    @property
    def coverage_all(self) -> float:
        return self._coverage(self.verdicts)

    @property
    def coverage_answerable(self) -> float:
        return self._coverage([v for v in self.verdicts if v.category in PATIENT_ANSWERABLE])


def _transcript(entry: dict) -> VignetteTranscript:
    if "transcript" not in entry:
        raise ValueError(
            f"{entry.get('provider')}/{entry.get('case_id')}/{entry.get('repeat')} has no transcript "
            "in the checkpoint; it cannot be rescored"
        )
    turns = [
        ConversationTurn(
            turn_index=t["turn_index"], patient_message=t["patient_message"],
            system_response=t["system_response"], graph_context_matched=False,
        )
        for t in entry["transcript"]
    ]
    return VignetteTranscript(str(entry["case_id"]), turns, None, None)


def score_entry(
    vignette: Vignette, entry: dict, judge: FeaturePresenceJudgePort, cache: VerdictCache
) -> EntryScore:
    transcript = _transcript(entry)
    opening, full = transcript.text_up_to(0), transcript.text_up_to()
    verdicts = []
    for feature in vignette.disclosure_items:
        in_opening = cache.judge(judge, feature, opening)
        # The full transcript contains the opening, so a fact in the opening needs no second call.
        surfaced = in_opening or cache.judge(judge, feature, full)
        verdicts.append(FeatureVerdict(feature.feature_id, feature.category, in_opening, surfaced))
    return EntryScore(entry["provider"], str(entry["case_id"]), entry.get("repeat", 0), verdicts)


def rescore_entries(
    vignettes: Mapping[str, Vignette],
    entries: Sequence[dict],
    judge_factory: Callable[[], FeaturePresenceJudgePort],
    workers: int = 1,
    cache: VerdictCache | None = None,
) -> list[EntryScore]:
    """Results come back in the order of `entries`. Each worker thread gets its own judge,
    because a DeepEval metric keeps state between calls and is not safe to share."""
    cache = cache or VerdictCache()
    local = threading.local()

    def run(entry: dict) -> EntryScore:
        if not hasattr(local, "judge"):
            local.judge = judge_factory()
        return score_entry(vignettes[str(entry["case_id"])], entry, local.judge, cache)

    if workers <= 1:
        return [run(e) for e in entries]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, entries))


@dataclass(frozen=True)
class CoverageComparison:
    leg_a: str
    leg_b: str
    metric: str
    n: int
    mean_a: float
    mean_b: float
    bootstrap: BootstrapResult  # diff = mean_b - mean_a, so positive means leg b elicits more


def compare_coverage(
    results: Sequence[EntryScore], leg_a: str, leg_b: str, metric: str, seed: int
) -> CoverageComparison:
    """The unit is the vignette: its value is the mean over its repeats. Only vignettes present in
    both legs are compared."""
    per_leg: dict[str, dict[str, list[float]]] = {leg_a: {}, leg_b: {}}
    for r in results:
        if r.provider in per_leg:
            per_leg[r.provider].setdefault(r.case_id, []).append(getattr(r, metric))
    shared = sorted(set(per_leg[leg_a]) & set(per_leg[leg_b]))
    mean = lambda xs: sum(xs) / len(xs)
    a = [mean(per_leg[leg_a][c]) for c in shared]
    b = [mean(per_leg[leg_b][c]) for c in shared]
    return CoverageComparison(
        leg_a, leg_b, metric, len(shared), mean(a), mean(b),
        paired_bootstrap_diff(b, a, seed),
    )


def cohens_kappa(first: Sequence[bool], second: Sequence[bool]) -> float:
    n = len(first)
    agree = sum(x == y for x, y in zip(first, second)) / n
    p_first, p_second = sum(first) / n, sum(second) / n
    chance = p_first * p_second + (1 - p_first) * (1 - p_second)
    if chance == 1:
        return 1.0 if agree == 1 else 0.0
    return (agree - chance) / (1 - chance)


@dataclass(frozen=True)
class Agreement:
    n: int
    n_positive: int
    positive_agreement: float  # of the first judge's "present" verdicts, the share the second also calls present
    negative_agreement: float  # of its "absent" verdicts, the share the second also calls absent
    kappa: float  # on this stratified sample, so a rough guide only; the two class rates are the clearer figures


def judge_agreement(
    cache: VerdictCache, second_judge: FeaturePresenceJudgePort, per_class: int, seed: int
) -> Agreement:
    """Re-judges unique (fact, text) verdicts with a second judge.

    Most verdicts are "absent", so a plain random sample is almost all negatives and kappa collapses
    (95% raw agreement can still give kappa 0). The sample therefore takes up to `per_class` of each
    class, which keeps the rare positives in, and reports the agreement within each class."""
    rng = random.Random(seed)
    items = cache.items()
    positives = [i for i in items if i[2]]
    negatives = [i for i in items if not i[2]]
    sample = rng.sample(positives, min(per_class, len(positives))) + rng.sample(
        negatives, min(per_class, len(negatives))
    )
    second = [
        bool(second_judge.was_surfaced(DisclosureItem("sample", "history", phrasing, True), text))
        for phrasing, text, _ in sample
    ]
    first = [verdict for _, _, verdict in sample]
    pairs = list(zip(first, second))
    rate = lambda want: (
        sum(f == s for f, s in pairs if f == want) / max(1, sum(1 for f, _ in pairs if f == want))
    )
    return Agreement(
        n=len(sample), n_positive=sum(first), positive_agreement=rate(True),
        negative_agreement=rate(False), kappa=cohens_kappa(first, second),
    )
