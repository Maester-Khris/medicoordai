"""Demo-mode switch and constants. Read through functions so tests can flip the environment."""
import json
import logging
import os

logger = logging.getLogger(__name__)

DOWNTOWN_TORONTO: dict[str, float] = {"lat": 43.6532, "lng": -79.3832}
ALL_MODES: list[str] = ["car", "bike", "bus", "walk"]
DEMO_MODES: list[str] = ["car", "bike", "bus", "walk"]  # every mode is a real route since sprint 21

DEFAULT_STARTER_PROMPTS: list[str] = [
    "I have a fever and sore throat",
    "Chest pain and shortness of breath",
    "Twisted my ankle — it's swollen",
]


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").strip().lower() in ("1", "true")


def modes_enabled() -> list[str]:
    return DEMO_MODES if demo_mode() else ALL_MODES


def starter_prompts() -> list[str]:
    raw = os.environ.get("DEMO_STARTER_PROMPTS", "").strip()
    if not raw:
        return DEFAULT_STARTER_PROMPTS
    try:
        parsed = json.loads(raw)
    except ValueError:
        return DEFAULT_STARTER_PROMPTS
    if not isinstance(parsed, list) or not parsed:
        return DEFAULT_STARTER_PROMPTS
    if not all(isinstance(p, str) and p.strip() for p in parsed):
        return DEFAULT_STARTER_PROMPTS
    return parsed


def internal_token() -> str:
    return os.environ.get("DEMO_INTERNAL_TOKEN", "").strip()


def env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    """An integer setting from the environment. A missing, malformed or out-of-range value
    falls back to `default` with one warning: a bad setting must never stop the API from starting."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("env_setting_invalid", extra={"setting": name, "reason": "not an integer"})
        return default
    if value < minimum or (maximum is not None and value > maximum):
        logger.warning("env_setting_invalid", extra={"setting": name, "reason": "out of range"})
        return default
    return value


def llm_timeout_seconds() -> int:
    return env_int("LLM_TIMEOUT_SECONDS", 30, minimum=1, maximum=300)


def llm_provider_chain() -> list[str]:
    """Ordered provider names from LLM_PROVIDER_CHAIN ("groq,openai,anthropic"); empty when unset."""
    raw = os.environ.get("LLM_PROVIDER_CHAIN", "")
    return [name.strip().lower() for name in raw.split(",") if name.strip()]
