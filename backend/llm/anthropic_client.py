import json
import os
import anthropic
from config import llm_timeout_seconds
from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition


class AnthropicClient(BaseLLMClient):

    def __init__(self, max_retries: int | None = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        # max_retries=None keeps the SDK's own retries (single-provider mode). A fallback chain
        # passes 0: there the next provider is the retry.
        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = anthropic.Anthropic(**options)
        self._model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

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
        system_content = ""
        filtered = []
        for m in messages:
            if m.role == "system":
                system_content = m.content
            else:
                filtered.append(self._to_anthropic_message(m))

        anthropic_tools = [self._to_anthropic_tool(t) for t in tools] if tools else None

        tool_choice = None
        if force_tool:
            tool_choice = {"type": "tool", "name": force_tool}
        elif tools:
            tool_choice = {"type": "auto"}

        kwargs: dict = dict(
            model=self._model,
            max_tokens=1024,
            temperature=temperature,
            messages=filtered,
        )
        if system_content:
            kwargs["system"] = system_content
        if stop:
            kwargs["stop_sequences"] = stop
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
            kwargs["tool_choice"] = tool_choice

        resp = self._client.messages.create(**kwargs)

        content_text = None
        tool_calls = None

        for block in resp.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                tool_calls = tool_calls or []
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                })

        finish_reason = "tool_calls" if tool_calls else "stop"

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            model=self._model,
            usage={
                "prompt_tokens": resp.usage.input_tokens,
                "completion_tokens": resp.usage.output_tokens,
            },
        )

    def _to_anthropic_message(self, msg: LLMMessage) -> dict:
        if msg.role == "tool":
            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                }],
            }
        return {"role": msg.role, "content": msg.content}

    def _to_anthropic_tool(self, tool: ToolDefinition) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": "object",
                "properties": tool.parameters,
                "required": tool.required,
            },
        }
