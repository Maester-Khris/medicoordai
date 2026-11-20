"""Chat client that plays the patient through the headless `claude -p` CLI (subscription, no API key).

Eval-only. The call runs from an empty temp directory with no settings, tools or hooks, so the
project's CLAUDE.md and hooks never reach the patient. The manifest records `claude-cli:<model>`.
"""
import asyncio
import subprocess
import tempfile
from typing import Callable

from llm.base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition

CLI_MODEL = "claude-haiku-4-5"
CLI_TIMEOUT_SECONDS = 120


class ClaudeCliClient(BaseLLMClient):
    def __init__(self, model: str = CLI_MODEL, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self._model = model
        self._runner = runner
        self._cwd = tempfile.mkdtemp(prefix="claude-cli-patient-")

    @property
    def model_name(self) -> str:
        return f"claude-cli:{self._model}"

    async def chat(
        self, messages: list[LLMMessage], tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2, stop: list[str] | None = None, force_tool: str | None = None,
    ) -> LLMResponse:
        system = "\n".join(m.content for m in messages if m.role == "system")
        lines = [
            ("Triage assistant says: " if m.role == "user" else "You said: ") + m.content
            for m in messages if m.role != "system"
        ]
        prompt = "\n".join(lines) + "\nReply as the patient:"
        cmd = [
            "claude", "-p", "--model", self._model, "--system-prompt", system, "--tools", "",
            "--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config",
            "--setting-sources", "", "--output-format", "text",
        ]
        # ponytail: temperature is not settable on the CLI; the manifest model label says so.
        result = await asyncio.to_thread(
            self._runner, cmd, input=prompt, cwd=self._cwd, capture_output=True, text=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
        text = result.stdout.strip()
        if result.returncode != 0 or not text:
            raise RuntimeError(f"claude -p failed (exit {result.returncode}): {result.stderr.strip()[:200]}")
        return LLMResponse(content=text, tool_calls=None, finish_reason="stop", model=self.model_name, usage={})
