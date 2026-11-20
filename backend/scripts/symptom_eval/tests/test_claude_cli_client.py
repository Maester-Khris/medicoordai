import asyncio
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from llm.base import LLMMessage
from scripts.symptom_eval.claude_cli_client import ClaudeCliClient


def _chat(client, messages):
    return asyncio.run(client.chat(messages=messages, tools=None, temperature=0.3))


class _Recorder:
    def __init__(self, stdout="It lasted a few seconds.\n", returncode=0):
        self.calls = []
        self._result = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="auth warning")

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return self._result


MESSAGES = [
    LLMMessage(role="system", content="You are a patient."),
    LLMMessage(role="user", content="Where does it hurt?"),
    LLMMessage(role="assistant", content="My head."),
    LLMMessage(role="user", content="How long?"),
]


def test_model_name_marks_the_cli_in_the_manifest():
    assert ClaudeCliClient(runner=_Recorder()).model_name == "claude-cli:claude-haiku-4-5"


def test_reply_is_stdout_stripped_and_stderr_is_ignored():
    assert _chat(ClaudeCliClient(runner=_Recorder()), MESSAGES).content == "It lasted a few seconds."


def test_system_message_goes_to_system_prompt_and_history_to_stdin():
    recorder = _Recorder()
    _chat(ClaudeCliClient(runner=recorder), MESSAGES)
    cmd, kwargs = recorder.calls[0]
    assert cmd[cmd.index("--system-prompt") + 1] == "You are a patient."
    assert "Where does it hurt?" in kwargs["input"] and "My head." in kwargs["input"]
    assert kwargs["input"].rstrip().endswith("Reply as the patient:")


def test_runs_isolated_from_project_settings_hooks_and_tools():
    recorder = _Recorder()
    _chat(ClaudeCliClient(runner=recorder), MESSAGES)
    cmd, kwargs = recorder.calls[0]
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--no-session-persistence" in cmd
    assert kwargs["cwd"] != os.getcwd()


def test_failed_cli_raises_instead_of_returning_empty_text():
    with pytest.raises(RuntimeError):
        _chat(ClaudeCliClient(runner=_Recorder(stdout="", returncode=1)), MESSAGES)
