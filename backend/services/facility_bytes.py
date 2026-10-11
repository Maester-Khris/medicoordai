"""The GET /facilities response body, encoded once per data version and filter set.

The key carries everything the body depends on: the facility list version, the wait-data
version and the three filters. The ETag is derived from the key, so answering a conditional
request needs neither the body nor a hash of it.
"""
import hashlib
import json
from collections import OrderedDict
from typing import Any

MAX_ENTRIES = 64  # `max_wait_minutes` is free-form: the cache must not grow with it

Key = tuple[Any, ...]

_entries: OrderedDict[Key, bytes] = OrderedDict()


def etag_for(key: Key) -> str:
    return '"' + hashlib.sha256(repr(key).encode()).hexdigest()[:32] + '"'


def encode(data: list[dict]) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def get(key: Key) -> bytes | None:
    body = _entries.get(key)
    if body is not None:
        _entries.move_to_end(key)
    return body


def put(key: Key, body: bytes) -> None:
    _entries[key] = body
    _entries.move_to_end(key)
    while len(_entries) > MAX_ENTRIES:
        _entries.popitem(last=False)


def clear() -> None:
    _entries.clear()
