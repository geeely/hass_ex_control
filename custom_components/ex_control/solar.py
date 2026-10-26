"""Solar charging for one car: reads the house, steers the car's charging.

The rules are in solar_logic.py. This part reads the house entities the owner
picked in the car's options, reads the car's own state, and sends the car's
charge current and charging controls when the decision changes. It runs only
while the car's "Solar charging" select is not Off; "Observe" decides and
reports without touching the car, so the rules can be watched for a day first.

While it is On it owns the charge current and the charging switch: a change
made by hand is put back at the next tick.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
import time as _time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from . import solar_logic as sl
from .car import CarState, cars
from .const import (
    CONF_CAR_ID,
    CONF_CONTROLS,
    DOMAIN,
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
    SIGN_DISCHARGING,
)

_LOGGER = logging.getLogger(__name__)

TICK = timedelta(seconds=15)
# A command the car did not act on is sent again, but not every tick.
RESEND_S = 60

MODE_OFF, MODE_OBSERVE, MODE_ON = "Off", "Observe", "On"
MODES = [MODE_OFF, MODE_OBSERVE, MODE_ON]

CURRENT, CHARGING = "charge_current", "charging"


def _clock() -> float:
    return _time.monotonic()


def controller(hass: HomeAssistant, entry_id: str) -> SolarController | None:
    return hass.data.get(DOMAIN, {}).get("solar", {}).get(entry_id)


def _watts(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id or (s := hass.states.get(entity_id)) is None:
        return None
    if s.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        return None
    try:
        v = float(s.state)
    except ValueError:
        return None
    unit = str(s.attributes.get("unit_of_measurement") or "").strip()
    return v * 1000.0 if unit.lower() == "kw" else v


def _wh(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id or (s := hass.states.get(entity_id)) is None:
        return None
    v = _number(s.state)
    if v is None:
        return None
    unit = str(s.attributes.get("unit_of_measurement") or "").strip().lower()
    return v * 1000.0 if unit == "kwh" else v


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("on", "true", "1")


class SolarController:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.car: CarState = cars(hass).get(entry.data[CONF_CAR_ID])
        self.mode = MODE_OFF
        self.status = "Off"
        self.detail: dict[str, Any] = {}
        self.target_a: int | None = None
        self._state = sl.State()
        self._synced = False
        self._sent: dict[str, tuple[str, float]] = {}
        self._unsub: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []

    # ---- lifecycle --------------------------------------------------------

    @callback
    def start(self) -> None:
        self._unsub = async_track_time_interval(self.hass, self._tick, TICK)

    @callback
    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    @callback
    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        # Start from what the car is doing now, not what an earlier run assumed.
        self._state = sl.State()
        self._synced = False
        self._sent.clear()
        self._tick(None)

    # ---- one pass ---------------------------------------------------------

    @property
    def configured(self) -> bool:
        o = self.entry.options
        return all(o.get(k) for k in (SOLAR_GRID, SOLAR_PRODUCTION, SOLAR_HB_SOC, SOLAR_HB_POWER))

    def _report(self, status: str, detail: dict[str, Any] | None = None) -> None:
        self.status = status
        self.detail = detail or {}
        for cb in list(self._listeners):
            cb()

    def _control(self, slug: str) -> dict[str, Any] | None:
        for d in self.entry.data.get(CONF_CONTROLS, []):
            if d.get("slug") == slug:
                return d
        return None

    def config(self) -> sl.Config:
        o = self.entry.options
        cur = self._control(CURRENT) or {}
        car_min = int(cur.get("min", 6))
        car_max = int(cur.get("max", 32))
        return sl.Config(
            min_a=max(car_min, int(o.get(SOLAR_MIN_A, 6))),
            max_a=min(car_max, int(o.get(SOLAR_MAX_A, 16))),
            voltage=float(o.get(SOLAR_VOLTAGE, 230)),
            hb_capacity_kwh=float(o.get(SOLAR_CAPACITY, 10)),
            solar_max_w=float(o.get(SOLAR_MAX_W, 5000)),
            car_min_soc=float(o.get(SOLAR_CAR_MIN_SOC, 30)),
            car_target_soc=float(o.get(SOLAR_CAR_TARGET_SOC, 100)),
            grid_charge=bool(o.get(SOLAR_GRID_CHARGE, False)),
            tolerance_w=float(o.get(SOLAR_TOLERANCE, 150)),
        )

    def context(self, now: datetime | None = None) -> sl.Context:
        now = now or dt_util.now()
        today = dt_util.as_local(now).date()
        sunrise = get_astral_event_date(self.hass, SUN_EVENT_SUNRISE, today)
        sunset = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, today)
        if sunrise is None or sunset is None or not (sunrise <= now < sunset):
            return sl.Context(sl.NIGHT, 0.0)
        dep_t = time.fromisoformat(str(self.entry.options.get(SOLAR_DEPARTURE, "12:00:00")))
        departure = datetime.combine(today, dep_t, tzinfo=dt_util.get_default_time_zone())
        phase = sl.MORNING if now < departure else sl.AFTERNOON
        return sl.Context(phase, (sunset - now).total_seconds() / 3600.0)

    def _reading(self) -> sl.Reading | None:
        o = self.entry.options
        grid = _watts(self.hass, o.get(SOLAR_GRID))
        solar = _watts(self.hass, o.get(SOLAR_PRODUCTION))
        hb_soc = _number(getattr(self.hass.states.get(o.get(SOLAR_HB_SOC) or ""), "state", None))
        hb_w = _watts(self.hass, o.get(SOLAR_HB_POWER))
        if None in (grid, solar, hb_soc, hb_w):
            return None
        if o.get(SOLAR_HB_POWER_SIGN) == SIGN_DISCHARGING:
            hb_w = -hb_w
        s = self.car.sensors
        return sl.Reading(
            grid_w=grid,
            solar_w=solar,
            hb_soc=hb_soc,
            hb_charge_w=hb_w,
            car_soc=_number(s.get("soc")),
            plugged=_truthy(s.get("charge_port_connected")),
            # Optional, and unavailable now and then: the rules then go without.
            forecast_remaining_wh=_wh(self.hass, o.get(SOLAR_FORECAST_REMAINING)),
            forecast_now_w=_watts(self.hass, o.get(SOLAR_FORECAST_NOW)),
        )

    @callback
    def _tick(self, _now: Any) -> None:
        if self.mode == MODE_OFF:
            self.target_a = None
            return self._report("Off")
        if not self.configured:
            return self._report("Not set up: pick the house sensors in the car's options")
        if self._control(CURRENT) is None or self._control(CHARGING) is None:
            return self._report("The car is not sharing its charging controls")
        if not self.car.connected:
            return self._report("Car offline")
        reading = self._reading()
        if reading is None:
            return self._report("House readings unavailable")

        if not self._synced:
            self._state.charging = _truthy(self.car.sensors.get(CHARGING))
            amps = _number(self.car.controls.get(CURRENT)) or _number(self.car.sensors.get("charge_current_limit"))
            self._state.current_a = int(amps or self.config().min_a)
            self._synced = True

        cfg, ctx = self.config(), self.context()
        d = sl.decide(_clock(), reading, cfg, ctx, self._state)
        self.target_a = d.current_a if d.charging else 0
        if d.changed:
            _LOGGER.info("%s: %s -> %s, %s A", self.entry.title, d.reason,
                         "charging" if d.charging else "stopped", d.current_a)
        detail = {"phase": ctx.phase, **d.detail}
        if self.mode == MODE_ON and reading.plugged:
            self._enforce(d)
        self._report(d.reason, detail)

    def _enforce(self, d: sl.Decision) -> None:
        if d.charging:
            self._send(CURRENT, f"{d.current_a:g}")
            self._send(CHARGING, "on")
        else:
            self._send(CHARGING, "off")

    def _send(self, slug: str, value: str) -> None:
        # What the car last reported (commands are optimistic until it reports).
        have = self.car.controls.get(slug)
        if have == value or (_number(value) is not None and _number(have) == _number(value)):
            return
        last = self._sent.get(slug)
        now = _clock()
        if last and last[0] == value and now - last[1] < RESEND_S:
            return
        self._sent[slug] = (value, now)
        self.car.command(slug, value)


@callback
def async_setup(hass: HomeAssistant, entry: ConfigEntry) -> SolarController:
    c = SolarController(hass, entry)
    hass.data.setdefault(DOMAIN, {}).setdefault("solar", {})[entry.entry_id] = c
    c.start()

    @callback
    def _unload() -> None:
        c.stop()
        hass.data.get(DOMAIN, {}).get("solar", {}).pop(entry.entry_id, None)

    entry.async_on_unload(_unload)
    return c
