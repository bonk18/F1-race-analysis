"""Tests for the clean-lap classification engine."""

from __future__ import annotations

import pandas as pd
import pytest

from src.cleaning.clean_laps import CleanLapEngine


class TestCleanLapEngine:
    """Test clean-lap classification rules."""

    def test_excludes_first_lap(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Lap 1 (formation lap) should be excluded."""
        engine = CleanLapEngine(min_lap_number=2)
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        clean_laps = result.clean_laps["lap_number"].tolist()
        assert 1 not in clean_laps

    def test_excludes_pit_out_lap(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Pit out laps should be excluded."""
        engine = CleanLapEngine()
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        excluded = result.excluded_laps
        pit_out_excluded = excluded[excluded["exclusion_reasons"].str.contains("pit_out_lap")]
        assert len(pit_out_excluded) >= 1

    def test_excludes_pit_in_lap(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Pit-in laps should be excluded."""
        engine = CleanLapEngine()
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        excluded = result.excluded_laps
        pit_in_excluded = excluded[excluded["exclusion_reasons"].str.contains("pit_in_lap")]
        assert len(pit_in_excluded) >= 1

    def test_clean_laps_have_valid_duration(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """All clean laps should have positive, non-null duration."""
        engine = CleanLapEngine()
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        assert result.clean_laps["lap_duration"].notna().all()
        assert (result.clean_laps["lap_duration"] > 0).all()

    def test_exclusion_reasons_documented(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Every excluded lap should have at least one exclusion reason."""
        engine = CleanLapEngine()
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        for _, row in result.excluded_laps.iterrows():
            assert row["exclusion_reasons"] != ""

    def test_all_laps_annotated(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Annotated DataFrame should have same row count as input."""
        engine = CleanLapEngine()
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        assert len(result.all_laps_annotated) == len(sample_laps_df)
        assert "is_clean" in result.all_laps_annotated.columns
        assert "exclusion_reasons" in result.all_laps_annotated.columns

    def test_clean_plus_excluded_equals_total(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Clean + excluded should equal total laps."""
        engine = CleanLapEngine()
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        assert len(result.clean_laps) + len(result.excluded_laps) == len(sample_laps_df)

    def test_mad_threshold_configurable(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Different MAD thresholds should produce different results."""
        strict = CleanLapEngine(mad_threshold=1.0)
        permissive = CleanLapEngine(mad_threshold=10.0)

        result_strict = strict.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        result_permissive = permissive.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        # Stricter threshold should exclude at least as many laps
        assert len(result_strict.clean_laps) <= len(result_permissive.clean_laps)

    def test_empty_dataframe_handled(self, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Empty input should return empty result without error."""
        engine = CleanLapEngine()
        result = engine.classify(
            pd.DataFrame(), sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        assert len(result.clean_laps) == 0
        assert result.summary["total"] == 0

    def test_summary_has_expected_keys(self, sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df):
        """Summary dict should contain all expected keys."""
        engine = CleanLapEngine()
        result = engine.classify(
            sample_laps_df, sample_stints_df, sample_pit_stops_df, sample_race_control_df
        )
        assert "total" in result.summary
        assert "clean" in result.summary
        assert "excluded" in result.summary
        assert "clean_pct" in result.summary
        assert "exclusion_breakdown" in result.summary
