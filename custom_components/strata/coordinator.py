"""Data update coordinator for Strata."""

from __future__ import annotations

import logging
import math
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


def _num(value: Any) -> int | float | None:
    """Return a finite number (not a bool), else None. Safe for huge integers."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        if not math.isfinite(value):
            return None
    except OverflowError:
        return None
    return value


def _count(value: Any) -> int | float | None:
    """Return a finite, non-negative number, else None."""
    number = _num(value)
    if number is None or number < 0:
        return None
    return number


def _text(value: Any) -> str | None:
    """Return a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def _timestamp(value: Any) -> datetime | None:
    """Convert a POSIX timestamp, tolerating out-of-range values."""
    number = _num(value)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _ratio(part: Any, whole: Any) -> float | None:
    """Return part/whole as a percentage, or None."""
    part, whole = _count(part), _count(whole)
    if part is None or whole is None or whole <= 0:
        return None
    try:
        result = 100 * part / whole
    except OverflowError:
        return None
    return round(result, 1) if math.isfinite(result) else None


def parse_data(status: dict[str, Any], slots: Any, metrics: Any) -> StrataData:
    """Build a StrataData from the raw endpoint payloads.

    Every field is validated on its own: anything malformed becomes None (unknown)
    and never an idle/unloaded state or an exception that would blank the other fields.
    """
    slot_list = [s for s in slots if isinstance(s, dict)] if isinstance(slots, list) else []
    in_flight = _count(_dig(status, "activity", "in_flight"))
    busy: bool | None
    slots_known = (
        isinstance(slots, list)
        and bool(slots)
        and all(isinstance(s, dict) and isinstance(s.get("is_processing"), bool) for s in slots)
    )
    if any(s.get("is_processing") is True for s in slot_list) or (in_flight or 0) > 0:
        busy = True
    elif slots_known or in_flight is not None:
        busy = False
    else:
        busy = None  # no explicit activity evidence: unknown, not idle

    timings = _dig(status, "last_timings")
    cache_n = _count(_dig(timings, "cache_n"))
    prompt_n = _count(_dig(timings, "prompt_n"))
    whole = None if cache_n is None or prompt_n is None else float(cache_n) + float(prompt_n)

    loaded = status.get("loaded")
    loaded = loaded if isinstance(loaded, bool) else None

    return StrataData(
        reachable=True,
        loaded=loaded,
        busy=busy,
        model=_text(status.get("model")) if loaded else None,
        context_size=_count(_dig(status, "context", "native")),
        kv_type=_text(_dig(metrics, "engine", "kv")),
        engine_version=_text(status.get("engine")) or _text(_dig(metrics, "engine", "version")),
        started=_timestamp(_dig(status, "started")),
        prompt_tokens=_count(slot_list[0].get("n_prompt_tokens")) if slot_list else None,
        queued=_count(_dig(metrics, "live", "queued")),
        requests_total=_count(_dig(status, "activity", "requests")),
        generation_speed=_count(_dig(timings, "predicted_per_second")),
        prompt_speed=_count(_dig(timings, "prompt_per_second")),
        cache_hit_ratio=_ratio(cache_n, whole),
        draft_acceptance=_ratio(_dig(timings, "draft_n_accepted"), _dig(timings, "draft_n")),
        gpu_temperature=_num(_dig(status, "machine", "gpu", "temp_c")),
        gpu_utilization=_count(_dig(status, "machine", "gpu", "util_pct")),
        gpu_memory_used=_count(_dig(status, "machine", "gpu", "used_mib")),
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
        try:
            data = parse_data(status, slots, metrics)
        except (TypeError, ValueError, ArithmeticError):  # defence in depth; fields are validated
            _LOGGER.debug("Unparseable Strata status payload", exc_info=True)
            self._note_reachable(False)
            return StrataData(reachable=False)
        self._note_reachable(True)
        return data

    def _note_reachable(self, reachable: bool) -> None:
        """Log reachability changes once instead of every poll."""
        if reachable != self._was_reachable and (self._was_reachable is not None or not reachable):
            if reachable:
                _LOGGER.info("Strata server is reachable again")
            else:
                _LOGGER.info("Strata server is not reachable")
        self._was_reachable = reachable
