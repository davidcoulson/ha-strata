"""Data update coordinator for Strata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import StrataAuthError, StrataClient, StrataConnectionError, StrataError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type StrataConfigEntry = ConfigEntry[StrataCoordinator]


@dataclass(slots=True)
class StrataData:
    """Snapshot of the server state. All fields are None when unknown."""

    reachable: bool = False
    loaded: bool | None = None
    busy: bool | None = None
    model: str | None = None
    context_size: int | None = None
    kv_type: str | None = None
    engine_version: str | None = None
    started: datetime | None = None
    prompt_tokens: int | None = None
    queued: int | None = None
    requests_total: int | None = None
    generation_speed: float | None = None
    prompt_speed: float | None = None
    cache_hit_ratio: float | None = None
    draft_acceptance: float | None = None
    gpu_temperature: float | None = None
    gpu_utilization: float | None = None
    gpu_memory_used: float | None = None


def _dig(data: Any, *keys: str) -> Any:
    """Safely walk nested dicts."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _ratio(part: Any, whole: Any) -> float | None:
    """Return part/whole as a percentage, or None."""
    if not isinstance(part, int | float) or not isinstance(whole, int | float):
        return None
    if whole <= 0:
        return None
    return round(100 * part / whole, 1)


def parse_data(status: dict[str, Any], slots: Any, metrics: Any) -> StrataData:
    """Build a StrataData from the raw endpoint payloads."""
    slot_list = [s for s in slots if isinstance(s, dict)] if isinstance(slots, list) else []
    in_flight = _dig(status, "activity", "in_flight")
    busy = any(s.get("is_processing") for s in slot_list) or bool(in_flight)
    if _dig(metrics, "live", "state") not in (None, "idle"):
        busy = True

    timings = _dig(status, "last_timings")
    cache_n = _dig(timings, "cache_n")
    prompt_n = _dig(timings, "prompt_n")
    whole = (
        cache_n + prompt_n
        if isinstance(cache_n, int | float) and isinstance(prompt_n, int | float)
        else None
    )
    started = _dig(status, "started")

    prompt_tokens = None
    if slot_list:
        prompt_tokens = slot_list[0].get("n_prompt_tokens")

    return StrataData(
        reachable=True,
        loaded=bool(status.get("loaded")),
        busy=busy,
        model=status.get("model") if status.get("loaded") else None,
        context_size=_dig(status, "context", "native"),
        kv_type=_dig(metrics, "engine", "kv"),
        engine_version=status.get("engine") or _dig(metrics, "engine", "version"),
        started=(
            datetime.fromtimestamp(started, tz=UTC) if isinstance(started, int | float) else None
        ),
        prompt_tokens=prompt_tokens,
        queued=_dig(metrics, "live", "queued"),
        requests_total=_dig(status, "activity", "requests"),
        generation_speed=_dig(timings, "predicted_per_second"),
        prompt_speed=_dig(timings, "prompt_per_second"),
        cache_hit_ratio=_ratio(cache_n, whole),
        draft_acceptance=_ratio(_dig(timings, "draft_n_accepted"), _dig(timings, "draft_n")),
        gpu_temperature=_dig(status, "machine", "gpu", "temp_c"),
        gpu_utilization=_dig(status, "machine", "gpu", "util_pct"),
        gpu_memory_used=_dig(status, "machine", "gpu", "used_mib"),
    )


class StrataCoordinator(DataUpdateCoordinator[StrataData]):
    """Poll the Strata status endpoints together."""

    config_entry: StrataConfigEntry

    def __init__(self, hass: HomeAssistant, entry: StrataConfigEntry, client: StrataClient) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._was_reachable: bool | None = None

    async def _optional(self, call: Any) -> Any:
        """Fetch a secondary endpoint, tolerating failure."""
        try:
            return await call()
        except StrataError:
            return None

    async def _async_update_data(self) -> StrataData:
        """Fetch data. An offline server is a normal state, not an error."""
        try:
            status = await self.client.status()
        except StrataAuthError as err:
            raise ConfigEntryAuthFailed("Strata API key rejected") from err
        except StrataConnectionError:
            self._note_reachable(False)
            return StrataData(reachable=False)
        if not isinstance(status, dict):
            self._note_reachable(False)
            return StrataData(reachable=False)

        slots = await self._optional(self.client.slots)
        metrics = await self._optional(self.client.metrics)
        self._note_reachable(True)
        return parse_data(status, slots, metrics)

    def _note_reachable(self, reachable: bool) -> None:
        """Log reachability changes once instead of every poll."""
        if reachable != self._was_reachable and (self._was_reachable is not None or not reachable):
            if reachable:
                _LOGGER.info("Strata server is reachable again")
            else:
                _LOGGER.info("Strata server is not reachable")
        self._was_reachable = reachable
