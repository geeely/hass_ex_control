"""Shared by the control platforms: a control is live only while the car is."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_CAR_ID, CONF_CONTROLS
from .entity import CarEntity


def controls_of(entry: ConfigEntry, kind: str) -> list[dict[str, Any]]:
    if CONF_CAR_ID not in entry.data:
        return []
    return [d for d in entry.data.get(CONF_CONTROLS, []) if d.get("kind") == kind]


class CarControl(CarEntity):
    """A setting on the car. Its value is what the car last reported."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, desc: dict[str, Any]) -> None:
        # "control_" keeps these apart from sensors with the same slug (ac, fan).
        super().__init__(hass, entry, f"control_{desc['slug']}", desc)
        self.slug = desc["slug"]

    @property
    def available(self) -> bool:
        # A command to a car that is not connected would go nowhere.
        return self.car.connected

    @property
    def value(self) -> str | None:
        return self.car.controls.get(self.slug)

    def send(self, value: str) -> None:
        if not self.car.command(self.slug, value):
            raise HomeAssistantError("The car is not connected")
