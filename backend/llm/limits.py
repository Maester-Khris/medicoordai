"""HTTP connection limits for LLM provider clients."""
import httpx

import config


def connection_limits() -> httpx.Limits:
    """Return httpx.Limits configured via LLM_MAX_CONNECTIONS."""
    max_connections = config.env_int("LLM_MAX_CONNECTIONS", 2000, minimum=1, maximum=20000)
    return httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)
