"""What every entity of a car shares: its device and its live state."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .car import CarState, cars
from .const import CONF_CAR_ID, CONF_MODEL, CONF_NAME, CONF_SW_VERSION, DOMAIN


def car_device_info(entry: ConfigEntry) -> DeviceInfo:
    """One device per car. A camera-only entry (no car id) is its own device."""
    car_id = entry.data.get(CONF_CAR_ID)
    if not car_id:
        return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer="EX Control")
    return DeviceInfo(
        identifiers={(DOMAIN, car_id)},
        name=entry.data.get(CONF_NAME) or entry.title,
        manufacturer="Geely",
        model="EX2",
        model_id=entry.data.get(CONF_MODEL),
        sw_version=entry.data.get(CONF_SW_VERSION),
    )


class CarEntity(Entity):
    """Follows the car's state; nothing polls."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str, desc: dict[str, Any]) -> None:
        self.car: CarState = cars(hass).get(entry.data[CONF_CAR_ID])
        self.desc = desc
        self._attr_unique_id = f"{entry.data[CONF_CAR_ID]}_{key}"
        self._attr_device_info = car_device_info(entry)
        self._attr_name = desc.get("name")
        if icon := desc.get("icon"):
            self._attr_icon = icon

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.car.add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()
