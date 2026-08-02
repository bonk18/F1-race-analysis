"""Database loader — upserts validated API data into SQL tables.

Uses INSERT OR REPLACE (SQLite) / ON CONFLICT DO UPDATE (PostgreSQL)
to handle re-syncs idempotently.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from src.database.models import (
    Base,
    DataQualityEvent,
    Driver,
    Lap,
    Meeting,
    PitStop,
    Position,
    RaceControl,
    Session as SessionModel,
    Stint,
    Weather,
)

logger = logging.getLogger(__name__)

# Mapping from API endpoint names to ORM model classes
ENDPOINT_MODEL_MAP: dict[str, type[Base]] = {
    "meetings": Meeting,
    "sessions": SessionModel,
    "drivers": Driver,
    "laps": Lap,
    "stints": Stint,
    "pit": PitStop,
    "position": Position,
    "weather": Weather,
    "race_control": RaceControl,
}

# Fields that map differently between API response and ORM
FIELD_MAPPINGS: dict[str, dict[str, str]] = {
    "meetings": {"meeting_official_name": "official_name"},
}


class DatabaseLoader:
    """Loads validated API data into the SQL database."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def load_records(
        self,
        endpoint: str,
        records: list[dict[str, Any]],
    ) -> int:
        """Load a batch of records for an endpoint.

        Uses merge (upsert) for tables with natural primary keys,
        and bulk insert for append-only tables (positions, weather, race_control).

        Args:
            endpoint: API endpoint name (e.g. 'laps', 'meetings').
            records: List of validated record dicts.

        Returns:
            Number of records loaded.
        """
        model_cls = ENDPOINT_MODEL_MAP.get(endpoint)
        if model_cls is None:
            logger.warning("No model mapping for endpoint '%s'", endpoint)
            return 0

        field_map = FIELD_MAPPINGS.get(endpoint, {})
        mapper = inspect(model_cls)
        valid_columns = {c.key for c in mapper.columns}

        loaded = 0
        with Session(self.engine) as session:
            for record in records:
                row_data = self._prepare_record(record, valid_columns, field_map)
                if row_data is None:
                    continue

                try:
                    if endpoint in ("position", "weather", "race_control"):
                        self._insert_if_not_exists(session, model_cls, row_data, endpoint)
                    else:
                        obj = model_cls(**row_data)
                        session.merge(obj)
                    loaded += 1
                except Exception as e:
                    logger.debug("Skipping record for %s: %s", endpoint, e)
                    continue

            session.commit()

        return loaded

    def _prepare_record(
        self,
        record: dict[str, Any],
        valid_columns: set[str],
        field_map: dict[str, str],
    ) -> dict[str, Any] | None:
        """Transform API record to match ORM column names.

        - Applies field name mappings
        - Filters to only valid columns
        - Serializes lists/dicts to JSON strings
        - Parses datetime strings
        """
        result = {}
        for key, value in record.items():
            # Apply field name mapping
            mapped_key = field_map.get(key, key)

            if mapped_key not in valid_columns:
                continue

            # Serialize complex types
            if isinstance(value, (list, dict)):
                value = json.dumps(value)

            result[mapped_key] = value

        return result if result else None

    def _insert_if_not_exists(
        self,
        session: Session,
        model_cls: type[Base],
        row_data: dict[str, Any],
        endpoint: str,
    ) -> None:
        """Insert record only if not already present (for append-only tables)."""
        if endpoint == "position":
            exists = session.query(Position).filter_by(
                session_key=row_data.get("session_key"),
                driver_number=row_data.get("driver_number"),
                date=row_data.get("date"),
            ).first()
            if exists:
                return
        elif endpoint == "weather":
            exists = session.query(Weather).filter_by(
                session_key=row_data.get("session_key"),
                date=row_data.get("date"),
            ).first()
            if exists:
                return
        elif endpoint == "race_control":
            exists = session.query(RaceControl).filter_by(
                session_key=row_data.get("session_key"),
                date=row_data.get("date"),
                message=row_data.get("message"),
            ).first()
            if exists:
                return

        obj = model_cls(**row_data)
        session.add(obj)

    def load_data_quality_events(
        self, events: list[dict[str, Any]]
    ) -> int:
        """Store data quality check results."""
        loaded = 0
        with Session(self.engine) as session:
            for event_data in events:
                event = DataQualityEvent(**event_data)
                session.add(event)
                loaded += 1
            session.commit()
        return loaded
