"""Hevy public REST API client (workouts).

Thin async wrapper over Hevy's ``/v1`` API, authenticated with a personal
``api-key`` header. Built lazily from config, mirroring ``llm_client``: importing
or constructing it never needs a key — only an actual request does — so the app
boots fine before Hevy is configured.

The service layer is handed a client instance (so tests pass a fake with the same
shape and never hit the network). ``HevyClient.from_config()`` is the production
factory.

Docs: https://api.hevyapp.com/docs/ — ``GET /v1/workouts`` is paginated
(``{"page", "page_count", "workouts": [...]}``); each workout is the
exercise→set tree we normalise downstream.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from vitals.config import Config, load_config

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_MAX_PAGE_SIZE = 10  # Hevy caps pageSize at 10.


class HevyNotConfigured(RuntimeError):
    """Raised when a request is attempted without ``VITALS_HEVY_API_KEY``."""


class HevyAPIError(RuntimeError):
    """Non-2xx response from the Hevy API (status code carried for the caller)."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Hevy API {status_code}: {message}")


class HevyClient:
    def __init__(self, config: Optional[Config] = None):
        self._config = config or load_config()

    @classmethod
    def from_config(cls, config: Optional[Config] = None) -> "HevyClient":
        return cls(config)

    @property
    def is_configured(self) -> bool:
        return bool(self._config.hevy_api_key)

    def _headers(self) -> dict[str, str]:
        if not self._config.hevy_api_key:
            raise HevyNotConfigured("VITALS_HEVY_API_KEY is not set")
        return {"api-key": self._config.hevy_api_key, "Accept": "application/json"}

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        import httpx  # lazy — httpx is already a dep, imported here for symmetry

        url = f"{self._config.hevy_base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
        if resp.status_code >= 400:
            raise HevyAPIError(resp.status_code, resp.text[:200])
        return resp.json()

    async def workout_count(self) -> int:
        data = await self._get("/v1/workouts/count")
        return int(data.get("workout_count", 0))

    async def fetch_workouts_page(self, page: int = 1, page_size: int = _MAX_PAGE_SIZE) -> dict:
        """One page of workouts, newest first. Returns the raw Hevy envelope
        (``page``, ``page_count``, ``workouts``)."""
        page_size = min(max(1, page_size), _MAX_PAGE_SIZE)
        return await self._get(
            "/v1/workouts", params={"page": page, "pageSize": page_size}
        )

    async def fetch_workouts(self, *, max_pages: int = 50) -> list[dict]:
        """Walk the paginated workout list (newest first) and return the flat list.

        ``max_pages`` bounds a first-ever full backfill; routine syncs hit far
        fewer pages because the service stops once it meets already-stored ids.
        """
        workouts: list[dict] = []
        page = 1
        while page <= max_pages:
            envelope = await self.fetch_workouts_page(page=page)
            batch = envelope.get("workouts") or []
            workouts.extend(batch)
            page_count = int(envelope.get("page_count", page))
            if page >= page_count or not batch:
                break
            page += 1
        return workouts
