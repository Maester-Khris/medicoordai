# Token Budget per LLM Provider (Layer 4): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat turn moves to the next LLM provider before the current one refuses it, and the answer to an emergent triage is never refused by our own budget.

**Architecture:** `BudgetedLLMClient` wraps one provider client behind the existing `BaseLLMClient` port, with an in-process token bucket at 90% of that provider's tokens per minute and a cooldown after the provider's own 429. Its refusal is a 429, which `FallbackLLMClient` already answers from the next provider. A context variable marks the emergent answer as priority, so no signature changes.

**Tech Stack:** Python 3.11, FastAPI, asyncio, prometheus-client, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-emergent-er-routing-and-llm-budget-design.md` (part 2)

## Global Constraints

- Budget share: `BUDGET_SHARE = 0.9` of `LLM_TPM_<PROVIDER>`. A provider without the setting is not wrapped.
- Only in chain mode (`LLM_PROVIDER_CHAIN` set): with one provider a budget refusal could only become a busy answer sooner.
- Emergent answers are never refused by the budget; debt is bounded at minus the bucket's capacity.
- No Redis, no new dependency.
- Severity values: `routine | moderate | urgent | emergent` only.
- Python only from `/home/niki/Documents/workenv/pydev/`; tests through `doppler run --`.
- Branch `feat/llm-provider-budget` cut from `preview`. One-line conventional commits, files staged by name, no AI attribution, every commit shown to the owner first.
- Model names are always pinned by env var: `ANTHROPIC_MODEL=claude-haiku-4-5` on every service.

## Review Focus

- An estimate larger than the whole bucket (a very long conversation): an ordinary call must go to the next provider, not wait or loop. Test in Task 2.
- A provider 429 without a `Retry-After` header: the cooldown falls back to 60 s. Test in Task 2.
- A call that fails for any reason: its estimate is given back, so failures do not drain the budget. Test in Task 2.
- Many emergent calls in a row: the debt stops at minus the capacity, and ordinary calls are refused until it refills. Test in Task 2.
- Every provider in the chain refusing: the guest gets the existing busy answer (status 429 reaches `routers/chat.py`), not a 500. Test in Task 2 (fallback raises the 429).

---

### Task 1: Turn on the chain with today's code (configuration only, can run before Friday)

**Files:** none. Doppler `stg` (feeds python-api) and Railway variables of `medicoordai-staging`.

**Interfaces:**
- Produces: `LLM_PROVIDER_CHAIN=groq,anthropic` on both services. The reactive fallback (switch after a 429) is live from here; Tasks 2 to 4 make it proactive.

- [ ] **Step 1: python-api through Doppler (owner's go first)**

```bash
doppler secrets set LLM_PROVIDER_CHAIN=groq,anthropic --project medicoord --config stg
doppler secrets get ANTHROPIC_MODEL LLM_PROVIDER_CHAIN --project medicoord --config stg --plain
```

Expected: `claude-haiku-4-5` and `groq,anthropic`.

- [ ] **Step 2: staging (stopped, so no deploy)**

```bash
cd backend && railway variable set --service medicoordai-staging LLM_PROVIDER_CHAIN=groq,anthropic --skip-deploys
```

- [ ] **Step 3: Check both services and the python-api deploy**

Run: `railway variables --service python-api --json` and the same for `medicoordai-staging`, printing only `LLM_PROVIDER_CHAIN` and `ANTHROPIC_MODEL`.
Expected: `groq,anthropic` and `claude-haiku-4-5` on both. Then `railway deployment list --service python-api --json`: the Doppler sync started a new deployment, `SUCCESS`, same commit hash.

- [ ] **Step 4: One real turn on the public demo**

Same commands as Task 4 Step 5 of `2026-10-14-emergent-er-only.md`, with any routine symptom. Expected: an answer, no error. Then `GET /metrics` (bearer token from Doppler, never printed) shows `llm_calls_total{provider="groq",outcome="ok"}` increasing.

### Task 2: The budget wrapper

**Files:**
- Create: `backend/llm/budget.py`
- Modify: `backend/metrics.py` (after `LLM_TOKENS`)
- Test: `backend/tests/llm/test_budget.py` (new)

**Interfaces:**
- Consumes: `llm.base.BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition`; `llm.fallback.FallbackLLMClient` (unchanged).
- Produces: `priority_call()` context manager; `ProviderBudgetExhausted(provider: str)` with `status_code = 429`; `TokenBucket(capacity: float, clock: Callable[[], float])` with `take(count: float, priority: bool) -> bool`, `give_back(count: float) -> None`, `tokens` property; `estimate_tokens(messages: list[LLMMessage], tools: list[ToolDefinition] | None) -> int`; `BudgetedLLMClient(inner: BaseLLMClient, provider: str, tokens_per_minute: int, clock: Callable[[], float] = time.monotonic)`; metric `LLM_BUDGET_REFUSALS` labelled `provider`, `reason` (`budget` | `cooldown`).

- [ ] **Step 1: Branch**

```bash
cd /home/niki/Documents/saas/medicoordai && git fetch origin && git switch -c feat/llm-provider-budget origin/preview
```

- [ ] **Step 2: Write the failing tests**

```python
"""Token budget per provider: switch before the provider refuses; emergent answers never refused."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.budget import (
    BudgetedLLMClient,
    ProviderBudgetExhausted,
    TokenBucket,
    estimate_tokens,
    priority_call,
)
from llm.fallback import FallbackLLMClient


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _RateLimited(Exception):
    status_code = 429

    def __init__(self, retry_after: str | None) -> None:
        super().__init__("rate limited")
        self.response = type("R", (), {"headers": {"retry-after": retry_after} if retry_after else {}})()


class _Fake(BaseLLMClient):
    def __init__(self, provider: str, used: int = 100, error: Exception | None = None) -> None:
        self.provider, self.used, self.error, self.calls = provider, used, error, 0

    @property
    def model_name(self) -> str:
        return f"{self.provider}-model"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResponse(content=self.provider, tool_calls=None, finish_reason="stop", model=self.model_name,
                           usage={"prompt_tokens": self.used, "completion_tokens": 0})


SHORT = [LLMMessage(role="user", content="x" * 400)]          # 100 + 400 allowance = 500 tokens estimated
LONG = [LLMMessage(role="user", content="x" * 40_000)]        # 10,400 tokens estimated


def test_the_estimate_is_text_over_four_plus_a_completion_allowance() -> None:
    assert estimate_tokens(SHORT, None) == 500


def test_the_bucket_refills_at_its_capacity_per_minute() -> None:
    clock = Clock()
    bucket = TokenBucket(600, clock)
    assert bucket.take(600, priority=False)
    assert not bucket.take(1, priority=False)
    clock.now += 30
    assert bucket.tokens == pytest.approx(300)


def test_priority_takes_into_debt_down_to_minus_the_capacity_only() -> None:
    bucket = TokenBucket(600, Clock())
    for _ in range(5):
        assert bucket.take(500, priority=True)
    assert bucket.tokens == pytest.approx(-600)
    assert not bucket.take(1, priority=False)


def test_a_spent_budget_moves_the_call_to_the_next_provider_without_calling_the_first() -> None:
    clock = Clock()
    groq = _Fake("groq", used=500)   # the first call really spends its 500-token estimate
    budgeted = BudgetedLLMClient(groq, "groq", tokens_per_minute=1000, clock=clock)   # bucket of 900, 400 left after it
    chain = FallbackLLMClient([budgeted, _Fake("anthropic")])
    assert asyncio.run(chain.chat(SHORT)).content == "groq"
    assert asyncio.run(chain.chat(SHORT)).content == "anthropic"
    assert groq.calls == 1


def test_a_call_larger_than_the_whole_bucket_goes_to_the_next_provider() -> None:
    chain = FallbackLLMClient([BudgetedLLMClient(_Fake("groq"), "groq", 8000, Clock()), _Fake("anthropic")])
    assert asyncio.run(chain.chat(LONG)).content == "anthropic"


def test_an_emergent_answer_is_never_refused_by_the_budget() -> None:
    groq = _Fake("groq")
    budgeted = BudgetedLLMClient(groq, "groq", tokens_per_minute=1000, clock=Clock())
    with priority_call():
        for _ in range(4):
            assert asyncio.run(budgeted.chat(SHORT)).content == "groq"
    assert groq.calls == 4


def test_the_real_usage_corrects_the_estimate() -> None:
    clock = Clock()
    budgeted = BudgetedLLMClient(_Fake("groq", used=50), "groq", tokens_per_minute=1000, clock=clock)
    asyncio.run(budgeted.chat(SHORT))
    assert budgeted._bucket.tokens == pytest.approx(850)


def test_a_failed_call_gives_its_estimate_back() -> None:
    budgeted = BudgetedLLMClient(_Fake("groq", error=RuntimeError("boom")), "groq", 1000, Clock())
    with pytest.raises(RuntimeError):
        asyncio.run(budgeted.chat(SHORT))
    assert budgeted._bucket.tokens == pytest.approx(900)


@pytest.mark.parametrize("retry_after, cooled_for", [("120", 120), (None, 60)])
def test_a_provider_429_cools_it_down_for_its_retry_after(retry_after, cooled_for) -> None:
    clock = Clock()
    groq = _Fake("groq", error=_RateLimited(retry_after))
    budgeted = BudgetedLLMClient(groq, "groq", 8000, clock)
    with pytest.raises(_RateLimited):
        asyncio.run(budgeted.chat(SHORT))
    groq.error = None
    clock.now += cooled_for - 1
    with pytest.raises(ProviderBudgetExhausted):
        asyncio.run(budgeted.chat(SHORT))
    clock.now += 2
    assert asyncio.run(budgeted.chat(SHORT)).content == "groq"


def test_when_every_provider_refuses_the_caller_gets_a_429() -> None:
    chain = FallbackLLMClient([BudgetedLLMClient(_Fake("groq"), "groq", 8000, Clock()),
                               BudgetedLLMClient(_Fake("anthropic"), "anthropic", 8000, Clock())])
    with pytest.raises(ProviderBudgetExhausted) as refused:
        asyncio.run(chain.chat(LONG))
    assert refused.value.status_code == 429
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd backend && source /home/niki/Documents/workenv/pydev/bin/activate && doppler run -- pytest tests/llm/test_budget.py -v`
Expected: FAIL at import: `No module named 'llm.budget'`.

- [ ] **Step 4: Add the metric to `backend/metrics.py`** (after `LLM_TOKENS`)

```python
LLM_BUDGET_REFUSALS = Counter(
    "llm_budget_refusals_total",
    "LLM calls refused before reaching the provider: its token budget was spent, or it is cooling down after a 429",
    ["provider", "reason"], registry=_registry,
)
```

- [ ] **Step 5: Write `backend/llm/budget.py`**

```python
"""Token budget per LLM provider: layer 4 of the rate limiting.

Each provider client is wrapped in a token bucket of BUDGET_SHARE of that provider's tokens per
minute. A call the bucket cannot cover raises ProviderBudgetExhausted, a 429 that FallbackLLMClient
already answers from the next provider, so the switch happens before the provider refuses. After the
provider's own 429 the wrapper stops sending to it until its Retry-After, which also covers a daily
cap. Priority calls (the answer to an emergent triage) are never refused by the budget: they may take
it into debt down to minus its capacity, which ordinary calls pay back as it refills.

In process on purpose: the demo runs one process, so the bucket is exact and no network call is added
to a turn. Several processes each set their share in LLM_TPM_<PROVIDER>, as GEOAPIFY_RATE_PER_SECOND
does; a shared counter belongs to the gateway. Everything runs on the event loop, so no lock.
"""
import contextlib
import contextvars
import json
import time
from collections.abc import Callable, Iterator

from metrics import LLM_BUDGET_REFUSALS

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition

BUDGET_SHARE = 0.9
CHARS_PER_TOKEN = 4
COMPLETION_ALLOWANCE = 400      # tokens back from one call; Sprint 21 measured about 345
DEFAULT_COOLDOWN_SECONDS = 60.0

_priority: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_priority", default=False)


@contextlib.contextmanager
def priority_call() -> Iterator[None]:
    """Calls made inside are never refused by a budget (the answer to an emergent triage)."""
    token = _priority.set(True)
    try:
        yield
    finally:
        _priority.reset(token)


class ProviderBudgetExhausted(Exception):
    """Our own refusal, shaped like the provider's: the fallback moves on, the chat route answers busy."""

    status_code = 429

    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider}: token budget spent or cooling down")


class TokenBucket:
    def __init__(self, capacity: float, clock: Callable[[], float]) -> None:
        self.capacity = capacity
        self._per_second = capacity / 60.0
        self._clock = clock
        self._tokens = capacity
        self._last = clock()

    @property
    def tokens(self) -> float:
        self._refill()
        return self._tokens

    def take(self, count: float, priority: bool) -> bool:
        self._refill()
        if priority:
            self._tokens = max(-self.capacity, self._tokens - count)
            return True
        if self._tokens < count:
            return False
        self._tokens -= count
        return True

    def give_back(self, count: float) -> None:
        """Positive returns tokens; negative charges the part of a call the estimate missed."""
        self._refill()
        self._tokens = max(-self.capacity, min(self.capacity, self._tokens + count))

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self._per_second)
        self._last = now


def estimate_tokens(messages: list[LLMMessage], tools: list[ToolDefinition] | None) -> int:
    chars = sum(len(m.content or "") for m in messages)
    chars += sum(len(t.description) + len(json.dumps(t.parameters)) for t in tools or [])
    return chars // CHARS_PER_TOKEN + COMPLETION_ALLOWANCE


def retry_after_seconds(exc: BaseException) -> float:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return max(1.0, float(headers.get("retry-after")))
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_SECONDS


class BudgetedLLMClient(BaseLLMClient):
    def __init__(self, inner: BaseLLMClient, provider: str, tokens_per_minute: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._inner = inner
        self.provider = provider
        self._clock = clock
        self._bucket = TokenBucket(tokens_per_minute * BUDGET_SHARE, clock)
        self._cool_until = 0.0

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        if self._clock() < self._cool_until:
            self._refuse("cooldown")
        estimate = estimate_tokens(messages, tools)
        if not self._bucket.take(estimate, priority=_priority.get()):
            self._refuse("budget")
        try:
            response = await self._inner.chat(
                messages=messages, tools=tools, temperature=temperature, stop=stop, force_tool=force_tool,
            )
        except Exception as exc:
            self._bucket.give_back(estimate)
            if getattr(exc, "status_code", None) == 429:
                self._cool_until = self._clock() + retry_after_seconds(exc)
            raise
        usage = response.usage or {}
        self._bucket.give_back(estimate - (usage.get("prompt_tokens") or 0) - (usage.get("completion_tokens") or 0))
        return response

    def _refuse(self, reason: str) -> None:
        LLM_BUDGET_REFUSALS.labels(provider=self.provider, reason=reason).inc()
        raise ProviderBudgetExhausted(self.provider)
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && doppler run -- pytest tests/llm/test_budget.py tests/llm/test_fallback.py -v`
Expected: all passed.

- [ ] **Step 7: Commit (show the diff first)**

```bash
git add backend/llm/budget.py backend/metrics.py backend/tests/llm/test_budget.py
git commit -m "feat(llm): add a token budget per provider that hands a call to the next provider before a 429"
```

### Task 3: Wrap the chain's providers that have a budget, and mark the emergent answer as priority

**Files:**
- Modify: `backend/config.py` (after `llm_provider_chain`)
- Modify: `backend/services/llm_agent.py` (`get_llm_client` chain loop; `_handle_triage` around `_generate_grounded_response`)
- Test: `backend/tests/llm/test_client_factory.py`, `backend/tests/llm/test_agent_recommendation.py`

**Interfaces:**
- Consumes: `BudgetedLLMClient`, `priority_call`, `llm.budget._priority` from Task 2.
- Produces: `config.llm_tokens_per_minute(provider: str) -> int` (0 = no budget).

- [ ] **Step 1: Write the failing tests**

In `tests/llm/test_client_factory.py`, add `"LLM_TPM_GROQ"` to the names the `_env` fixture deletes, then:

```python
from llm.budget import BudgetedLLMClient


def test_a_chain_provider_with_a_tokens_per_minute_setting_is_budgeted(monkeypatch: pytest.MonkeyPatch, _env) -> None:
    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "groq,anthropic")
    monkeypatch.setenv("LLM_TPM_GROQ", "8000")
    client = get_llm_client()
    first, second = client._clients  # type: ignore[attr-defined]
    assert isinstance(first, BudgetedLLMClient) and first.provider == "groq"
    assert isinstance(second, InstrumentedLLMClient) and second.provider == "anthropic"


def test_a_single_provider_is_never_budgeted(monkeypatch: pytest.MonkeyPatch, _env) -> None:
    monkeypatch.setenv("LLM_TPM_GROQ", "8000")
    assert isinstance(get_llm_client(), InstrumentedLLMClient)
```

In `tests/llm/test_agent_recommendation.py`:

```python
import pytest

from llm import budget


@pytest.mark.parametrize("severity, answer_is_priority", [("emergent", True), ("moderate", False)])
def test_only_the_answer_to_an_emergent_triage_is_a_priority_call(severity: str, answer_is_priority: bool) -> None:
    seen: list[bool] = []
    client = _client(severity)
    replies = list(client.chat.side_effect)

    async def chat(*args, **kwargs):
        seen.append(budget._priority.get())
        return replies.pop(0)

    client.chat = chat
    with patch("services.llm_agent.find_nearest_facilities", return_value=[A, B]), \
         patch("services.llm_agent.rank_facilities", return_value=[B, A]), \
         patch("services.llm_agent.facility_load.record"):
        asyncio.run(LLMAgent(client=client).respond("No", HISTORY, lat=HERE[0], lng=HERE[1]))

    assert seen == [False, answer_is_priority]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && doppler run -- pytest tests/llm/test_client_factory.py tests/llm/test_agent_recommendation.py -v`
Expected: the new tests FAIL (`first` is an `InstrumentedLLMClient`; `seen == [False, False]` for emergent).

- [ ] **Step 3: Implement**

`backend/config.py`, after `llm_provider_chain`:

```python
def llm_tokens_per_minute(provider: str) -> int:
    """This process's share of a provider's tokens per minute (LLM_TPM_GROQ, ...); 0 means no budget."""
    return env_int(f"LLM_TPM_{provider.upper()}", 0, minimum=0, maximum=100_000_000)
```

`backend/services/llm_agent.py`: imports

```python
import contextlib
from config import llm_provider_chain, llm_tokens_per_minute
from llm.budget import BudgetedLLMClient, priority_call
```

In `get_llm_client`, the chain loop body becomes:

```python
        try:
            client = InstrumentedLLMClient(_build_provider_client(provider, 0), provider)
        except RuntimeError as exc:  # a missing key or model
            logger.warning("llm_provider_skipped", extra={"provider": provider, "reason": str(exc)})
            continue
        tokens_per_minute = llm_tokens_per_minute(provider)
        clients.append(BudgetedLLMClient(client, provider, tokens_per_minute) if tokens_per_minute else client)
```

In `_handle_triage`, around the grounded answer:

```python
        answer_priority = priority_call() if severity == "emergent" else contextlib.nullcontext()
        with answer_priority:
            response_text = await self._generate_grounded_response(
                messages=messages,
                severity=severity,
                reasoning=reasoning,
                facility=recommended_facility,
            )
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `cd backend && doppler run -- pytest tests/llm -v && doppler run -- pytest -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/services/llm_agent.py backend/tests/llm/test_client_factory.py backend/tests/llm/test_agent_recommendation.py
git commit -m "feat(llm): budget the chain's providers that have a tokens-per-minute setting and never refuse an emergent answer"
```

### Task 4: Document the setting and record the deferred layers

**Files:**
- Modify: `docs/API.md` (settings table near line 254; the fallback paragraph near line 274)
- Modify: `CHANGELOG.md` (open sprint; `[Deferred — v2.1+]` section)

- [ ] **Step 1: `docs/API.md` settings row** (after `LLM_PROVIDER_CHAIN`)

```markdown
| `LLM_TPM_<PROVIDER>` | unset (no budget) | This process's share of a provider's tokens per minute, e.g. `LLM_TPM_GROQ=8000`. Chain mode only: past 90% of it, a call goes to the next provider before the provider refuses; the answer to an emergent triage is never refused |
```

And one sentence at the end of the fallback paragraph: `A provider that answers 429 is skipped until its Retry-After (60 s without one).`

- [ ] **Step 2: Changelog**

Under the open sprint, a bullet: `Token budget per LLM provider (layer 4): with LLM_PROVIDER_CHAIN set, a call moves to the next provider at 90% of LLM_TPM_<PROVIDER>, and a provider is skipped after its own 429 until Retry-After. Emergent answers are never refused by the budget.`

Under `[Deferred — v2.1+]`:

```markdown
- **Required before a production launch: tokens per user (rate-limit layer 3).** A token bucket per guest; not on the demo, where the 10-turns-per-10-minutes window already caps a guest. Design: `docs/superpowers/specs/2026-10-14-emergent-er-routing-and-llm-budget-design.md`.
- **Watch during the demo:** busy answers (request window or turns-in-flight limit) on turns that come back emergent once retried; emergent is not exempt from those two layers yet, since severity is known only after the LLM call. Also watch conversations that move from Groq to Anthropic mid-way.
```

- [ ] **Step 3: Commit**

```bash
git add docs/API.md CHANGELOG.md
git commit -m "docs: document the per-provider token budget and record the deferred rate-limit layers"
```

### Task 5: Configure, deploy, verify

**Files:** none. Doppler `stg`, Railway variables.

- [ ] **Step 1: Settings (owner's go)**

```bash
doppler secrets set LLM_TPM_GROQ=8000 --project medicoord --config stg
cd backend && railway variable set --service medicoordai-staging LLM_TPM_GROQ=8000 --skip-deploys
```

- [ ] **Step 2: PR to `preview`, merge, python-api deploys the branch code**

Verify with `railway deployment list --service python-api --json`: newest `SUCCESS` on the merge commit.

- [ ] **Step 3: Live checks**

- `GET /health` ok.
- One routine turn (Task 1 Step 4 commands): an answer.
- `GET /metrics`: `llm_budget_refusals_total` is present (0 at rest), and `llm_calls_total` by provider.
- To see the switch on purpose: on staging only (start it, mock not needed), set `LLM_TPM_GROQ=600` so one turn spends the bucket; send two turns; expect `llm_calls_total{provider="anthropic"}` to rise and `llm_budget_refusals_total{provider="groq",reason="budget"}` to be 1 or more. Put `LLM_TPM_GROQ=8000` back and stop staging.
