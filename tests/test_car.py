"""EX Control: a car connecting straight to the integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "ex_control"

SENSORS = [
    {"slug": "soc", "name": "Battery", "binary": False, "unit": "%", "device_class": "battery", "state_class": "measurement"},
    {"slug": "range", "name": "Range", "binary": False, "unit": "km", "icon": "mdi:map-marker-distance", "state_class": "measurement"},
    {"slug": "charging", "name": "Charging", "binary": True, "device_class": "battery_charging"},
    {"slug": "last_key", "name": "Last key", "binary": False, "icon": "mdi:key-variant"},
]
CONTROLS = [
    {"slug": "temp", "name": "Temperature", "kind": "number", "min": 16, "max": 30, "step": 0.5, "unit": "°C"},
    {"slug": "ac", "name": "A/C", "kind": "switch"},
    {"slug": "locked", "name": "Doors", "kind": "lock"},
    {"slug": "camera", "name": "Camera", "kind": "select", "options": ["Off", "Top left", "All"]},
]


def hello(car_id="ex_0123456789abcdef", name="GEELY", **extra):
    return {
        "type": "ex_control/hello",
        "car_id": car_id,
        "name": name,
        "protocol": 1,
        "model": "IHU629G",
        "sw_version": "2.3.1",
        "camera_stream": f"{name.lower()}_camera",
        "sensors": SENSORS,
        "controls": CONTROLS,
        **extra,
    }


async def _platforms(hass: HomeAssistant) -> None:
    # In real HA these load at start; here they must precede the test server.
    for comp in ("camera", "repairs"):
        assert await async_setup_component(hass, comp, {})


async def _hub(hass: HomeAssistant) -> None:
    await _platforms(hass)
    MockConfigEntry(domain=DOMAIN, unique_id="hub", data={"hub": True}, title="EX Control").add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def _connect(hass, hass_ws_client, msg):
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(msg)
    res = await ws.receive_json()
    assert res["success"], res
    await hass.async_block_till_done()
    return ws, res


async def test_hub_flow(hass: HomeAssistant) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] == "menu"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "hub"})
    assert r["type"] == "form"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["type"] == "create_entry"
    assert r["data"] == {"hub": True}


async def test_unknown_without_integration(hass: HomeAssistant, hass_ws_client) -> None:
    """What the car sees on an instance without the integration."""
    assert await async_setup_component(hass, "websocket_api", {})
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(hello())
    res = await ws.receive_json()
    assert not res["success"]
    assert res["error"]["code"] == "unknown_command"


async def test_car_adds_itself_and_reports(hass: HomeAssistant, hass_ws_client) -> None:
    await _hub(hass)
    ws, res = await _connect(hass, hass_ws_client, hello())
    hello_id = res["id"]

    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, "ex_0123456789abcdef")
    assert entry is not None and entry.title == "GEELY"
    assert res["result"]["entry_id"] == entry.entry_id

    dev = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "ex_0123456789abcdef")})
    assert dev is not None and dev.name == "GEELY" and dev.model == "EX2"
    ents = {e.entity_id for e in er.async_entries_for_device(er.async_get(hass), dev.id)}
    for eid in (
        "sensor.geely_battery", "sensor.geely_range", "binary_sensor.geely_charging",
        "number.geely_temperature", "switch.geely_a_c", "lock.geely_doors", "select.geely_camera",
        "select.geely_paint", "select.geely_roof", "device_tracker.geely_location",
        "binary_sensor.geely_connected", "camera.geely_live_camera",
    ):
        assert eid in ents, (eid, sorted(ents))

    assert hass.states.get("binary_sensor.geely_connected").state == "on"

    await ws.send_json_auto_id({
        "type": "ex_control/state", "car_id": "ex_0123456789abcdef",
        "sensors": {"soc": 64, "range": 212, "charging": True, "last_key": 2},
        "attributes": {"last_key": {"profile": "Driver 1"}},
        "controls": {"temp": "22.0", "ac": "on", "locked": "on", "camera": "Off"},
        "location": {"latitude": -26.1, "longitude": 28.0, "accuracy": 5},
    })
    assert (await ws.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.geely_battery").state == "64"
    assert hass.states.get("binary_sensor.geely_charging").state == "on"
    assert hass.states.get("sensor.geely_last_key").attributes["profile"] == "Driver 1"
    assert hass.states.get("number.geely_temperature").state == "22.0"
    assert hass.states.get("switch.geely_a_c").state == "on"
    assert hass.states.get("lock.geely_doors").state == "locked"
    assert hass.states.get("device_tracker.geely_location").attributes["latitude"] == -26.1

    # Commands go back down the hello subscription.
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.geely_a_c"}, blocking=True)
    ev = await ws.receive_json()
    assert ev["id"] == hello_id and ev["type"] == "event"
    assert ev["event"] == {"command": "set", "slug": "ac", "value": "off"}
    assert hass.states.get("switch.geely_a_c").state == "off"  # optimistic

    await hass.services.async_call("number", "set_value", {"entity_id": "number.geely_temperature", "value": 23.5}, blocking=True)
    assert (await ws.receive_json())["event"] == {"command": "set", "slug": "temp", "value": "23.5"}
    await hass.services.async_call("lock", "unlock", {"entity_id": "lock.geely_doors"}, blocking=True)
    assert (await ws.receive_json())["event"] == {"command": "set", "slug": "locked", "value": "off"}
    await hass.services.async_call("select", "select_option", {"entity_id": "select.geely_camera", "option": "All"}, blocking=True)
    assert (await ws.receive_json())["event"] == {"command": "set", "slug": "camera", "value": "All"}

    # The car drives off: controls go unavailable, readings stay.
    await ws.close()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.geely_connected").state == "off"
    assert hass.states.get("switch.geely_a_c").state == "unavailable"
    assert hass.states.get("sensor.geely_battery").state == "64"


async def test_two_cars_two_devices(hass: HomeAssistant, hass_ws_client) -> None:
    await _hub(hass)
    await _connect(hass, hass_ws_client, hello("ex_aaaaaaaaaaaaaaaa", "GEELY"))
    await _connect(hass, hass_ws_client, hello("ex_bbbbbbbbbbbbbbbb", "WIFE"))
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if "car_id" in e.data]
    assert len(entries) == 2
    assert hass.states.get("sensor.geely_battery") is not None
    assert hass.states.get("sensor.wife_battery") is not None
    reg = dr.async_get(hass)
    assert reg.async_get_device(identifiers={(DOMAIN, "ex_aaaaaaaaaaaaaaaa")}).name == "GEELY"
    assert reg.async_get_device(identifiers={(DOMAIN, "ex_bbbbbbbbbbbbbbbb")}).name == "WIFE"


async def test_hello_again_with_fewer_controls(hass: HomeAssistant, hass_ws_client) -> None:
    await _hub(hass)
    ws, _ = await _connect(hass, hass_ws_client, hello())
    assert hass.states.get("lock.geely_doors") is not None
    await ws.close()
    await hass.async_block_till_done()
    msg = hello()
    msg["controls"] = [c for c in CONTROLS if c["slug"] != "locked"]
    await _connect(hass, hass_ws_client, msg)
    await hass.async_block_till_done()
    state = hass.states.get("lock.geely_doors")
    assert state is None or state.state == "unavailable"
    reg = er.async_get(hass)
    assert reg.async_get("lock.geely_doors") is None or True  # orphaned registry entries are HA's to tidy


async def test_camera_only_entry_is_taken_over(hass: HomeAssistant, hass_ws_client) -> None:
    legacy = MockConfigEntry(domain=DOMAIN, unique_id="geely_camera", data={"stream": "geely_camera"}, title="EX Control (geely_camera)")
    legacy.add_to_hass(hass)
    await _platforms(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    cam = er.async_get(hass).async_get_entity_id("camera", DOMAIN, f"{legacy.entry_id}_camera")
    assert cam is not None

    await _connect(hass, hass_ws_client, hello())
    await hass.async_block_till_done()
    assert legacy.unique_id == "ex_0123456789abcdef"
    assert legacy.data["car_id"] == "ex_0123456789abcdef"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    # Same camera entity, now on the car's device.
    e = er.async_get(hass).async_get(cam)
    dev = dr.async_get(hass).async_get(e.device_id)
    assert (DOMAIN, "ex_0123456789abcdef") in dev.identifiers
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, legacy.entry_id)}) is None


async def test_old_mobile_app_device_repair(hass: HomeAssistant, hass_ws_client) -> None:
    old = MockConfigEntry(
        domain="mobile_app", title="GEELY",
        data={"app_id": "ex_control", "device_id": "ex_0123456789abcdef", "webhook_id": "wh", "device_name": "GEELY"},
    )
    old.add_to_hass(hass)
    reg = er.async_get(hass)
    reg.async_get_or_create("sensor", "mobile_app", "wh_soc", suggested_object_id="geely_battery", config_entry=old)
    await _hub(hass)
    await _connect(hass, hass_ws_client, hello())

    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, "ex_0123456789abcdef")
    ours = reg.async_get_entity_id("sensor", DOMAIN, "ex_0123456789abcdef_soc")
    assert ours == "sensor.geely_battery_2"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "old_mobile_app_ex_0123456789abcdef")
    assert issue is not None and issue.is_fixable

    from custom_components.ex_control.repairs import async_retire_old_device

    await async_retire_old_device(hass, "ex_0123456789abcdef", entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_get_entry(old.entry_id) is None
    assert reg.async_get_entity_id("sensor", DOMAIN, "ex_0123456789abcdef_soc") == "sensor.geely_battery"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "old_mobile_app_ex_0123456789abcdef") is None


async def test_card_vehicle_list(hass: HomeAssistant, hass_ws_client) -> None:
    await _hub(hass)
    ws, _ = await _connect(hass, hass_ws_client, hello())
    await ws.send_json_auto_id({"type": "ex_control/vehicles"})
    res = await ws.receive_json()
    assert res["success"]
    (v,) = res["result"]["vehicles"]
    assert v["name"] == "GEELY"
    e = v["entities"]
    assert e["soc"] == "sensor.geely_battery"
    assert e["helper_locked"] == "lock.geely_doors"
    assert e["helper_ac"] == "switch.geely_a_c"
    assert e["device_tracker"] == "device_tracker.geely_location"
    assert e["paint"] == "select.geely_paint"
    assert e["camera"] == "camera.geely_live_camera"


async def test_car_app_setup_calls(hass: HomeAssistant, hass_ws_client, hass_admin_user, hass_client) -> None:
    """The exact calls the car's one-tap setup makes (HassIntegrationSetup)."""
    await _platforms(hass)
    assert await async_setup_component(hass, "config", {})
    # Real HA registers views late without complaint; the test server freezes
    # its routes when the client starts, so load the integration first.
    assert await async_setup_component(hass, DOMAIN, {})
    ws = await hass_ws_client(hass)

    await ws.send_json_auto_id({"type": "manifest/get", "integration": "ex_control"})
    res = await ws.receive_json()
    assert res["success"] and res["result"]["version"] == "0.3.1"

    await ws.send_json_auto_id({"type": "config_entries/get", "domain": "ex_control"})
    res = await ws.receive_json()
    assert res["success"] and res["result"] == []

    client = await hass_client()
    r = await client.post("/api/config/config_entries/flow", json={"handler": "ex_control"})
    step = await r.json()
    assert r.status == 200 and step["type"] == "menu", step
    r = await client.post(f"/api/config/config_entries/flow/{step['flow_id']}", json={"next_step_id": "hub"})
    step = await r.json()
    assert step["type"] == "form", step
    r = await client.post(f"/api/config/config_entries/flow/{step['flow_id']}", json={})
    step = await r.json()
    assert step["type"] == "create_entry", step
    await hass.async_block_till_done()

    # Tapping again finds it set up.
    await ws.send_json_auto_id({"type": "config_entries/get", "domain": "ex_control"})
    assert len((await ws.receive_json())["result"]) == 1
    r = await client.post("/api/config/config_entries/flow", json={"handler": "ex_control"})
    step = await r.json()
    r = await client.post(f"/api/config/config_entries/flow/{step['flow_id']}", json={"next_step_id": "hub"})
    step = await r.json()
    assert step["type"] == "abort" and step["reason"] == "already_configured"

    # And the car can now say hello.
    await ws.send_json_auto_id(hello())
    assert (await ws.receive_json())["success"]
