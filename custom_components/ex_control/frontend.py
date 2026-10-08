"""The dashboard card: serves its JS, registers it with Lovelace, and tells it
which entities belong to which car.

The car reports in one of three ways (see HassService on the car):

- Straight to this integration (the normal path from app 2.3.1 on): one
  config entry per car, entity unique ids "<car id>_<slug>" for readings and
  "<car id>_control_<slug>" for controls.

- As a mobile_app device (the normal path). Entity ids are slugified from
  "<device name> <sensor name>" (sensor.ex_battery, not sensor.ex_soc), so they
  are found here by unique id instead: mobile_app stores "<webhook id>_<slug>".
- As loose states from POST /api/states (the fallback). Those have no registry
  entry, but their ids are predictable: sensor.<prefix>_<slug>.

Either way the card gets one map of slug -> entity id per car and never has to
guess at names.

Resource registration follows the BMW CarData integration's frontend_cards.py
(BSD 2-clause, Copyright (c) 2025 Kris Van Biesen, Renaud Allard, Jonas
Huberts; licence in frontend/LICENSE-bmw-cardata.txt), including its guard against overwriting an unloaded resource store.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from .const import CONF_CAR_ID, CONF_STREAM, DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILE = "ex-control-vehicle-card.js"
CARD_ASSETS = ("ex2.webp", "ex2-mask.png")
_STATIC_URL = f"/{DOMAIN}/{CARD_FILE}"
_CARD_PATH = Path(__file__).parent / "frontend" / CARD_FILE
_MANIFEST_PATH = Path(__file__).parent / "manifest.json"

_SETUP_KEY = "_frontend_setup"
_RESOURCE_KEY = "_frontend_resource_id"

# What the car's app_id is in its mobile_app registration (HassDevice.APP_ID).
CAR_APP_ID = "ex_control"

# Sensor slugs the car publishes (HassSensors.ALL), with their domain, for the
# loose-state fallback where there is no registry to read them from.
SENSOR_SLUGS = (
    "speed", "soc", "range", "odometer", "outside_temp", "hvac_temp", "fan",
    "power", "charge_power", "aux_12v", "consumption", "trip_consumed",
    "trip_regen", "gear", "battery_energy", "battery_capacity", "charge_rate",
    "charge_current_limit", "last_key", "last_key_profile",
)
BINARY_SLUGS = ("charging", "dc_fast", "ac", "charge_port_connected", "fob_watch")

# Helpers the car listens to (HassCommands.ALL), keyed "helper_<slug>".
HELPERS = (
    ("input_number", "temp"), ("input_number", "fan"),
    ("input_number", "charge_current"), ("input_number", "seat_driver"),
    ("input_number", "seat_passenger"), ("input_boolean", "ac"),
    ("input_boolean", "charging"), ("input_boolean", "recirc"),
    ("input_boolean", "wheel_heat"), ("input_boolean", "front_defrost"),
    ("input_boolean", "locked"), ("input_boolean", "windows_open"),
    ("input_select", "camera"),
)


def _manifest_version() -> str:
    """Blocking; run in the executor."""
    try:
        return str(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")).get("version", "0"))
    except Exception:  # noqa: BLE001
        return "0"


async def _resource_url(hass: HomeAssistant) -> str:
    # The static path is served with long cache headers; the version query is
    # what makes browsers fetch a new card after an upgrade.
    version = await hass.async_add_executor_job(_manifest_version)
    return f"{_STATIC_URL}?v={version}"


async def _register_resource(hass: HomeAssistant) -> str | None:
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None:
        return None
    try:
        # An unloaded store returns no items, and creating one then would
        # overwrite every resource the user has. Load it first.
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        url = await _resource_url(hass)
        for item in resources.async_items():
            existing = item.get("url")
            if not isinstance(existing, str) or not existing.startswith(_STATIC_URL):
                continue
            if existing != url:
                await resources.async_update_item(item["id"], {"url": url})
            return item["id"]
        item = await resources.async_create_item({"res_type": "module", "url": url})
        return item["id"]
    except AttributeError:
        # YAML-mode resources cannot be written; the README says what to add.
        _LOGGER.debug("Lovelace resources are in YAML mode; add %s by hand", _STATIC_URL)
        return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register the EX Control card: %s", err)
        return None


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Every entry setup; the static path and command only once per start."""
    data = hass.data.setdefault(DOMAIN, {})
    if not data.get(_SETUP_KEY):
        data[_SETUP_KEY] = True
        websocket_api.async_register_command(hass, ws_vehicles)

        from homeassistant.components.http import StaticPathConfig

        if await hass.async_add_executor_job(_CARD_PATH.exists):
            # The card, and the photo it repaints (see paintedCar in the card).
            await hass.http.async_register_static_paths(
                [StaticPathConfig(_STATIC_URL, str(_CARD_PATH), True)]
                + [
                    StaticPathConfig(f"/{DOMAIN}/{name}", str(_CARD_PATH.parent / name), True)
                    for name in CARD_ASSETS
                ]
            )
        else:
            _LOGGER.warning("Card file missing at %s", _CARD_PATH)

    async def _register(_event: Any = None) -> None:
        if rid := await _register_resource(hass):
            data[_RESOURCE_KEY] = rid

    # Wait for a full start so the resource store is not raced while loading.
    # Registering is idempotent, so an entry added later simply re-checks it.
    if hass.state is CoreState.running:
        await _register()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)


async def async_remove_frontend(hass: HomeAssistant, removed_entry_id: str) -> None:
    """Drop the Lovelace resource when the last entry is deleted (not on reload)."""
    others = [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != removed_entry_id]
    if others:
        return
    rid = hass.data.get(DOMAIN, {}).pop(_RESOURCE_KEY, None)
    resources = getattr(hass.data.get("lovelace"), "resources", None)
    if rid and resources is not None:
        try:
            await resources.async_delete_item(rid)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not remove the card resource: %s", err)


# ---- which entities are which car's ----------------------------------------


def _helpers(hass: HomeAssistant, prefix: str) -> dict[str, str]:
    out = {}
    for domain, slug in HELPERS:
        eid = f"{domain}.{prefix}_{slug}"
        if hass.states.get(eid):
            out[f"helper_{slug}"] = eid
    return out


def _cameras(hass: HomeAssistant) -> dict[str, str]:
    """Stream name -> this integration's camera entity."""
    ent_reg = er.async_get(hass)
    out = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_CAR_ID):
            continue  # already on its car (build_vehicles)
        eid = ent_reg.async_get_entity_id("camera", DOMAIN, f"{entry.entry_id}_camera")
        if eid:
            out[entry.data.get(CONF_STREAM, "")] = eid
    return out


def build_vehicles(hass: HomeAssistant) -> list[dict[str, Any]]:
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    cameras = _cameras(hass)
    vehicles: list[dict[str, Any]] = []

    # Cars on this integration: everything keyed by unique id, nothing guessed.
    direct: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        car_id = entry.data.get(CONF_CAR_ID)
        if not car_id:
            continue
        direct.add(car_id)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, car_id)})
        entities: dict[str, str] = {}
        for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            uid = e.unique_id or ""
            if uid == f"{entry.entry_id}_camera":
                entities["camera"] = e.entity_id
                continue
            if not uid.startswith(f"{car_id}_"):
                continue
            key = uid[len(car_id) + 1 :]
            if key.startswith("control_"):
                entities[f"helper_{key[len('control_'):]}"] = e.entity_id
            elif key == "location":
                entities["device_tracker"] = e.entity_id
            else:
                entities[key] = e.entity_id
        name = (device and (device.name_by_user or device.name)) or entry.title
        vehicles.append(
            {
                "id": car_id,
                "device_id": device.id if device else None,
                "prefix": slugify(name),
                "name": name,
                "model": "EX2",
                "entities": entities,
            }
        )

    for entry in hass.config_entries.async_entries("mobile_app"):
        # A car that also talks to the integration shows once, from there.
        if entry.data.get("app_id") != CAR_APP_ID or entry.data.get("device_id") in direct:
            continue
        webhook = entry.data.get("webhook_id", "")
        for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            entities: dict[str, str] = {}
            for e in er.async_entries_for_device(ent_reg, device.id):
                if e.platform != "mobile_app":
                    continue
                if e.domain == "device_tracker":
                    entities["device_tracker"] = e.entity_id
                    continue
                uid = e.unique_id or ""
                slug = uid[len(webhook) + 1 :] if webhook and uid.startswith(f"{webhook}_") else uid
                entities[slug] = e.entity_id
            # The car names its device after the prefix in capitals ("EX").
            prefix = slugify(device.name or entry.data.get("device_name", "")) or "ex"
            entities.update(_helpers(hass, prefix))
            vehicles.append(
                {
                    "id": device.id,
                    "device_id": device.id,
                    "prefix": prefix,
                    "name": device.name_by_user or device.name or entry.title,
                    "model": device.model,
                    "entities": entities,
                }
            )

    # Loose states: any sensor.<prefix>_soc that no device above already owns.
    taken = {v["prefix"] for v in vehicles}
    for state in hass.states.async_all("sensor"):
        oid = state.object_id
        if not oid.endswith("_soc"):
            continue
        prefix = oid[: -len("_soc")]
        if prefix in taken or not hass.states.get(f"sensor.{prefix}_odometer"):
            continue
        taken.add(prefix)
        entities = {}
        for slug in SENSOR_SLUGS:
            if hass.states.get(eid := f"sensor.{prefix}_{slug}"):
                entities[slug] = eid
        for slug in BINARY_SLUGS:
            if hass.states.get(eid := f"binary_sensor.{prefix}_{slug}"):
                entities[slug] = eid
        if hass.states.get(eid := f"device_tracker.{prefix}_location"):
            entities["device_tracker"] = eid
        entities.update(_helpers(hass, prefix))
        vehicles.append(
            {
                "id": f"prefix:{prefix}",
                "device_id": None,
                "prefix": prefix,
                "name": prefix.upper(),
                "model": None,
                "entities": entities,
            }
        )

    for v in vehicles:
        if "camera" in v["entities"]:
            continue
        # The car's default stream is "<prefix>_camera" (HassConfig.cameraStream);
        # with a single camera entry, it is that car's whatever it is called.
        cam = cameras.get(f"{v['prefix']}_camera")
        if cam is None and len(cameras) == 1 and len(vehicles) == 1:
            cam = next(iter(cameras.values()))
        if cam:
            v["entities"]["camera"] = cam

    vehicles.sort(key=lambda v: str(v["name"]))
    return vehicles


@websocket_api.websocket_command({"type": f"{DOMAIN}/vehicles"})
@websocket_api.async_response
async def ws_vehicles(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(msg["id"], {"vehicles": build_vehicles(hass)})
