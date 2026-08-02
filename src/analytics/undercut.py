"""Pit strategy and undercut/overcut detection module.

Analyzes the impact of pit stops relative to direct competitors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from src.database.models import Lap, PitStop, Stint

logger = logging.getLogger(__name__)


@dataclass
class PitStopImpact:
    """Analysis of a single pit stop's outcome."""

    session_key: int
    driver_number: int
    lap_number: int
    pit_duration: float
    tyre_age_before: int
    compound_before: str | None
    compound_after: str | None
    pre_stop_pace: float | None
    post_stop_pace: float | None
    pace_gain: float | None
    positions_lost_during_stop: int
    positions_regained_within_5_laps: int
    is_undercut_attempt: bool = False
    is_undercut_success: bool = False
    target_driver_number: int | None = None


class PitStrategyAnalyzer:
    """Analyzes pit stops, pace changes, and track position impact."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_pit_stops_for_session(self, session_key: int) -> pd.DataFrame:
        """Fetch all pit stops with relevant context."""
        with Session(self.engine) as session:
            stops = session.query(PitStop).filter_by(session_key=session_key).all()
            return pd.DataFrame([s.__dict__ for s in stops]).drop(columns=["_sa_instance_state"], errors="ignore")

    def get_stints_for_session(self, session_key: int) -> pd.DataFrame:
        """Fetch stints."""
        with Session(self.engine) as session:
            stints = session.query(Stint).filter_by(session_key=session_key).all()
            return pd.DataFrame([s.__dict__ for s in stints]).drop(columns=["_sa_instance_state"], errors="ignore")

    def get_laps_for_session(self, session_key: int) -> pd.DataFrame:
        """Fetch laps."""
        with Session(self.engine) as session:
            laps = session.query(Lap).filter_by(session_key=session_key).all()
            return pd.DataFrame([l.__dict__ for l in laps]).drop(columns=["_sa_instance_state"], errors="ignore")

    def analyze_pit_stops(self, session_key: int, clean_laps: pd.DataFrame | None = None) -> list[PitStopImpact]:
        """Compute the impact of every pit stop in a session."""
        pit_stops = self.get_pit_stops_for_session(session_key)
        if pit_stops.empty:
            return []

        stints = self.get_stints_for_session(session_key)
        laps = self.get_laps_for_session(session_key)
        if clean_laps is None:
            # If not provided, fallback to raw laps for basic math (not ideal, but works)
            clean_laps = laps

        results = []
        for _, stop in pit_stops.iterrows():
            dn = stop["driver_number"]
            ln = stop["lap_number"]

            # Get pre and post stints
            pre_stint = stints[(stints["driver_number"] == dn) & (stints["lap_end"] == ln)]
            post_stint = stints[(stints["driver_number"] == dn) & (stints["lap_start"] == ln + 1)]

            compound_before = pre_stint.iloc[0]["compound"] if not pre_stint.empty else None
            compound_after = post_stint.iloc[0]["compound"] if not post_stint.empty else None
            tyre_age_before = 0
            if not pre_stint.empty:
                stint_start = pre_stint.iloc[0]["lap_start"]
                age_at_start = pre_stint.iloc[0].get("tyre_age_at_start", 0)
                tyre_age_before = (ln - stint_start) + age_at_start

            # Compute pace delta
            # We look at median of 3 laps before, and 3 laps after
            pre_laps = clean_laps[
                (clean_laps["driver_number"] == dn) & 
                (clean_laps["lap_number"].between(ln - 3, ln - 1))
            ]["lap_duration"].dropna()
            
            post_laps = clean_laps[
                (clean_laps["driver_number"] == dn) & 
                (clean_laps["lap_number"].between(ln + 2, ln + 4))
            ]["lap_duration"].dropna()

            pre_pace = float(pre_laps.median()) if len(pre_laps) > 0 else None
            post_pace = float(post_laps.median()) if len(post_laps) > 0 else None
            pace_gain = pre_pace - post_pace if pre_pace and post_pace else None

            # Simple placeholder for position math (to be implemented with Intervals/Position)
            # For now, this requires joining on intervals which is complex.
            results.append(PitStopImpact(
                session_key=session_key,
                driver_number=dn,
                lap_number=ln,
                pit_duration=stop["pit_duration"],
                tyre_age_before=tyre_age_before,
                compound_before=compound_before,
                compound_after=compound_after,
                pre_stop_pace=pre_pace,
                post_stop_pace=post_pace,
                pace_gain=pace_gain,
                positions_lost_during_stop=0,  # TODO: implement with position endpoints
                positions_regained_within_5_laps=0,
            ))

        return results

    def detect_undercuts(self, session_key: int) -> pd.DataFrame:
        """Detect undercut attempts between drivers."""
        # Find drivers who pitted within 2-3 laps of each other
        # If Driver A pits on lap N, and Driver B pits on lap N+1 or N+2
        # And Driver A was behind Driver B before the stop
        # And Driver A is ahead of Driver B after the stop
        # Then Driver A successfully undercut Driver B.
        
        # This requires the intervals endpoint data which we have synced.
        # For Phase 2 MVP, we will construct a basic outline here.
        pass
