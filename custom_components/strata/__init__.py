"""The Strata local LLM server integration."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.loader import BASE_PRELOAD_PLATFORMS

from .client import StrataClient
from .const import (
    CONF_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    build_base_url,
)
from .coordinator import StrataConfigEntry, StrataCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


def _import_code(package: str) -> None:
    """Import the new code in the import executor, not the event loop.

    After an unload HA still lists "<domain>.<platform>" as loaded, so it
    would import the new modules in the event loop (and warn about it);
    once they are in sys.modules its own import is a cache hit.
    """
    module = importlib.import_module(package)
    # The new module's list, plus what HA preloads with a package (diagnostics, ...).
    for name in (*module.PLATFORMS, *BASE_PRELOAD_PLATFORMS):
        if importlib.util.find_spec(f"{package}.{name}") is not None:
            importlib.import_module(f"{package}.{name}")


def _forget_code(hass: HomeAssistant, package: str, domain: str) -> None:
    """Drop a package's modules so the next setup imports them from disk again.

    Home Assistant keeps its own copy of each imported integration module
    (loader.py: hass.data["components"], keyed "<domain>" and
    "<domain>.<platform>") next to Python's sys.modules; both have to go.
    """
    for cache, root in (
        (sys.modules, package),
        (hass.data.get("components", {}), domain),
        (hass.data.get("missing_platforms", {}), domain),
    ):
        for name in [n for n in cache if n == root or n.startswith(root + ".")]:
            del cache[name]
    importlib.invalidate_caches()  # or a file added since the last import may not be found


_CODE_VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]


def _clear_marketplace_restart(hass: HomeAssistant) -> None:
    """Drop Marketplace's "restart to finish the update" repairs for Strata.

    Marketplace cannot see reload_code, so they would stay until a restart. Called from
    entry setup, it uses the new code's version even when the old handler did the reload;
    a repair for any other version still waits.
    """
    for (domain, issue_id), issue in list(ir.async_get(hass).issues.items()):
        if (
            domain == "marketplace"
            and issue_id.startswith("restart_required_")
            and issue.issue_domain == DOMAIN
            and issue_id.rsplit("/", 1)[-1].removeprefix("v") == _CODE_VERSION
        ):
            ir.async_delete_issue(hass, domain, issue_id)


def _register_reload_code(hass: HomeAssistant) -> None:
    """Dev: strata.reload_code loads the Python files from disk without a restart."""

    async def _reload_code(call: ServiceCall) -> None:
        # Disabled and ignored entries are never set up, so they are not ours to reload.
        entries = hass.config_entries.async_entries(
            DOMAIN, include_ignore=False, include_disabled=False
        )
        for entry in entries:
            if not await hass.config_entries.async_unload(entry.entry_id):
                raise HomeAssistantError(
                    f"{DOMAIN} did not unload; restart Home Assistant instead"
                )
        _forget_code(hass, __name__, DOMAIN)
        try:
            await hass.async_add_import_executor_job(_import_code, __name__)
        except Exception as err:
            # This handler stays registered, so the action works again once the code is fixed.
            raise HomeAssistantError(
                f"{DOMAIN} is unloaded: the new code did not load ({err}). "
                f"Fix it and call {DOMAIN}.reload_code again"
            ) from err
        failed = [e.title for e in entries if not await hass.config_entries.async_setup(e.entry_id)]
        if failed:
            raise HomeAssistantError(f"{DOMAIN} did not set up again for {failed}; see the log")

    async_register_admin_service(hass, DOMAIN, "reload_code", _reload_code)


async def async_setup_entry(hass: HomeAssistant, entry: StrataConfigEntry) -> bool:
    """Set up Strata from a config entry."""
    _register_reload_code(hass)
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
    _clear_marketplace_restart(hass)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: StrataConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StrataConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
