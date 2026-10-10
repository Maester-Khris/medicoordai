"""Demo-mode switch and constants. Read through functions so tests can flip the environment."""
import json
import os

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
