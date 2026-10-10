"""Ordered fallback over several LLM provider clients.

In-process on purpose: it is the smallest thing that shows a provider failing and the next one
answering. The intended next step is a deployed gateway that does the same job outside the API;
this class is the seam where it would plug in.
"""
import logging

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .instrumented import classify_llm_error, worth_trying_another_provider

logger = logging.getLogger(__name__)


def _provider_name(client: BaseLLMClient) -> str:
    return getattr(client, "provider", type(client).__name__)


class FallbackLLMClient(BaseLLMClient):
    """Tries each client once, in order, until one answers.

    Moves on only for failures that belong to the provider (see worth_trying_another_provider).
    Anything else is raised at once: another provider would fail the same way, and switching
    would hide a bug. No retry of the same provider, no sleep, no memory between calls.
    """

    def __init__(self, clients: list[BaseLLMClient]) -> None:
        if not clients:
            raise ValueError("FallbackLLMClient needs at least one client")
        self._clients = clients
        self._answered_by = clients[0]

    @property
    def model_name(self) -> str:
        return self._answered_by.model_name

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        last = len(self._clients) - 1
        for position, client in enumerate(self._clients):
            try:
                response = client.chat(
                    messages=messages, tools=tools, temperature=temperature, stop=stop, force_tool=force_tool,
                )
            except Exception as exc:
                if position == last or not worth_trying_another_provider(exc):
                    raise
                logger.warning(
                    "llm_fallback",
                    extra={
                        "from_provider": _provider_name(client),
                        "to_provider": _provider_name(self._clients[position + 1]),
                        "outcome": classify_llm_error(exc),
                    },
                )
                continue
            self._answered_by = client
            return response
        raise AssertionError("unreachable: the loop returns or raises")
