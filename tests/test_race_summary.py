"""Regression tests for race summary data loading."""

from src.analytics.race_summary import RaceAnalyzer


def test_empty_session_tables_keep_model_columns(tmp_db):
    """Empty Sprint pit data must retain columns used by KPI calculations."""
    data = RaceAnalyzer(tmp_db).get_session_data(999999)

    assert "driver_number" in data["pit_stops"].columns
    assert "pit_duration" in data["pit_stops"].columns
    assert "driver_number" in data["drivers"].columns
