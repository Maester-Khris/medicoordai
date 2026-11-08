"""
Entities for the symptom-understanding eval harness (design §3). Pure
dataclasses — zero framework, zero vendor-SDK dependency. See
docs/superpowers/specs/2026-08-03-symptom-understanding-eval-design.md.
"""
from dataclasses import dataclass, field

SEVERITY_RANK: dict[str, int] = {"routine": 0, "moderate": 1, "urgent": 2, "emergent": 3}


@dataclass
class DisclosureItem:
    feature_id: str
    category: str  # "chief_complaint" | "history" | "vitals" | "exam"
    first_person_phrasing: str
    reveal_only_if_asked: bool
    disclosed: bool = False


@dataclass
class Vignette:
    case_id: str
    opening_message: str
    disclosure_items: list[DisclosureItem]
    gold_severity: str
    gold_ctas_level: int
    update_message: str | None = None
    updated_gold_severity: str | None = None
    source_pages: str = ""
    pairing_exclusion: str | None = None  # reason a lay version can't support the gold label; None = pairable


@dataclass
class ConversationTurn:
    turn_index: int
    patient_message: str
    system_response: str
    graph_context_matched: bool
    surfaced_red_flag_indicators: list[str] = field(default_factory=list)
    surfaced_followup_questions: list[str] = field(default_factory=list)
    cap_reached: bool = False


@dataclass
class VignetteTranscript:
    vignette_case_id: str
    turns: list[ConversationTurn]
    final_severity: str | None
    final_reasoning: str | None

    def text_up_to(self, turn_index: int | None = None) -> str:
        turns = self.turns if turn_index is None else self.turns[: turn_index + 1]
        lines = []
        for turn in turns:
            lines.append(f"Patient: {turn.patient_message}")
            lines.append(f"Assistant: {turn.system_response}")
        return "\n".join(lines)
