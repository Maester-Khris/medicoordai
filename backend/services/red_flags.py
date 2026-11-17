"""Deterministic red-flag matcher: the pattern source for the pre-model floor and the mismatch guard.

Pure and local (no I/O, no model, no graph), so it works on the production path where the knowledge
graph is off. It reads what the patient wrote and only ever answers "which emergency categories
were mentioned"; it never lowers anything and it returns category ids, never the patient's text.

THE LIST IS A DRAFT until a clinical reviewer has signed it. Until then the guards that use it stay
in shadow mode (see config.red_flag_floor_mode). A false positive sends someone to 911 who may not
need it, so every change here changes the eval configuration (the list hash is in the run manifest).
"""
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RedFlag:
    category: str


# category -> regexes over normalised text (lower case, straight apostrophes). Word boundaries
# throughout; no fuzzy matching on purpose (it raises false positives).
RED_FLAG_PATTERNS: dict[str, tuple[str, ...]] = {
    "chest_pain": (
        r"\bchest (?:pain|pains|pressure|tightness)\b",
        r"\bpain in (?:my|his|her|their|the) chest\b",
        r"\bpressure (?:in|on) (?:my|his|her|their|the) chest\b",
        r"\bchest (?:feels?|is|was|are)\b[^.?!;]{0,25}\b(?:tight|heavy|crushing)\b",
    ),
    "breathing": (
        r"\b(?:can'?t|cannot|can not|unable to) breathe\b",
        r"\b(?:struggling|fighting) to breathe\b",
        r"\b(?:difficulty|trouble) breathing\b",
        r"\bgasping\b",
        r"\bnot breathing\b",
    ),
    "unresponsive": (
        r"\bunconscious\b",
        r"\bunresponsive\b",
        r"\bloss of consciousness\b",
        r"\b(?:won'?t|will not|can'?t be|cannot be) (?:wake|woken|react|respond)\b",
        r"\bnot (?:responding|reacting)\b",
    ),
    "stroke_signs": (
        r"\bstroke\b",
        r"\bface (?:is |was )?(?:drooping|droopy|drooped)\b",
        r"\bdrooping face\b",
        r"\bslurred speech\b",
        r"\bspeech is slurred\b",
        r"\bslurring (?:his|her|my|their) words\b",
        r"\bsudden (?:weakness|numbness) (?:on|in) one side\b",
    ),
    "severe_bleeding": (
        r"\bsevere bleeding\b",
        r"\bbleeding (?:heavily|badly|profusely|a lot)\b",
        r"\bbleeding (?:that |and )?(?:won'?t|will not|doesn'?t|does not|can'?t|cannot) (?:stop|be stopped)\b",
        r"\bcan'?t stop (?:the )?bleeding\b",
    ),
    "seizure": (
        r"\b(?:having|had|started having|is having) (?:a )?(?:seizure|convulsion)s?\b",
        r"\bconvulsing\b",
    ),
    "choking": (
        r"\bchoking\b",
    ),
    "airway_swelling": (
        r"\b(?:throat|tongue) (?:is |are )?(?:swelling|swollen|closing)\b",
        r"\bswelling (?:of|in) (?:the |my |his |her |their )?(?:throat|tongue)\b",
    ),
}

NEGATION_WORDS = frozenset({
    "no", "not", "without", "denies", "denied", "never", "neither", "nor",
    "don't", "dont", "doesn't", "doesnt", "didn't", "didnt", "isn't", "isnt",
    "wasn't", "wasnt", "aren't", "hasn't", "haven't", "havent",
})
# A negation reaches back over a list ("haven't noticed any numbness or trouble breathing") but stops
# at a contrast word, so "no fever but I can't breathe" still finds the breathing problem.
CONTRAST_WORDS = frozenset({"but", "however", "although", "though", "except", "yet", "now", "then", "until", "still"})
NEGATION_REACH_WORDS = 12
HISTORY_BEFORE = ("history of", "family history")
HISTORY_AFTER = ("years ago", "year ago", "decades ago")
HISTORY_WINDOW_WORDS = 4

_SENTENCE_BREAK = re.compile(r"[.?!;\n]+")
_WORD = re.compile(r"[a-z']+")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("’", "'").replace("‘", "'")).strip()


def _cancelled(sentence: str, start: int, end: int) -> bool:
    """A mention is cancelled by a negation cue before it with no contrast word in between, or by a
    history cue ("history of ..." before it, "years ago" after it). Only its own mention is cancelled."""
    for word in reversed(_WORD.findall(sentence[:start])[-NEGATION_REACH_WORDS:]):
        if word in CONTRAST_WORDS:
            break
        if word in NEGATION_WORDS:
            return True
    before_text = " ".join(_WORD.findall(sentence[:start])[-HISTORY_WINDOW_WORDS:])
    after_text = " ".join(_WORD.findall(sentence[end:])[:HISTORY_WINDOW_WORDS])
    return any(cue in before_text for cue in HISTORY_BEFORE) or any(cue in after_text for cue in HISTORY_AFTER)


def find_red_flags(user_messages: Sequence[str]) -> list[RedFlag]:
    """The red-flag categories mentioned anywhere in the patient's messages, each once, in order of
    first mention. Assistant text must never be passed in."""
    found: list[str] = []
    for message in user_messages:
        for sentence in _SENTENCE_BREAK.split(_normalise(message)):
            for category, patterns in RED_FLAG_PATTERNS.items():
                if category in found:
                    continue
                for pattern in patterns:
                    if any(not _cancelled(sentence, m.start(), m.end()) for m in re.finditer(pattern, sentence)):
                        found.append(category)
                        break
    return [RedFlag(category) for category in found]


def red_flag_list_sha256() -> str:
    """Hash of the pattern list, recorded in the eval run manifest so a changed list is a new configuration."""
    return hashlib.sha256(json.dumps(RED_FLAG_PATTERNS, sort_keys=True).encode("utf-8")).hexdigest()
