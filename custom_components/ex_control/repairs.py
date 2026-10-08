"""Retiring the older way a car reported: its mobile_app device.

Before cars spoke to this integration they registered as a mobile_app device,
and one-tap setup hung template controls off it. Once a car connects here the
car stops feeding that device, so it sits there frozen, and while it exists
its entity ids hold the good names (this integration's get "_2").

Nothing is removed without asking: a repair issue offers it, and fixing it
removes the mobile_app entry and those template entries, then gives this
integration's entities the freed names. The hidden input_* helpers are left;
they are harmless, and deleting a user's helpers is theirs to decide.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir

from .const import CAR_APP_ID, CONF_CAR_ID, CONF_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _issue_id(car_id: str) -> str:
    return f"old_mobile_app_{car_id}"


def _old_entry(hass: HomeAssistant, car_id: str) -> ConfigEntry | None:
    """The car's mobile_app registration: same app id, same install id."""
    for e in hass.config_entries.async_entries("mobile_app"):
        if e.data.get("app_id") == CAR_APP_ID and e.data.get("device_id") == car_id:
            return e
    return None


async def async_check_old_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    car_id = entry.data[CONF_CAR_ID]
    old = _old_entry(hass, car_id)
    if old is None:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(car_id))
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(car_id),
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="old_mobile_app",
        translation_placeholders={"car": entry.data.get(CONF_NAME, entry.title), "old": old.title},
        data={"car_id": car_id, "entry_id": entry.entry_id},
    )


async def async_retire_old_device(hass: HomeAssistant, car_id: str, entry_id: str) -> None:
    old = _old_entry(hass, car_id)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    if old is not None:
        # Template controls made by one-tap setup sit on the old device.
        templates: set[str] = set()
        for device in dr.async_entries_for_config_entry(dev_reg, old.entry_id):
            for e in er.async_entries_for_device(ent_reg, device.id, include_disabled_entities=True):
                if e.platform == "template" and e.config_entry_id:
                    templates.add(e.config_entry_id)
        for tid in templates:
            await hass.config_entries.async_remove(tid)
        await hass.config_entries.async_remove(old.entry_id)

    # Now that the old names are free, take them: sensor.geely_battery_2 back
    # to sensor.geely_battery, so dashboards made for the old device still work
    # wherever the entity names match.
    for e in er.async_entries_for_config_entry(ent_reg, entry_id):
        base, sep, n = e.entity_id.rpartition("_")
        if not sep or not n.isdigit():
            continue
        if ent_reg.async_get(base) is None and hass.states.get(base) is None:
            ent_reg.async_update_entity(e.entity_id, new_entity_id=base)
    ir.async_delete_issue(hass, DOMAIN, _issue_id(car_id))


class RetireFlow(RepairsFlow):
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    async def async_step_init(self, user_input: dict | None = None) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict | None = None) -> data_entry_flow.FlowResult:
        if user_input is not None:
            await async_retire_old_device(self.hass, self._data["car_id"], self._data["entry_id"])
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, str] | None) -> RepairsFlow:
    return RetireFlow(data or {})
