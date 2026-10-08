"""One car talking to this integration directly.

The car opens Home Assistant's WebSocket with its usual token and sends
``ex_control/hello``: who it is and what it has (sensors and controls, each
described by the car itself, so a new sensor on the car needs no new release
of this integration). From then on it sends ``ex_control/state`` whenever
something changes, and this side sends commands back down the hello
subscription. Nothing reaches into the car; it holds the connection.

A car is keyed on its install id (HassDevice.deviceUid on the car), so any
number of cars can share one Home Assistant, each its own config entry and
device.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


@dataclass
class CarState:
    """Everything known about one car, whether or not it is online now."""

    car_id: str
    sensors: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    controls: dict[str, str] = field(default_factory=dict)
    location: dict[str, float] | None = None
    # The live link: one callable that sends an event down the hello
    # subscription. A reconnect replaces it; the old link's close then finds
    # it is no longer current and leaves it alone.
    _link: tuple[object, Callable[[dict[str, Any]], None]] | None = None
    _listeners: list[Callable[[], None]] = field(default_factory=list)

    @property
    def connected(self) -> bool:
        return self._link is not None

    @callback
    def attach(self, token: object, send: Callable[[dict[str, Any]], None]) -> None:
        self._link = (token, send)
        self.notify()

    @callback
    def detach(self, token: object) -> None:
        if self._link is not None and self._link[0] is token:
            self._link = None
            self.notify()

    @callback
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        @callback
        def remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return remove

    @callback
    def notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    @callback
    def update(self, msg: dict[str, Any]) -> None:
        """A state message: partial, only what changed since the last one."""
        self.sensors.update(msg.get("sensors") or {})
        for slug, attrs in (msg.get("attributes") or {}).items():
            if isinstance(attrs, dict):
                self.attributes[slug] = attrs
        self.controls.update({k: str(v) for k, v in (msg.get("controls") or {}).items()})
        if loc := msg.get("location"):
            self.location = loc
        self.notify()

    @callback
    def command(self, slug: str, value: str) -> bool:
        """Sends one control change to the car. False when it is offline."""
        if self._link is None:
            return False
        self._link[1]({"command": "set", "slug": slug, "value": value})
        # Optimistic until the car's next state message says what happened.
        self.controls[slug] = value
        self.notify()
        return True


class Cars:
    """Every car this Home Assistant has heard from since it started."""

    def __init__(self) -> None:
        self._cars: dict[str, CarState] = {}

    def get(self, car_id: str) -> CarState:
        car = self._cars.get(car_id)
        if car is None:
            car = self._cars[car_id] = CarState(car_id)
        return car


def cars(hass: HomeAssistant) -> Cars:
    from .const import DOMAIN

    data = hass.data.setdefault(DOMAIN, {})
    if "cars" not in data:
        data["cars"] = Cars()
    return data["cars"]
