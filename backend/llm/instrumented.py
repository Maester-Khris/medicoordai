"""Timing and outcome counting for any LLM provider client, and the one place that decides what
kind of failure a provider error is.

Provider clients stay free of metric code: the factory wraps each of them in
InstrumentedLLMClient. The classifier reads only `status_code` and exception class names, which
the Groq, OpenAI and Anthropic SDKs all expose, so this module imports none of them.
"""
from metrics import LLM_CALL_DURATION, LLM_CALLS, LLM_TOKENS, timed

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition


def _class_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def classify_llm_error(exc: BaseException) -> str:
    """rate_limited, timeout or error: the outcome label for a failed provider call."""
    if getattr(exc, "status_code", None) == 429:
        return "rate_limited"
    if isinstance(exc, TimeoutError) or any("Timeout" in name for name in _class_names(exc)):
        return "timeout"
    return "error"


def worth_trying_another_provider(exc: BaseException) -> bool:
    """True when the failure belongs to this provider: rate limit, timeout, its server, the
    connection to it, or its credentials (a revoked key must not take the chat down while another
    provider works). False for a request another provider would reject too."""
    if classify_llm_error(exc) in ("rate_limited", "timeout"):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status >= 500 or status in (401, 403)
    return isinstance(exc, ConnectionError) or any("Connection" in name for name in _class_names(exc))


class InstrumentedLLMClient(BaseLLMClient):
    """Wraps one provider client: every call is timed and counted under `provider`."""

    def __init__(self, inner: BaseLLMClient, provider: str) -> None:
        self._inner = inner
        self.provider = provider

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        outcome = "ok"
        try:
            with timed(LLM_CALL_DURATION, provider=self.provider) as timing:
                try:
                    response = self._inner.chat(
                        messages=messages, tools=tools, temperature=temperature, stop=stop, force_tool=force_tool,
                    )
                except Exception as exc:
                    outcome = timing.outcome = classify_llm_error(exc)
                    raise
        finally:
            LLM_CALLS.labels(provider=self.provider, outcome=outcome).inc()

        usage = response.usage or {}
        LLM_TOKENS.labels(provider=self.provider, kind="prompt").inc(usage.get("prompt_tokens") or 0)
        LLM_TOKENS.labels(provider=self.provider, kind="completion").inc(usage.get("completion_tokens") or 0)
        return response
