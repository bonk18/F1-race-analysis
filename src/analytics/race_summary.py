"""Race overview and summary analytics.

Produces the data structures for:
- Race overview (grid vs finish, position changes, key events)
- Driver comparison (pace, consistency, stint performance)
- Tyre/stint analysis (degradation, compound performance)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from src.analytics.kpis import (
    DriverKPIs,
    compute_driver_kpis,
    compute_tyre_degradation_rate,
)
from src.cleaning.clean_laps import CleanLapEngine
from src.database.models import (
    Driver,
    Lap,
    PitStop,
    Position,
    RaceControl,
    Stint,
    Weather,
)

logger = logging.getLogger(__name__)


@dataclass
class RaceOverview:
    """High-level race summary data."""

    session_key: int
    meeting_name: str
    circuit: str
    total_laps: int
    driver_count: int
    driver_kpis: list[DriverKPIs]
    podium: list[dict[str, Any]]
    largest_gainers: list[dict[str, Any]]
    largest_losers: list[dict[str, Any]]
    key_events: list[dict[str, Any]]
    takeaways: list[str]
    weather_summary: dict[str, Any]
    data_quality_summary: dict[str, Any]


@dataclass
class StintAnalysis:
    """Per-stint analysis results."""

    session_key: int
    driver_number: int
    driver_name: str
    stint_number: int
    compound: str | None
    lap_start: int
    lap_end: int
    clean_lap_count: int
    median_pace: float | None
    degradation_rate: float | None
    fastest_lap: float | None
    tyre_age_range: tuple[int, int] | None


class RaceAnalyzer:
    """Produces comprehensive race analysis from ingested data."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.clean_engine = CleanLapEngine()

    def get_session_data(self, session_key: int) -> dict[str, pd.DataFrame]:
        """Load all data for a session into DataFrames."""
        tables = {
            "laps": Lap,
            "stints": Stint,
            "pit_stops": PitStop,
            "positions": Position,
            "race_control": RaceControl,
            "weather": Weather,
            "drivers": Driver,
        }

        data = {}
        with Session(self.engine) as session:
            for name, model in tables.items():
                query = session.query(model).filter_by(session_key=session_key)
                records = [
                    {c.key: getattr(row, c.key) for c in row.__table__.columns}
                    for row in query.all()
                ]
                df = pd.DataFrame(records) if records else pd.DataFrame()
                if name == "drivers" and not df.empty and "full_name" in df.columns:
                    df["full_name"] = df["full_name"].str.title()
                data[name] = df

        return data

    def analyze_race(self, session_key: int) -> RaceOverview:
        """Run complete race analysis.

        Loads data → cleans laps → computes KPIs → generates takeaways.
        """
        data = self.get_session_data(session_key)

        # Get meeting info
        with Session(self.engine) as session:
            from src.database.models import Session as SessionModel, Meeting
            sess = session.query(SessionModel).filter_by(session_key=session_key).first()
            if sess:
                meeting = session.query(Meeting).filter_by(meeting_key=sess.meeting_key).first()
                meeting_name = meeting.meeting_name if meeting else "Unknown"
                circuit = sess.circuit_short_name or "Unknown"
            else:
                meeting_name = "Unknown"
                circuit = "Unknown"

        laps_df = data["laps"]
        stints_df = data["stints"]
        pit_stops_df = data["pit_stops"]
        rc_df = data["race_control"]
        weather_df = data["weather"]
        drivers_df = data["drivers"]

        if laps_df.empty:
            logger.warning("No lap data for session %d", session_key)
            return self._empty_overview(session_key, meeting_name, circuit)

        # Clean laps
        cleaning_result = self.clean_engine.classify(
            laps_df, stints_df, pit_stops_df, rc_df
        )
        clean_laps = cleaning_result.clean_laps

        # Get positions
        positions_df = data["positions"]
        grid_positions = self._get_grid_positions(positions_df)
        finish_positions = self._get_finish_positions(positions_df)

        # Compute KPIs per driver
        driver_kpis = []
        for _, driver in drivers_df.iterrows():
            dn = driver["driver_number"]
            driver_clean = clean_laps[clean_laps["driver_number"] == dn]
            driver_all = laps_df[laps_df["driver_number"] == dn]

            # Find teammate
            teammate_median = self._get_teammate_median(
                dn, driver["team_name"], clean_laps, drivers_df
            )

            kpi = compute_driver_kpis(
                session_key=session_key,
                driver_number=dn,
                driver_name=driver["full_name"],
                team_name=driver.get("team_name", ""),
                clean_laps=driver_clean,
                all_laps=driver_all,
                pit_stops=pit_stops_df,
                grid_position=grid_positions.get(dn),
                finish_position=finish_positions.get(dn),
                teammate_median=teammate_median,
            )
            driver_kpis.append(kpi)

        # Sort by finish position
        driver_kpis.sort(key=lambda k: k.finish_position or 999)

        # Build overview components
        podium = [
            {"position": k.finish_position, "driver": k.driver_name,
             "team": k.team_name, "acronym": k.driver_name.split()[-1][:3].upper()}
            for k in driver_kpis[:3] if k.finish_position is not None
        ]

        gainers = sorted(
            [k for k in driver_kpis if k.positions_gained is not None],
            key=lambda k: k.positions_gained, reverse=True
        )[:3]

        losers = sorted(
            [k for k in driver_kpis if k.positions_gained is not None],
            key=lambda k: k.positions_gained
        )[:3]

        key_events = self._extract_key_events(rc_df)
        weather_summary = self._summarize_weather(weather_df)
        takeaways = self._generate_takeaways(driver_kpis, key_events, cleaning_result)

        return RaceOverview(
            session_key=session_key,
            meeting_name=meeting_name,
            circuit=circuit,
            total_laps=int(laps_df["lap_number"].max()) if not laps_df.empty else 0,
            driver_count=len(drivers_df),
            driver_kpis=driver_kpis,
            podium=podium,
            largest_gainers=[
                {"driver": g.driver_name, "gained": g.positions_gained, "team": g.team_name}
                for g in gainers
            ],
            largest_losers=[
                {"driver": l.driver_name, "lost": l.positions_gained, "team": l.team_name}
                for l in losers
            ],
            key_events=key_events,
            takeaways=takeaways,
            weather_summary=weather_summary,
            data_quality_summary=cleaning_result.summary,
        )

    def analyze_stints(
        self, session_key: int, clean_laps: pd.DataFrame, stints_df: pd.DataFrame, drivers_df: pd.DataFrame
    ) -> list[StintAnalysis]:
        """Compute per-stint analysis for all drivers."""
        results = []
        for _, stint in stints_df.iterrows():
            dn = stint["driver_number"]
            stint_laps = clean_laps[
                (clean_laps["driver_number"] == dn) &
                (clean_laps["lap_number"].between(stint["lap_start"], stint["lap_end"]))
            ]

            driver_info = drivers_df[drivers_df["driver_number"] == dn]
            driver_name = driver_info.iloc[0]["full_name"] if not driver_info.empty else str(dn)

            # Compute tyre age for degradation calc
            if not stint_laps.empty:
                tyre_ages = stint_laps["lap_number"] - stint["lap_start"] + stint.get("tyre_age_at_start", 0)
                stint_laps = stint_laps.copy()
                stint_laps["tyre_age"] = tyre_ages.values

            results.append(StintAnalysis(
                session_key=session_key,
                driver_number=int(dn),
                driver_name=driver_name,
                stint_number=int(stint["stint_number"]),
                compound=stint.get("compound"),
                lap_start=int(stint["lap_start"]),
                lap_end=int(stint["lap_end"]),
                clean_lap_count=len(stint_laps),
                median_pace=float(stint_laps["lap_duration"].median()) if not stint_laps.empty else None,
                degradation_rate=compute_tyre_degradation_rate(stint_laps) if len(stint_laps) >= 3 else None,
                fastest_lap=float(stint_laps["lap_duration"].min()) if not stint_laps.empty else None,
                tyre_age_range=(
                    int(stint_laps["tyre_age"].min()),
                    int(stint_laps["tyre_age"].max()),
                ) if not stint_laps.empty and "tyre_age" in stint_laps.columns else None,
            ))

        return results

    # ── Helper methods ─────────────────────────────────────────

    def _get_grid_positions(self, positions_df: pd.DataFrame) -> dict[int, int]:
        """Extract starting grid positions from position data."""
        if positions_df.empty:
            return {}
        first_positions = positions_df.sort_values("date").groupby("driver_number").first()
        return {int(dn): int(row["position"]) for dn, row in first_positions.iterrows()}

    def _get_finish_positions(self, positions_df: pd.DataFrame) -> dict[int, int]:
        """Extract finishing positions from position data."""
        if positions_df.empty:
            return {}
        last_positions = positions_df.sort_values("date").groupby("driver_number").last()
        return {int(dn): int(row["position"]) for dn, row in last_positions.iterrows()}

    def _get_teammate_median(
        self, driver_number: int, team_name: str,
        clean_laps: pd.DataFrame, drivers_df: pd.DataFrame,
    ) -> float | None:
        """Get teammate's median clean pace."""
        teammates = drivers_df[
            (drivers_df["team_name"] == team_name) &
            (drivers_df["driver_number"] != driver_number)
        ]
        if teammates.empty:
            return None
        tm_number = int(teammates.iloc[0]["driver_number"])
        tm_laps = clean_laps[clean_laps["driver_number"] == tm_number]["lap_duration"]
        if tm_laps.empty:
            return None
        return float(tm_laps.median())

    def _extract_key_events(self, rc_df: pd.DataFrame) -> list[dict[str, Any]]:
        """Extract notable race control events."""
        if rc_df.empty:
            return []
        key_categories = {"SafetyCar", "Flag", "SessionStatus", "CarEvent"}
        key_flags = {"SAFETY CAR", "VIRTUAL SAFETY CAR", "RED", "CHEQUERED"}

        events = []
        for _, row in rc_df.iterrows():
            if (row.get("category") in key_categories or
                    row.get("flag") in key_flags):
                events.append({
                    "lap": row.get("lap_number"),
                    "category": row.get("category"),
                    "flag": row.get("flag"),
                    "message": row.get("message"),
                })
        return events[:20]  # Cap at 20 most important

    def _summarize_weather(self, weather_df: pd.DataFrame) -> dict[str, Any]:
        """Produce summary weather statistics."""
        if weather_df.empty:
            return {"available": False}
        return {
            "available": True,
            "air_temp_range": [
                float(weather_df["air_temperature"].min()),
                float(weather_df["air_temperature"].max()),
            ] if weather_df["air_temperature"].notna().any() else None,
            "track_temp_range": [
                float(weather_df["track_temperature"].min()),
                float(weather_df["track_temperature"].max()),
            ] if weather_df["track_temperature"].notna().any() else None,
            "rainfall": bool(weather_df["rainfall"].max() > 0) if weather_df["rainfall"].notna().any() else False,
            "max_wind_speed": float(weather_df["wind_speed"].max()) if weather_df["wind_speed"].notna().any() else None,
        }

    def _generate_takeaways(
        self,
        kpis: list[DriverKPIs],
        events: list[dict],
        cleaning_result: Any,
    ) -> list[str]:
        """Generate factual, data-driven takeaways.

        These are observations directly supported by computed KPIs.
        No speculation or fabricated conclusions.
        """
        takeaways = []

        # Fastest driver
        fastest = min(
            [k for k in kpis if k.fastest_clean_lap is not None],
            key=lambda k: k.fastest_clean_lap, default=None,
        )
        if fastest and fastest.fastest_clean_lap:
            takeaways.append(
                f"{fastest.driver_name} set the fastest clean-race lap "
                f"at {fastest.fastest_clean_lap:.3f}s."
            )

        # Most consistent
        most_consistent = min(
            [k for k in kpis if k.consistency_mad is not None and k.clean_lap_count >= 10],
            key=lambda k: k.consistency_mad, default=None,
        )
        if most_consistent and most_consistent.consistency_mad:
            takeaways.append(
                f"{most_consistent.driver_name} was the most consistent driver "
                f"(MAD: {most_consistent.consistency_mad:.3f}s over "
                f"{most_consistent.clean_lap_count} clean laps)."
            )

        # Biggest position gainer
        gainer = max(
            [k for k in kpis if k.positions_gained is not None],
            key=lambda k: k.positions_gained, default=None,
        )
        if gainer and gainer.positions_gained and gainer.positions_gained > 0:
            takeaways.append(
                f"{gainer.driver_name} gained {gainer.positions_gained} positions "
                f"(P{gainer.grid_position} → P{gainer.finish_position})."
            )

        return takeaways[:3]

    def _empty_overview(self, session_key: int, meeting_name: str, circuit: str) -> RaceOverview:
        """Return an empty overview when no data is available."""
        return RaceOverview(
            session_key=session_key,
            meeting_name=meeting_name,
            circuit=circuit,
            total_laps=0,
            driver_count=0,
            driver_kpis=[],
            podium=[],
            largest_gainers=[],
            largest_losers=[],
            key_events=[],
            takeaways=["No lap data available for this session."],
            weather_summary={"available": False},
            data_quality_summary={"total": 0, "clean": 0, "excluded": 0},
        )
