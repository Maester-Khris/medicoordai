import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

import config
from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.retry import RetryBudget, RetryingLLMClient, shared_retry_budget
from observability import _registry


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _budget(percent: int = 10) -> tuple[RetryBudget, _Clock]:
    clock = _Clock()
    return RetryBudget(percent=percent, clock=clock), clock


def _allowed(budget: RetryBudget, attempts: int) -> int:
    return sum(1 for _ in range(attempts) if budget.allow_retry())


def test_with_100_calls_at_10_percent_exactly_10_retries_are_allowed() -> None:
    budget, _ = _budget(10)
    for _ in range(100):
        budget.record_call()
    assert _allowed(budget, 15) == 10


def test_at_low_traffic_the_floor_of_3_retries_applies() -> None:
    budget, _ = _budget(10)
    for _ in range(5):
        budget.record_call()
    assert _allowed(budget, 6) == 3


def test_the_allowance_returns_after_the_window_passes() -> None:
    budget, clock = _budget(10)
    for _ in range(5):
        budget.record_call()
    assert _allowed(budget, 6) == 3
    clock.now += 61
    assert budget.allow_retry() is True


def test_a_higher_percent_allows_more() -> None:
    budget, _ = _budget(50)
    for _ in range(100):
        budget.record_call()
    assert _allowed(budget, 80) == 50


class _FailingThenOk(BaseLLMClient):
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "fake"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.failures:
            err = Exception("overloaded")
            err.status_code = 503  # type: ignore[attr-defined]
            raise err
        return LLMResponse(content="ok", tool_calls=None, finish_reason="stop", model="fake", usage={})


class _Denying:
    def __init__(self) -> None:
        self.recorded = 0

    def record_call(self) -> None:
        self.recorded += 1

    def allow_retry(self) -> bool:
        return False


def _run(client: RetryingLLMClient) -> LLMResponse:
    return asyncio.run(client.chat(messages=[LLMMessage(role="user", content="hi")]))


def _no_sleep(sleeps: list[float]):
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
    return sleep


def test_an_exhausted_budget_raises_the_original_error_without_retrying_or_sleeping() -> None:
    inner, sleeps, denying = _FailingThenOk(failures=1), [], _Denying()
    before = _registry.get_sample_value("llm_retry_budget_exhausted_total", {"provider": "p1"}) or 0
    client = RetryingLLMClient(inner, provider="p1", attempts=3, sleep=_no_sleep(sleeps), budget=denying)
    with pytest.raises(Exception, match="overloaded"):
        _run(client)
    assert inner.calls == 1 and sleeps == [] and denying.recorded == 1
    assert _registry.get_sample_value("llm_retry_budget_exhausted_total", {"provider": "p1"}) == before + 1


def test_an_available_budget_lets_the_retry_happen() -> None:
    budget, _ = _budget(10)
    inner, sleeps = _FailingThenOk(failures=1), []
    client = RetryingLLMClient(inner, provider="p2", attempts=3, sleep=_no_sleep(sleeps), budget=budget)
    assert _run(client).content == "ok"
    assert inner.calls == 2 and len(sleeps) == 1


def test_without_a_budget_retries_work_as_before() -> None:
    inner, sleeps = _FailingThenOk(failures=1), []
    assert _run(RetryingLLMClient(inner, provider="p3", attempts=2, sleep=_no_sleep(sleeps))).content == "ok"
    assert inner.calls == 2


def test_the_shared_budget_is_one_object_built_from_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    assert shared_retry_budget() is shared_retry_budget()


@pytest.mark.parametrize("raw,expected", [(None, 10), ("25", 25), ("0", 10), ("101", 10), ("x", 10), ("", 10), (" 30 ", 30)])
def test_the_budget_percent_setting_falls_back_to_10(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int) -> None:
    if raw is None:
        monkeypatch.delenv("RETRY_BUDGET_PERCENT", raising=False)
    else:
        monkeypatch.setenv("RETRY_BUDGET_PERCENT", raw)
    assert config.retry_budget_percent() == expected
