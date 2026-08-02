"""Configuration loader for the F1 strategy analytics platform."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class CleaningConfig:
    """Thresholds for clean-lap classification."""

    mad_threshold: float = 4.0
    min_lap_number: int = 2
    max_duration_ratio: float = 2.0
    min_lap_duration: float = 30.0


@dataclass
class IngestionConfig:
    """Settings for OpenF1 API ingestion."""

    base_url: str = "https://api.openf1.org/v1"
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    cache_dir: str = "data/raw"

    @property
    def cache_path(self) -> Path:
        return PROJECT_ROOT / self.cache_dir


@dataclass
class DatabaseConfig:
    """Database connection settings."""

    url: str = "sqlite:///data/f1_strategy.db"

    @property
    def resolved_url(self) -> str:
        """Return DATABASE_URL from env or fallback to config."""
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url
        # Make SQLite paths absolute relative to project root
        if self.url.startswith("sqlite:///") and not self.url.startswith("sqlite:////"):
            db_path = self.url.replace("sqlite:///", "")
            abs_path = PROJECT_ROOT / db_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{abs_path}"
        return self.url


@dataclass
class AnalysisConfig:
    """Parameters for analytical computations."""

    pit_stop_window: int = 3
    consistency_pct_threshold: float = 0.005
    min_clean_laps: int = 5


@dataclass
class AppConfig:
    """Top-level application configuration."""

    cleaning: CleaningConfig = field(default_factory=CleaningConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file, falling back to defaults.

    Args:
        config_path: Path to config.yaml. If None, uses project root config.yaml.

    Returns:
        Populated AppConfig dataclass.
    """
    if config_path is None:
        config_path = PROJECT_ROOT / "config.yaml"

    config_path = Path(config_path)
    raw: dict[str, Any] = {}

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

    return AppConfig(
        cleaning=CleaningConfig(**raw.get("cleaning", {})),
        ingestion=IngestionConfig(**raw.get("ingestion", {})),
        database=DatabaseConfig(**raw.get("database", {})),
        analysis=AnalysisConfig(**raw.get("analysis", {})),
    )


# Global singleton — import this from anywhere
config = load_config()
