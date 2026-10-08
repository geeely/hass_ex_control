"""The doors. Only offered when the car's own Vehicle control switch is on."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controls import CarControl, controls_of


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(CarLock(hass, entry, d) for d in controls_of(entry, "lock"))


class CarLock(CarControl, LockEntity):
    @property
    def is_locked(self) -> bool | None:
        return None if self.value is None else self.value == "on"

    async def async_lock(self, **kwargs: Any) -> None:
        self.send("on")

    async def async_unlock(self, **kwargs: Any) -> None:
        self.send("off")
