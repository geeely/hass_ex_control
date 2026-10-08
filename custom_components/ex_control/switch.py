"""On/off controls: A/C, recirculation, heating, charging and so on."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controls import CarControl, controls_of


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(CarSwitch(hass, entry, d) for d in controls_of(entry, "switch"))


class CarSwitch(CarControl, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        return None if self.value is None else self.value == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.send("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.send("off")
