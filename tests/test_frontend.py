"""The dashboard card: served, and registered as a Lovelace resource."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .test_car import _platforms

DOMAIN = "ex_control"


async def test_card_served_and_registered(hass: HomeAssistant, hass_client) -> None:
    await _platforms(hass)
    assert await async_setup_component(hass, "lovelace", {})
    MockConfigEntry(domain=DOMAIN, unique_id="hub", data={"hub": True}).add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    resources = hass.data["lovelace"].resources
    await resources.async_load()
    urls = [r["url"] for r in resources.async_items()]
    assert any(u.startswith("/ex_control/ex-control-vehicle-card.js?v=") for u in urls), urls

    client = await hass_client()
    r = await client.get("/ex_control/ex-control-vehicle-card.js")
    assert r.status == 200
    assert "customElements.define" in await r.text()
    for name, kind in (("ex2.webp", "image/webp"), ("ex2-mask.png", "image/png")):
        r = await client.get(f"/ex_control/{name}")
        assert r.status == 200 and r.content_type == kind, (name, r.status, r.content_type)
