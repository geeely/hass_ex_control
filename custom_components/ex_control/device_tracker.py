"""Where the car is, from its last GPS fix."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_CAR_ID
from .entity import CarEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if CONF_CAR_ID not in entry.data:
        return
    async_add_entities([CarTracker(hass, entry, "location", {"name": "Location"})])


class CarTracker(CarEntity, TrackerEntity, RestoreEntity):
    _attr_source_type = SourceType.GPS

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The map should not lose the car because Home Assistant restarted.
        if self.car.location is None and (last := await self.async_get_last_state()):
            lat, lon = last.attributes.get("latitude"), last.attributes.get("longitude")
            if lat is not None and lon is not None:
                self.car.location = {
                    "latitude": lat,
                    "longitude": lon,
                    "accuracy": last.attributes.get("gps_accuracy", 0),
                }

    @property
    def latitude(self) -> float | None:
        return (self.car.location or {}).get("latitude")

    @property
    def longitude(self) -> float | None:
        return (self.car.location or {}).get("longitude")

    @property
    def location_accuracy(self) -> float:
        return float((self.car.location or {}).get("accuracy") or 0)
