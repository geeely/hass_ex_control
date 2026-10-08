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

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_CAR_ID, CONF_HUB, CONF_NAME, CONF_STREAM, DEFAULT_STREAM, DOMAIN


class ExControlFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
