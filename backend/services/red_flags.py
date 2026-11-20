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
        r"\b(?:isn'?t|is not|stopped|stops) breathing\b",
    ),
    "unresponsive": (
        r"\bunconscious\b",
        r"\bunresponsive\b",
        r"\bloss of consciousness\b",
        r"\b(?:won'?t|will not|can'?t be|cannot be) (?:wake|woken|react|respond)\b",
        r"\bnot (?:responding|reacting)\b",
    ),
    "stroke_signs": (
        r"(?<!heat )(?<!sun )\bstroke\b",
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
# A negation reaches back over a short list in one clause ("haven't noticed any numbness or trouble
# breathing") but stops at a contrast word or a clause joiner, so "no fever but I can't breathe" and
# "it isn't getting better and I have chest pain" still find the problem. Commas and colons end the
# clause altogether; a comma does so only when a new subject follows it ("No, I can't breathe" is an
# emergency, not a denial), not for list items ("no fever, chills, or trouble breathing").
SUBJECT_WORDS = frozenset({
    "i", "i'm", "i've", "i'd", "he", "she", "they", "we", "you", "it", "he's", "she's", "they're", "it's",
    "my", "his", "her", "their", "our", "there", "there's", "this", "that",
})
CONTRAST_WORDS = frozenset({
    "but", "however", "although", "though", "except", "yet", "now", "then", "until", "still",
    "and", "so", "because",
})
NEGATION_REACH_WORDS = 8
# "I've never felt chest pain like this" is a worst-ever symptom, not a denial.
NEVER_LIKE_THIS = ("like this", "like that")
HISTORY_BEFORE = ("history of", "family history")
HISTORY_AFTER = ("years ago", "year ago", "decades ago")
HISTORY_WINDOW_WORDS = 4

_SENTENCE_BREAK = re.compile(r"[.?!;\n]+")
_WORD = re.compile(r"[a-z']+")
_WORD_OR_PAUSE = re.compile(r"[a-z']+|[,:]")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("’", "'").replace("‘", "'")).strip()


def _cancelled(sentence: str, start: int, end: int) -> bool:
    """A mention is cancelled by a negation cue before it in the same clause with no contrast word in
    between, or by a history cue ("history of ..." before it, "years ago" after it). Only its own
    mention is cancelled."""
    tokens = _WORD_OR_PAUSE.findall(sentence[:start])
    clause_words: list[str] = []  # the words between the scan position and the mention, nearest last
    for token in reversed(tokens):
        if token in (",", ":"):
            if token == ":" or any(w in SUBJECT_WORDS for w in clause_words):
                break
            continue
        if token in CONTRAST_WORDS or len(clause_words) >= NEGATION_REACH_WORDS:
            break
        if token in NEGATION_WORDS:
            if token == "never" and " ".join(_WORD.findall(sentence[end:])[:2]) in NEVER_LIKE_THIS:
                clause_words.insert(0, token)
                continue
            return True
        clause_words.insert(0, token)
    clause_before = sentence[:start].rsplit(",", 1)[-1].rsplit(":", 1)[-1]
    before_text = " ".join(_WORD.findall(clause_before)[-HISTORY_WINDOW_WORDS:])
    after_text = " ".join(_WORD.findall(sentence[end:].split(",")[0])[:HISTORY_WINDOW_WORDS])
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
