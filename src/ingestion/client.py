"""OpenF1 API client with caching, retries, timeouts, and response validation.

Usage:
    client = OpenF1Client()
    meetings = client.get_meetings(year=2024)
    laps = client.get_laps(session_key=9472, driver_number=1)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import config
from src.ingestion.schemas import ENDPOINT_SCHEMAS

logger = logging.getLogger(__name__)


class OpenF1Error(Exception):
    """Base exception for OpenF1 API errors."""


class OpenF1RateLimitError(OpenF1Error):
    """Raised when the API returns 429 Too Many Requests."""


class OpenF1Client:
    """Reusable client for the OpenF1 REST API.

    Features:
        - Local JSON caching to avoid repeated downloads of unchanged data
        - Automatic retries with exponential backoff
        - Configurable timeouts
        - Response validation via Pydantic schemas
        - Metadata recording (ingestion timestamps, source URLs)
    """

    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: str | Path | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        cfg = config.ingestion
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        self.cache_dir = Path(cache_dir or cfg.cache_path)
        self.timeout = timeout or cfg.timeout
        self.max_retries = max_retries or cfg.max_retries
        self.requests_per_second = cfg.requests_per_second
        self.requests_per_minute = cfg.requests_per_minute

        # A rolling-window limiter enforces both published OpenF1 limits.
        self._request_times: deque[float] = deque()
        self._rate_lock = Lock()
        self._monotonic = time.monotonic
        self._sleep = time.sleep

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> OpenF1Client:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── Cache helpers ──────────────────────────────────────────────

    def _cache_key(self, endpoint: str, params: dict[str, Any]) -> str:
        """Generate a deterministic cache filename from endpoint + params."""
        sorted_params = sorted(params.items())
        raw = f"{endpoint}|{sorted_params}"
        digest = hashlib.md5(raw.encode()).hexdigest()[:12]
        safe_endpoint = endpoint.replace("/", "_")
        return f"{safe_endpoint}_{digest}.json"

    def _read_cache(self, cache_file: Path) -> list[dict[str, Any]] | None:
        """Read cached response if it exists."""
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                logger.debug("Cache hit: %s", cache_file.name)
                return cached.get("data", cached) if isinstance(cached, dict) else cached
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Cache read failed for %s: %s", cache_file.name, e)
        return None

    def _write_cache(
        self,
        cache_file: Path,
        data: list[dict[str, Any]],
        endpoint: str,
        params: dict[str, Any],
    ) -> None:
        """Write API response to cache with metadata."""
        cache_record = {
            "metadata": {
                "endpoint": endpoint,
                "params": params,
                "record_count": len(data),
                "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "source_url": f"{self.base_url}/{endpoint}",
            },
            "data": data,
        }
        try:
            with open(cache_file, "w") as f:
                json.dump(cache_record, f, indent=2, default=str)
            logger.debug("Cached %d records to %s", len(data), cache_file.name)
        except OSError as e:
            logger.warning("Cache write failed for %s: %s", cache_file.name, e)

    # ── Core request method ────────────────────────────────────────

    def _wait_for_rate_limit(self) -> None:
        """Block until a request is allowed by both rolling windows."""
        with self._rate_lock:
            while True:
                now = self._monotonic()
                minute_cutoff = now - 60.0
                while self._request_times and self._request_times[0] <= minute_cutoff:
                    self._request_times.popleft()

                waits: list[float] = []
                if len(self._request_times) >= self.requests_per_minute:
                    waits.append(self._request_times[0] + 60.0 - now)

                recent = [stamp for stamp in self._request_times if stamp > now - 1.0]
                if len(recent) >= self.requests_per_second:
                    waits.append(recent[-self.requests_per_second] + 1.0 - now)

                wait_for = max(waits, default=0.0)
                if wait_for <= 0:
                    self._request_times.append(now)
                    return

                logger.info("OpenF1 rate limit: waiting %.2fs", wait_for)
                self._sleep(wait_for)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, OpenF1RateLimitError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _request(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Make a GET request to the OpenF1 API with retry logic.

        Args:
            endpoint: API endpoint path (e.g. 'laps', 'weather').
            params: Query parameters.

        Returns:
            List of response records.

        Raises:
            OpenF1Error: On non-retryable API errors.
            OpenF1RateLimitError: On 429 (triggers retry).
        """
        url = f"/{endpoint}"
        self._wait_for_rate_limit()
        logger.info("GET %s/%s params=%s", self.base_url, endpoint, params)

        response = self._client.get(url, params=params)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(0.0, float(retry_after))
                except ValueError:
                    delay = 0.0
                if delay:
                    logger.warning("OpenF1 returned 429; waiting %.2fs", delay)
                    self._sleep(delay)
            raise OpenF1RateLimitError("Rate limited by OpenF1 API")

        if response.status_code == 404:
            logger.warning("Endpoint %s returned 404 — may not exist for this session", endpoint)
            return []

        if response.status_code != 200:
            raise OpenF1Error(
                f"API error {response.status_code} for {endpoint}: {response.text[:200]}"
            )

        data = response.json()
        if not isinstance(data, list):
            logger.warning("Unexpected response type for %s: %s", endpoint, type(data))
            return []

        return data

    # ── Public fetch method ────────────────────────────────────────

    def fetch(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
        validate: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch data from an OpenF1 endpoint.

        Args:
            endpoint: Endpoint name (e.g. 'meetings', 'laps').
            params: Query parameters.
            use_cache: Whether to read/write from local cache.
            validate: Whether to validate through Pydantic schemas.

        Returns:
            List of validated record dicts.
        """
        params = params or {}
        cache_file = self.cache_dir / self._cache_key(endpoint, params)

        # Check cache first
        if use_cache:
            cached = self._read_cache(cache_file)
            if cached is not None:
                if validate:
                    return self._validate(endpoint, cached)
                return cached

        # Fetch from API
        data = self._request(endpoint, params)

        # Cache the raw response
        if use_cache and data:
            self._write_cache(cache_file, data, endpoint, params)

        if validate:
            return self._validate(endpoint, data)
        return data

    def _validate(
        self, endpoint: str, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Validate records against the Pydantic schema for the endpoint.

        Invalid records are logged and skipped, not raised as errors.
        """
        schema_cls = ENDPOINT_SCHEMAS.get(endpoint)
        if schema_cls is None:
            logger.debug("No schema for endpoint '%s', returning raw data", endpoint)
            return records

        validated = []
        error_count = 0
        for i, record in enumerate(records):
            try:
                obj = schema_cls.model_validate(record)
                validated.append(obj.model_dump())
            except ValidationError as e:
                error_count += 1
                if error_count <= 5:
                    logger.warning(
                        "Validation error in %s record %d: %s",
                        endpoint, i, e.error_count(),
                    )

        if error_count > 0:
            logger.warning(
                "Endpoint '%s': %d/%d records failed validation",
                endpoint, error_count, len(records),
            )
        return validated

    # ── Typed convenience methods ──────────────────────────────────

    def get_meetings(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch meetings. Common params: year."""
        return self.fetch("meetings", params)

    def get_sessions(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch sessions. Common params: meeting_key, session_type."""
        return self.fetch("sessions", params)

    def get_drivers(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch drivers. Common params: session_key."""
        return self.fetch("drivers", params)

    def get_laps(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch laps. Common params: session_key, driver_number."""
        return self.fetch("laps", params)

    def get_stints(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch stints. Common params: session_key, driver_number."""
        return self.fetch("stints", params)

    def get_pit_stops(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch pit stops. Common params: session_key, driver_number."""
        return self.fetch("pit", params)

    def get_positions(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch position changes. Common params: session_key, driver_number."""
        return self.fetch("position", params)

    def get_intervals(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch interval/gap data. Common params: session_key, driver_number."""
        return self.fetch("intervals", params)

    def get_weather(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch weather data. Common params: session_key."""
        return self.fetch("weather", params)

    def get_race_control(self, **params: Any) -> list[dict[str, Any]]:
        """Fetch race control events. Common params: session_key."""
        return self.fetch("race_control", params)
