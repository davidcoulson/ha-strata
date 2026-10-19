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


async def test_busy_via_metrics_and_inflight(hass: HomeAssistant, aioclient_mock, entry) -> None:
    mock_server(
        aioclient_mock,
        status={**STATUS, "activity": {"in_flight": 1, "requests": 3}},
        slots=[],
    )
    await _setup(hass, entry)
    assert entry.runtime_data.data.busy is True
    mock_server(
        aioclient_mock,
        metrics={"live": {"state": "prefill", "queued": 2}},
    )
    await entry.runtime_data.async_refresh()
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
