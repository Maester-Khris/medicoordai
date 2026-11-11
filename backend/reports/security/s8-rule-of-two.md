# S8. Rule of Two for the triage agent (2026-11-10)

Method: code reading at branch `chore/security-review` (from `feat/eval-hardening` @ ba16bc9), plus two live local experiments.

| Leg | Held? | Evidence |
|---|---|---|
| Untrusted input | **Yes** | Guest free text and history reach the model unredacted (S6); graph/lay-description data reaches the system prompt when `GRAPH_RAG_PROVIDER` is on (S9). |
| Sensitive data | **Yes** | Symptom text; coordinates stay in the backend (S6) but the conversation is health information. The agent has no data-reading tool, so it cannot read another guest's data. |
| Power to act / send data out | **Gated** | The agent has ONE tool, `triage_response` (a classification: severity, reasoning, sufficiency; `llm/tools.py`). No tool fetches a URL, sends mail or a notification, calls a webhook or runs code. The only backend side effect after a classification is `facility_load.record` (an in-memory/Redis counter used for ranking, behind `LOAD_AWARE_ROUTING`). Notifications (`routers/notifications.py`) are a separate user-authenticated route the agent cannot call. The one subprocess (`graph/semantic/build.py`) is launched by the index state machine with a command built from settings, not from model or user text. |
| Rendering exfiltration channel | **Absent** | The chat renders `msg.content` as plain React text (`ChatPanel.tsx:362`, `BottomSheet.tsx:42`): no markdown, images, links or HTML. The four `dangerouslySetInnerHTML` uses are static pages (Disclosure, Landing, FacilityLegend). |

Verdict: two of three legs held, third gated: Rule of Two **pass**.

## Findings

1. **High, fixed (ours): the model's severity was not validated.** `severity = args["severity"]` was used as given; the tool enum is only a hint to the model. Live experiment (rewriting proxy changing the model's severity to `critical`): the turn was held back for 3 follow-ups (only exactly `emergent` bypasses the minimum-turn gate), then the client received `severity: "critical"` (outside the four-value schema), no facility, and the reply said "call 211" for a chest-pain case. Fix: `services/llm_agent.py` validates against `VALID_SEVERITIES` and fails toward `emergent` with a `triage_invalid_severity` warning; `tests/llm/test_invalid_severity.py` (11 cases); live re-run: `emergent` + facility on the first turn (`s8-invalid-severity-after.txt`). Note for the eval: valid severities are unchanged, so existing results are unaffected; a run that previously produced an off-enum value would now count as `emergent`.
2. **Medium, open: output checks are advisory only.** `check_facility_groundedness` and `check_emergency_mismatch` only log; a reply that names another facility, or a classification below an emergency keyword, is still delivered. Plan: when not grounded, replace the reply with the existing template (`capped_reply`), and count `triage_ungrounded_total`. S7 measures how often the model drifts.
3. **Low, open: PostgREST filter built from the severity string** in the non-demo path (`services/facilities.py:46`, `f"cs.{{{severity}}}"`). The new validation closes it for agent-originated values; the `/facilities?severity=` query parameter is typed separately (S4 showed 422 on bad input).
4. **Low, open: `facility_load.record`** lets a guest nudge ranking counters by chatting; bounded by the per-guest rate limit (10 per 10 min) and only affects ordering.
