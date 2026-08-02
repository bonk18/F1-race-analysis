"""Tests for KPI calculation functions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analytics.kpis import (
    compute_clean_median_pace,
    compute_consistency_iqr,
    compute_consistency_mad,
    compute_consistency_std,
    compute_net_pit_impact,
    compute_pace_deficit_to_teammate,
    compute_pct_within_threshold,
    compute_positions_gained,
    compute_post_stop_pace_gain,
    compute_tyre_degradation_rate,
)


class TestPositionsGained:
    def test_gained_positions(self):
        assert compute_positions_gained(10, 5) == 5

    def test_lost_positions(self):
        assert compute_positions_gained(3, 8) == -5

    def test_no_change(self):
        assert compute_positions_gained(5, 5) == 0

    def test_none_grid(self):
        assert compute_positions_gained(None, 5) is None

    def test_none_finish(self):
        assert compute_positions_gained(5, None) is None


class TestMedianPace:
    def test_normal(self):
        laps = pd.Series([96.5, 96.8, 97.0, 96.6, 96.9])
        result = compute_clean_median_pace(laps)
        assert result == pytest.approx(96.8, abs=0.01)

    def test_empty(self):
        assert compute_clean_median_pace(pd.Series(dtype=float)) is None

    def test_single_lap(self):
        result = compute_clean_median_pace(pd.Series([96.5]))
        assert result == 96.5


class TestPaceDeficit:
    def test_slower_than_teammate(self):
        result = compute_pace_deficit_to_teammate(97.0, 96.5)
        assert result == pytest.approx(0.5)

    def test_faster_than_teammate(self):
        result = compute_pace_deficit_to_teammate(96.0, 96.5)
        assert result == pytest.approx(-0.5)

    def test_none_input(self):
        assert compute_pace_deficit_to_teammate(None, 96.5) is None


class TestConsistency:
    def test_std(self):
        laps = pd.Series([96.5, 96.8, 97.0, 96.6, 96.9])
        result = compute_consistency_std(laps)
        assert result is not None
        assert result > 0

    def test_iqr(self):
        laps = pd.Series([96.0, 96.5, 96.8, 97.0, 97.5])
        result = compute_consistency_iqr(laps)
        assert result is not None
        assert result > 0

    def test_mad(self):
        laps = pd.Series([96.5, 96.8, 97.0, 96.6, 96.9])
        result = compute_consistency_mad(laps)
        assert result is not None
        assert result >= 0

    def test_too_few_laps(self):
        assert compute_consistency_std(pd.Series([96.5])) is None
        assert compute_consistency_iqr(pd.Series([96.5, 97.0])) is None
        assert compute_consistency_mad(pd.Series([96.5, 97.0])) is None


class TestPctWithinThreshold:
    def test_all_within(self):
        # All within 0.5% of median (96.8 * 0.005 = 0.484)
        laps = pd.Series([96.5, 96.7, 96.8, 96.9, 97.0])
        result = compute_pct_within_threshold(laps, threshold_pct=0.005)
        assert result is not None
        assert result > 50.0  # Most should be within

    def test_empty(self):
        assert compute_pct_within_threshold(pd.Series(dtype=float)) is None


class TestDegradationRate:
    def test_positive_degradation(self):
        """Lap times increasing with tyre age = positive degradation."""
        df = pd.DataFrame({
            "tyre_age": [1, 2, 3, 4, 5],
            "lap_duration": [96.0, 96.1, 96.3, 96.5, 96.8],
        })
        result = compute_tyre_degradation_rate(df)
        assert result is not None
        assert result > 0

    def test_too_few_laps(self):
        df = pd.DataFrame({"tyre_age": [1, 2], "lap_duration": [96.0, 96.1]})
        assert compute_tyre_degradation_rate(df) is None


class TestPostStopPaceGain:
    def test_improved_pace(self):
        pre = pd.Series([97.0, 97.2, 97.5])
        post = pd.Series([96.0, 96.2, 96.1])
        result = compute_post_stop_pace_gain(pre, post)
        assert result is not None
        assert result > 0

    def test_worsened_pace(self):
        pre = pd.Series([96.0, 96.2, 96.1])
        post = pd.Series([97.0, 97.2, 97.5])
        result = compute_post_stop_pace_gain(pre, post)
        assert result is not None
        assert result < 0


class TestNetPitImpact:
    def test_beneficial_stop(self):
        result = compute_net_pit_impact(
            pace_gain=1.0, pit_duration=25.0, remaining_laps=30
        )
        assert result is not None
        assert result > 0  # 30 laps × 1s = 30s gain - 25s loss = +5s

    def test_costly_stop(self):
        result = compute_net_pit_impact(
            pace_gain=0.5, pit_duration=25.0, remaining_laps=20
        )
        assert result is not None
        assert result < 0  # 20 × 0.5 = 10s gain - 25s loss = -15s

    def test_none_input(self):
        assert compute_net_pit_impact(None, 25.0) is None
