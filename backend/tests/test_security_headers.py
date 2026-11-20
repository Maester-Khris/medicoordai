from fastapi.testclient import TestClient

from main import app


def test_every_response_has_baseline_headers() -> None:
    client = TestClient(app)
    for path in ("/health", "/does-not-exist"):  # a success and an error response
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["cross-origin-resource-policy"] == "same-origin"
