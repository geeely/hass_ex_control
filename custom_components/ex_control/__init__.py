"""EX Control: the car in Home Assistant, as one device per car.

The car connects to Home Assistant's WebSocket with the token it already has
and introduces itself (link.py). It becomes a config entry of its own, with
its sensors, controls, location and live camera all on one device, and any
number of cars can do the same. Commands go back down the car's own
connection, so nothing has to be opened on the owner's router.

The live camera (views.py, hub.py) is uploaded by the car over that same URL
and played through Home Assistant's own go2rtc.

It also ships the dashboard card (frontend.py): the car's picture in its own
paint colour, its state at a glance, and its place on a map.

Three kinds of entry:
- a car (data has car_id), added by the car itself;
- the hub (data has hub), added by hand once so the integration is loaded and
  listening before any car has connected; it has no entities;
- camera-only (just a stream), the setup from before cars spoke to the
  integration. Still works; a car connecting with the same stream name takes
  it over.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import CONF_CAR_ID, CONF_HUB, DOMAIN
from .frontend import async_remove_frontend, async_setup_frontend
from .hub import Hub
from .link import async_register as async_register_link
from .views import IngestView, LiveView

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CAMERA_ONLY = [Platform.CAMERA]
CAR_PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


def _platforms(entry: ConfigEntry) -> list[Platform]:
    if CONF_CAR_ID in entry.data:
        return CAR_PLATFORMS
    return [] if entry.data.get(CONF_HUB) else CAMERA_ONLY


def _hub(hass: HomeAssistant) -> Hub:
    data = hass.data.setdefault(DOMAIN, {})
    if "hub" not in data:
        hub = data["hub"] = Hub()
        # Views and commands cannot be removed, so they are registered once per start.
        hass.http.register_view(IngestView(hub))
        hass.http.register_view(LiveView(hub))
        async_register_link(hass)
    return data["hub"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    # Runs whenever any entry exists (the hub entry guarantees one), so a new
    # car's hello always finds the command waiting.
    _hub(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _hub(hass)
    if CONF_CAR_ID in entry.data:
        # A camera-only entry this car took over had a device of its own;
        # the camera now lives on the car's device, so that one is empty.
        dev_reg = dr.async_get(hass)
        if old := dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)}):
            dev_reg.async_remove_device(old.id)
    await async_setup_frontend(hass)
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, _platforms(entry))


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_remove_frontend(hass, entry.entry_id)
