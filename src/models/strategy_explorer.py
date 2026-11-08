"""Counterfactual Strategy Explorer.

Simulates different pit-stop strategies (e.g., pit now vs. pit later)
using trained machine learning models to compare expected cumulative race times.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from src.features.engineering import FeatureEngineer
from src.models.tyre_degradation import TyreDegradationModel

logger = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    """Result of a simulated strategy scenario."""
    strategy_name: str
    total_time: float
    lap_times: list[float]
    tyre_ages: list[int]
    compounds: list[str]


class StrategyExplorer:
    """Estimates race time under counterfactual pit strategies."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.fe = FeatureEngineer(engine)
        
        # We need a pre-trained tyre degradation model for simulations.
        self.tyre_model = TyreDegradationModel()
        self.is_trained = False
        
        # Historical average pit lane loss (can be overridden per circuit)
        self.avg_pit_loss = 24.0  # seconds

    def train_models(self, session_key: int) -> None:
        """Train models on the given session for simulation."""
        logger.info("Training simulation models on session %d...", session_key)
        df = self.fe.generate_tyre_degradation_features(session_key)
        self.tyre_model.train_final_model(df, model_type="lgb")
        self.is_trained = True
        logger.info("Models trained successfully.")

    def simulate_stint(
        self, 
        start_lap: int, 
        end_lap: int, 
        compound: str, 
        initial_tyre_age: int,
        base_features: dict,
    ) -> list[float]:
        """Simulate lap times for a specific stint."""
        if not self.is_trained:
            raise RuntimeError("Models must be trained before simulating.")
            
        lap_times = []
        current_age = initial_tyre_age
        
        # Prepare a dummy dataframe for the LightGBM model
        for lap in range(start_lap, end_lap + 1):
            row = base_features.copy()
            row["tyre_age"] = current_age
            row["fuel_effect_proxy"] = row.get("total_laps", 60) - lap
            
            # Create a 1-row DataFrame
            df_row = pd.DataFrame([row])
            df_row["compound"] = compound
            
            # To avoid dropping during preparation, we temporarily add lap_duration
            df_row["lap_duration"] = 0.0
            
            # Ensure categorical columns exist for the encoder
            # The model's _prepare_data expects 'compound' to exist.
            # We don't fit encoder here, we transform.
            try:
                X, _, _ = self.tyre_model._prepare_data(df_row, self.tyre_model.lgb_features, fit_encoder=False)
                # Predict
                pred = self.tyre_model.models["lgb"].predict(X)[0]
                lap_times.append(float(pred))
            except Exception as e:
                logger.error("Simulation failed at lap %d: %s", lap, e)
                raise RuntimeError(f"Simulation failed at lap {lap}: {e}") from e
                
            current_age += 1
            
        return lap_times

    def compare_pit_windows(
        self, 
        current_lap: int, 
        target_lap: int, 
        current_compound: str, 
        next_compound: str,
        current_tyre_age: int,
        base_features: dict,
        laps_to_simulate: int = 15
    ) -> dict[str, ScenarioResult]:
        """
        Compare "Pit Now" vs "Pit on Target Lap".
        Returns the expected cumulative time and lap-by-lap breakdown over the next `laps_to_simulate` laps.
        """
        end_lap = current_lap + laps_to_simulate - 1
        
        # Scenario 1: Pit Now (at the end of current_lap)
        # Lap 1: In-lap (normal + pit loss)
        # Lap 2 to End: New stint on next_compound
        s1_in_lap = self.simulate_stint(current_lap, current_lap, current_compound, current_tyre_age, base_features)
        s1_new_stint = self.simulate_stint(current_lap + 1, end_lap, next_compound, 0, base_features)
        
        s1_times = s1_in_lap + s1_new_stint
        s1_times[0] += self.avg_pit_loss # Add pit loss to the in-lap
        
        s1_result = ScenarioResult(
            strategy_name=f"Pit Now (Lap {current_lap})",
            total_time=sum(s1_times),
            lap_times=s1_times,
            tyre_ages=[current_tyre_age] + list(range(0, laps_to_simulate - 1)),
            compounds=[current_compound] + [next_compound] * (laps_to_simulate - 1)
        )
        
        # Scenario 2: Pit Later (at the end of target_lap)
        if target_lap <= current_lap or target_lap >= end_lap:
            raise ValueError("Target lap must be strictly between current_lap and end_lap.")
            
        laps_before_pit = target_lap - current_lap + 1
        s2_old_stint = self.simulate_stint(current_lap, target_lap, current_compound, current_tyre_age, base_features)
        s2_new_stint = self.simulate_stint(target_lap + 1, end_lap, next_compound, 0, base_features)
        
        s2_times = s2_old_stint + s2_new_stint
        s2_times[laps_before_pit - 1] += self.avg_pit_loss # Add pit loss
        
        s2_result = ScenarioResult(
            strategy_name=f"Pit Lap {target_lap}",
            total_time=sum(s2_times),
            lap_times=s2_times,
            tyre_ages=list(range(current_tyre_age, current_tyre_age + laps_before_pit)) + list(range(0, laps_to_simulate - laps_before_pit)),
            compounds=[current_compound] * laps_before_pit + [next_compound] * (laps_to_simulate - laps_before_pit)
        )
        
        return {
            "pit_now": s1_result,
            "pit_later": s2_result,
            "delta_seconds": s2_result.total_time - s1_result.total_time  # Positive means Pit Now is faster
        }
