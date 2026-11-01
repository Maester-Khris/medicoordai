"""
Unit tests for the /facilities and /facilities/nearby route handlers.
Called directly as plain async functions (bypassing the ASGI stack and
app lifespan) — only the filtering and caching logic under test needs exercising.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import main
from services import facility_bytes
from services.wait_cache import WaitSnapshot

LAST_RUN = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
TWO_HOSPITALS = [
    {"id": "a", "category": "hospital", "accepted_severity": ["urgent"]},
    {"id": "b", "category": "hospital", "accepted_severity": ["urgent"]},
]


def _info(**minutes: int) -> dict:
    """{'a': 10} -> the get_wait_map() shape."""
    return {fid: {"wait_minutes": m, "raw_wait": None, "predicted": False} for fid, m in minutes.items()}


def _snap(wait_map: dict, version: str = "w1", last_run: datetime | None = None) -> WaitSnapshot:
    return WaitSnapshot(wait_map, version, last_run)


def _request(**headers: str):
    return type("FakeRequest", (), {"headers": headers})()


@pytest.fixture(autouse=True)
def _empty_bytes_cache():
    facility_bytes.clear()
    yield
    facility_bytes.clear()


class TestFacilitiesRoute:
    def test_max_wait_minutes_filters_results(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=60))):
            response = asyncio.run(main.facilities(_request(), max_wait_minutes=30))

        assert [r["id"] for r in json.loads(response.body)] == ["a"]

    def test_no_max_wait_minutes_returns_all(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=60))):
            response = asyncio.run(main.facilities(_request()))

        assert len(json.loads(response.body)) == 2

    def test_facilities_treats_empty_cached_list_as_not_warm(self):
        """I-6 regression guard: an empty list (not None) from a lifespan warm-up
        that ran before the database had any operational rows must not be served
        forever — main.py's `if not cached_data` (not `is None`) re-queries and
        re-warms on the next request once real data exists."""
        fake_fresh_data = [
            {"id": "a", "category": "hospital", "accepted_severity": ["urgent"]},
        ]
        with patch("main.get_cached_facilities", return_value=([], "etag-empty")), \
             patch("main.get_all_facilities", return_value=fake_fresh_data), \
             patch("main.set_cached_facilities", return_value='"f-fresh"') as mock_set, \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            response = asyncio.run(main.facilities(_request()))

        assert [r["id"] for r in json.loads(response.body)] == ["a"]
        mock_set.assert_called_once_with(fake_fresh_data)

    def test_facilities_carry_raw_wait_and_predicted(self):
        fake_data = [{"id": "a", "category": "hospital", "accepted_severity": ["urgent"]}]
        wait = {"a": {"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}}
        with patch("main.get_cached_facilities", return_value=(fake_data, '"f1"')), \
             patch("main.current_wait", return_value=_snap(wait)):
            response = asyncio.run(main.facilities(_request(), max_wait_minutes=30))
        assert json.loads(response.body) == [
            {"id": "a", "category": "hospital", "accepted_severity": ["urgent"],
             "wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}]


class TestFacilitiesCaching:
    def test_the_list_is_encoded_once_per_data_version(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))), \
             patch.object(facility_bytes, "encode", wraps=facility_bytes.encode) as encode:
            first = asyncio.run(main.facilities(_request()))
            second = asyncio.run(main.facilities(_request()))

        assert encode.call_count == 1
        assert first.body == second.body and first.headers["ETag"] == second.headers["ETag"]

    def test_a_matching_if_none_match_is_304_without_encoding(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            first = asyncio.run(main.facilities(_request()))
            with patch.object(facility_bytes, "encode") as encode:
                second = asyncio.run(main.facilities(_request(**{"If-None-Match": first.headers["ETag"]})))

        assert second.status_code == 304 and second.body == b""
        assert second.headers["ETag"] == first.headers["ETag"]
        encode.assert_not_called()

    @pytest.mark.parametrize("wrap", ['W/{etag}', '"other", {etag}', 'W/"other", W/{etag}'])
    def test_a_weak_or_listed_tag_matches_because_a_proxy_that_compresses_makes_ours_weak(self, wrap):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            first = asyncio.run(main.facilities(_request()))
            header = wrap.format(etag=first.headers["ETag"])
            second = asyncio.run(main.facilities(_request(**{"If-None-Match": header})))

        assert second.status_code == 304

    def test_a_different_tag_is_not_a_match(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            second = asyncio.run(main.facilities(_request(**{"If-None-Match": 'W/"stale"'})))

        assert second.status_code == 200

    def test_new_wait_data_gives_a_new_etag_and_a_new_body(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')):
            with patch("main.current_wait", return_value=_snap(_info(a=10), version="w1")):
                before = asyncio.run(main.facilities(_request()))
            with patch("main.current_wait", return_value=_snap(_info(a=45), version="w2")):
                after = asyncio.run(main.facilities(_request()))

        assert before.headers["ETag"] != after.headers["ETag"]
        assert json.loads(after.body)[0]["wait_minutes"] == 45

    def test_each_filter_set_has_its_own_etag(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=60))):
            everything = asyncio.run(main.facilities(_request()))
            short_waits = asyncio.run(main.facilities(_request(), max_wait_minutes=30))

        assert everything.headers["ETag"] != short_waits.headers["ETag"]
        assert len(json.loads(everything.body)) == 2 and len(json.loads(short_waits.body)) == 1

    def test_the_browser_may_reuse_the_answer_until_the_next_worker_run(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10), last_run=LAST_RUN)), \
             patch("main.max_age_seconds", return_value=600):
            response = asyncio.run(main.facilities(_request()))

        assert response.headers["Cache-Control"] == "max-age=600"
        assert response.headers["X-Wait-As-Of"] == LAST_RUN.isoformat()

    def test_without_a_known_run_there_is_no_as_of_header(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            response = asyncio.run(main.facilities(_request()))

        assert "X-Wait-As-Of" not in response.headers
        assert response.headers["Cache-Control"].startswith("max-age=")

    def test_no_request_reads_wait_times_from_redis(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))), \
             patch("main.supabase_rpc", return_value=[]), \
             patch("services.wait_cache.get_wait_map") as load:
            asyncio.run(main.facilities(_request()))
            asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))

        load.assert_not_called()


class TestFacilitiesNearbyRoute:
    def test_max_wait_minutes_filters_results(self):
        fake_rows = [
            {"facility_id": "a", "distance_m": 100},
            {"facility_id": "b", "distance_m": 200},
        ]
        with patch("main.supabase_rpc", return_value=fake_rows), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=999))):
            result = asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4, max_wait_minutes=30))

        assert [r["facility_id"] for r in result] == ["a"]

    def test_rpc_failure_raises_500(self):
        from fastapi import HTTPException

        with patch("main.supabase_rpc", side_effect=Exception("rpc down")):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))
        assert exc_info.value.status_code == 500


from fastapi.testclient import TestClient


class TestFacilitiesNearbyAsgiStack:
    def test_valid_rpc_response_passes_response_model_validation(self):
        fake_rows = [{
            "facility_id": "11111111-1111-1111-1111-111111111111",
            "facility_name": "Test Hospital",
            "category": "hospital",
            "address": "123 Main St",
            "phone": None,
            "is_operational": True,
            "distance_m": 100,
            "eta_walk_min": 20,
            "eta_transit_min": 10,
            "eta_drive_min": 5,
        }]
        with patch("main.supabase_rpc", return_value=fake_rows), \
             patch("main.current_wait", return_value=_snap({})), \
             patch("main.wait_cache.refresh_once"):
            with TestClient(main.app) as client:
                resp = client.get("/facilities/nearby", params={"lat": 43.6, "lng": -79.4})

        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["facility_id"] == "11111111-1111-1111-1111-111111111111"
        assert body[0]["wait_minutes"] is None


class TestFacilitiesRouteUsesThreadpool:
    async def _run_inline(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def test_nearby_rpc_call_is_offloaded_to_threadpool(self):
        fake_rows = [{"facility_id": "a", "distance_m": 100}]
        with patch("main.supabase_rpc", return_value=fake_rows) as mock_rpc, \
             patch("main.current_wait", return_value=_snap(_info(a=10))), \
             patch("main.run_in_threadpool", side_effect=self._run_inline) as mock_threadpool:
            asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))

        mock_threadpool.assert_any_call(
            mock_rpc,
            "nearby_facilities",
            {
                "user_lat": 43.6, "user_lng": -79.4, "radius_m": 5000,
                "facility_types": None, "result_limit": 50,
            },
        )


class TestFacilitiesNearbyDemoBranch:
    ROW = {
        "facility_id": "a", "facility_name": "A", "category": "hospital", "address": "1 Main St",
        "phone": None, "is_operational": True, "distance_m": 800,
        "eta_walk_min": 10, "eta_transit_min": 2, "eta_drive_min": 1,
    }

    def test_demo_mode_reads_the_cache_and_never_calls_supabase(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        with patch("main.find_facilities_within", return_value=[self.ROW]) as within, \
             patch("main.supabase_rpc") as rpc, \
             patch("main.current_wait", return_value=_snap(_info(a=25))):
            result = asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4, radius_m=10000, category="hospital"))

        within.assert_called_once_with(43.6, -79.4, 10000, "hospital")
        rpc.assert_not_called()
        assert result == [{**self.ROW, "wait_minutes": 25}]

    def test_demo_mode_applies_the_wait_filter(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        with patch("main.find_facilities_within", return_value=[self.ROW]), \
             patch("main.current_wait", return_value=_snap(_info(a=90))):
            assert asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4, max_wait_minutes=30)) == []

    def test_demo_mode_with_an_empty_cache_is_503(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setenv("DEMO_MODE", "true")
        with patch("main.find_facilities_within", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))
        assert exc_info.value.status_code == 503

    def test_without_demo_mode_the_supabase_function_is_still_called(self, monkeypatch):
        monkeypatch.delenv("DEMO_MODE", raising=False)
        with patch("main.find_facilities_within") as within, \
             patch("main.supabase_rpc", return_value=[]) as rpc, \
             patch("main.current_wait", return_value=_snap({})):
            assert asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4)) == []
        within.assert_not_called()
        rpc.assert_called_once()
