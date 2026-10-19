"""Coordinator and setup tests."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.strata.coordinator import _ratio

from .conftest import BASE, SLOTS, STATUS, mock_server


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_unload(hass: HomeAssistant, aioclient_mock, entry) -> None:
    mock_server(aioclient_mock)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data.model == "qwen-test"
    await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_offline_and_back(
    hass: HomeAssistant, aioclient_mock, entry, freezer: FrozenDateTimeFactory, caplog
) -> None:
    caplog.set_level(logging.INFO)
    mock_server(aioclient_mock)
    await _setup(hass, entry)
    assert hass.states.get("sensor.strata_10_0_0_5_model").state == "qwen-test"

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/v1/status", exc=aiohttp.ClientError)
    for _ in range(3):
        freezer.tick(timedelta(seconds=20))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.strata_10_0_0_5_model").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.strata_10_0_0_5_server_reachable").state == "off"
    assert caplog.text.count("not reachable") == 1
    assert "ERROR" not in caplog.text

    mock_server(aioclient_mock)
    freezer.tick(timedelta(seconds=20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.strata_10_0_0_5_model").state == "qwen-test"
    assert hass.states.get("binary_sensor.strata_10_0_0_5_server_reachable").state == "on"
    assert "reachable again" in caplog.text


async def test_offline_at_startup(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.get(f"{BASE}/v1/status", exc=TimeoutError)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.strata_10_0_0_5_model").state == STATE_UNAVAILABLE


async def test_bad_payload_is_offline(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.get(f"{BASE}/v1/status", json=["nope"])
    await _setup(hass, entry)
    assert hass.states.get("binary_sensor.strata_10_0_0_5_server_reachable").state == "off"


async def test_http_error_is_offline(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.get(f"{BASE}/v1/status", status=503)
    await _setup(hass, entry)
    assert hass.states.get("binary_sensor.strata_10_0_0_5_server_reachable").state == "off"


async def test_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.get(f"{BASE}/v1/status", status=401)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress()
    )


async def test_secondary_endpoints_optional(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.get(f"{BASE}/v1/status", json=STATUS)
    aioclient_mock.get(f"{BASE}/slots", status=500)
    aioclient_mock.get(f"{BASE}/metrics", exc=aiohttp.ClientError)
    await _setup(hass, entry)
    data = entry.runtime_data.data
    assert data.reachable and data.prompt_tokens is None and data.kv_type is None
    assert hass.states.get("sensor.strata_10_0_0_5_model").state == "qwen-test"


async def test_unloaded_and_busy(hass: HomeAssistant, aioclient_mock, entry) -> None:
    mock_server(
        aioclient_mock,
        status={**STATUS, "loaded": False, "last_timings": None, "started": None},
        slots=[{**SLOTS[0], "is_processing": True}, "junk"],
    )
    await _setup(hass, entry)
    data = entry.runtime_data.data
    assert data.loaded is False and data.model is None and data.busy is True
    assert data.cache_hit_ratio is None and data.started is None


async def test_busy_via_inflight(hass: HomeAssistant, aioclient_mock, entry) -> None:
    mock_server(
        aioclient_mock,
        status={**STATUS, "activity": {"in_flight": 1, "requests": 3}},
        slots=[],
    )
    await _setup(hass, entry)
    assert entry.runtime_data.data.busy is True


def test_ratio() -> None:
    assert _ratio(1, 4) == 25.0
    assert _ratio(None, 4) is None
    assert _ratio(1, 0) is None


async def test_auth_lost_while_running(
    hass: HomeAssistant, aioclient_mock, entry, freezer: FrozenDateTimeFactory
) -> None:
    mock_server(aioclient_mock)
    await _setup(hass, entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/v1/status", status=403)
    freezer.tick(timedelta(seconds=20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.strata_10_0_0_5_model").state == STATE_UNAVAILABLE
    assert any(
        f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress()
    )


def test_parse_unknown_activity_and_loaded() -> None:
    """Missing evidence stays unknown instead of reading as idle/unloaded."""
    from custom_components.strata.coordinator import parse_data

    data = parse_data({}, None, None)
    assert data.reachable is True
    assert data.busy is None
    assert data.loaded is None
    assert parse_data({"activity": {"in_flight": 0}}, None, None).busy is False
    assert parse_data({}, [{"is_processing": False}], None).busy is False
    assert parse_data({}, [{"is_processing": True}], None).busy is True
    assert parse_data({"loaded": False}, None, None).loaded is False


def test_parse_partial_slot_evidence_is_unknown() -> None:
    """Slots without an explicit is_processing flag are not evidence of idleness."""
    from custom_components.strata.coordinator import parse_data

    assert parse_data({}, [{}], None).busy is None
    assert parse_data({}, [{"is_processing": None}], None).busy is None
    assert parse_data({}, [{"is_processing": False}, {}], None).busy is None
    assert parse_data({}, [{"is_processing": False}, {"is_processing": True}], None).busy is True
    assert parse_data({"activity": {"in_flight": 2}}, [{}], None).busy is True
    assert parse_data({"activity": {"in_flight": 0}}, [{}], None).busy is False
    assert parse_data({"activity": {"in_flight": None}}, [{}], None).busy is None


def test_parse_malformed_slot_entries_are_unknown() -> None:
    """A null or scalar slot entry means that slot's activity is unknown."""
    from custom_components.strata.coordinator import parse_data

    assert parse_data({}, [{"is_processing": False}, None], None).busy is None
    assert parse_data({}, [{"is_processing": False}, 5], None).busy is None
    assert parse_data({}, [{"is_processing": True}, None], None).busy is True
    assert parse_data({}, "bad", None).busy is None


def test_parse_invalid_counts_and_timestamps() -> None:
    """Invalid in-flight counts are unknown; a bad timestamp does not break parsing."""
    from custom_components.strata.coordinator import parse_data

    for bad in (-1, False, True, float("nan"), float("inf"), "2", None):
        got = parse_data({"activity": {"in_flight": bad}}, None, None).busy
        assert got is None, bad
    for bad in (1e20, 1.7e12 * 1000, -1e20, True, "x"):
        data = parse_data({"started": bad, "loaded": True, "model": "m"}, None, None)
        assert data.started is None
        assert data.model == "m"
    assert parse_data({"started": 1_700_000_000}, None, None).started is not None
