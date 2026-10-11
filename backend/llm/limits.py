"""HTTP connection limits for LLM provider clients.

Set explicitly because the SDK defaults are a hidden cap on LLM calls in flight: 100 for Groq,
1,000 for OpenAI and Anthropic.
"""
import httpx

import config


def connection_limits() -> httpx.Limits:
    """Return httpx.Limits configured via LLM_MAX_CONNECTIONS."""
    max_connections = config.env_int("LLM_MAX_CONNECTIONS", 2000, minimum=1, maximum=20000)
    return httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)
