"""Pit stop outcome models.

Predicts the expected pace gain after a pit stop, using:
- Baseline (Historical average)
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
from src.analytics.undercut import PitStrategyAnalyzer

logger = logging.getLogger(__name__)


class PitOutcomeModel:
    """Trains and evaluates pit stop outcome models."""

    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
        
        self.linear_features = ["pit_duration", "tyre_age_before"]
        self.ridge_features = [
            "pit_duration", "tyre_age_before", "pre_stop_pace"
        ]
        self.lgb_features = [
            "pit_duration", "tyre_age_before", "pre_stop_pace"
        ]

    def _prepare_data(self, pit_df: pd.DataFrame, features: list[str], fit_encoder: bool = False) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
        """Prepare feature matrix X and target y."""
        df_clean = pit_df.dropna(subset=["pace_gain"] + features + ["compound_before", "compound_after"]).copy()
        
        if df_clean.empty:
            raise ValueError("Dataset is empty after dropping NaNs.")
            
        y = df_clean["pace_gain"].values
        X_num = df_clean[features].values
        
        compounds = df_clean[["compound_before", "compound_after"]].fillna("UNKNOWN")
        if fit_encoder:
            X_cat = self.encoder.fit_transform(compounds)
        else:
            X_cat = self.encoder.transform(compounds)
            
        X = np.hstack([X_num, X_cat])
        return X, y, df_clean

    def evaluate_grouped_cv(self, df: pd.DataFrame, model_type: str = "lgb", n_splits: int = 5) -> dict[str, float]:
        """Evaluate a model using Grouped K-Fold."""
        features = self.lgb_features
        if model_type == "linear":
            features = self.linear_features
        elif model_type == "ridge":
            features = self.ridge_features

        X, y, df_clean = self._prepare_data(df, features, fit_encoder=True)
        
        unique_sessions = np.unique(df_clean["session_key"].values) if "session_key" in df_clean.columns else []
        if len(unique_sessions) > 1:
            groups = df_clean["session_key"].values
        else:
            groups = df_clean["driver_number"].values
            
        gkf = GroupKFold(n_splits=min(n_splits, max(2, len(np.unique(groups)))))
        
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
                    n_estimators=50, 
                    learning_rate=0.05, 
                    max_depth=3, 
                    random_state=42,
                    verbose=-1
                )
                model.fit(X_train, y_train)
                preds = model.predict(X_test)
            elif model_type == "baseline":
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
