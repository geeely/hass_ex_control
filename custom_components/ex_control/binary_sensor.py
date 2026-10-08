"""The car's on/off readings, plus whether it is connected right now."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_CAR_ID, CONF_SENSORS
from .entity import CarEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if CONF_CAR_ID not in entry.data:
        return
    entities: list[BinarySensorEntity] = [
        CarBinarySensor(hass, entry, d) for d in entry.data.get(CONF_SENSORS, []) if d.get("binary")
    ]
    entities.append(CarConnected(hass, entry, "connected", {"name": "Connected"}))
    async_add_entities(entities)


def _truthy(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("on", "true", "1")


class CarBinarySensor(CarEntity, BinarySensorEntity, RestoreEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, desc: dict[str, Any]) -> None:
        super().__init__(hass, entry, desc["slug"], desc)
        self.slug = desc["slug"]
        try:
            self._attr_device_class = BinarySensorDeviceClass(desc["device_class"]) if desc.get("device_class") else None
        except ValueError:
            self._attr_device_class = None
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.slug not in self.car.sensors and (last := await self.async_get_last_state()):
            self._restored = last.state == STATE_ON

    @property
    def is_on(self) -> bool | None:
        value = _truthy(self.car.sensors.get(self.slug))
        return self._restored if value is None else value


class CarConnected(CarEntity, BinarySensorEntity):
    """On while the car holds its link: parked and asleep reads off."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.car.connected
