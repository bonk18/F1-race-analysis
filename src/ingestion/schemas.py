"""Pydantic schemas for OpenF1 API responses.

Each model validates required fields and expected data types while
tolerating missing or null optional fields, since not all races
expose identical data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class MeetingSchema(BaseModel):
    """Schema for /v1/meetings endpoint."""

    meeting_key: int
    meeting_name: str
    meeting_official_name: Optional[str] = None
    location: Optional[str] = None
    country_key: Optional[int] = None
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    circuit_key: Optional[int] = None
    circuit_short_name: Optional[str] = None
    circuit_type: Optional[str] = None
    gmt_offset: Optional[str] = None
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    year: int
    is_cancelled: bool = False


class SessionSchema(BaseModel):
    """Schema for /v1/sessions endpoint."""

    session_key: int
    session_type: str
    session_name: Optional[str] = None
    meeting_key: int
    circuit_key: Optional[int] = None
    circuit_short_name: Optional[str] = None
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    year: Optional[int] = None
    is_cancelled: bool = False


class DriverSchema(BaseModel):
    """Schema for /v1/drivers endpoint."""

    session_key: int
    driver_number: int
    broadcast_name: Optional[str] = None
    full_name: str
    name_acronym: Optional[str] = None
    team_name: Optional[str] = None
    team_colour: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    country_code: Optional[str] = None
    headshot_url: Optional[str] = None


class LapSchema(BaseModel):
    """Schema for /v1/laps endpoint."""

    meeting_key: Optional[int] = None
    session_key: int
    driver_number: int
    lap_number: int
    date_start: Optional[datetime] = None
    lap_duration: Optional[float] = None
    duration_sector_1: Optional[float] = None
    duration_sector_2: Optional[float] = None
    duration_sector_3: Optional[float] = None
    i1_speed: Optional[int] = None
    i2_speed: Optional[int] = None
    st_speed: Optional[int] = None
    is_pit_out_lap: Optional[bool] = None
    segments_sector_1: Optional[list[Optional[int]]] = None
    segments_sector_2: Optional[list[Optional[int]]] = None
    segments_sector_3: Optional[list[Optional[int]]] = None

    @field_validator("lap_duration", "duration_sector_1", "duration_sector_2", "duration_sector_3",
                     mode="before")
    @classmethod
    def validate_positive_duration(cls, v: float | None) -> float | None:
        """Reject negative durations — these indicate data errors."""
        if v is not None and v < 0:
            return None
        return v


class StintSchema(BaseModel):
    """Schema for /v1/stints endpoint."""

    meeting_key: Optional[int] = None
    session_key: int
    driver_number: int
    stint_number: int
    lap_start: int
    lap_end: int
    compound: Optional[str] = None
    tyre_age_at_start: int = 0


class PitStopSchema(BaseModel):
    """Schema for /v1/pit endpoint."""

    session_key: int
    driver_number: int
    lap_number: int
    pit_duration: Optional[float] = None
    lane_duration: Optional[float] = None
    stop_duration: Optional[float] = None
    date: Optional[datetime] = None
    meeting_key: Optional[int] = None


class PositionSchema(BaseModel):
    """Schema for /v1/position endpoint."""

    session_key: int
    driver_number: int
    position: int
    date: datetime
    meeting_key: Optional[int] = None


class IntervalSchema(BaseModel):
    """Schema for /v1/intervals endpoint."""

    session_key: int
    driver_number: int
    gap_to_leader: Optional[float] = None
    interval: Optional[float] = None
    date: Optional[datetime] = None
    meeting_key: Optional[int] = None

    @field_validator("gap_to_leader", "interval", mode="before")
    @classmethod
    def coerce_numeric(cls, v: str | float | None) -> float | None:
        """Interval fields can be strings like '+1 LAP' or numeric."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        # Non-numeric gaps (e.g. '+1 LAP') → None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


class WeatherSchema(BaseModel):
    """Schema for /v1/weather endpoint."""

    session_key: int
    air_temperature: Optional[float] = None
    track_temperature: Optional[float] = None
    humidity: Optional[float] = None
    rainfall: Optional[int] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[int] = None
    pressure: Optional[float] = None
    date: datetime
    meeting_key: Optional[int] = None


class RaceControlSchema(BaseModel):
    """Schema for /v1/race_control endpoint."""

    session_key: int
    category: Optional[str] = None
    flag: Optional[str] = None
    scope: Optional[str] = None
    sector: Optional[int] = None
    message: Optional[str] = None
    driver_number: Optional[int] = None
    lap_number: Optional[int] = None
    date: Optional[datetime] = None
    meeting_key: Optional[int] = None
    qualifying_phase: Optional[str | int] = None


# Mapping from endpoint name to schema class
ENDPOINT_SCHEMAS: dict[str, type[BaseModel]] = {
    "meetings": MeetingSchema,
    "sessions": SessionSchema,
    "drivers": DriverSchema,
    "laps": LapSchema,
    "stints": StintSchema,
    "pit": PitStopSchema,
    "position": PositionSchema,
    "intervals": IntervalSchema,
    "weather": WeatherSchema,
    "race_control": RaceControlSchema,
}
