import os

import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")  # the module builds a client at import; no call is made

from scripts.embedding_eval.gen_queries import make_client, retry_delay  # noqa: E402


def test_gen_queries_reads_base_url_and_key_env_for_a_non_openai_provider():
    client = make_client({"EVAL_GEN_BASE_URL": "https://api.example.com/openai/v1", "EVAL_GEN_API_KEY_ENV": "MY_PROVIDER_KEY",
                          "MY_PROVIDER_KEY": "secret-value"})
    assert str(client.base_url).startswith("https://api.example.com/openai/v1")
    assert client.api_key == "secret-value"


def test_default_client_uses_the_openai_key_variable():
    client = make_client({"OPENAI_API_KEY": "openai-key"})
    assert client.api_key == "openai-key" and "api.openai.com" in str(client.base_url)


def test_retry_delay_backs_off_and_honours_a_retry_after_hint():
    assert retry_delay(0, None) < retry_delay(2, None) <= 60
    assert retry_delay(0, 7.0) == 7.0
    assert retry_delay(0, 500.0) == 60  # never sleep unboundedly


def test_hint_seconds_parses_the_providers_wait_message():
    from scripts.embedding_eval.gen_queries import hint_seconds
    assert hint_seconds("Rate limit ... Please try again in 3.097499999s. Need more tokens?") == pytest.approx(3.0975)
    assert hint_seconds("Please try again in 1m2.5s.") == pytest.approx(62.5)
    assert hint_seconds("something else") is None
