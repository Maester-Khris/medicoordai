import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import pytest

from scripts.symptom_eval.domain import DisclosureItem, Vignette
from scripts.symptom_eval.rescore import (
    VerdictCache,
    cohens_kappa,
    compare_coverage,
    rescore_entries,
    score_entry,
)


def _item(feature_id, category="history"):
    return DisclosureItem(feature_id, category, f"phrase:{feature_id}", True)


VIGNETTE = Vignette(
    case_id="1", opening_message="chest pain",
    disclosure_items=[_item("onset"), _item("radiation", "exam"), _item("pulse", "vitals"), _item("fever")],
    gold_severity="emergent", gold_ctas_level=1,
)


def _entry(provider, repeat, turns, case_id="1"):
    return {
        "variant": "lay", "provider": provider, "case_id": case_id, "repeat": repeat,
        "transcript": [
            {"turn_index": i, "patient_message": p, "system_response": s} for i, (p, s) in enumerate(turns)
        ],
    }


class _ScriptedJudge:
    """Says a feature is present when its id appears in the text; counts every call."""

    def __init__(self):
        self.calls = 0

    def was_surfaced(self, feature, transcript_text):
        self.calls += 1
        return feature.feature_id in transcript_text


class TestScoreEntry:
    def test_a_fact_in_the_opening_is_volunteered_and_the_full_transcript_is_not_judged_for_it(self):
        judge = _ScriptedJudge()
        entry = _entry("off", 0, [("chest pain, onset today", "ok"), ("also radiation", "thanks")])

        result = score_entry(VIGNETTE, entry, judge, VerdictCache())

        by_id = {v.feature_id: v for v in result.verdicts}
        assert by_id["onset"].in_opening and not by_id["onset"].elicited
        assert by_id["radiation"].elicited and not by_id["radiation"].in_opening
        assert not by_id["fever"].surfaced
        # onset: 1 call (opening only). radiation, pulse, fever: opening + full = 2 each.
        assert judge.calls == 1 + 2 + 2 + 2

    def test_coverage_counts_elicited_facts_over_all_facts_and_over_patient_answerable_facts(self):
        entry = _entry("off", 0, [("chest pain", "ok"), ("onset and pulse here", "thanks")])

        result = score_entry(VIGNETTE, entry, _ScriptedJudge(), VerdictCache())

        assert result.coverage_all == pytest.approx(2 / 4)  # onset and pulse elicited, of 4 facts
        assert result.coverage_answerable == pytest.approx(1 / 3)  # vitals (pulse) left out: onset of 3

    def test_the_opening_verdicts_are_reused_across_conversations_of_the_same_vignette(self):
        judge = _ScriptedJudge()
        cache = VerdictCache()
        opening = ("chest pain", "ok")

        score_entry(VIGNETTE, _entry("off", 0, [opening, ("onset", "x")]), judge, cache)
        first = judge.calls
        score_entry(VIGNETTE, _entry("v3", 0, [opening, ("onset", "y")]), judge, cache)

        # Second conversation: the four opening verdicts come from the cache; only the full text is judged
        # for the four facts that were not in the opening.
        assert judge.calls - first == 4

    def test_a_conversation_without_a_transcript_is_refused_not_scored_as_zero(self):
        with pytest.raises(ValueError, match="transcript"):
            score_entry(VIGNETTE, {"provider": "off", "case_id": "1", "repeat": 0}, _ScriptedJudge(), VerdictCache())


class TestRescoreEntries:
    def test_workers_give_the_same_results_as_a_single_thread(self):
        entries = [
            _entry(p, r, [("chest pain", "ok"), (f"onset {'radiation' if r else ''}", "x")])
            for p in ("off", "v3") for r in range(3)
        ]

        single = rescore_entries({"1": VIGNETTE}, entries, _ScriptedJudge, workers=1)
        pooled = rescore_entries({"1": VIGNETTE}, entries, _ScriptedJudge, workers=4)

        key = lambda r: (r.provider, r.case_id, r.repeat)
        assert [(key(r), r.coverage_all) for r in single] == [(key(r), r.coverage_all) for r in pooled]


class TestCompareCoverage:
    def test_the_difference_is_leg_b_minus_leg_a_per_vignette_mean_over_repeats(self):
        v2 = Vignette("2", "x", [_item("onset"), _item("fever")], "urgent", 3)
        vignettes = {"1": VIGNETTE, "2": v2}
        entries = []
        for case, vig in (("1", VIGNETTE), ("2", v2)):
            entries += [
                _entry("off", 0, [("chest pain", "a"), ("none", "b")], case),
                _entry("v3", 0, [("chest pain", "a"), ("onset fever radiation", "b")], case),
            ]

        results = rescore_entries(vignettes, entries, _ScriptedJudge, workers=1)
        comparison = compare_coverage(results, leg_a="off", leg_b="v3", metric="coverage_all", seed=7)

        assert comparison.n == 2
        assert comparison.mean_a == 0.0
        assert comparison.bootstrap.diff == pytest.approx(comparison.mean_b - comparison.mean_a)
        assert comparison.mean_b > 0


class TestCohensKappa:
    def test_perfect_agreement_is_one(self):
        assert cohens_kappa([True, False, True, False], [True, False, True, False]) == pytest.approx(1.0)

    def test_known_value(self):
        # agreement 3 of 4; chance agreement 0.5 -> kappa 0.5
        assert cohens_kappa([True, True, False, False], [True, False, False, False]) == pytest.approx(0.5)

    def test_no_variation_in_either_rater_is_not_a_division_by_zero(self):
        assert cohens_kappa([True, True], [True, True]) == pytest.approx(1.0)


class TestJudgeAgreement:
    class _PhrasingJudge:
        """Judges from the fact's wording only, as a real judge does (the id is not sent to it)."""

        def __init__(self, flip=False):
            self._flip = flip

        def was_surfaced(self, feature, transcript_text):
            present = feature.first_person_phrasing.removeprefix("phrase:") in transcript_text
            return present != self._flip

    def test_rare_positives_are_always_sampled_beside_a_capped_number_of_negatives(self):
        from scripts.symptom_eval.rescore import judge_agreement

        cache = VerdictCache()
        for i in range(20):  # 20 facts, only "onset" is ever present
            feature = _item("onset" if i == 0 else f"absent{i}")
            cache.judge(_ScriptedJudge(), feature, "the patient reports onset today")

        agreement = judge_agreement(cache, self._PhrasingJudge(), per_class=5, seed=1)

        assert agreement.n_positive == 1
        assert agreement.n == 1 + 5
        assert agreement.positive_agreement == 1.0 and agreement.negative_agreement == 1.0

    def test_a_second_judge_that_disagrees_on_everything_has_no_agreement(self):
        from scripts.symptom_eval.rescore import judge_agreement

        cache = VerdictCache()
        for feature_id in ("onset", "radiation", "fever", "cough"):
            cache.judge(_ScriptedJudge(), _item(feature_id), "onset and radiation")

        agreement = judge_agreement(cache, self._PhrasingJudge(flip=True), per_class=5, seed=1)

        assert agreement.positive_agreement == 0.0 and agreement.negative_agreement == 0.0
        assert agreement.kappa == pytest.approx(-1.0)

    def test_the_cache_is_not_shared_between_judge_models(self, tmp_path):
        path = str(tmp_path / "cache.jsonl")
        judge = _ScriptedJudge()
        feature = _item("onset")

        VerdictCache(path, salt="gpt-4o-mini").judge(judge, feature, "onset here")
        reread_same_model = VerdictCache(path, salt="gpt-4o-mini")
        reread_other_model = VerdictCache(path, salt="gpt-4.1-mini")
        before = judge.calls
        reread_same_model.judge(judge, feature, "onset here")
        assert judge.calls == before  # served from the file

        reread_other_model.judge(judge, feature, "onset here")
        assert judge.calls == before + 1  # a different model's verdicts are not reused


class TestRescoreCommand:
    def test_the_command_writes_a_report_with_legs_comparisons_and_the_primary_flag(self, tmp_path):
        from scripts.symptom_eval.cli import rescore_command

        class _PainJudge:
            def was_surfaced(self, feature, transcript_text):
                return "pain" in transcript_text

        lines = []
        for provider, second in (("off", "no"), ("neo4j_semantic", "pain")):
            for case in ("1", "2"):
                entry = _entry(provider, 0, [("hello", "hi"), (second, "ok")], case)
                entry["confusion_row"] = {"case_id": case}
                lines.append(json.dumps(entry))
        checkpoint = tmp_path / "checkpoint.jsonl"
        checkpoint.write_text("\n".join(lines) + "\n")
        out = tmp_path / "report.json"

        report = rescore_command(
            str(checkpoint), "lay", str(out), workers=1, judge_factory=_PainJudge,
            agreement_per_class=5, second_judge_factory=_PainJudge,
        )

        assert json.loads(out.read_text())["variant"] == "lay"
        assert set(report["legs"]) == {"off", "neo4j_semantic"}
        assert report["legs"]["neo4j_semantic"]["coverage_all"] > report["legs"]["off"]["coverage_all"]
        primary = [c for c in report["comparisons"] if c["primary"]]
        assert len(primary) == 1 and primary[0]["metric"] == "coverage_answerable"
        assert report["agreement"]["kappa"] == pytest.approx(1.0)
        assert report["agreement"]["positive_agreement"] == 1.0
