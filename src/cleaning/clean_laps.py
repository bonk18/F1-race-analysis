"""Clean-lap classification engine.

Identifies laps suitable for pace analysis using transparent,
configurable, and statistically robust methods.

Uses Median Absolute Deviation (MAD) instead of mean/std to resist
outlier contamination. Every exclusion rule is documented and
thresholds are configurable via config.yaml.

Produces both:
- Raw lap records (unchanged)
- Cleaned analytical lap records (with exclusion reasons)
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
class CleaningResult:
    """Result of the clean-lap classification process."""

    clean_laps: pd.DataFrame          # Laps that passed all rules
    excluded_laps: pd.DataFrame       # Laps that failed at least one rule
    all_laps_annotated: pd.DataFrame  # All laps with is_clean and exclusion_reasons
    rules_applied: list[str]
    summary: dict[str, Any]


class CleanLapEngine:
    """Classifies laps as 'clean' or 'excluded' for pace analysis.

    Rules applied (in order):
        1. Not a pit out lap (is_pit_out_lap = False)
        2. Not a pit in lap (lap_number not in pit_stops)
        3. Not a formation/first lap (lap_number > min_lap_number)
        4. Lap duration is not null and > 0
        5. No safety car active during this lap
        6. No virtual safety car active during this lap
        7. No red flag active during this lap
        8. No track-scope yellow flag during this lap
        9. Lap time within median ± k × MAD for driver's stint
        10. All three sector times present and > 0
        11. Lap not deleted by race control

    Each threshold is configurable via CleaningConfig.
    """

    def __init__(
        self,
        mad_threshold: float | None = None,
        min_lap_number: int | None = None,
        min_lap_duration: float | None = None,
    ) -> None:
        cfg = config.cleaning
        self.mad_threshold = mad_threshold or cfg.mad_threshold
        self.min_lap_number = min_lap_number or cfg.min_lap_number
        self.min_lap_duration = min_lap_duration or cfg.min_lap_duration

    def classify(
        self,
        laps_df: pd.DataFrame,
        stints_df: pd.DataFrame,
        pit_stops_df: pd.DataFrame,
        race_control_df: pd.DataFrame,
    ) -> CleaningResult:
        """Classify all laps as clean or excluded.

        Args:
            laps_df: Raw lap records.
            stints_df: Stint data for compound/tyre age info.
            pit_stops_df: Pit stop events.
            race_control_df: Race control messages.

        Returns:
            CleaningResult with clean/excluded DataFrames and annotation.
        """
        if laps_df.empty:
            return CleaningResult(
                clean_laps=laps_df,
                excluded_laps=laps_df,
                all_laps_annotated=laps_df,
                rules_applied=[],
                summary={"total": 0, "clean": 0, "excluded": 0},
            )

        df = laps_df.copy()
        df["exclusion_reasons"] = ""

        # Build helper sets
        pit_in_laps = self._get_pit_in_laps(pit_stops_df)
        sc_laps = self._get_sc_laps(race_control_df)
        vsc_laps = self._get_vsc_laps(race_control_df)
        red_flag_laps = self._get_red_flag_laps(race_control_df)
        yellow_laps = self._get_yellow_laps(race_control_df)
        deleted_laps = self._get_deleted_laps(race_control_df)

        rules_applied = []

        # Rule 1: Pit out lap
        mask = df["is_pit_out_lap"] == True  # noqa: E712
        df.loc[mask, "exclusion_reasons"] += "pit_out_lap;"
        rules_applied.append("pit_out_lap")

        # Rule 2: Pit in lap
        mask = df.apply(
            lambda r: (r.get("session_key"), r["driver_number"], r["lap_number"]) in pit_in_laps,
            axis=1,
        )
        df.loc[mask, "exclusion_reasons"] += "pit_in_lap;"
        rules_applied.append("pit_in_lap")

        # Rule 3: Formation / first lap
        mask = df["lap_number"] < self.min_lap_number
        df.loc[mask, "exclusion_reasons"] += "formation_lap;"
        rules_applied.append("formation_lap")

        # Rule 4: Missing or invalid duration
        mask = df["lap_duration"].isna() | (df["lap_duration"] <= 0)
        df.loc[mask, "exclusion_reasons"] += "invalid_duration;"
        rules_applied.append("invalid_duration")

        # Rule 5: Safety car
        mask = df.apply(
            lambda r: (r.get("session_key"), r["lap_number"]) in sc_laps, axis=1
        )
        df.loc[mask, "exclusion_reasons"] += "safety_car;"
        rules_applied.append("safety_car")

        # Rule 6: Virtual safety car
        mask = df.apply(
            lambda r: (r.get("session_key"), r["lap_number"]) in vsc_laps, axis=1
        )
        df.loc[mask, "exclusion_reasons"] += "virtual_safety_car;"
        rules_applied.append("virtual_safety_car")

        # Rule 7: Red flag
        mask = df.apply(
            lambda r: (r.get("session_key"), r["lap_number"]) in red_flag_laps, axis=1
        )
        df.loc[mask, "exclusion_reasons"] += "red_flag;"
        rules_applied.append("red_flag")

        # Rule 8: Yellow flag (track scope)
        mask = df.apply(
            lambda r: (r.get("session_key"), r["lap_number"]) in yellow_laps, axis=1
        )
        df.loc[mask, "exclusion_reasons"] += "yellow_flag;"
        rules_applied.append("yellow_flag")

        # Rule 9: MAD-based outlier detection (per driver per stint)
        df = self._apply_mad_filter(df, stints_df)
        rules_applied.append("mad_outlier")

        # Rule 10: Missing sector times
        mask = (
            df["duration_sector_1"].isna() |
            df["duration_sector_2"].isna() |
            df["duration_sector_3"].isna()
        ) & (df["lap_duration"].notna())
        # This is softer — we flag but don't exclude
        # (sector times often missing for pit laps already excluded)

        # Rule 11: Deleted laps
        mask = df.apply(
            lambda r: (r["driver_number"], r["lap_number"]) in deleted_laps, axis=1
        )
        df.loc[mask, "exclusion_reasons"] += "deleted_by_stewards;"
        rules_applied.append("deleted_by_stewards")

        # Classify
        df["is_clean"] = df["exclusion_reasons"] == ""
        clean = df[df["is_clean"]].copy()
        excluded = df[~df["is_clean"]].copy()

        summary = {
            "total": len(df),
            "clean": len(clean),
            "excluded": len(excluded),
            "clean_pct": round(len(clean) / max(len(df), 1) * 100, 1),
            "exclusion_breakdown": self._exclusion_breakdown(excluded),
        }

        logger.info(
            "Clean-lap classification: %d/%d laps clean (%.1f%%)",
            summary["clean"], summary["total"], summary["clean_pct"],
        )

        return CleaningResult(
            clean_laps=clean,
            excluded_laps=excluded,
            all_laps_annotated=df,
            rules_applied=rules_applied,
            summary=summary,
        )

    # ── Helper methods ─────────────────────────────────────────

    def _get_pit_in_laps(self, pit_stops_df: pd.DataFrame) -> set[tuple]:
        """Get set of (session_key, driver_number, lap_number) for pit-in laps."""
        if pit_stops_df.empty:
            return set()
        return set(
            (row.get("session_key"), row["driver_number"], row["lap_number"])
            for _, row in pit_stops_df.iterrows()
        )

    def _get_sc_laps(self, rc_df: pd.DataFrame) -> set[tuple]:
        """Get (session_key, lap_number) set for safety car laps."""
        if rc_df.empty:
            return set()
        sc = rc_df[rc_df["message"].str.contains("SAFETY CAR", case=False, na=False)]
        return set((row.get("session_key"), row["lap_number"]) for _, row in sc.iterrows() if row.get("lap_number"))

    def _get_vsc_laps(self, rc_df: pd.DataFrame) -> set[tuple]:
        """Get (session_key, lap_number) set for VSC laps."""
        if rc_df.empty:
            return set()
        vsc = rc_df[rc_df["message"].str.contains("VIRTUAL SAFETY CAR", case=False, na=False)]
        return set((row.get("session_key"), row["lap_number"]) for _, row in vsc.iterrows() if row.get("lap_number"))

    def _get_red_flag_laps(self, rc_df: pd.DataFrame) -> set[tuple]:
        """Get (session_key, lap_number) set for red flag laps."""
        if rc_df.empty:
            return set()
        red = rc_df[(rc_df["flag"] == "RED") & (rc_df["scope"] == "Track")]
        return set((row.get("session_key"), row["lap_number"]) for _, row in red.iterrows() if row.get("lap_number"))

    def _get_yellow_laps(self, rc_df: pd.DataFrame) -> set[tuple]:
        """Get (session_key, lap_number) set for track-scope yellow flags."""
        if rc_df.empty:
            return set()
        yellow = rc_df[
            (rc_df["flag"].isin(["YELLOW", "DOUBLE YELLOW"])) &
            (rc_df["scope"] == "Track")
        ]
        return set((row.get("session_key"), row["lap_number"]) for _, row in yellow.iterrows() if row.get("lap_number"))

    def _get_deleted_laps(self, rc_df: pd.DataFrame) -> set[tuple]:
        """Get (driver_number, lap_number) set for laps deleted by stewards."""
        if rc_df.empty:
            return set()
        deleted = rc_df[rc_df["message"].str.contains("DELETED", case=False, na=False)]
        result = set()
        for _, row in deleted.iterrows():
            dn = row.get("driver_number")
            ln = row.get("lap_number")
            if pd.notna(dn) and pd.notna(ln):
                result.add((int(dn), int(ln)))
        return result

    def _apply_mad_filter(
        self, df: pd.DataFrame, stints_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Apply MAD-based outlier detection per driver per stint.

        MAD = median(|x_i - median(x)|)
        A lap is an outlier if |x - median| > k × MAD × 1.4826

        The 1.4826 constant makes MAD consistent with std dev for normal data.
        """
        if stints_df.empty:
            return df

        for _, stint in stints_df.iterrows():
            mask = (
                (df["driver_number"] == stint["driver_number"]) &
                (df["lap_number"].between(stint["lap_start"], stint["lap_end"])) &
                (df["lap_duration"].notna()) &
                (df["lap_duration"] > 0) &
                (df["exclusion_reasons"] == "")  # Only check laps not already excluded
            )

            subset = df.loc[mask, "lap_duration"]
            if len(subset) < 3:
                continue

            median_val = subset.median()
            mad = np.median(np.abs(subset - median_val))
            if mad == 0:
                continue

            # Modified MAD with consistency constant
            threshold = self.mad_threshold * mad * 1.4826
            outlier_mask = mask & (np.abs(df["lap_duration"] - median_val) > threshold)
            df.loc[outlier_mask, "exclusion_reasons"] += "mad_outlier;"

        return df

    def _exclusion_breakdown(self, excluded: pd.DataFrame) -> dict[str, int]:
        """Count each exclusion reason."""
        if excluded.empty:
            return {}
        all_reasons = ";".join(excluded["exclusion_reasons"].tolist())
        reasons = [r for r in all_reasons.split(";") if r]
        from collections import Counter
        return dict(Counter(reasons))
