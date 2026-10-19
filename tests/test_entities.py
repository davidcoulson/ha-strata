"""Entity and diagnostics tests."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.strata.diagnostics import async_get_config_entry_diagnostics

from .conftest import API_KEY, BASE, mock_server

P = "strata_10_0_0_5_"

EXPECTED = {
    "binary_sensor": {
        "server_reachable": ("on", "connectivity"),
        "model_loaded": ("on", None),
        "busy": ("off", "running"),
    },
    "sensor": {
        "model": ("qwen-test", None),
        "context_size": ("131072", None),
        "kv_cache_type": ("int8", None),
        "engine_version": ("0.1.45", None),
        "started": ("2026-10-19T", "timestamp"),
        "prompt_tokens_in_slot": ("6103", None),
        "queued_requests": ("0", None),
        "requests_served": ("11", None),
        "generation_speed": ("88.2", None),
        "prompt_processing_speed": ("445.2", None),
        "prompt_cache_hit_ratio": ("90.0", None),
        "draft_acceptance": ("64.0", None),
        "gpu_temperature": ("34", "temperature"),
        "gpu_utilization": ("7", None),
        "gpu_memory_used": ("21141.0", "data_size"),
    },
}


async def test_all_entities(hass: HomeAssistant, aioclient_mock, entry) -> None:
    mock_server(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    for domain, ents in EXPECTED.items():
        for suffix, (value, dclass) in ents.items():
            state = hass.states.get(f"{domain}.{P}{suffix}")
            assert state is not None, suffix
            assert state.state.startswith(value) or state.state == value, suffix
            assert state.attributes.get("device_class") == dclass, suffix
    assert len(ent_reg.entities) == 18
    assert ent_reg.async_get(f"binary_sensor.{P}server_reachable").unique_id == (
        "10.0.0.5:8095_reachable"
    )

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].manufacturer == "Strata"


async def test_diagnostics_redacts(hass: HomeAssistant, aioclient_mock, entry) -> None:
    mock_server(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["api_key"] == REDACTED
    assert diag["entry"]["host"] == REDACTED
    assert diag["data"]["model"] == "qwen-test"
    assert API_KEY not in str(diag)


async def test_diagnostics_offline(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.get(f"{BASE}/v1/status", exc=TimeoutError)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["data"]["reachable"] is False
    assert diag["data"]["started"] is None
