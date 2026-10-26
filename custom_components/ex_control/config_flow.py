"""Setup.

Cars add themselves: when one connects (link.py) it arrives here as an
integration discovery and becomes its own entry, so nobody types anything and
two cars are simply two entries. Being able to send that hello at all takes
the owner's admin token, which is the consent.

Adding it by hand makes the hub entry: no entities, it only keeps the
integration loaded so the first car's hello has somewhere to go. The older
camera-only setup stays reachable from the same step, for cars on an app
version that does not speak to the integration yet.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TimeSelector,
)

from .const import (
    CONF_CAR_ID,
    CONF_HUB,
    CONF_NAME,
    CONF_STREAM,
    DEFAULT_STREAM,
    DOMAIN,
    SIGN_CHARGING,
    SIGN_DISCHARGING,
    SOLAR_CAPACITY,
    SOLAR_CAR_MIN_SOC,
    SOLAR_CAR_TARGET_SOC,
    SOLAR_DEPARTURE,
    SOLAR_FORECAST_NOW,
    SOLAR_FORECAST_REMAINING,
    SOLAR_GRID,
    SOLAR_GRID_CHARGE,
    SOLAR_HB_POWER,
    SOLAR_HB_POWER_SIGN,
    SOLAR_HB_SOC,
    SOLAR_MAX_A,
    SOLAR_MAX_W,
    SOLAR_MIN_A,
    SOLAR_PRODUCTION,
    SOLAR_TOLERANCE,
    SOLAR_VOLTAGE,
)


class ExControlFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SolarOptionsFlow()

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info[CONF_CAR_ID])
        self._abort_if_unique_id_configured(updates=discovery_info)
        return self.async_create_entry(title=discovery_info[CONF_NAME], data=discovery_info)

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["hub", "camera"])

    async def async_step_hub(self, user_input: dict | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(CONF_HUB)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="EX Control", data={CONF_HUB: True})
        return self.async_show_form(step_id="hub", data_schema=vol.Schema({}))

    async def async_step_camera(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            stream = user_input[CONF_STREAM].strip()
            await self.async_set_unique_id(stream)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"EX Control ({stream})", data={CONF_STREAM: stream})
        return self.async_show_form(
            step_id="camera",
            data_schema=vol.Schema({vol.Required(CONF_STREAM, default=DEFAULT_STREAM): str}),
        )


def _num(lo: float, hi: float, step: float, unit: str) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX))


SENSOR = EntitySelector(EntitySelectorConfig(domain="sensor"))


class SolarOptionsFlow(OptionsFlow):
    """Solar charging, per car: the house sensors and the limits (solar.py)."""

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        if CONF_CAR_ID not in self.config_entry.data:
            return self.async_abort(reason="not_a_car")
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options

        def opt(key: str, default=None) -> dict:
            return {"default": o[key]} if key in o else ({"default": default} if default is not None else {})

        schema = vol.Schema({
            vol.Required(SOLAR_GRID, **opt(SOLAR_GRID)): SENSOR,
            vol.Required(SOLAR_PRODUCTION, **opt(SOLAR_PRODUCTION)): SENSOR,
            vol.Required(SOLAR_HB_SOC, **opt(SOLAR_HB_SOC)): SENSOR,
            vol.Required(SOLAR_HB_POWER, **opt(SOLAR_HB_POWER)): SENSOR,
            vol.Required(SOLAR_HB_POWER_SIGN, **opt(SOLAR_HB_POWER_SIGN, SIGN_CHARGING)): SelectSelector(
                SelectSelectorConfig(options=[SIGN_CHARGING, SIGN_DISCHARGING], translation_key="hb_sign")
            ),
            vol.Required(SOLAR_CAPACITY, **opt(SOLAR_CAPACITY, 10)): _num(1, 200, 0.1, "kWh"),
            vol.Required(SOLAR_MAX_W, **opt(SOLAR_MAX_W, 5000)): _num(500, 50000, 100, "W"),
            vol.Required(SOLAR_MIN_A, **opt(SOLAR_MIN_A, 6)): _num(5, 32, 1, "A"),
            vol.Required(SOLAR_MAX_A, **opt(SOLAR_MAX_A, 16)): _num(5, 32, 1, "A"),
            vol.Required(SOLAR_VOLTAGE, **opt(SOLAR_VOLTAGE, 230)): _num(100, 250, 1, "V"),
            vol.Required(SOLAR_DEPARTURE, **opt(SOLAR_DEPARTURE, "12:00:00")): TimeSelector(),
            vol.Required(SOLAR_CAR_MIN_SOC, **opt(SOLAR_CAR_MIN_SOC, 30)): _num(0, 100, 1, "%"),
            vol.Required(SOLAR_CAR_TARGET_SOC, **opt(SOLAR_CAR_TARGET_SOC, 100)): _num(10, 100, 1, "%"),
            vol.Required(SOLAR_GRID_CHARGE, **opt(SOLAR_GRID_CHARGE, False)): BooleanSelector(),
            vol.Required(SOLAR_TOLERANCE, **opt(SOLAR_TOLERANCE, 150)): _num(0, 2000, 10, "W"),
            # Optional, and clearable: suggested rather than defaulted.
            vol.Optional(SOLAR_FORECAST_REMAINING, description={"suggested_value": o.get(SOLAR_FORECAST_REMAINING)}): SENSOR,
            vol.Optional(SOLAR_FORECAST_NOW, description={"suggested_value": o.get(SOLAR_FORECAST_NOW)}): SENSOR,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
