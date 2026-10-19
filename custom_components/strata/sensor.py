"""Sensors for Strata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import StrataConfigEntry, StrataData
from .entity import StrataEntity

UNIT_TOKENS = "tokens"
UNIT_TOKENS_PER_SECOND = "tok/s"


@dataclass(frozen=True, kw_only=True)
class StrataSensorDescription(SensorEntityDescription):
    """Describes a Strata sensor."""

    value_fn: Callable[[StrataData], StateType | datetime]


SENSORS: tuple[StrataSensorDescription, ...] = (
    StrataSensorDescription(
        key="model",
        value_fn=lambda d: d.model,
    ),
    StrataSensorDescription(
        key="context_size",
        native_unit_of_measurement=UNIT_TOKENS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.context_size,
    ),
    StrataSensorDescription(
        key="kv_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.kv_type,
    ),
    StrataSensorDescription(
        key="engine_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.engine_version,
    ),
    StrataSensorDescription(
        key="started",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.started,
    ),
    StrataSensorDescription(
        key="prompt_tokens",
        native_unit_of_measurement=UNIT_TOKENS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.prompt_tokens,
    ),
    StrataSensorDescription(
        key="queued_requests",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.queued,
    ),
    StrataSensorDescription(
        key="requests_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.requests_total,
    ),
    StrataSensorDescription(
        key="generation_speed",
        native_unit_of_measurement=UNIT_TOKENS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.generation_speed,
    ),
    StrataSensorDescription(
        key="prompt_speed",
        native_unit_of_measurement=UNIT_TOKENS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.prompt_speed,
    ),
    StrataSensorDescription(
        key="cache_hit_ratio",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.cache_hit_ratio,
    ),
    StrataSensorDescription(
        key="draft_acceptance",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: d.draft_acceptance,
    ),
    StrataSensorDescription(
        key="gpu_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.gpu_temperature,
    ),
    StrataSensorDescription(
        key="gpu_utilization",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.gpu_utilization,
    ),
    StrataSensorDescription(
        key="gpu_memory_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda d: d.gpu_memory_used,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StrataConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(StrataSensor(coordinator, desc) for desc in SENSORS)


class StrataSensor(StrataEntity, SensorEntity):
    """A Strata sensor."""

    entity_description: StrataSensorDescription

    def __init__(self, coordinator, description: StrataSensorDescription) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator.data)
