"""The car's WebSocket commands: ex_control/hello and ex_control/state.

See car.py for the shape of the conversation. Both commands need an admin,
because hello can create a config entry; the car's token is the owner's.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .car import cars
from .const import (
    CONF_CAR_ID,
    CONF_CONTROLS,
    CONF_MODEL,
    CONF_NAME,
    CONF_SENSORS,
    CONF_STREAM,
    CONF_SW_VERSION,
    DOMAIN,
    PROTOCOL,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required("slug"): str,
        vol.Required("name"): str,
        vol.Optional("binary", default=False): bool,
        vol.Optional("unit"): vol.Any(str, None),
        vol.Optional("device_class"): vol.Any(str, None),
        vol.Optional("state_class"): vol.Any(str, None),
        vol.Optional("icon"): vol.Any(str, None),
    },
    extra=vol.REMOVE_EXTRA,
)

CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required("slug"): str,
        vol.Required("name"): str,
        vol.Required("kind"): vol.In(["number", "switch", "select", "lock"]),
        vol.Optional("min"): vol.Coerce(float),
        vol.Optional("max"): vol.Coerce(float),
        vol.Optional("step"): vol.Coerce(float),
        vol.Optional("unit"): vol.Any(str, None),
        vol.Optional("icon"): vol.Any(str, None),
        vol.Optional("options"): [str],
    },
    extra=vol.REMOVE_EXTRA,
)


def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_hello)
    websocket_api.async_register_command(hass, ws_state)


def entry_for_car(hass: HomeAssistant, car_id: str) -> ConfigEntry | None:
    return hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, car_id)


def _entry_data(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_CAR_ID: msg["car_id"],
        CONF_NAME: msg["name"],
        CONF_MODEL: msg.get("model"),
        CONF_SW_VERSION: msg.get("sw_version"),
        CONF_STREAM: msg.get("camera_stream") or f"{msg['car_id']}_camera",
        CONF_SENSORS: msg.get("sensors", []),
        CONF_CONTROLS: msg.get("controls", []),
    }


async def _ensure_entry(hass: HomeAssistant, msg: dict[str, Any]) -> ConfigEntry | None:
    """Find, adopt or create this car's entry, and keep its description current."""
    car_id = msg["car_id"]
    data = _entry_data(msg)

    entry = entry_for_car(hass, car_id)
    if entry is None:
        # A camera-only entry from before cars spoke to the integration, on the
        # same stream name: that is this car. Take it over so the camera keeps
        # its entity id and history.
        for legacy in hass.config_entries.async_entries(DOMAIN):
            if CONF_CAR_ID not in legacy.data and legacy.data.get(CONF_STREAM) == data[CONF_STREAM]:
                _LOGGER.info("Car %s takes over the camera entry %s", data[CONF_NAME], legacy.title)
                hass.config_entries.async_update_entry(
                    legacy, unique_id=car_id, title=data[CONF_NAME], data=data
                )
                hass.config_entries.async_schedule_reload(legacy.entry_id)
                return legacy

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data=data
        )
        if result.get("type") != "create_entry":
            _LOGGER.warning("Could not add car %s: %s", data[CONF_NAME], result.get("reason"))
            return None
        return result.get("result")

    # Same car with new sensors, controls or a new name: rebuild its entities.
    if any(entry.data.get(k) != v for k, v in data.items()):
        hass.config_entries.async_update_entry(entry, data=data)
        hass.config_entries.async_schedule_reload(entry.entry_id)
    return entry


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/hello",
        vol.Required("car_id"): vol.All(str, vol.Length(min=4, max=64)),
        vol.Required("name"): str,
        vol.Optional("protocol", default=PROTOCOL): int,
        vol.Optional("model"): vol.Any(str, None),
        vol.Optional("sw_version"): vol.Any(str, None),
        vol.Optional("camera_stream"): vol.Any(str, None),
        vol.Optional("sensors", default=[]): [SENSOR_SCHEMA],
        vol.Optional("controls", default=[]): [CONTROL_SCHEMA],
    }
)
@websocket_api.async_response
async def ws_hello(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The car connects. Stays open: commands go back as events on it."""
    if msg["protocol"] > PROTOCOL:
        connection.send_error(msg["id"], "unsupported_protocol", f"this integration speaks {PROTOCOL}")
        return

    entry = await _ensure_entry(hass, msg)
    if entry is None:
        connection.send_error(msg["id"], "not_added", "the car could not be added")
        return

    car = cars(hass).get(msg["car_id"])
    token = object()

    @callback
    def send(event: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], event))

    @callback
    def closed() -> None:
        # The socket dropped, or the car unsubscribed. Controls go unavailable;
        # sensors keep their last values, as a parked car's should.
        car.detach(token)

    connection.subscriptions[msg["id"]] = closed
    car.attach(token, send)
    connection.send_result(msg["id"], {"entry_id": entry.entry_id, "protocol": PROTOCOL})

    from .repairs import async_check_old_device

    await async_check_old_device(hass, entry)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/state",
        vol.Required("car_id"): str,
        vol.Optional("sensors"): dict,
        vol.Optional("attributes"): dict,
        vol.Optional("controls"): dict,
        vol.Optional("location"): vol.Any(
            None,
            vol.Schema(
                {
                    vol.Required("latitude"): vol.Coerce(float),
                    vol.Required("longitude"): vol.Coerce(float),
                    vol.Optional("accuracy"): vol.Coerce(float),
                },
                extra=vol.REMOVE_EXTRA,
            ),
        ),
    }
)
@callback
def ws_state(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """What changed on the car since its last message."""
    cars(hass).get(msg["car_id"]).update(msg)
    connection.send_result(msg["id"])
