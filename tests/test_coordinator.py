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

from custom_components.strata.coordinator import _ratio, parse_data

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


def test_parse_overflow_and_malformed_fields() -> None:
    """Huge ints, odd types and bad booleans never raise and never read as definite state."""
    from custom_components.strata.coordinator import parse_data

    huge = 10**400
    data = parse_data(
        {
            "activity": {"in_flight": huge, "requests": huge},
            "last_timings": {
                "draft_n_accepted": huge,
                "draft_n": 1,
                "cache_n": huge,
                "prompt_n": 1.5,
            },
            "loaded": "false",
            "model": ["x"],
            "engine": 5,
            "context": {"native": "big"},
            "machine": {"gpu": {"temp_c": huge, "util_pct": -3, "used_mib": float("nan")}},
        },
        [{"n_prompt_tokens": "7"}],
        {"engine": {"kv": 3}, "live": {"queued": True}},
    )
    assert data.busy is None
    assert data.loaded is None
    assert data.model is None
    assert data.draft_acceptance is None
    assert data.cache_hit_ratio is None
    assert data.engine_version is None
    assert data.context_size is None
    assert data.kv_type is None
    assert data.queued is None
    assert data.prompt_tokens is None
    assert data.gpu_temperature is None
    assert data.gpu_utilization is None
    assert data.gpu_memory_used is None
    assert data.requests_total is None
    # Overflowing sum and ratio of finite parts are unknown, not an exception.
    big = 1.7e308
    assert (
        parse_data({"last_timings": {"cache_n": big, "prompt_n": big}}, None, None).cache_hit_ratio
        is None
    )
    assert (
        parse_data(
            {"last_timings": {"draft_n_accepted": big, "draft_n": 1e-300}}, None, None
        ).draft_acceptance
        is None
    )
    assert parse_data({"loaded": True, "model": "m"}, None, None).model == "m"


async def test_parser_failure_is_offline_not_crash(
    hass: HomeAssistant, aioclient_mock, entry, monkeypatch
) -> None:
    """If parsing ever raises, the server reads as offline instead of breaking the refresh."""
    from custom_components.strata import coordinator as coord

    def boom(*_args):
        raise OverflowError

    mock_server(aioclient_mock)
    monkeypatch.setattr(coord, "parse_data", boom)
    await _setup(hass, entry)
    assert hass.states.get("binary_sensor.strata_10_0_0_5_server_reachable").state == "off"


def test_ratio_integer_overflow_is_unknown() -> None:
    """An int that fits a float but overflows once scaled gives None, not an exception."""
    assert _ratio(10**15, 1) is None  # part above whole is never a percentage
    assert _ratio(5, 4) is None
    assert _ratio(1e15, 1e-300) is None  # scaled result is infinite
    assert _ratio(10**308, 1) is None  # out of the accepted range


def test_parse_values_beyond_state_limits_are_unknown() -> None:
    """Over-long text and absurdly large numbers read as unknown (HA caps state at 255 chars)."""
    from custom_components.strata.coordinator import parse_data

    data = parse_data(
        {"loaded": True, "model": "m" * 256, "activity": {"requests": 10**300}},
        None,
        {"engine": {"kv": "k" * 256}},
    )
    assert data.model is None
    assert data.kv_type is None
    assert data.requests_total is None
    ok = parse_data(
        {"loaded": True, "model": "m" * 255, "activity": {"requests": 10**15}}, None, None
    )
    assert ok.model == "m" * 255
    assert ok.requests_total == 10**15


def test_timestamp_out_of_datetime_range_is_unknown() -> None:
    """A number inside the accepted range but beyond datetime's years is still just unknown."""
    from custom_components.strata.coordinator import _timestamp

    assert _timestamp(1e14) is None


def test_prompt_tokens_sums_slots() -> None:
    slots = [{"n_prompt_tokens": 6103}, {"n_prompt_tokens": 800}, {"n_prompt_tokens": "x"}, 5]
    assert parse_data({}, slots, None).prompt_tokens == 6903
    assert parse_data({}, [{"n_prompt_tokens": None}], None).prompt_tokens is None


async def test_scan_interval_is_clamped(hass: HomeAssistant, aioclient_mock, entry) -> None:
    mock_server(aioclient_mock)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"scan_interval": 1})
    await _setup(hass, entry)
    assert entry.runtime_data.update_interval.total_seconds() == 5


def test_base_url_brackets_ipv6() -> None:
    from custom_components.strata.const import build_base_url

    assert build_base_url("::1", 8095, False) == "http://[::1]:8095"
    assert build_base_url("[::1]", 8095, True) == "https://[::1]:8095"
