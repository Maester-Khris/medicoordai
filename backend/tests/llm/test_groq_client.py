"""
Unit tests for GroqClient's retry-once-on-malformed-tool-call behavior.
No real network access — the underlying Groq SDK client is mocked.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import httpx
import pytest
from groq import BadRequestError
from unittest.mock import MagicMock, patch

os.environ.setdefault("GROQ_API_KEY", "test-key")


def _tool_use_failed_error() -> BadRequestError:
    response = httpx.Response(
        status_code=400,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    return BadRequestError(
        "Error code: 400 - {'error': {'message': 'tool call validation failed: "
        "parameters for tool triage_response did not match schema: errors: "
        "[`/information_sufficient`: expected boolean, but got string]', "
        "'type': 'invalid_request_error', 'code': 'tool_use_failed'}}",
        response=response,
        body=None,
    )


def _ok_completion():
    function = MagicMock(arguments="{}")
    function.name = "triage_response"  # MagicMock(name=...) sets repr, not the attribute
    return MagicMock(
        choices=[MagicMock(
            finish_reason="tool_calls",
            message=MagicMock(content=None, tool_calls=[MagicMock(id="tc1", function=function)]),
        )],
        usage=MagicMock(prompt_tokens=10, completion_tokens=5),
    )


class TestGroqClientRetry:
    def test_retries_once_on_tool_use_failed_then_succeeds(self):
        from llm.groq_client import GroqClient
        from llm.base import LLMMessage
        from llm.tools import TRIAGE_RESPONSE

        client = GroqClient()
        with patch.object(
            client._client.chat.completions, "create",
            side_effect=[_tool_use_failed_error(), _ok_completion()],
        ) as mock_create:
            resp = asyncio.run(client.chat(
                messages=[LLMMessage(role="user", content="hi")],
                tools=[TRIAGE_RESPONSE],
            ))

        assert mock_create.call_count == 2
        assert resp.tool_calls[0]["name"] == "triage_response"

    def test_raises_after_second_failure(self):
        from llm.groq_client import GroqClient
        from llm.base import LLMMessage
        from llm.tools import TRIAGE_RESPONSE

        client = GroqClient()
        with patch.object(
            client._client.chat.completions, "create",
            side_effect=[_tool_use_failed_error(), _tool_use_failed_error()],
        ) as mock_create:
            with pytest.raises(BadRequestError):
                asyncio.run(client.chat(
                    messages=[LLMMessage(role="user", content="hi")],
                    tools=[TRIAGE_RESPONSE],
                ))

        assert mock_create.call_count == 2

    def test_does_not_retry_unrelated_bad_request(self):
        from llm.groq_client import GroqClient
        from llm.base import LLMMessage
        from llm.tools import TRIAGE_RESPONSE

        response = httpx.Response(
            status_code=400,
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )
        unrelated_error = BadRequestError("model not found", response=response, body=None)

        client = GroqClient()
        with patch.object(
            client._client.chat.completions, "create", side_effect=[unrelated_error],
        ) as mock_create:
            with pytest.raises(BadRequestError):
                asyncio.run(client.chat(
                    messages=[LLMMessage(role="user", content="hi")],
                    tools=[TRIAGE_RESPONSE],
                ))

        assert mock_create.call_count == 1
