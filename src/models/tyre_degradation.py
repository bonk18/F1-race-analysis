"""Tyre degradation models.

Models the decay in lap time as tyres age, using:
- Baseline (Historical Stint-Median)
- Linear Regression
- Ridge Regression
- Gradient Boosting (LightGBM)
"""

from __future__ import annotations

import logging
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import OneHotEncoder

logger = logging.getLogger(__name__)


class TyreDegradationModel:
    """Trains and evaluates tyre degradation models."""

    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
        
        # Define feature sets
        self.linear_features = ["tyre_age"]
        self.ridge_features = [
            "tyre_age", "fuel_effect_proxy", "track_evolution_index",
            "track_temperature", "air_temperature"
        ]
        self.lgb_features = [
            "tyre_age", "fuel_effect_proxy", "track_evolution_index",
            "track_temperature", "air_temperature", "stint_baseline_pace",
            "rolling_median_pace_3L", "recent_degradation_slope_5L"
        ]

    def _prepare_data(self, df: pd.DataFrame, features: list[str], fit_encoder: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Prepare feature matrix X and target y."""
        # Drop rows with NaN in target or features
        df_clean = df.dropna(subset=["lap_duration"] + features + ["compound"]).copy()
        
        if df_clean.empty:
            raise ValueError("Dataset is empty after dropping NaNs.")
            
        y = df_clean["lap_duration"].values
        
        # Base numerical features
        X_num = df_clean[features].values
        
        # Categorical features (compound)
        compounds = df_clean[["compound"]].fillna("UNKNOWN")
        if fit_encoder:
            X_cat = self.encoder.fit_transform(compounds)
        else:
            X_cat = self.encoder.transform(compounds)
            
        X = np.hstack([X_num, X_cat])
        return X, y, df_clean

    def evaluate_grouped_cv(self, df: pd.DataFrame, model_type: str = "lgb", n_splits: int = 5) -> dict[str, float]:
        """Evaluate a model using Leave-One-Session-Out or Grouped K-Fold."""
        # We group by session_key to prevent data leakage (predicting lap 40 when training on lap 42 of the same race)
        if "session_key" not in df.columns:
            # If single session, group by driver_number
            groups = df["driver_number"].values
        else:
            groups = df["session_key"].values
            
        features = self.lgb_features
        if model_type == "linear":
            features = self.linear_features
        elif model_type == "ridge":
            features = self.ridge_features

        X, y, df_clean = self._prepare_data(df, features, fit_encoder=True)
        # Grouping strategy: use session_key if multiple races, else driver_number
        unique_sessions = np.unique(df_clean["session_key"].values) if "session_key" in df_clean.columns else []
        if len(unique_sessions) > 1:
            groups = df_clean["session_key"].values
        else:
            groups = df_clean["driver_number"].values
            
        gkf = GroupKFold(n_splits=min(n_splits, len(np.unique(groups))))
        
        maes = []
        rmses = []
        
        for train_idx, test_idx in gkf.split(X, y, groups):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            
            if model_type == "linear":
                model = LinearRegression()
                model.fit(X_train, y_train)
                preds = model.predict(X_test)
            elif model_type == "ridge":
                model = Ridge(alpha=1.0)
                model.fit(X_train, y_train)
                preds = model.predict(X_test)
            elif model_type == "lgb":
                model = lgb.LGBMRegressor(
                    n_estimators=100, 
                    learning_rate=0.05, 
                    max_depth=5, 
                    random_state=42,
                    verbose=-1
                )
                model.fit(X_train, y_train)
                preds = model.predict(X_test)
            elif model_type == "baseline":
                # Baseline predicts the mean of the training set
                preds = np.full_like(y_test, y_train.mean())
            else:
                raise ValueError(f"Unknown model_type: {model_type}")
                
            maes.append(mean_absolute_error(y_test, preds))
            rmses.append(root_mean_squared_error(y_test, preds))
            
        return {
            "model": model_type,
            "mae_mean": float(np.mean(maes)),
            "mae_std": float(np.std(maes)),
            "rmse_mean": float(np.mean(rmses))
        }

    def train_final_model(self, df: pd.DataFrame, model_type: str = "lgb") -> Any:
        """Train the final model on all data and save it in memory."""
        features = self.lgb_features if model_type == "lgb" else self.ridge_features
        X, y, _ = self._prepare_data(df, features, fit_encoder=True)
        
        if model_type == "lgb":
            model = lgb.LGBMRegressor(
                n_estimators=150, 
                learning_rate=0.05, 
                max_depth=6, 
                random_state=42,
                verbose=-1
            )
        else:
            model = Ridge(alpha=1.0)
            
        model.fit(X, y)
        self.models[model_type] = model
        return model
