"""
Deterministic (no LLM judge) groundedness check for triage Pass-2 responses.

The facility name is injected into the model's context as a fact before Pass 2
generates its response (see LLMAgent._generate_grounded_response). If the model
followed that fact instead of inventing a different name, the real facility name
appears verbatim in the response. This check confirms that — no LLM call, no
cost, safe to run on every logged session.
"""

from collections.abc import Sequence

from services.red_flags import find_red_flags


def check_facility_groundedness(response_text: str, facility: dict | None) -> dict:
    """
    Returns {"grounded": bool | None, "facility_name": str | None}.

    grounded is None when no facility was provided to the model at all (e.g. no
    location data) — there is nothing to check groundedness against in that case.
    """
    if facility is None:
        return {"grounded": None, "facility_name": None}

    name = facility["name"]
    return {
        "grounded": name.lower() in response_text.lower(),
        "facility_name": name,
    }


def reply_problem(response_text: str, facility: dict | None) -> str | None:
    """What is wrong with a patient-facing reply, if anything (deterministic, no model call).

    "not_prose": empty, a JSON or tool-call blob, or no letters at all.
    "ungrounded": a facility was chosen for this patient and the reply does not name it.
    A forged reply (a code word planted by injected text) names no facility, so it is "ungrounded";
    with no facility to name, only the prose check can catch it.
    """
    text = response_text.strip()
    if not text or text[0] in "{[" or '"arguments"' in text or not any(c.isalpha() for c in text):
        return "not_prose"
    if check_facility_groundedness(text, facility)["grounded"] is False:
        return "ungrounded"
    return None


def check_emergency_mismatch(user_messages: Sequence[str], severity: str) -> bool:
    """True (anomalous) when the patient's messages mention a red flag but the severity is not
    'emergent'. Deterministic, no model: a second check that does not rely on the prompt having held.
    It reads every patient message of the conversation, using the same pattern list as the floor
    (services.red_flags), so a negated or historical mention ("no chest pain") does not count."""
    return severity != "emergent" and bool(find_red_flags(user_messages))
