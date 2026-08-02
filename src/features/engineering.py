"""Feature engineering pipeline for machine learning models.

Transforms raw DB tables into a structured dataset for modelling.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from src.database.models import Lap, Meeting, Session as SessionModel, Stint, Weather
from src.analytics.race_summary import RaceAnalyzer

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Generates features for tyre degradation and pit outcome models."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.analyzer = RaceAnalyzer(engine)

    def load_raw_data(self, session_key: int) -> dict[str, pd.DataFrame]:
        """Load raw data needed for feature engineering."""
        raw_data = self.analyzer.get_session_data(session_key)
        
        # We need the clean laps
        clean_result = self.analyzer.clean_engine.classify(
            raw_data["laps"], raw_data["stints"], raw_data["pit_stops"], raw_data["race_control"]
        )
        raw_data["clean_laps"] = clean_result.clean_laps
        return raw_data

    def generate_tyre_degradation_features(self, session_key: int) -> pd.DataFrame:
        """Engineer dataset for Tyre Degradation modelling."""
        raw_data = self.load_raw_data(session_key)
        
        laps_df = raw_data["clean_laps"].copy()
        if laps_df.empty:
            return pd.DataFrame()
            
        stints_df = raw_data["stints"]
        weather_df = raw_data["weather"]
        
        # 1. Join Stint Info (Compound)
        # We need to map each lap to its stint to get compound and tyre age
        # A simple merge_asof or interval join is needed, but since we have lap_number,
        # we can just map it iteratively or via a temporary key.
        
        laps_with_stints = []
        for _, stint in stints_df.iterrows():
            dn = stint["driver_number"]
            stint_laps = laps_df[
                (laps_df["driver_number"] == dn) & 
                (laps_df["lap_number"] >= stint["lap_start"]) & 
                (laps_df["lap_number"] <= stint["lap_end"])
            ].copy()
            
            if not stint_laps.empty:
                stint_laps["compound"] = stint.get("compound")
                stint_laps["stint_number"] = stint.get("stint_number")
                stint_laps["tyre_age"] = stint_laps["lap_number"] - stint["lap_start"] + stint.get("tyre_age_at_start", 0)
                laps_with_stints.append(stint_laps)
                
        if not laps_with_stints:
            return pd.DataFrame()
            
        df = pd.concat(laps_with_stints, ignore_index=True)
        
        # 2. Add Fuel Proxy Feature
        total_laps = int(df["lap_number"].max())
        df["fuel_effect_proxy"] = total_laps - df["lap_number"]
        
        # 3. Add Track Evolution Index
        # Median lap time of the top 3 drivers on this specific lap
        lap_medians = df.groupby("lap_number")["lap_duration"].apply(
            lambda x: x.nsmallest(3).median()
        ).reset_index()
        lap_medians.rename(columns={"lap_duration": "track_evolution_index"}, inplace=True)
        df = df.merge(lap_medians, on="lap_number", how="left")
        
        # 4. Rolling Features (Pace and Degradation Slope)
        # Sort by driver, then lap number
        df = df.sort_values(["driver_number", "lap_number"]).reset_index(drop=True)
        
        # Rolling median of last 3 laps
        df["rolling_median_pace_3L"] = df.groupby(["driver_number", "stint_number"])["lap_duration"].transform(
            lambda x: x.shift(1).rolling(window=3, min_periods=1).median()
        )
        
        # Simple slope over last 5 laps
        df["recent_degradation_slope_5L"] = df.groupby(["driver_number", "stint_number"])["lap_duration"].transform(
            lambda x: (x.shift(1) - x.shift(5)) / 5.0
        )
        
        # Stint baseline pace (median of first 3 clean laps of the stint)
        df["stint_baseline_pace"] = df.groupby(["driver_number", "stint_number"])["lap_duration"].transform(
            lambda x: x.head(3).median()
        )
        
        # 5. Join Weather Data (Merge As-of by closest timestamp)
        df["date_start"] = pd.to_datetime(df["date_start"])
        if not weather_df.empty:
            weather_df["date"] = pd.to_datetime(weather_df["date"])
            weather_df = weather_df.sort_values("date").dropna(subset=["date"])
            df = df.sort_values("date_start").dropna(subset=["date_start"])
            
            df = pd.merge_asof(
                df, 
                weather_df[["date", "track_temperature", "air_temperature", "rainfall"]],
                left_on="date_start",
                right_on="date",
                direction="backward"
            )
        else:
            df["track_temperature"] = np.nan
            df["air_temperature"] = np.nan
            df["rainfall"] = 0
            
        # Target variable is already lap_duration, but we can also predict delta to baseline
        df["target_delta_to_baseline"] = df["lap_duration"] - df["stint_baseline_pace"]
        
        # Drop rows where critical rolling features are NaNs
        df = df.dropna(subset=["compound", "tyre_age"]).reset_index(drop=True)
        
        return df

    def get_dataset_across_sessions(self, session_keys: list[int]) -> pd.DataFrame:
        """Generate combined features for multiple sessions."""
        datasets = []
        for sk in session_keys:
            logger.info("Generating features for session %d", sk)
            try:
                df = self.generate_tyre_degradation_features(sk)
                if not df.empty:
                    datasets.append(df)
            except Exception as e:
                logger.error("Failed to generate features for %d: %s", sk, e)
                
        if not datasets:
            return pd.DataFrame()
            
        return pd.concat(datasets, ignore_index=True)
