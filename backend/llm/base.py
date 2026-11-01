from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str        # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolDefinition:
    """
    Provider-agnostic tool definition.
    Each client implementation translates this to its own wire format.
    Tool definitions are defined once in tools.py — never in provider files.
    """
    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[dict] | None
    finish_reason: str          # "stop" | "tool_calls" | "length"
    model: str
    usage: dict[str, int]       # prompt_tokens, completion_tokens


class BaseLLMClient(ABC):
    """
    Abstract interface all LLM implementations must satisfy.
    LLMAgent only interacts with this interface — never with provider classes directly.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...
