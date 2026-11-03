"""Sensorer: kurvens total og antal varer."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IndkobConfigEntry
from .const import DOMAIN
from .coordinator import NemligCoordinator


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class NemligSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


SENSORS: tuple[NemligSensorDescription, ...] = (
    NemligSensorDescription(
        key="basket_total",
        translation_key="basket_total",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="DKK",
        suggested_display_precision=2,
        value_fn=lambda b: _num(b.get("TotalPrice")),
    ),
    NemligSensorDescription(
        key="basket_products",
        translation_key="basket_products",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: _num(b.get("NumberOfProducts")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: IndkobConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(NemligSensor(coordinator, entry, d) for d in SENSORS)


class NemligSensor(CoordinatorEntity[NemligCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: NemligSensorDescription

    def __init__(
        self, coordinator: NemligCoordinator, entry: IndkobConfigEntry,
        description: NemligSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Indkøb",
            
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})
