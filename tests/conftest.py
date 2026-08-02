"""Test fixtures and shared test utilities.

Uses small fixture datasets so tests do not depend on live API.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine

from src.database.engine import init_db, reset_engine
from src.database.models import Base


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database for testing."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db_url = f"sqlite:///{db_path}"
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()
    reset_engine()


@pytest.fixture
def sample_laps_df():
    """Small fixture DataFrame of lap data."""
    return pd.DataFrame({
        "session_key": [9472] * 10,
        "driver_number": [1] * 10,
        "lap_number": list(range(1, 11)),
        "lap_duration": [
            120.0,  # Lap 1 - formation, slow
            96.5, 96.8, 97.0, 96.6, 96.9,  # Clean laps
            130.0,  # Pit in lap
            105.0,  # Pit out lap
            96.7, 96.4,  # Clean laps
        ],
        "duration_sector_1": [35.0, 30.5, 30.8, 31.0, 30.6, 30.9, 40.0, 33.0, 30.7, 30.4],
        "duration_sector_2": [50.0, 42.0, 42.0, 42.0, 42.0, 42.0, 50.0, 45.0, 42.0, 42.0],
        "duration_sector_3": [35.0, 24.0, 24.0, 24.0, 24.0, 24.0, 40.0, 27.0, 24.0, 24.0],
        "i1_speed": [230] * 10,
        "i2_speed": [240] * 10,
        "st_speed": [290] * 10,
        "is_pit_out_lap": [False, False, False, False, False, False, False, True, False, False],
        "date_start": pd.date_range("2024-03-02 15:00:00", periods=10, freq="100s"),
    })


@pytest.fixture
def sample_stints_df():
    """Small fixture DataFrame of stint data."""
    return pd.DataFrame({
        "session_key": [9472, 9472],
        "driver_number": [1, 1],
        "stint_number": [1, 2],
        "lap_start": [1, 8],
        "lap_end": [7, 10],
        "compound": ["SOFT", "HARD"],
        "tyre_age_at_start": [3, 0],
    })


@pytest.fixture
def sample_pit_stops_df():
    """Small fixture DataFrame of pit stop data."""
    return pd.DataFrame({
        "session_key": [9472],
        "driver_number": [1],
        "lap_number": [7],
        "pit_duration": [25.0],
        "lane_duration": [25.0],
        "stop_duration": [None],
        "date": [pd.Timestamp("2024-03-02 15:15:00")],
    })


@pytest.fixture
def sample_race_control_df():
    """Small fixture DataFrame of race control events."""
    return pd.DataFrame({
        "session_key": [9472, 9472, 9472],
        "category": ["SessionStatus", "Flag", "SessionStatus"],
        "flag": [None, "GREEN", None],
        "scope": [None, "Track", None],
        "sector": [None, None, None],
        "message": ["SESSION STARTED", "GREEN LIGHT - PIT EXIT OPEN", "SESSION FINISHED"],
        "driver_number": [None, None, None],
        "lap_number": [1, 1, 57],
        "date": [
            pd.Timestamp("2024-03-02 15:03:42"),
            pd.Timestamp("2024-03-02 15:03:42"),
            pd.Timestamp("2024-03-02 16:35:27"),
        ],
    })


@pytest.fixture
def sample_weather_df():
    """Small fixture DataFrame of weather data."""
    return pd.DataFrame({
        "session_key": [9472] * 5,
        "air_temperature": [18.3, 18.2, 18.1, 18.0, 17.9],
        "track_temperature": [23.8, 23.5, 23.2, 22.9, 22.7],
        "humidity": [49.0, 50.0, 50.0, 49.0, 49.0],
        "rainfall": [0, 0, 0, 0, 0],
        "wind_speed": [1.0, 0.5, 0.7, 0.8, 0.6],
        "wind_direction": [30, 45, 60, 30, 40],
        "pressure": [1017.0] * 5,
        "date": pd.date_range("2024-03-02 15:00:00", periods=5, freq="20min"),
    })


@pytest.fixture
def sample_api_meetings_response():
    """Fixture for raw API meetings response."""
    return [
        {
            "meeting_key": 1229,
            "meeting_name": "Bahrain Grand Prix",
            "meeting_official_name": "FORMULA 1 GULF AIR BAHRAIN GRAND PRIX 2024",
            "location": "Sakhir",
            "country_key": 36,
            "country_code": "BRN",
            "country_name": "Bahrain",
            "circuit_key": 63,
            "circuit_short_name": "Sakhir",
            "circuit_type": "Permanent",
            "gmt_offset": "03:00:00",
            "date_start": "2024-02-29T11:30:00+00:00",
            "date_end": "2024-03-02T17:00:00+00:00",
            "year": 2024,
            "is_cancelled": False,
        }
    ]


@pytest.fixture
def sample_api_laps_response():
    """Fixture for raw API laps response."""
    return [
        {
            "meeting_key": 1229,
            "session_key": 9472,
            "driver_number": 1,
            "lap_number": 10,
            "date_start": "2024-03-02T15:18:15.404000+00:00",
            "duration_sector_1": 30.986,
            "duration_sector_2": 42.009,
            "duration_sector_3": 23.965,
            "i1_speed": 232,
            "i2_speed": 244,
            "is_pit_out_lap": False,
            "lap_duration": 96.96,
            "segments_sector_1": [2048, 2049, 2049],
            "segments_sector_2": [2048, 2048],
            "segments_sector_3": [2048, 2048],
            "st_speed": 293,
        }
    ]
