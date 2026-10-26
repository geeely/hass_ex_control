"""The car's readings, as the car describes them in its hello."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAR_ID, CONF_SENSORS
from .entity import CarEntity
from .solar import controller


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if CONF_CAR_ID not in entry.data:
        return
    entities: list[SensorEntity] = [
        CarSensor(hass, entry, d) for d in entry.data.get(CONF_SENSORS, []) if not d.get("binary")
    ]
    entities.append(SolarStatus(hass, entry, "solar_status", {"name": "Solar charging status", "icon": "mdi:solar-power"}))
    entities.append(SolarTarget(hass, entry, "solar_target", {"name": "Solar charging target", "icon": "mdi:current-ac"}))
    async_add_entities(entities)


# HA rounds some device classes to whole numbers by default (12.6 V shows
# as 13 V); the car sends one decimal for these, so show it.
ONE_DECIMAL = {"V", "kW", "kWh", "°C", "kWh/100km", "A"}

# Live power flows. An offline car is parked and asleep, so its last reading
# (a charge that has since ended, say) would be wrong; these read 0 instead
# of keeping their last value like the rest.
ZERO_WHEN_OFFLINE = {"power", "charge_power", "charge_rate"}


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
        if desc.get("unit") in ONE_DECIMAL:
            self._attr_suggested_display_precision = 1
        self._restored: Any = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.slug not in self.car.sensors and (last := await self.async_get_last_sensor_data()):
            self._restored = last.native_value

    @property
    def native_value(self) -> Any:
        if self.slug in ZERO_WHEN_OFFLINE and not self.car.connected:
            return 0
        return self.car.sensors.get(self.slug, self._restored)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.car.attributes.get(self.slug)


class _Solar(CarEntity, SensorEntity):
    """Follows the solar controller rather than the car."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str, desc: dict[str, Any]) -> None:
        super().__init__(hass, entry, key, desc)
        self.entry_id = entry.entry_id

    async def async_added_to_hass(self) -> None:
        if c := controller(self.hass, self.entry_id):
            self.async_on_remove(c.add_listener(self._changed))


class SolarStatus(_Solar):
    """What the controller is doing and why, with the numbers it used."""

    @property
    def native_value(self) -> str | None:
        c = controller(self.hass, self.entry_id)
        return c.status[:255] if c else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        c = controller(self.hass, self.entry_id)
        return c.detail if c else None


class SolarTarget(_Solar):
    """The current the controller wants: 0 for stopped."""

    _attr_native_unit_of_measurement = "A"
    _attr_device_class = SensorDeviceClass.CURRENT

    @property
    def native_value(self) -> int | None:
        c = controller(self.hass, self.entry_id)
        return c.target_a if c else None
