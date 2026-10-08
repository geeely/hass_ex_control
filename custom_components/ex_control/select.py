"""Choice controls (the camera), and the car's paint for the dashboard card."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_CAR_ID
from .controls import CarControl, controls_of
from .entity import CarEntity

# The EX2's factory paints; the card turns these names into colours.
PAINTS = ["Moon White", "Star Silver", "Comet Grey", "Nebula Beige", "Aurora Green", "Nova Pink"]
ROOFS = ["Body colour", "Black"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if CONF_CAR_ID not in entry.data:
        return
    entities: list[SelectEntity] = [CarSelect(hass, entry, d) for d in controls_of(entry, "select")]
    entities.append(Appearance(hass, entry, "paint", {"name": "Paint", "icon": "mdi:palette"}, PAINTS))
    entities.append(Appearance(hass, entry, "roof", {"name": "Roof", "icon": "mdi:car-select"}, ROOFS))
    async_add_entities(entities)


class CarSelect(CarControl, SelectEntity):
    def __init__(self, hass, entry, desc) -> None:
        super().__init__(hass, entry, desc)
        self._attr_options = list(desc.get("options") or [])

    @property
    def current_option(self) -> str | None:
        return self.value if self.value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        self.send(option)


class Appearance(CarEntity, SelectEntity, RestoreEntity):
    """Set once by the owner; nothing on the car reports its paint."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass, entry, key: str, desc: dict[str, Any], options: list[str]) -> None:
        super().__init__(hass, entry, key, desc)
        self._attr_options = options
        self._attr_current_option = options[0]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in self._attr_options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()
