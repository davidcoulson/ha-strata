"""Config flow for Strata."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import StrataAuthError, StrataClient, StrataConnectionError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    build_base_url,
)
from .coordinator import StrataConfigEntry

_LOGGER = logging.getLogger(__name__)


async def _validate(hass, host: str, port: int, ssl: bool, verify: bool, key: str) -> None:
    """Check the server answers /health and accepts the key."""
    client = StrataClient(
        async_get_clientsession(hass, verify_ssl=verify),
        build_base_url(host, port, ssl),
        key,
    )
    health = await client.health()
    if not isinstance(health, dict) or health.get("service") != "strata":
        raise StrataConnectionError("Not a Strata server")
    # /health is unauthenticated, so confirm the key against a protected endpoint.
    await client.status()


class StrataConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Strata."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: StrataConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return StrataOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            await self.async_set_unique_id(f"{host.lower()}:{port}")
            self._abort_if_unique_id_configured()
            try:
                await _validate(
                    self.hass,
                    host,
                    port,
                    user_input[CONF_SSL],
                    user_input[CONF_VERIFY_SSL],
                    user_input[CONF_API_KEY],
                )
            except StrataAuthError:
                errors["base"] = "invalid_auth"
            except StrataConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Strata ({host})", data={**user_input, CONF_HOST: host}
                )

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_API_KEY, default=defaults.get(CONF_API_KEY, "")): str,
                vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, DEFAULT_SSL)): bool,
                vol.Required(
                    CONF_VERIFY_SSL,
                    default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                ): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = entry.data
            try:
                await _validate(
                    self.hass,
                    data[CONF_HOST],
                    data[CONF_PORT],
                    data.get(CONF_SSL, DEFAULT_SSL),
                    data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                    user_input[CONF_API_KEY],
                )
            except StrataAuthError:
                errors["base"] = "invalid_auth"
            except StrataConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )


class StrataOptionsFlow(OptionsFlow):
    """Handle Strata options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
