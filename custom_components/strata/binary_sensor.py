"""Binary sensors for Strata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import StrataConfigEntry, StrataData
from .entity import StrataEntity


@dataclass(frozen=True, kw_only=True)
class StrataBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Strata binary sensor."""

    value_fn: Callable[[StrataData], bool | None]
    requires_server: bool = True


BINARY_SENSORS: tuple[StrataBinarySensorDescription, ...] = (
    StrataBinarySensorDescription(
        key="reachable",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.reachable,
        requires_server=False,
    ),
    StrataBinarySensorDescription(
        key="model_loaded",
        value_fn=lambda d: d.loaded,
    ),
    StrataBinarySensorDescription(
        key="busy",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: d.busy,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StrataConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(StrataBinarySensor(coordinator, desc) for desc in BINARY_SENSORS)


class StrataBinarySensor(StrataEntity, BinarySensorEntity):
    """A Strata binary sensor."""

    entity_description: StrataBinarySensorDescription

    def __init__(self, coordinator, description: StrataBinarySensorDescription) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._requires_server = description.requires_server

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)
