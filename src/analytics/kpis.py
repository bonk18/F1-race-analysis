"""KPI calculation module.

Every metric is documented with:
- Definition and formula
- Unit of measurement
- Required inputs
- Edge case handling

No metric is presented without documentation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class DriverKPIs:
    """Complete KPI set for a driver in a session."""

    session_key: int
    driver_number: int
    driver_name: str
    team_name: str

    # Position metrics
    grid_position: int | None
    finish_position: int | None
    positions_gained: int | None

    # Pace metrics (seconds)
    clean_median_pace: float | None
    clean_mean_pace: float | None
    fastest_clean_lap: float | None
    pace_deficit_to_teammate: float | None

    # Consistency metrics (seconds)
    consistency_std: float | None
    consistency_iqr: float | None
    consistency_mad: float | None
    pct_within_half_pct: float | None

    # Pit metrics
    pit_count: int
    total_pit_time: float
    avg_pit_duration: float | None

    # Data quality
    clean_lap_count: int
    total_lap_count: int
    clean_lap_pct: float


def compute_positions_gained(grid: int | None, finish: int | None) -> int | None:
    """Positions gained = grid_position - finish_position.

    Positive = gained positions, Negative = lost positions.
    Returns None if either position is unknown.
    """
    if grid is None or finish is None:
        return None
    return grid - finish


def compute_clean_median_pace(clean_laps: pd.Series) -> float | None:
    """Median lap time from clean laps only.

    Formula: median(lap_duration) where lap ∈ clean_race_laps
    Unit: seconds
    """
    if clean_laps.empty:
        return None
    return float(clean_laps.median())


def compute_pace_deficit_to_teammate(
    driver_median: float | None,
    teammate_median: float | None,
) -> float | None:
    """Pace deficit = driver_median - teammate_median.

    Positive = driver is slower. Negative = driver is faster.
    Unit: seconds
    """
    if driver_median is None or teammate_median is None:
        return None
    return driver_median - teammate_median


def compute_consistency_std(clean_laps: pd.Series) -> float | None:
    """Standard deviation of clean lap times.

    Unit: seconds. Lower = more consistent.
    """
    if len(clean_laps) < 2:
        return None
    return float(clean_laps.std())


def compute_consistency_iqr(clean_laps: pd.Series) -> float | None:
    """Interquartile range (Q3 - Q1) of clean lap times.

    Unit: seconds. More robust to outliers than std.
    """
    if len(clean_laps) < 4:
        return None
    q1 = clean_laps.quantile(0.25)
    q3 = clean_laps.quantile(0.75)
    return float(q3 - q1)


def compute_consistency_mad(clean_laps: pd.Series) -> float | None:
    """Median Absolute Deviation of clean lap times.

    Formula: median(|x_i - median(x)|)
    Unit: seconds. Most robust consistency metric.
    """
    if len(clean_laps) < 3:
        return None
    median_val = clean_laps.median()
    return float(np.median(np.abs(clean_laps - median_val)))


def compute_pct_within_threshold(
    clean_laps: pd.Series,
    threshold_pct: float | None = None,
) -> float | None:
    """Percentage of clean laps within threshold % of median pace.

    Default threshold: 0.5% (0.005).
    Unit: percentage (0-100).
    """
    if clean_laps.empty:
        return None
    if threshold_pct is None:
        threshold_pct = config.analysis.consistency_pct_threshold
    median_val = clean_laps.median()
    threshold_abs = threshold_pct * median_val
    within = (np.abs(clean_laps - median_val) < threshold_abs).sum()
    return float(within / len(clean_laps) * 100)


def compute_tyre_degradation_rate(
    laps_df: pd.DataFrame,
    tyre_age_col: str = "tyre_age",
    lap_time_col: str = "lap_duration",
) -> float | None:
    """Linear degradation rate: slope of lap_duration ~ tyre_age.

    Computed via simple linear regression (polyfit degree 1).
    Unit: seconds per lap of tyre age. Positive = degrading.
    """
    if len(laps_df) < 3:
        return None

    x = laps_df[tyre_age_col].values
    y = laps_df[lap_time_col].values

    # Remove any NaN
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    if len(x) < 3:
        return None

    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def compute_post_stop_pace_gain(
    pre_stop_laps: pd.Series,
    post_stop_laps: pd.Series,
) -> float | None:
    """Post-stop pace gain = median(pre_stop_N_laps) - median(post_stop_N_laps).

    Positive = pace improved after stop. Negative = pace worsened.
    Unit: seconds.
    """
    if pre_stop_laps.empty or post_stop_laps.empty:
        return None
    return float(pre_stop_laps.median() - post_stop_laps.median())


def compute_net_pit_impact(
    pace_gain: float | None,
    pit_duration: float | None,
    remaining_laps: int | None = None,
) -> float | None:
    """Net pit impact = pace_gain_over_remaining_stint - pit_lane_loss.

    This is a simplified estimate. If remaining_laps is provided:
        net = (pace_gain_per_lap × remaining_laps) - pit_duration
    Otherwise:
        net = pace_gain - pit_duration (per-stop estimate)

    Positive = net beneficial. Negative = net costly.
    Unit: seconds.
    """
    if pace_gain is None or pit_duration is None:
        return None
    if remaining_laps is not None and remaining_laps > 0:
        return (pace_gain * remaining_laps) - pit_duration
    return pace_gain - pit_duration


def compute_driver_kpis(
    session_key: int,
    driver_number: int,
    driver_name: str,
    team_name: str,
    clean_laps: pd.DataFrame,
    all_laps: pd.DataFrame,
    pit_stops: pd.DataFrame,
    grid_position: int | None = None,
    finish_position: int | None = None,
    teammate_median: float | None = None,
) -> DriverKPIs:
    """Compute all KPIs for a single driver in a session.

    Args:
        session_key: Session identifier.
        driver_number: Driver number.
        driver_name: Full driver name.
        team_name: Team name.
        clean_laps: DataFrame of clean laps for this driver.
        all_laps: DataFrame of all laps for this driver.
        pit_stops: DataFrame of pit stops for this driver.
        grid_position: Starting grid position.
        finish_position: Final race position.
        teammate_median: Teammate's clean median pace for comparison.

    Returns:
        Populated DriverKPIs dataclass.
    """
    clean_times = clean_laps["lap_duration"].dropna()
    driver_pits = pit_stops[pit_stops["driver_number"] == driver_number]

    median_pace = compute_clean_median_pace(clean_times)
    total_pit = float(driver_pits["pit_duration"].sum()) if not driver_pits.empty else 0.0

    return DriverKPIs(
        session_key=session_key,
        driver_number=driver_number,
        driver_name=driver_name,
        team_name=team_name,
        grid_position=grid_position,
        finish_position=finish_position,
        positions_gained=compute_positions_gained(grid_position, finish_position),
        clean_median_pace=median_pace,
        clean_mean_pace=float(clean_times.mean()) if not clean_times.empty else None,
        fastest_clean_lap=float(clean_times.min()) if not clean_times.empty else None,
        pace_deficit_to_teammate=compute_pace_deficit_to_teammate(median_pace, teammate_median),
        consistency_std=compute_consistency_std(clean_times),
        consistency_iqr=compute_consistency_iqr(clean_times),
        consistency_mad=compute_consistency_mad(clean_times),
        pct_within_half_pct=compute_pct_within_threshold(clean_times),
        pit_count=len(driver_pits),
        total_pit_time=total_pit,
        avg_pit_duration=float(driver_pits["pit_duration"].mean()) if not driver_pits.empty else None,
        clean_lap_count=len(clean_laps),
        total_lap_count=len(all_laps),
        clean_lap_pct=round(len(clean_laps) / max(len(all_laps), 1) * 100, 1),
    )
