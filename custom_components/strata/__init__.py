"""The Strata local LLM server integration."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import StrataClient
from .const import CONF_SSL, CONF_VERIFY_SSL, DEFAULT_SSL, DEFAULT_VERIFY_SSL
from .coordinator import StrataConfigEntry, StrataCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


def build_base_url(host: str, port: int, ssl: bool) -> str:
    """Build the server base URL."""
    return f"{'https' if ssl else 'http'}://{host}:{port}"


async def async_setup_entry(hass: HomeAssistant, entry: StrataConfigEntry) -> bool:
    """Set up Strata from a config entry."""
    data = entry.data
    session = async_get_clientsession(
        hass, verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    )
    client = StrataClient(
        session,
        build_base_url(data[CONF_HOST], data[CONF_PORT], data.get(CONF_SSL, DEFAULT_SSL)),
        data[CONF_API_KEY],
    )
    coordinator = StrataCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: StrataConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StrataConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
