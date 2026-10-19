"""Base entity for Strata."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SSL, DEFAULT_SSL, DOMAIN, build_base_url
from .coordinator import StrataCoordinator


class StrataEntity(CoordinatorEntity[StrataCoordinator]):
    """Common behaviour: one device, translated names."""

    _attr_has_entity_name = True
    # Entities other than "reachable" go unavailable while the server is off.
    _requires_server = True

    def __init__(self, coordinator: StrataCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=f"Strata ({entry.data[CONF_HOST]})",
            manufacturer="Strata",
            model="Local LLM server",
            configuration_url=build_base_url(
                entry.data[CONF_HOST],
                entry.data[CONF_PORT],
                entry.data.get(CONF_SSL, DEFAULT_SSL),
            ),
        )

    @property
    def available(self) -> bool:
        """Return True when the server is reachable (if the entity needs it)."""
        if not super().available:
            return False
        return self.coordinator.data.reachable or not self._requires_server
