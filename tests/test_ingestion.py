"""Tests for OpenF1 API client and Pydantic schema validation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.schemas import (
    ENDPOINT_SCHEMAS,
    LapSchema,
    MeetingSchema,
    PitStopSchema,
    SessionSchema,
    StintSchema,
    WeatherSchema,
)


class TestPydanticSchemas:
    """Test Pydantic schema validation for API responses."""

    def test_meeting_schema_valid(self, sample_api_meetings_response):
        """Valid meeting data should parse without error."""
        meeting = MeetingSchema.model_validate(sample_api_meetings_response[0])
        assert meeting.meeting_key == 1229
        assert meeting.meeting_name == "Bahrain Grand Prix"
        assert meeting.year == 2024
        assert meeting.is_cancelled is False

    def test_meeting_schema_missing_optional(self):
        """Meeting with only required fields should validate."""
        data = {"meeting_key": 1, "meeting_name": "Test GP", "year": 2024}
        meeting = MeetingSchema.model_validate(data)
        assert meeting.location is None
        assert meeting.circuit_key is None

    def test_lap_schema_valid(self, sample_api_laps_response):
        """Valid lap data should parse correctly."""
        lap = LapSchema.model_validate(sample_api_laps_response[0])
        assert lap.session_key == 9472
        assert lap.driver_number == 1
        assert lap.lap_number == 10
        assert lap.lap_duration == 96.96
        assert lap.is_pit_out_lap is False

    def test_lap_schema_negative_duration_becomes_none(self):
        """Negative duration should be coerced to None (data error)."""
        data = {
            "session_key": 9472,
            "driver_number": 1,
            "lap_number": 5,
            "lap_duration": -1.0,
        }
        lap = LapSchema.model_validate(data)
        assert lap.lap_duration is None

    def test_lap_schema_null_duration(self):
        """Null duration should be accepted as None."""
        data = {
            "session_key": 9472,
            "driver_number": 1,
            "lap_number": 5,
            "lap_duration": None,
        }
        lap = LapSchema.model_validate(data)
        assert lap.lap_duration is None

    def test_stint_schema_valid(self):
        """Valid stint data should parse correctly."""
        data = {
            "meeting_key": 1229,
            "session_key": 9472,
            "stint_number": 1,
            "driver_number": 1,
            "lap_start": 1,
            "lap_end": 17,
            "compound": "SOFT",
            "tyre_age_at_start": 3,
        }
        stint = StintSchema.model_validate(data)
        assert stint.compound == "SOFT"
        assert stint.tyre_age_at_start == 3

    def test_pit_stop_schema_null_stop_duration(self):
        """Pit stop with null stop_duration should validate."""
        data = {
            "session_key": 9472,
            "driver_number": 1,
            "lap_number": 17,
            "pit_duration": 25.0,
            "lane_duration": 25.0,
            "stop_duration": None,
        }
        pit = PitStopSchema.model_validate(data)
        assert pit.pit_duration == 25.0
        assert pit.stop_duration is None

    def test_weather_schema_valid(self):
        """Valid weather data should parse correctly."""
        data = {
            "session_key": 9472,
            "air_temperature": 18.3,
            "track_temperature": 23.8,
            "humidity": 49.0,
            "rainfall": 0,
            "wind_speed": 1.0,
            "wind_direction": 30,
            "pressure": 1017.0,
            "date": "2024-03-02T15:00:00+00:00",
        }
        weather = WeatherSchema.model_validate(data)
        assert weather.air_temperature == 18.3
        assert weather.rainfall == 0

    def test_all_endpoints_have_schemas(self):
        """Every endpoint in the map should have a schema class."""
        expected = {
            "meetings", "sessions", "drivers", "laps", "stints",
            "pit", "position", "intervals", "weather", "race_control",
        }
        assert set(ENDPOINT_SCHEMAS.keys()) == expected


class TestOpenF1ClientCache:
    """Test the client's caching behavior."""

    def test_cache_key_deterministic(self):
        """Same endpoint + params should produce same cache key."""
        from src.ingestion.client import OpenF1Client

        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenF1Client(cache_dir=tmpdir)
            key1 = client._cache_key("laps", {"session_key": 9472, "driver_number": 1})
            key2 = client._cache_key("laps", {"session_key": 9472, "driver_number": 1})
            assert key1 == key2
            client.close()

    def test_cache_key_differs_for_different_params(self):
        """Different params should produce different cache keys."""
        from src.ingestion.client import OpenF1Client

        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenF1Client(cache_dir=tmpdir)
            key1 = client._cache_key("laps", {"session_key": 9472})
            key2 = client._cache_key("laps", {"session_key": 9999})
            assert key1 != key2
            client.close()

    def test_cache_write_and_read(self):
        """Data written to cache should be readable."""
        from src.ingestion.client import OpenF1Client

        with tempfile.TemporaryDirectory() as tmpdir:
            client = OpenF1Client(cache_dir=tmpdir)
            cache_file = Path(tmpdir) / "test_cache.json"
            data = [{"meeting_key": 1, "name": "Test"}]

            client._write_cache(cache_file, data, "test", {"key": "val"})
            result = client._read_cache(cache_file)

            assert result == data
            client.close()
