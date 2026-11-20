"""
RunVignetteConversation — the core multi-turn loop. Turn 0 sends the
vignette's static opening_message (deterministic, no LLM — design §7).
Turns 1..N are patient-simulator replies to the system's question,
checklist-gated so information surfaces only when asked. Stops when the
system fires a triage classification (severity is not None) or MAX_TURNS
is hit — a safety bound distinct from LLMAgent's own internal followup
ceiling (TRIAGE_MAX_FOLLOWUPS), which this harness doesn't reimplement.
"""
from scripts.symptom_eval.domain import ConversationTurn, Vignette, VignetteTranscript
from scripts.symptom_eval.patient_simulator import PatientSimulatorPort
from scripts.symptom_eval.system_under_test import SystemUnderTestPort

MAX_TURNS = 8


def run_vignette_conversation(
    vignette: Vignette,
    simulator: PatientSimulatorPort,
    system: SystemUnderTestPort,
    conversation_id: str,
) -> VignetteTranscript:
    history: list[dict] = []
    turns: list[ConversationTurn] = []
    patient_message = vignette.opening_message

    for turn_index in range(MAX_TURNS):
        result = system.respond(patient_message, history, conversation_id)
        turns.append(
            ConversationTurn(
                turn_index=turn_index,
                patient_message=patient_message,
                system_response=result.response_text,
                graph_context_matched=result.graph_context_matched,
                surfaced_red_flag_indicators=result.surfaced_red_flag_indicators,
                surfaced_followup_questions=result.surfaced_followup_questions,
                cap_reached=result.cap_reached,
                tokens_used=result.tokens_used,
                complaint_name=result.complaint_name,
            )
        )
        history.append({"role": "user", "content": patient_message})
        history.append({"role": "assistant", "content": result.response_text})

        if result.severity is not None:
            return VignetteTranscript(
                vignette_case_id=vignette.case_id, turns=turns,
                final_severity=result.severity, final_reasoning=result.reasoning,
            )

        patient_message = simulator.reply(vignette, result.response_text, turns)

    return VignetteTranscript(
        vignette_case_id=vignette.case_id, turns=turns,
        final_severity=None, final_reasoning=None,
    )
