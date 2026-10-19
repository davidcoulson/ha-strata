"""Config, reauth and options flow tests."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.strata.const import DOMAIN

from .conftest import API_KEY, BASE, HEALTH, HOST, PORT, mock_server

USER_INPUT = {
    "host": HOST,
    "port": PORT,
    "api_key": API_KEY,
    "ssl": False,
    "verify_ssl": False,
}


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_success(hass: HomeAssistant, aioclient_mock) -> None:
    mock_server(aioclient_mock)
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.strata.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == HOST
    assert result["result"].unique_id == f"{HOST}:{PORT}"


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/health", exc=aiohttp.ClientError)
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_not_strata(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/health", json={"status": "ok"})
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_invalid_auth_then_recover(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/v1/status", status=401)
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "invalid_auth"}
    mock_server(aioclient_mock)
    with patch("custom_components.strata.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate(hass: HomeAssistant, aioclient_mock, entry) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_configure(
        (await _start(hass))["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, aioclient_mock, entry) -> None:
    entry.add_to_hass(hass)
    mock_server(aioclient_mock)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/v1/status", status=401)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "bad"})
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", exc=aiohttp.ClientError)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "x"})
    assert result["errors"] == {"base": "cannot_connect"}

    mock_server(aioclient_mock)
    with patch("custom_components.strata.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "new-key"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "new-key"


async def test_options(hass: HomeAssistant, aioclient_mock, entry) -> None:
    entry.add_to_hass(hass)
    mock_server(aioclient_mock)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["scan_interval"] == 30
    assert entry.runtime_data.update_interval.total_seconds() == 30
