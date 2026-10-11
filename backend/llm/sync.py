"""Synchronous runner for coroutines in scripts, reusing a single process event loop."""
import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_sync(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine synchronously using the process event loop and return its result."""
    loop = _get_loop()
    return loop.run_until_complete(coroutine)
