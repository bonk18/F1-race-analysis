"""SQLAlchemy ORM table definitions matching the normalized schema.

These models define the relational structure for all F1 strategy data.
The schema supports both SQLite (local dev) and PostgreSQL (production).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Meeting(Base):
    """Race weekend / meeting."""

    __tablename__ = "meetings"

    meeting_key = Column(Integer, primary_key=True)
    meeting_name = Column(String(200), nullable=False)
    official_name = Column(String(500))
    location = Column(String(100))
    country_key = Column(Integer)
    country_code = Column(String(10))
    country_name = Column(String(100))
    circuit_key = Column(Integer)
    circuit_short_name = Column(String(100))
    circuit_type = Column(String(50))
    gmt_offset = Column(String(20))
    date_start = Column(DateTime)
    date_end = Column(DateTime)
    year = Column(Integer, nullable=False, index=True)
    is_cancelled = Column(Boolean, default=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("Session", back_populates="meeting")


class Session(Base):
    """Individual session within a meeting (FP1, Quali, Race, etc.)."""

    __tablename__ = "sessions"

    session_key = Column(Integer, primary_key=True)
    session_type = Column(String(50), nullable=False)
    session_name = Column(String(100))
    meeting_key = Column(Integer, ForeignKey("meetings.meeting_key"), nullable=False, index=True)
    circuit_key = Column(Integer)
    circuit_short_name = Column(String(100))
    date_start = Column(DateTime)
    date_end = Column(DateTime)
    year = Column(Integer)
    is_cancelled = Column(Boolean, default=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)

    meeting = relationship("Meeting", back_populates="sessions")


class Driver(Base):
    """Driver entry per session."""

    __tablename__ = "drivers"

    session_key = Column(
        Integer, ForeignKey("sessions.session_key"), primary_key=True
    )
    driver_number = Column(Integer, primary_key=True)
    broadcast_name = Column(String(100))
    full_name = Column(String(200), nullable=False)
    name_acronym = Column(String(5))
    team_name = Column(String(100))
    team_colour = Column(String(10))
    first_name = Column(String(100))
    last_name = Column(String(100))
    country_code = Column(String(10))
    headshot_url = Column(String(500))


class Lap(Base):
    """Individual lap timing record."""

    __tablename__ = "laps"

    session_key = Column(
        Integer, ForeignKey("sessions.session_key"), primary_key=True
    )
    driver_number = Column(Integer, primary_key=True)
    lap_number = Column(Integer, primary_key=True)
    date_start = Column(DateTime)
    lap_duration = Column(Float)
    duration_sector_1 = Column(Float)
    duration_sector_2 = Column(Float)
    duration_sector_3 = Column(Float)
    i1_speed = Column(Integer)
    i2_speed = Column(Integer)
    st_speed = Column(Integer)
    is_pit_out_lap = Column(Boolean)
    segments_sector_1 = Column(Text)  # JSON array stored as text
    segments_sector_2 = Column(Text)
    segments_sector_3 = Column(Text)


class Stint(Base):
    """Tyre stint — contiguous run on one set of tyres."""

    __tablename__ = "stints"

    session_key = Column(
        Integer, ForeignKey("sessions.session_key"), primary_key=True
    )
    driver_number = Column(Integer, primary_key=True)
    stint_number = Column(Integer, primary_key=True)
    lap_start = Column(Integer, nullable=False)
    lap_end = Column(Integer, nullable=False)
    compound = Column(String(20))
    tyre_age_at_start = Column(Integer, default=0)


class PitStop(Base):
    """Pit stop event."""

    __tablename__ = "pit_stops"

    session_key = Column(
        Integer, ForeignKey("sessions.session_key"), primary_key=True
    )
    driver_number = Column(Integer, primary_key=True)
    lap_number = Column(Integer, primary_key=True)
    pit_duration = Column(Float)
    lane_duration = Column(Float)
    stop_duration = Column(Float)
    date = Column(DateTime)


class Position(Base):
    """Position change event (high-frequency timestamps)."""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(
        Integer, ForeignKey("sessions.session_key"), nullable=False
    )
    driver_number = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_positions_session_driver", "session_key", "driver_number"),
        UniqueConstraint(
            "session_key", "driver_number", "date",
            name="uq_positions_session_driver_date",
        ),
    )


class Weather(Base):
    """Weather measurements (approx 1-minute intervals)."""

    __tablename__ = "weather"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(
        Integer, ForeignKey("sessions.session_key"), nullable=False
    )
    air_temperature = Column(Float)
    track_temperature = Column(Float)
    humidity = Column(Float)
    rainfall = Column(Integer)
    wind_speed = Column(Float)
    wind_direction = Column(Integer)
    pressure = Column(Float)
    date = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_weather_session_date", "session_key", "date"),
        UniqueConstraint(
            "session_key", "date", name="uq_weather_session_date"
        ),
    )


class RaceControl(Base):
    """Race control messages (flags, penalties, incidents)."""

    __tablename__ = "race_control"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(
        Integer, ForeignKey("sessions.session_key"), nullable=False
    )
    category = Column(String(50))
    flag = Column(String(50))
    scope = Column(String(20))
    sector = Column(Integer)
    message = Column(Text)
    driver_number = Column(Integer)
    lap_number = Column(Integer)
    date = Column(DateTime)

    __table_args__ = (
        Index("idx_rc_session_date", "session_key", "date"),
    )


class DataQualityEvent(Base):
    """Record of a data quality issue detected during validation."""

    __tablename__ = "data_quality_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(Integer, nullable=False)
    driver_number = Column(Integer)
    lap_number = Column(Integer)
    issue_type = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)  # info, warning, critical
    description = Column(Text)
    rule_name = Column(String(100))
    action_taken = Column(String(20))  # flagged, corrected, removed, retained
    affected_count = Column(Integer, default=1)
    detected_at = Column(DateTime, default=datetime.utcnow)


class ModelRun(Base):
    """Metadata for a model training/evaluation run."""

    __tablename__ = "model_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50))
    training_period = Column(String(200))
    evaluation_races = Column(Text)
    feature_set = Column(Text)  # JSON
    hyperparameters = Column(Text)  # JSON
    metrics = Column(Text)  # JSON
    git_commit = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class Prediction(Base):
    """Stored model prediction for tracking and evaluation."""

    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_run_id = Column(Integer, ForeignKey("model_runs.id"))
    session_key = Column(Integer, nullable=False)
    driver_number = Column(Integer, nullable=False)
    lap_number = Column(Integer, nullable=False)
    prediction_type = Column(String(50), nullable=False)
    predicted_value = Column(Float)
    actual_value = Column(Float)
    confidence_lower = Column(Float)
    confidence_upper = Column(Float)
    features_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
