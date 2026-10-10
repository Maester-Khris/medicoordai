import os

from openai import OpenAI

from config import llm_timeout_seconds

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition


class OpenAIClient(BaseLLMClient):
    """OpenAI chat completions behind the provider interface. Same request and response shape as
    GroqClient, without the tool_use_failed retry, which is specific to Groq."""

    def __init__(self, max_retries: int | None = None) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        # No default model on purpose: which model answers patients is an explicit choice.
        model = os.environ.get("OPENAI_MODEL", "").strip()
        if not model:
            raise RuntimeError("OPENAI_MODEL is not set")
        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = OpenAI(**options)
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "messages": [self._to_openai_message(m) for m in messages],
            "temperature": temperature,
        }
        if stop:
            kwargs["stop"] = stop
        if tools:
            kwargs["tools"] = [self._to_openai_tool(t) for t in tools]
            kwargs["tool_choice"] = (
                {"type": "function", "function": {"name": force_tool}} if force_tool else "auto"
            )

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        # Read the tool calls themselves, not finish_reason: with a forced tool choice OpenAI
        # reports "stop" while still returning the call.
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in choice.message.tool_calls
            ]

        return LLMResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            model=self._model,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
            },
        )

    def _to_openai_message(self, msg: LLMMessage) -> dict:
        m: dict = {"role": msg.role, "content": msg.content or ""}
        if msg.tool_call_id:
            m["tool_call_id"] = msg.tool_call_id
        if msg.name:
            m["name"] = msg.name
        return m

    def _to_openai_tool(self, tool: ToolDefinition) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters,
                    "required": tool.required,
                },
            },
        }
