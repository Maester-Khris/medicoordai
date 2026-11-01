import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import MagicMock, patch

from llm.base import BaseLLMClient, LLMResponse
from services import llm_agent
from services.llm_agent import LLMAgent, get_agent


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _ProbeClient(BaseLLMClient):
    """Answers with a follow-up question and records whether it was called on the event loop."""

    def __init__(self) -> None:
        self.called_on_loop: list[bool] = []

    @property
    def model_name(self) -> str:
        return "probe"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.called_on_loop.append(_on_event_loop())
        return LLMResponse(content="Since when?", tool_calls=None, finish_reason="stop",
                           model="probe", usage={"prompt_tokens": 1, "completion_tokens": 1})


def test_respond_is_a_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(LLMAgent.respond)


def test_the_agent_awaits_the_client_on_the_event_loop() -> None:
    client = _ProbeClient()
    result = asyncio.run(LLMAgent(client=client).respond("I feel dizzy", []))
    assert result["turn_type"] == "followup" and result["response"] == "Since when?"
    assert client.called_on_loop == [True]


def test_get_agent_builds_one_agent_per_process() -> None:
    with patch.object(llm_agent, "_agent", None), \
         patch.object(llm_agent, "get_llm_client", return_value=MagicMock()) as build:
        first = get_agent()
        assert get_agent() is first
    assert build.call_count == 1
