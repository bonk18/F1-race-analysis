"""Data quality pipeline — systematic checks for F1 timing data.

Each check produces DataQualityEvent records with:
- issue_type, severity, description, rule_name
- affected session/driver/lap
- recommended handling action
- count of affected records

No data is silently removed. All issues are logged and stored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class QualityIssue:
    """A single data quality issue detected by a check rule."""

    session_key: int
    issue_type: str
    severity: str  # 'info', 'warning', 'critical'
    description: str
    rule_name: str
    action_taken: str  # 'flagged', 'corrected', 'removed', 'retained'
    driver_number: int | None = None
    lap_number: int | None = None
    affected_count: int = 1


@dataclass
class QualityReport:
    """Summary report of all data quality checks for a session."""

    session_key: int
    issues: list[QualityIssue] = field(default_factory=list)
    checks_run: int = 0
    total_issues: int = 0

    def add(self, issue: QualityIssue) -> None:
        self.issues.append(issue)
        self.total_issues += 1

    def to_records(self) -> list[dict[str, Any]]:
        """Convert to list of dicts for database storage."""
        return [
            {
                "session_key": i.session_key,
                "driver_number": i.driver_number,
                "lap_number": i.lap_number,
                "issue_type": i.issue_type,
                "severity": i.severity,
                "description": i.description,
                "rule_name": i.rule_name,
                "action_taken": i.action_taken,
                "affected_count": i.affected_count,
            }
            for i in self.issues
        ]

    def summary(self) -> dict[str, int]:
        """Counts by severity level."""
        counts = {"info": 0, "warning": 0, "critical": 0}
        for issue in self.issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        return counts


class DataQualityPipeline:
    """Runs systematic data quality checks on ingested F1 data.

    Each check method follows the pattern:
        def check_<name>(self, laps_df, ...) -> list[QualityIssue]
    """

    def run_all_checks(
        self,
        session_key: int,
        laps_df: pd.DataFrame,
        stints_df: pd.DataFrame,
        pit_stops_df: pd.DataFrame,
        race_control_df: pd.DataFrame,
        weather_df: pd.DataFrame,
    ) -> QualityReport:
        """Execute all quality checks and return a consolidated report.

        Args:
            session_key: The session being checked.
            laps_df: DataFrame of laps for this session.
            stints_df: DataFrame of stints.
            pit_stops_df: DataFrame of pit stops.
            race_control_df: DataFrame of race control events.
            weather_df: DataFrame of weather records.

        Returns:
            QualityReport with all detected issues.
        """
        report = QualityReport(session_key=session_key)

        checks = [
            ("missing_lap_duration", self.check_missing_lap_duration),
            ("negative_duration", self.check_negative_duration),
            ("extreme_lap_times", self.check_extreme_lap_times),
            ("duplicate_laps", self.check_duplicate_laps),
            ("missing_sector_times", self.check_missing_sector_times),
            ("sector_sum_mismatch", self.check_sector_sum_mismatch),
            ("missing_compound", self.check_missing_compound),
            ("incomplete_stints", self.check_incomplete_stints),
            ("pit_lap_not_flagged", self.check_pit_lap_classification),
            ("inconsistent_timestamps", self.check_timestamp_consistency),
            ("driver_coverage", self.check_driver_coverage),
            ("weather_gaps", self.check_weather_gaps),
        ]

        for name, check_fn in checks:
            try:
                kwargs = {
                    "session_key": session_key,
                    "laps_df": laps_df,
                    "stints_df": stints_df,
                    "pit_stops_df": pit_stops_df,
                    "race_control_df": race_control_df,
                    "weather_df": weather_df,
                }
                issues = check_fn(**kwargs)
                for issue in issues:
                    report.add(issue)
                report.checks_run += 1
            except Exception as e:
                logger.error("Quality check '%s' failed: %s", name, e)

        logger.info(
            "Quality report for session %d: %d checks, %d issues (%s)",
            session_key, report.checks_run, report.total_issues, report.summary(),
        )
        return report

    # ── Individual check methods ───────────────────────────────

    def check_missing_lap_duration(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for laps with null lap_duration."""
        missing = laps_df[laps_df["lap_duration"].isna()]
        if missing.empty:
            return []

        issues = []
        for driver, group in missing.groupby("driver_number"):
            issues.append(QualityIssue(
                session_key=session_key,
                driver_number=int(driver),
                issue_type="missing_lap_duration",
                severity="warning",
                description=f"Driver {driver}: {len(group)} laps with null duration "
                            f"(laps: {sorted(group['lap_number'].tolist())})",
                rule_name="check_missing_lap_duration",
                action_taken="flagged",
                affected_count=len(group),
            ))
        return issues

    def check_negative_duration(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for laps with negative or zero duration."""
        invalid = laps_df[laps_df["lap_duration"].notna() & (laps_df["lap_duration"] <= 0)]
        if invalid.empty:
            return []

        return [QualityIssue(
            session_key=session_key,
            issue_type="negative_duration",
            severity="critical",
            description=f"{len(invalid)} laps with non-positive duration",
            rule_name="check_negative_duration",
            action_taken="flagged",
            affected_count=len(invalid),
        )]

    def check_extreme_lap_times(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for impossibly fast or slow laps."""
        valid = laps_df[laps_df["lap_duration"].notna()].copy()
        if valid.empty:
            return []

        issues = []
        too_fast = valid[valid["lap_duration"] < 30]
        if not too_fast.empty:
            issues.append(QualityIssue(
                session_key=session_key,
                issue_type="impossibly_fast_lap",
                severity="critical",
                description=f"{len(too_fast)} laps faster than 30 seconds",
                rule_name="check_extreme_lap_times",
                action_taken="flagged",
                affected_count=len(too_fast),
            ))

        too_slow = valid[valid["lap_duration"] > 300]
        if not too_slow.empty:
            issues.append(QualityIssue(
                session_key=session_key,
                issue_type="impossibly_slow_lap",
                severity="warning",
                description=f"{len(too_slow)} laps slower than 5 minutes",
                rule_name="check_extreme_lap_times",
                action_taken="flagged",
                affected_count=len(too_slow),
            ))
        return issues

    def check_duplicate_laps(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for duplicate (session, driver, lap_number) combinations."""
        dupes = laps_df.duplicated(
            subset=["session_key", "driver_number", "lap_number"], keep=False
        )
        if not dupes.any():
            return []

        return [QualityIssue(
            session_key=session_key,
            issue_type="duplicate_laps",
            severity="critical",
            description=f"{dupes.sum()} duplicate lap records found",
            rule_name="check_duplicate_laps",
            action_taken="flagged",
            affected_count=int(dupes.sum()),
        )]

    def check_missing_sector_times(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for laps with valid duration but missing sector splits."""
        has_duration = laps_df[laps_df["lap_duration"].notna()]
        missing_sectors = has_duration[
            has_duration["duration_sector_1"].isna() |
            has_duration["duration_sector_2"].isna() |
            has_duration["duration_sector_3"].isna()
        ]
        if missing_sectors.empty:
            return []

        return [QualityIssue(
            session_key=session_key,
            issue_type="missing_sector_times",
            severity="info",
            description=f"{len(missing_sectors)} laps with duration but incomplete sectors",
            rule_name="check_missing_sector_times",
            action_taken="retained",
            affected_count=len(missing_sectors),
        )]

    def check_sector_sum_mismatch(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for laps where sector times don't sum to lap duration."""
        complete = laps_df.dropna(subset=[
            "lap_duration", "duration_sector_1", "duration_sector_2", "duration_sector_3"
        ]).copy()
        if complete.empty:
            return []

        complete["sector_sum"] = (
            complete["duration_sector_1"]
            + complete["duration_sector_2"]
            + complete["duration_sector_3"]
        )
        complete["discrepancy"] = abs(complete["lap_duration"] - complete["sector_sum"])
        mismatched = complete[complete["discrepancy"] > 1.0]

        if mismatched.empty:
            return []

        return [QualityIssue(
            session_key=session_key,
            issue_type="sector_sum_mismatch",
            severity="warning",
            description=f"{len(mismatched)} laps where sector sum differs from lap duration by >1s",
            rule_name="check_sector_sum_mismatch",
            action_taken="flagged",
            affected_count=len(mismatched),
        )]

    def check_missing_compound(self, session_key: int, stints_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for stints with unknown tyre compound."""
        missing = stints_df[stints_df["compound"].isna() | (stints_df["compound"] == "")]
        if missing.empty:
            return []

        return [QualityIssue(
            session_key=session_key,
            issue_type="missing_compound",
            severity="warning",
            description=f"{len(missing)} stints with unknown tyre compound",
            rule_name="check_missing_compound",
            action_taken="flagged",
            affected_count=len(missing),
        )]

    def check_incomplete_stints(self, session_key: int, stints_df: pd.DataFrame, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for stints where lap range has gaps."""
        issues = []
        for _, stint in stints_df.iterrows():
            driver = stint["driver_number"]
            expected_laps = set(range(int(stint["lap_start"]), int(stint["lap_end"]) + 1))
            actual_laps = set(
                laps_df[
                    (laps_df["driver_number"] == driver) &
                    (laps_df["lap_number"].between(stint["lap_start"], stint["lap_end"]))
                ]["lap_number"].tolist()
            )
            missing = expected_laps - actual_laps
            if len(missing) > 2:  # Small gaps are normal (e.g., lap 1)
                issues.append(QualityIssue(
                    session_key=session_key,
                    driver_number=int(driver),
                    issue_type="incomplete_stint",
                    severity="info",
                    description=f"Driver {driver} stint {stint['stint_number']}: "
                                f"{len(missing)} missing laps in range "
                                f"{stint['lap_start']}-{stint['lap_end']}",
                    rule_name="check_incomplete_stints",
                    action_taken="retained",
                    affected_count=len(missing),
                ))
        return issues

    def check_pit_lap_classification(
        self, session_key: int, laps_df: pd.DataFrame, pit_stops_df: pd.DataFrame, **_: Any
    ) -> list[QualityIssue]:
        """Check for pit laps not flagged as is_pit_out_lap."""
        if pit_stops_df.empty:
            return []

        pit_out_laps = set(
            (row["driver_number"], row["lap_number"] + 1)
            for _, row in pit_stops_df.iterrows()
        )
        issues = []
        for driver, lap in pit_out_laps:
            lap_row = laps_df[
                (laps_df["driver_number"] == driver) &
                (laps_df["lap_number"] == lap)
            ]
            if not lap_row.empty and not lap_row.iloc[0].get("is_pit_out_lap", False):
                issues.append(QualityIssue(
                    session_key=session_key,
                    driver_number=int(driver),
                    lap_number=int(lap),
                    issue_type="pit_out_not_flagged",
                    severity="info",
                    description=f"Driver {driver} lap {lap} is a pit out but not flagged",
                    rule_name="check_pit_lap_classification",
                    action_taken="retained",
                    affected_count=1,
                ))
        return issues

    def check_timestamp_consistency(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for non-monotonic timestamps within a driver's laps."""
        issues = []
        for driver, group in laps_df.groupby("driver_number"):
            if "date_start" not in group.columns or group["date_start"].isna().all():
                continue
            sorted_group = group.sort_values("lap_number")
            timestamps = pd.to_datetime(sorted_group["date_start"], errors="coerce").dropna()
            if len(timestamps) < 2:
                continue
            non_monotonic = (timestamps.diff().dt.total_seconds().dropna() < 0).sum()
            if non_monotonic > 0:
                issues.append(QualityIssue(
                    session_key=session_key,
                    driver_number=int(driver),
                    issue_type="non_monotonic_timestamps",
                    severity="warning",
                    description=f"Driver {driver}: {non_monotonic} timestamp inversions",
                    rule_name="check_timestamp_consistency",
                    action_taken="flagged",
                    affected_count=int(non_monotonic),
                ))
        return issues

    def check_driver_coverage(self, session_key: int, laps_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for drivers with very few laps (potential DNF or data gap)."""
        if laps_df.empty:
            return []

        max_laps = laps_df["lap_number"].max()
        driver_counts = laps_df.groupby("driver_number")["lap_number"].count()
        low_coverage = driver_counts[driver_counts < max_laps * 0.3]

        issues = []
        for driver, count in low_coverage.items():
            issues.append(QualityIssue(
                session_key=session_key,
                driver_number=int(driver),
                issue_type="low_driver_coverage",
                severity="info",
                description=f"Driver {driver}: only {count}/{max_laps} laps recorded "
                            f"({count/max_laps*100:.0f}% coverage)",
                rule_name="check_driver_coverage",
                action_taken="retained",
                affected_count=int(count),
            ))
        return issues

    def check_weather_gaps(self, session_key: int, weather_df: pd.DataFrame, **_: Any) -> list[QualityIssue]:
        """Check for large gaps in weather data."""
        if weather_df.empty or len(weather_df) < 2:
            return [QualityIssue(
                session_key=session_key,
                issue_type="no_weather_data",
                severity="warning",
                description="No weather data available for this session",
                rule_name="check_weather_gaps",
                action_taken="retained",
                affected_count=0,
            )]

        weather_sorted = weather_df.sort_values("date")
        timestamps = pd.to_datetime(weather_sorted["date"], errors="coerce")
        gaps = timestamps.diff().dt.total_seconds().dropna()
        large_gaps = gaps[gaps > 300]  # >5 min gaps

        if large_gaps.empty:
            return []

        return [QualityIssue(
            session_key=session_key,
            issue_type="weather_data_gap",
            severity="info",
            description=f"{len(large_gaps)} gaps >5 minutes in weather data "
                        f"(max gap: {large_gaps.max():.0f}s)",
            rule_name="check_weather_gaps",
            action_taken="retained",
            affected_count=len(large_gaps),
        )]
