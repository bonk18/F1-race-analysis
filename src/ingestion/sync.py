"""CLI entry point for syncing OpenF1 data into the local database.

Usage:
    python -m src.ingestion.sync --year 2024 --meeting-key 1229
    python -m src.ingestion.sync --year 2024              # sync all races in season
    python -m src.ingestion.sync --year 2024 --session-type Race  # only race sessions
"""

from __future__ import annotations

import logging
import sys
import time

import click

from src.database.engine import get_engine, init_db
from src.database.loader import DatabaseLoader
from src.ingestion.client import OpenF1Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Endpoints to sync for each race session, in dependency order
RACE_ENDPOINTS = [
    "drivers",
    "laps",
    "stints",
    "pit",
    "position",
    "weather",
    "race_control",
]


def sync_session(
    client: OpenF1Client,
    loader: DatabaseLoader,
    session_key: int,
    session_info: dict,
) -> dict[str, int]:
    """Sync all data for a single session.

    Returns:
        Dict of endpoint → record count ingested.
    """
    counts: dict[str, int] = {}
    session_name = session_info.get("session_name", "Unknown")
    session_type = session_info.get("session_type", "Unknown")
    logger.info(
        "  Syncing session %d: %s (%s)", session_key, session_name, session_type
    )

    for endpoint in RACE_ENDPOINTS:
        try:
            data = client.fetch(endpoint, {"session_key": session_key})
            if data:
                loader.load_records(endpoint, data)
                counts[endpoint] = len(data)
                logger.info("    %-15s %d records", endpoint, len(data))
            else:
                counts[endpoint] = 0
                logger.info("    %-15s no data", endpoint)
        except Exception as e:
            logger.error("    %-15s FAILED: %s", endpoint, e)
            counts[endpoint] = 0

    return counts


@click.command()
@click.option("--year", required=True, type=int, help="Season year (e.g. 2024)")
@click.option("--meeting-key", type=int, default=None, help="Specific meeting key")
@click.option(
    "--session-type",
    type=str,
    default=None,
    help="Filter by session type (e.g. Race, Qualifying)",
)
@click.option("--no-cache", is_flag=True, help="Bypass local cache, re-download all")
def main(
    year: int,
    meeting_key: int | None,
    session_type: str | None,
    no_cache: bool,
) -> None:
    """Sync OpenF1 data for a season or specific meeting into the database."""
    start_time = time.time()
    use_cache = not no_cache

    logger.info("=" * 60)
    logger.info("F1 Strategy Analytics — Data Sync")
    logger.info("Year: %d | Meeting: %s | Session: %s | Cache: %s",
                year, meeting_key or "ALL", session_type or "ALL", use_cache)
    logger.info("=" * 60)

    # Initialize database
    engine = get_engine()
    init_db(engine)
    loader = DatabaseLoader(engine)

    with OpenF1Client() as client:
        # ── Step 1: Fetch meetings ──────────────────────────────
        params: dict = {"year": year}
        if meeting_key:
            params["meeting_key"] = meeting_key

        meetings = client.get_meetings(**params)
        if not meetings:
            logger.error("No meetings found for year=%d, meeting_key=%s", year, meeting_key)
            sys.exit(1)

        # Filter out pre-season testing
        meetings = [m for m in meetings if "Testing" not in m.get("meeting_name", "")]
        logger.info("Found %d meeting(s)", len(meetings))

        # Load meetings into DB
        loader.load_records("meetings", meetings)

        total_records = 0

        for meeting in meetings:
            m_key = meeting["meeting_key"]
            m_name = meeting.get("meeting_name", "Unknown")
            logger.info("\n▶ Meeting: %s (key=%d)", m_name, m_key)

            # ── Step 2: Fetch sessions ──────────────────────────
            sess_params: dict = {"meeting_key": m_key}
            if session_type:
                sess_params["session_type"] = session_type

            sessions = client.fetch("sessions", sess_params, use_cache=use_cache)
            if not sessions:
                logger.warning("  No sessions found for meeting %s", m_name)
                continue

            loader.load_records("sessions", sessions)

            # ── Step 3: Sync each session ───────────────────────
            for session in sessions:
                s_key = session["session_key"]
                counts = sync_session(client, loader, s_key, session)
                total_records += sum(counts.values())

    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info("Sync complete. Total records: %d | Time: %.1fs", total_records, elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
