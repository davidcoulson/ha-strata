"""Minimal read-only client for the Strata server API."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT


class StrataError(Exception):
    """Base error for Strata API problems."""


class StrataConnectionError(StrataError):
    """The server could not be reached or answered badly."""


class StrataAuthError(StrataError):
    """The API key was rejected."""


class StrataClient:
    """Tiny GET-only client; Strata exposes status endpoints we poll."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, api_key: str) -> None:
        """Initialise the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def get(self, path: str, *, auth: bool = True) -> Any:
        """GET a JSON document from the server."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.get(
                    f"{self._base_url}{path}",
                    headers=self._headers if auth else None,
                )
                if resp.status in (401, 403):
                    raise StrataAuthError(f"{path} returned {resp.status}")
                if resp.status >= 400:
                    raise StrataConnectionError(f"{path} returned {resp.status}")
                return await resp.json(content_type=None)
        except StrataError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise StrataConnectionError(str(err)) from err

    async def health(self) -> dict[str, Any]:
        """Fetch /health (not authenticated by the server)."""
        return await self.get("/health", auth=False)

    async def status(self) -> dict[str, Any]:
        """Fetch /v1/status (requires a valid API key)."""
        return await self.get("/v1/status")

    async def slots(self) -> list[dict[str, Any]]:
        """Fetch /slots."""
        return await self.get("/slots")

    async def metrics(self) -> dict[str, Any]:
        """Fetch /metrics."""
        return await self.get("/metrics")
