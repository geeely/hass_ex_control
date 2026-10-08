"""Numeric controls: temperature, fan, seat heating, charge current."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controls import CarControl, controls_of


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(CarNumber(hass, entry, d) for d in controls_of(entry, "number"))


class CarNumber(CarControl, NumberEntity):
    _attr_mode = NumberMode.SLIDER

    def __init__(self, hass, entry, desc) -> None:
        super().__init__(hass, entry, desc)
        self._attr_native_min_value = desc.get("min", 0)
        self._attr_native_max_value = desc.get("max", 100)
        self._attr_native_step = desc.get("step", 1)
        self._attr_native_unit_of_measurement = desc.get("unit")

    @property
    def native_value(self) -> float | None:
        try:
            return float(self.value) if self.value is not None else None
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        self.send(f"{value:g}")
