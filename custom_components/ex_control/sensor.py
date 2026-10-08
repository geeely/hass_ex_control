"""The car's readings, as the car describes them in its hello."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAR_ID, CONF_SENSORS
from .entity import CarEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if CONF_CAR_ID not in entry.data:
        return
    async_add_entities(
        CarSensor(hass, entry, d) for d in entry.data.get(CONF_SENSORS, []) if not d.get("binary")
    )


def _enum(cls: type, value: str | None) -> Any:
    try:
        return cls(value) if value else None
    except ValueError:
        return None


class CarSensor(CarEntity, RestoreSensor):
    """Keeps its last value while the car is parked and offline."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, desc: dict[str, Any]) -> None:
        super().__init__(hass, entry, desc["slug"], desc)
        self.slug = desc["slug"]
        self._attr_native_unit_of_measurement = desc.get("unit")
        self._attr_device_class = _enum(SensorDeviceClass, desc.get("device_class"))
        self._attr_state_class = _enum(SensorStateClass, desc.get("state_class"))
        self._restored: Any = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.slug not in self.car.sensors and (last := await self.async_get_last_sensor_data()):
            self._restored = last.native_value

    @property
    def native_value(self) -> Any:
        return self.car.sensors.get(self.slug, self._restored)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.car.attributes.get(self.slug)
