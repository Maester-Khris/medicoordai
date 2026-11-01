import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

from services import retention


def test_purge_runs_when_lock_is_acquired() -> None:
    redis = MagicMock()
    redis.set.return_value = True
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions", return_value=3) as purge:
        retention.purge_if_due()
    purge.assert_called_once_with()
    redis.set.assert_called_once_with("demo:purge:lock", "1", nx=True, ex=3600)


def test_purge_is_skipped_within_the_hour() -> None:
    redis = MagicMock()
    redis.set.return_value = None  # NX not acquired
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions") as purge:
        retention.purge_if_due()
    purge.assert_not_called()


def test_purge_runs_when_redis_down() -> None:
    redis = MagicMock()
    redis.set.side_effect = ConnectionError("down")
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions", return_value=0) as purge:
        retention.purge_if_due()
    purge.assert_called_once_with()


def test_purge_failure_is_swallowed() -> None:
    redis = MagicMock()
    redis.set.return_value = True
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions", side_effect=RuntimeError("db")):
        retention.purge_if_due()  # must not raise
