import dataclasses
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from services import red_flags
from services.red_flags import RedFlag, find_red_flags, red_flag_list_sha256


def cats(*messages: str) -> list[str]:
    return [flag.category for flag in find_red_flags(list(messages))]


@pytest.mark.parametrize("text,expected", [
    ("I have chest pain", ["chest_pain"]),
    ("my chest feels really tight and heavy", ["chest_pain"]),
    ("there is a crushing pressure in my chest", ["chest_pain"]),
    ("he can't breathe", ["breathing"]),
    ("the baby is gasping for air", ["breathing"]),
    ("I am struggling to breathe", ["breathing"]),
    ("he won't wake up", ["unresponsive"]),
    ("she is unconscious", ["unresponsive"]),
    ("he is not responding to anything", ["unresponsive"]),
    ("her face is drooping and her speech is slurred", ["stroke_signs"]),
    ("sudden weakness on one side of the body", ["stroke_signs"]),
    ("the bleeding won't stop", ["severe_bleeding"]),
    ("he is bleeding heavily", ["severe_bleeding"]),
    ("she is having a seizure right now", ["seizure"]),
    ("he is choking", ["choking"]),
    ("her throat is swelling shut", ["airway_swelling"]),
])
def test_a_clear_red_flag_is_found(text: str, expected: list[str]) -> None:
    assert cats(text) == expected


@pytest.mark.parametrize("text", [
    "", "headache", "I cut my finger, a bit of bleeding", "a mild cough and a sore throat",
    "my stomach hurts", "I feel dizzy",
])
def test_ordinary_complaints_find_nothing(text: str) -> None:
    assert cats(text) == []


@pytest.mark.parametrize("text", [
    "no chest pain", "I don't have chest pain", "I DON’T have chest pain", "without any chest pain",
    "he denies chest pain", "never had chest pain",
    "I haven't noticed any numbness or trouble breathing",
    "I'm not running a fever or having trouble breathing",
    "no fever, no cough, and no trouble breathing",
    "my dad had a stroke years ago", "history of stroke in the family", "family history of stroke",
])
def test_a_negated_or_historical_mention_is_ignored(text: str) -> None:
    assert cats(text) == []


def test_a_plain_statement_of_trouble_breathing_is_found() -> None:
    assert cats("I've been having trouble breathing.") == ["breathing"]


@pytest.mark.parametrize("text", [
    "no fever but I can't breathe",
    "I don't have a cough, however I am gasping",
    "no pain until now, I can't breathe",
])
def test_a_contrast_word_ends_the_reach_of_a_negation(text: str) -> None:
    assert cats(text) == ["breathing"]


def test_a_negation_only_cancels_its_own_phrase() -> None:
    assert cats("I don't have chest pain but I can't breathe") == ["breathing"]


def test_a_cancelled_mention_never_cancels_a_later_real_one() -> None:
    assert cats("No chest pain at first, now there is chest pain") == ["chest_pain"]


def test_the_flag_is_found_in_an_earlier_message_of_the_conversation() -> None:
    assert cats("I have chest pain", "it started an hour ago", "it is getting worse") == ["chest_pain"]


def test_each_category_is_reported_once_in_order_of_first_hit() -> None:
    assert cats("he can't breathe", "chest pain too", "still can't breathe") == ["breathing", "chest_pain"]


def test_a_red_flag_carries_only_a_category_never_user_text() -> None:
    assert [f.name for f in dataclasses.fields(RedFlag)] == ["category"]


def test_the_list_hash_is_a_sha256_and_changes_with_the_list(monkeypatch: pytest.MonkeyPatch) -> None:
    before = red_flag_list_sha256()
    assert len(before) == 64 and int(before, 16) >= 0
    monkeypatch.setitem(red_flags.RED_FLAG_PATTERNS, "chest_pain", ("something else",))
    assert red_flag_list_sha256() != before


@pytest.mark.parametrize("text,expected", [
    ("No, I can't breathe", ["breathing"]),
    ("I don't know what's happening, I can't breathe", ["breathing"]),
    ("I don't know, my chest pain is really bad", ["chest_pain"]),
    ("It isn't getting better and I have chest pain", ["chest_pain"]),
    ("I've never felt chest pain like this", ["chest_pain"]),
    ("Never had this before: chest pain and sweating", ["chest_pain"]),
    ("I did not eat, and chest pain started", ["chest_pain"]),
    ("history of seizures, he is having a seizure now", ["seizure"]),
    ("My wife collapsed and isn't breathing", ["breathing"]),
    ("he stopped breathing", ["breathing"]),
])
def test_lay_emergency_phrasing_is_not_cancelled_by_a_nearby_negation_or_history(text: str, expected: list[str]) -> None:
    assert cats(text) == expected


@pytest.mark.parametrize("text", [
    "no fever and no chest pain",
    "I never had chest pain",
    "no cough or chest pain",
    "No, I haven't noticed any fever, chills, or trouble breathing",
    "He's not struggling to breathe, no coughing, choking, or drooling",
    "I haven't had any nausea or pain, and I don't think I have a fever or trouble breathing",
])
def test_a_negation_still_reaches_across_a_short_list_in_one_clause(text: str) -> None:
    assert cats(text) == []


@pytest.mark.parametrize("text", ["I think it is heat stroke from the sun", "he had a sun stroke yesterday"])
def test_heat_stroke_is_not_a_neurological_stroke(text: str) -> None:
    assert cats(text) == []


def test_a_stroke_is_still_found() -> None:
    assert cats("I think she is having a stroke") == ["stroke_signs"]
