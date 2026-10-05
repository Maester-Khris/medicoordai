import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scraper  # noqa: E402

# A slice of the real hospital rows in medicoord-db-demo.
HOSPITALS = [
    {"id": "tgh", "name": "University Health Network - Toronto General Hospital"},
    {"id": "tw", "name": "University Health Network - Toronto Western Hospital"},
    {"id": "teg", "name": "Toronto East General Hospital"},
    {"id": "nyg", "name": "North York General Hospital - General Division"},
    {"id": "hr", "name": "Humber River Hospital"},
    {"id": "hr-yf", "name": "Humber River Hospital -York Finch"},
    {"id": "hr-church", "name": "Humber River Regional Hospital - Church St. Site"},
    {"id": "sb", "name": "Sunnybrook Health Sciences Centre"},
    {"id": "sb-bay", "name": "Sunnybrook Health Sciences Centre - Bayview Campus"},
    {"id": "osler-e", "name": "William Osler Health System - Etobicoke"},
    {"id": "sickkids", "name": "Hospital for Sick Children"},
    {"id": "uhn", "name": "University Health Network"},
]
ALIASES = {
    scraper.normalize("Michael Garron Hospital"): scraper.normalize("Toronto East General Hospital"),
    scraper.normalize("Etobicoke General Hospital"): scraper.normalize("William Osler Health System - Etobicoke"),
    scraper.normalize("Ghost Hospital"): scraper.normalize("Not A Real Facility"),
}


def row(name, minutes=60, raw=None, **extra):
    return {"name": name, "wait_minutes": minutes, "raw_wait": raw or f"{minutes}m", **extra}


def match(names):
    return {r["name"]: r["facility_id"] for r in scraper.match_to_hospitals([row(n) for n in names], HOSPITALS, ALIASES)}


# ── parsing ───────────────────────────────────────────────────────────────────

class TestParseTime:
    @pytest.mark.parametrize("raw,expected", [
        ("3h 59m", 239), ("6 hr 26 min", 386), ("30m", 30), ("45", 45), ("2h", 120),
    ])
    def test_live_values(self, raw, expected):
        assert scraper.parse_time_to_minutes(raw) == expected

    @pytest.mark.parametrize("raw", [
        "3h 15m–8hPredicted", "45m–2h 15mPredicted", "Not available", "No data", "--", "—", "", None,
    ])
    def test_no_data_and_predicted_ranges_are_ignored(self, raw):
        assert scraper.parse_time_to_minutes(raw) is None


class TestParsePredicted:
    @pytest.mark.parametrize("raw,expected", [
        ("45m–2hPredicted", "45m–2h"), ("1h 15m–2h 45mPredicted", "1h 15m–2h 45m"), ("2h–5h predicted", "2h–5h"),
    ])
    def test_range_becomes_display_text(self, raw, expected):
        assert scraper.parse_predicted(raw) == expected

    @pytest.mark.parametrize("raw", ["3h 59m", "Not available", "--", "Predicted", "", None])
    def test_everything_else_is_not_predicted(self, raw):
        assert scraper.parse_predicted(raw) is None


class TestParseErstat:
    def test_reads_hospital_rows_and_ignores_predicted(self):
        html = """
        <div class="hospital-row"><div class="hospital-row-info"><h3>Toronto General Hospital</h3></div>
            <div class="hospital-row-wait">3h 59m</div></div>
        <div class="hospital-row"><div class="hospital-row-info"><h3>Kingston General Hospital</h3></div>
            <div class="hospital-row-wait">2h–5hPredicted</div></div>
        """
        rows = scraper.parse_erstat(html)
        assert [(r["name"], r["wait_minutes"]) for r in rows] == [
            ("Toronto General Hospital", 239), ("Kingston General Hospital", None)]
        assert [r["predicted_text"] for r in rows] == [None, "2h–5h"]


# ── matching: the regression suite for the 2026-10-05 bug ─────────────────────

class TestMatching:
    def test_exact_and_branded_names_match_their_hospital(self):
        m = match(["Toronto General Hospital", "Toronto General (University Health Network)",
                   "Toronto Western Hospital", "Sunnybrook Health Sciences Centre", "Sunnybrook",
                   "Hospital for Sick Children", "North York General"])
        assert m == {
            "Toronto General Hospital": "tgh", "Toronto General (University Health Network)": "tgh",
            "Toronto Western Hospital": "tw", "Sunnybrook Health Sciences Centre": "sb", "Sunnybrook": "sb",
            "Hospital for Sick Children": "sickkids", "North York General": "nyg",
        }

    def test_toronto_general_is_not_toronto_east_general(self):
        assert match(["Toronto General Hospital"]) == {"Toronto General Hospital": "tgh"}

    @pytest.mark.parametrize("name", [
        "Kingston General Hospital", "Brantford General Hospital", "Hamilton General Hospital",
        "Thunder Bay Regional Hospital", "Grand River Hospital", "Health Sciences North",
        "Almonte General Hospital", "St. Mary's General Hospital",
    ])
    def test_other_cities_hospitals_never_match(self, name):
        assert match([name]) == {}

    def test_campus_names_pick_the_right_site(self):
        m = match(["Humber River Hospital", "Humber River Hospital (Church St.)", "Humber River Hospital -York Finch"])
        assert m == {"Humber River Hospital": "hr", "Humber River Hospital (Church St.)": "hr-church",
                     "Humber River Hospital -York Finch": "hr-yf"}

    def test_alias_handles_renames(self):
        assert match(["Michael Garron Hospital", "Etobicoke General Hospital"]) == {
            "Michael Garron Hospital": "teg", "Etobicoke General Hospital": "osler-e"}

    def test_alias_pointing_at_a_missing_facility_is_skipped(self, caplog):
        assert match(["Ghost Hospital"]) == {}
        assert "alias target not found" in caplog.text

    def test_name_with_only_generic_words_matches_nothing(self):
        assert match(["General Hospital", "Regional Health Centre"]) == {}

    def test_hospital_with_no_distinctive_words_is_never_a_target(self):
        assert "uhn" not in match(["University Health Network"]).values()

    def test_shipped_alias_file_only_names_real_looking_targets(self):
        aliases = scraper.load_aliases()
        assert aliases and all(k and v for k, v in aliases.items())


# ── consolidate ───────────────────────────────────────────────────────────────

class TestConsolidate:
    def test_two_sources_are_averaged(self):
        out = scraper.consolidate([row("a", 200, "3h 20m", facility_id="f1", score=1.0)],
                                  [row("b", 100, "1 hr 40 min", facility_id="f1", score=1.0)])
        assert len(out) == 1 and out[0]["wait_minutes"] == 150 and out[0]["source"] == "erstat+howlongwilliwait"

    def test_single_source_passes_through(self):
        out = scraper.consolidate([row("a", 90, facility_id="f1", score=1.0)], [])
        assert out[0]["wait_minutes"] == 90 and out[0]["source"] == "erstat"

    def test_one_value_per_source_never_an_average_of_many_names(self):
        er = [row("A", 30, facility_id="f1", score=0.7), row("B", 600, facility_id="f1", score=1.0),
              row("C", 900, facility_id="f1", score=0.6)]
        out = scraper.consolidate(er, [])
        assert len(out) == 1 and out[0]["wait_minutes"] == 600   # best match wins, no averaging

    def test_live_value_beats_a_better_scored_entry_without_data(self):
        er = [row("A", None, "Not available", facility_id="f1", score=1.0), row("B", 45, facility_id="f1", score=0.7)]
        assert scraper.consolidate(er, [])[0]["wait_minutes"] == 45

    def test_no_data_keeps_a_null_record_for_redis_only(self):
        out = scraper.consolidate([row("a", None, "Not available", facility_id="f1", score=1.0)], [])
        assert out[0]["wait_minutes"] is None and out[0]["predicted"] is False
        assert scraper._live(out) == [] and scraper._publishable(out) == []

    def test_predicted_only_is_kept_flagged_with_display_text_and_no_minutes(self):
        out = scraper.consolidate([row("a", None, "45m–2hPredicted", predicted_text="45m–2h", facility_id="f1", score=1.0)], [])
        assert len(out) == 1
        assert (out[0]["wait_minutes"], out[0]["predicted"], out[0]["raw_wait"]) == (None, True, "45m–2h")
        assert scraper._publishable(out) == out and scraper._live(out) == []

    def test_live_value_from_another_source_beats_a_predicted_range_and_is_not_averaged_with_it(self):
        er = [row("a", None, "45m–2hPredicted", predicted_text="45m–2h", facility_id="f1", score=1.0)]
        hw = [row("b", 41, "0 hr 41 min", facility_id="f1", score=1.0)]
        out = scraper.consolidate(er, hw)
        assert (out[0]["wait_minutes"], out[0]["predicted"], out[0]["source"]) == (41, False, "howlongwilliwait")

    def test_predicted_range_beats_a_no_data_entry_from_the_same_source(self):
        er = [row("a", None, "--", facility_id="f1", score=1.0),
              row("b", None, "1h–2hPredicted", predicted_text="1h–2h", facility_id="f1", score=0.7)]
        assert scraper.consolidate(er, [])[0]["raw_wait"] == "1h–2h"


# ── sinks: each is a single batched write ─────────────────────────────────────

T0 = "2026-10-05T10:00:00+00:00"
RECORDS = [
    {"facility_id": "f1", "wait_minutes": 90, "predicted": False, "raw_wait": "1h 30m", "source": "erstat", "scraped_at": T0},
    {"facility_id": "f2", "wait_minutes": 45, "predicted": False, "raw_wait": "45m", "source": "howlongwilliwait", "scraped_at": T0},
    {"facility_id": "f3", "wait_minutes": None, "predicted": False, "raw_wait": "Not available", "source": "erstat", "scraped_at": T0},
    {"facility_id": "f4", "wait_minutes": None, "predicted": True, "raw_wait": "45m–2h", "source": "erstat", "scraped_at": T0},
]


class TestSinks:
    @patch("scraper.psycopg.connect")
    def test_postgres_is_one_statement_with_arrays_live_and_predicted_but_not_no_data(self, mock_connect):
        conn = mock_connect.return_value.__enter__.return_value
        assert scraper.write_postgres("postgresql://x", RECORDS) == 3
        assert conn.execute.call_count == 1
        sql, params = conn.execute.call_args.args
        assert "unnest" in sql and "on conflict (facility_id) do update" in sql
        assert params[0] == ["f1", "f2", "f4"]
        assert params[1] == [90, 45, None]          # predicted rows carry NULL minutes, never 0
        assert params[2] == [False, False, True]
        assert params[3][2] == "45m–2h"             # display text

    @patch("scraper.psycopg.connect")
    def test_postgres_with_nothing_to_write_does_not_connect(self, mock_connect):
        assert scraper.write_postgres("postgresql://x", [RECORDS[2]]) == 0
        mock_connect.assert_not_called()

    @patch("scraper.requests.post")
    def test_supabase_is_one_post_with_only_live_rows_and_no_predicted_column(self, mock_post):
        assert scraper.write_supabase("https://sb", "key", RECORDS) == 2
        assert mock_post.call_count == 1
        sent = mock_post.call_args.kwargs["json"]
        assert [r["facility_id"] for r in sent] == ["f1", "f2"]
        assert all("predicted" not in r for r in sent)
        assert mock_post.call_args.args[0] == "https://sb/rest/v1/wait_times"

    def test_redis_is_one_pipeline_with_everything_including_the_predicted_flag(self):
        client = MagicMock()
        assert scraper.write_redis(client, RECORDS) == 4
        pipe = client.pipeline.return_value
        assert pipe.hset.call_count == 4 and pipe.execute.call_count == 1
        payload = [__import__("json").loads(c.args[2]) for c in pipe.hset.call_args_list]
        assert payload[3] == {"wait_minutes": None, "predicted": True, "raw_wait": "45m–2h", "source": "erstat", "updated_at": T0}


# ── main ──────────────────────────────────────────────────────────────────────

ENV = {"POSTGRES_DB_URL_WORKER": "postgresql://w", "SUPABASE_URL": "https://sb",
       "SUPABASE_SERVICE_ROLE_KEY": "k", "UPSTASH_REDIS_URL": "redis://r"}
MANY = [{"id": f"h{i}", "name": f"Testville Number{i} Hospital"} for i in range(12)]


def scraped(n):
    return [row(f"Testville Number{i} Hospital", 30 + i) for i in range(n)]


@pytest.fixture
def world(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SENTRY_DSN_BACKEND", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    with patch("scraper.read_hospitals", return_value=MANY) as rh, \
         patch("scraper.scrape_erstat", return_value=scraped(10)), \
         patch("scraper.scrape_howlongwilliwait", return_value=[]), \
         patch("scraper.load_aliases", return_value={}), \
         patch("scraper.write_postgres", return_value=10) as pg, \
         patch("scraper.write_supabase", return_value=10) as sb, \
         patch("scraper.write_redis", return_value=10) as rd, \
         patch("scraper.redis.from_url"), \
         patch("scraper.sentry_sdk") as sentry:
        yield {"read": rh, "pg": pg, "sb": sb, "rd": rd, "sentry": sentry}


class TestMain:
    def test_happy_path_writes_all_three_sinks_once(self, world):
        scraper.main([])
        assert world["pg"].call_count == world["sb"].call_count == world["rd"].call_count == 1

    def test_dry_run_writes_nothing(self, world):
        scraper.main(["--dry-run"])
        assert world["pg"].call_count == world["sb"].call_count == world["rd"].call_count == 0

    def test_one_failing_sink_does_not_block_the_others_but_fails_the_run(self, world):
        world["pg"].side_effect = RuntimeError("connection refused")
        with pytest.raises(SystemExit) as e:
            scraper.main([])
        assert e.value.code == 1
        assert world["sb"].call_count == 1 and world["rd"].call_count == 1
        world["sentry"].capture_exception.assert_called()

    def test_too_few_matches_aborts_before_any_write(self, world):
        with patch("scraper.scrape_erstat", return_value=scraped(3)), pytest.raises(SystemExit) as e:
            scraper.main([])
        assert e.value.code == 1
        assert world["pg"].call_count == world["sb"].call_count == world["rd"].call_count == 0

    def test_both_scrapers_empty_aborts(self, world):
        with patch("scraper.scrape_erstat", return_value=[]), pytest.raises(SystemExit) as e:
            scraper.main([])
        assert e.value.code == 1 and world["pg"].call_count == 0

    def test_unreadable_hospital_list_aborts_and_reports(self, world):
        world["read"].side_effect = RuntimeError("password authentication failed")
        with pytest.raises(SystemExit):
            scraper.main([])
        world["sentry"].capture_exception.assert_called()
        assert world["pg"].call_count == 0

    def test_missing_env_var_aborts(self, world, monkeypatch):
        monkeypatch.delenv("UPSTASH_REDIS_URL")
        with pytest.raises(SystemExit):
            scraper.main([])
        assert world["read"].call_count == 0
