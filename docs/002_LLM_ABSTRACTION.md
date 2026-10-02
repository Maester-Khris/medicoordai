# ADR-003: LLM Provider Abstraction with Feature Flag

## Status
Accepted

## Context
The project needs a reliable LLM for symptom classification and chat response generation.
Two candidates exist: Groq (preferred for free tier) and Anthropic Claude (higher quality,
cost per token). The right choice may change as the project scales or API costs become relevant.

## Decision
Implement a provider abstraction layer in `backend/llm/` with a `LLM_PROVIDER` environment
variable (`groq` | `anthropic`) selecting the active implementation at startup.

Default: `groq`

Both implementations must conform to the same internal interface so switching providers
requires only a config change, not a code change.

## Consequences
- No provider-specific code outside of `backend/llm/groq.py` and `backend/llm/anthropic.py`
- Tool definitions in `backend/llm/tools.py` are provider-agnostic
- `LLM_PROVIDER` is managed in Doppler per environment (dev/staging/prod can differ)
- If Groq rate limits become a problem in production, flipping to Anthropic requires
  one Doppler config change and a Railway redeploy (`railway redeploy`) — no code change