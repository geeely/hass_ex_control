"""Solar charging wired up: options, the mode select, and commands to the car."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ex_control import solar_logic as sl

from .test_car import CONTROLS, DOMAIN, SENSORS, _connect, _hub, hello

CHARGE_SENSORS = SENSORS + [
    {"slug": "charge_port_connected", "name": "Charge port connected", "binary": True, "device_class": "plug"},
]
CHARGE_CONTROLS = CONTROLS + [
    {"slug": "charge_current", "name": "Charge current limit", "kind": "number", "min": 6, "max": 32, "step": 1, "unit": "A"},
    {"slug": "charging", "name": "Charging", "kind": "switch"},
]

OPTIONS = {
    "solar_grid_entity": "sensor.grid",
    "solar_production_entity": "sensor.solar",
    "solar_house_battery_soc_entity": "sensor.hb_soc",
    "solar_house_battery_power_entity": "sensor.hb_power",
    "solar_house_battery_power_sign": "charging",
    "solar_house_battery_kwh": 10,
    "solar_max_w": 5000,
    "solar_min_a": 6,
    "solar_max_a": 16,
    "solar_voltage": 230,
    "solar_departure": "12:00:00",
    "solar_car_min_soc": 30,
    "solar_car_target_soc": 100,
    "solar_grid_charge": False,
    "solar_tolerance_w": 150,
}


async def _event(ws) -> dict:
    return (await asyncio.wait_for(ws.receive_json(), 2))["event"]


def _house(hass, grid=0, solar=3000, hb_soc=100, hb_power=0) -> None:
    hass.states.async_set("sensor.grid", str(grid), {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.solar", str(solar / 1000), {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.hb_soc", str(hb_soc), {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.hb_power", str(hb_power), {"unit_of_measurement": "W"})


async def test_options_flow(hass: HomeAssistant, hass_ws_client) -> None:
    await _hub(hass)
    await _connect(hass, hass_ws_client, hello(sensors=CHARGE_SENSORS, controls=CHARGE_CONTROLS))
    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, "ex_0123456789abcdef")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] == "form" and r["step_id"] == "init"
    r = await hass.config_entries.options.async_configure(r["flow_id"], OPTIONS)
    assert r["type"] == "create_entry"
    assert entry.options["solar_grid_entity"] == "sensor.grid"

    hub = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, "hub")
    r = await hass.config_entries.options.async_init(hub.entry_id)
    assert r["type"] == "abort" and r["reason"] == "not_a_car"


async def test_steers_the_car(hass: HomeAssistant, hass_ws_client) -> None:
    await _hub(hass)
    ws, res = await _connect(hass, hass_ws_client, hello(sensors=CHARGE_SENSORS, controls=CHARGE_CONTROLS))
    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, "ex_0123456789abcdef")
    hass.config_entries.async_update_entry(entry, options=OPTIONS)
    await ws.send_json_auto_id({
        "type": "ex_control/state", "car_id": "ex_0123456789abcdef",
        "sensors": {"soc": 50, "charging": False, "charge_port_connected": True},
        "controls": {"charge_current": "6", "charging": "off"},
    })
    assert (await ws.receive_json())["success"]
    _house(hass, grid=-2000, solar=2300)  # house battery full, 2 kW going out
    await hass.async_block_till_done()

    assert hass.states.get("select.geely_solar_charging").state == "Off"
    assert hass.states.get("sensor.geely_solar_charging_status").state == "Off"

    clock = [0.0]
    with (
        patch("custom_components.ex_control.solar.SolarController.context", return_value=sl.Context(sl.AFTERNOON, 4)),
        patch("custom_components.ex_control.solar._clock", side_effect=lambda: clock[0]),
    ):
        # Observe: decides, sends nothing.
        await hass.services.async_call(
            "select", "select_option", {"entity_id": "select.geely_solar_charging", "option": "Observe"}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get("sensor.geely_solar_charging_status").state == "Solar: trying to start"
        assert hass.states.get("sensor.geely_solar_charging_target").state == "8"

        # On: the same decision now reaches the car.
        await hass.services.async_call(
            "select", "select_option", {"entity_id": "select.geely_solar_charging", "option": "On"}, blocking=True
        )
        events = [await _event(ws), await _event(ws)]
        assert events == [
            {"command": "set", "slug": "charge_current", "value": "8"},
            {"command": "set", "slug": "charging", "value": "on"},
        ]

        # Settled, still exporting: it raises the current, and nothing else.
        clock[0] = 100.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()
        assert await _event(ws) == {"command": "set", "slug": "charge_current", "value": "12"}

        # Off: stops steering, leaves the car as it is.
        await hass.services.async_call(
            "select", "select_option", {"entity_id": "select.geely_solar_charging", "option": "Off"}, blocking=True
        )
        assert hass.states.get("sensor.geely_solar_charging_status").state == "Off"
