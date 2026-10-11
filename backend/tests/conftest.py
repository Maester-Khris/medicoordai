import pytest


@pytest.fixture(autouse=True)
def _nearest_first_recommendations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "off")
