"""Tests for database models, constraints, and loader."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from src.database.loader import DatabaseLoader
from src.database.models import (
    Base,
    Driver,
    Lap,
    Meeting,
    PitStop,
    Session as SessionModel,
    Stint,
)


class TestDatabaseSchema:
    """Test database table creation and constraints."""

    def test_tables_created(self, tmp_db):
        """All tables should be created by init_db."""
        from sqlalchemy import inspect
        inspector = inspect(tmp_db)
        table_names = inspector.get_table_names()

        expected = {
            "meetings", "sessions", "drivers", "laps", "stints",
            "pit_stops", "positions", "weather", "race_control",
            "data_quality_events", "model_runs", "predictions",
        }
        assert expected.issubset(set(table_names))

    def test_meeting_insert(self, tmp_db):
        """Should insert and retrieve a meeting."""
        with Session(tmp_db) as session:
            meeting = Meeting(
                meeting_key=1229,
                meeting_name="Bahrain Grand Prix",
                year=2024,
            )
            session.add(meeting)
            session.commit()

            result = session.query(Meeting).filter_by(meeting_key=1229).first()
            assert result is not None
            assert result.meeting_name == "Bahrain Grand Prix"

    def test_lap_composite_primary_key(self, tmp_db):
        """Duplicate (session, driver, lap) should raise."""
        with Session(tmp_db) as session:
            # Need meeting and session first for FK
            session.add(Meeting(meeting_key=1229, meeting_name="Test", year=2024))
            session.add(SessionModel(session_key=9472, session_type="Race", meeting_key=1229))
            session.commit()

            session.add(Lap(session_key=9472, driver_number=1, lap_number=1, lap_duration=95.0))
            session.commit()

            # Duplicate should fail
            session.add(Lap(session_key=9472, driver_number=1, lap_number=1, lap_duration=96.0))
            with pytest.raises(Exception):
                session.commit()


class TestDatabaseLoader:
    """Test the DatabaseLoader upsert logic."""

    def test_load_meetings(self, tmp_db):
        """Should load meeting records."""
        loader = DatabaseLoader(tmp_db)
        records = [
            {
                "meeting_key": 1229,
                "meeting_name": "Bahrain Grand Prix",
                "year": 2024,
                "meeting_official_name": "FORMULA 1 BAHRAIN GP",
            }
        ]
        loaded = loader.load_records("meetings", records)
        assert loaded == 1

        with Session(tmp_db) as session:
            result = session.query(Meeting).first()
            assert result.meeting_key == 1229

    def test_load_laps(self, tmp_db):
        """Should load lap records with FK constraints satisfied."""
        loader = DatabaseLoader(tmp_db)

        # Load dependencies first
        loader.load_records("meetings", [
            {"meeting_key": 1229, "meeting_name": "Test", "year": 2024}
        ])
        loader.load_records("sessions", [
            {"session_key": 9472, "session_type": "Race", "meeting_key": 1229}
        ])

        laps = [
            {
                "session_key": 9472,
                "driver_number": 1,
                "lap_number": i,
                "lap_duration": 95.0 + i * 0.1,
            }
            for i in range(1, 6)
        ]
        loaded = loader.load_records("laps", laps)
        assert loaded == 5

    def test_upsert_updates_existing(self, tmp_db):
        """Re-loading should update existing records, not duplicate."""
        loader = DatabaseLoader(tmp_db)
        records = [
            {"meeting_key": 1229, "meeting_name": "Bahrain GP v1", "year": 2024}
        ]
        loader.load_records("meetings", records)

        records[0]["meeting_name"] = "Bahrain GP v2"
        loader.load_records("meetings", records)

        with Session(tmp_db) as session:
            count = session.query(Meeting).count()
            assert count == 1
            result = session.query(Meeting).first()
            assert result.meeting_name == "Bahrain GP v2"

    def test_load_stints_with_json_segments(self, tmp_db):
        """Should handle JSON array fields (segments)."""
        loader = DatabaseLoader(tmp_db)
        loader.load_records("meetings", [
            {"meeting_key": 1229, "meeting_name": "Test", "year": 2024}
        ])
        loader.load_records("sessions", [
            {"session_key": 9472, "session_type": "Race", "meeting_key": 1229}
        ])

        laps = [{
            "session_key": 9472,
            "driver_number": 1,
            "lap_number": 1,
            "lap_duration": 96.0,
            "segments_sector_1": [2048, 2049, 2049],
            "segments_sector_2": [2048, 2048],
            "segments_sector_3": [2048],
        }]
        loaded = loader.load_records("laps", laps)
        assert loaded == 1
