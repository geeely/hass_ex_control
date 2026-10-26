"""Solar charging: what the car should be doing, from what the house reports.

Pure logic, no Home Assistant: solar.py feeds it readings and carries out
what it returns, so every rule here is testable on its own.

Two things make this harder than "charge at the surplus":

- The house's solar reading only shows what is being used. With the house
  battery full and nothing else on, production equals the car's draw, so the
  surplus cannot be read. It is found the way an inverter finds its peak: raise
  the car one amp, wait, and keep it if nothing else started paying for it.
- The house battery must reach 100% by sunset and must never feed the car. So
  whatever the house battery takes beyond what it needs to make sunset is
  spare, and anything the grid or the house battery supplies is a deficit.

The day has three parts:

- morning (sunrise to the departure time): the car is unplugged around midday
  and nobody says when, so it charges and does not stop - at least the minimum
  current, more as solar allows. Only a really cloudy morning stops it, and
  only while the car is above its minimum battery.
- afternoon (departure to sunset): solar surplus only; the house battery comes
  first.
- night: off, unless grid charging is allowed and the car is below its minimum
  battery.

A car below its minimum battery charges at least the minimum current at any
time of day when grid charging is allowed.

A solar forecast is optional. With one, a poor day is known in the morning
instead of after fifteen cloudy minutes (the rest of the day's sun cannot fill
the house battery and run the house), and probing stops near what the sun is
forecast to give now rather than at the panels' maximum.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math

# After any change the car ramps and the house sensors catch up; decide nothing
# until then.
SETTLE_S = 45
# How long a deficit at the minimum current is tolerated before stopping
# (outside the morning).
BELOW_MIN_STOP_S = 300
# After a stop (or a failed start), how long before trying to start again.
RESTART_COOLDOWN_S = 600
# The window a "really cloudy" morning is judged over.
CLOUDY_WINDOW_S = 900
# On a cloudy morning, the share of the car's draw being paid by the grid or the
# house battery that counts as "really cloudy".
CLOUDY_SHARE = 0.5
# The house battery counts as full from here.
HB_FULL_PCT = 99.0
# Headroom kept on the house battery's sunset target.
HB_MARGIN = 1.2
# Probing stops at the forecast for now times this: forecasts are rough, and
# under-reaching would leave sun unused.
FORECAST_HEADROOM = 1.5
# The most a single step raises the current, so a wrong reading costs little.
MAX_STEP_UP_A = 4
# After easing off, how long before probing for more again: the peak was just
# found, and probing straight back would rock the current up and down.
PROBE_PAUSE_S = 300
# Each probe taken straight back doubles the pause, up to this: at the peak on
# a steady day, probing settles to a short grid sip every half hour.
PROBE_PAUSE_MAX_S = 1800
# Samples this soon after a change are still the old state, and are not used.
SAMPLE_AFTER_S = 20

MORNING, AFTERNOON, NIGHT = "morning", "afternoon", "night"


@dataclass
class Config:
    min_a: int
    max_a: int
    voltage: float = 230.0
    hb_capacity_kwh: float = 10.0
    solar_max_w: float = 5000.0
    car_min_soc: float = 30.0
    car_target_soc: float = 100.0
    grid_charge: bool = False
    tolerance_w: float = 150.0


@dataclass
class Reading:
    """One sample. Powers in watts; the house battery's is + when charging."""

    grid_w: float  # + importing
    solar_w: float
    hb_soc: float
    hb_charge_w: float
    car_soc: float | None
    plugged: bool
    # From a solar forecast, when one is set up.
    forecast_remaining_wh: float | None = None
    forecast_now_w: float | None = None


@dataclass
class Context:
    phase: str
    hours_to_sunset: float  # 0 at night


@dataclass
class Decision:
    charging: bool
    current_a: int
    reason: str
    changed: bool = False
    detail: dict = field(default_factory=dict)


@dataclass
class State:
    """What the controller remembers between ticks."""

    charging: bool = False
    current_a: int = 0
    last_change: float = -1e9
    below_min_since: float | None = None
    cooldown_until: float = -1e9
    probe_after: float = -1e9
    probe_pause: float = PROBE_PAUSE_S
    last_probe: float = -1e9
    # Stopped for a cloudy morning: stays stopped until solar alone can start it.
    cloudy: bool = False
    # (time, watts the grid and house battery paid for the car) while charging in daylight.
    deficits: deque = field(default_factory=deque)
    # Readings since the last change, averaged so one noisy sample does not move the car.
    samples: deque = field(default_factory=deque)


def hb_required_w(r: Reading, cfg: Config, ctx: Context) -> float:
    """What the house battery must keep taking to be full by sunset."""
    if r.hb_soc >= HB_FULL_PCT or ctx.hours_to_sunset <= 0:
        return 0.0
    need_wh = (100.0 - r.hb_soc) / 100.0 * cfg.hb_capacity_kwh * 1000.0
    hours = max(0.25, ctx.hours_to_sunset - 0.5)
    return need_wh / hours * HB_MARGIN


def _avg(samples: deque) -> Reading:
    n = len(samples)
    last = samples[-1][1]
    return Reading(
        grid_w=sum(s.grid_w for _, s in samples) / n,
        solar_w=sum(s.solar_w for _, s in samples) / n,
        hb_soc=last.hb_soc,
        hb_charge_w=sum(s.hb_charge_w for _, s in samples) / n,
        car_soc=last.car_soc,
        plugged=last.plugged,
        forecast_remaining_wh=last.forecast_remaining_wh,
        forecast_now_w=last.forecast_now_w,
    )


def poor_day(r: Reading, cfg: Config, ctx: Context, car_w: float) -> bool | None:
    """The forecast's view: is the rest of today's sun short of the house's needs?

    The house's needs are filling its battery and running its load until
    sunset. None without a forecast.
    """
    if r.forecast_remaining_wh is None or ctx.hours_to_sunset <= 0:
        return None
    need_wh = max(0.0, 100.0 - r.hb_soc) / 100.0 * cfg.hb_capacity_kwh * 1000.0 * HB_MARGIN
    load_w = max(0.0, r.grid_w + r.solar_w - r.hb_charge_w - car_w)
    return r.forecast_remaining_wh < need_wh + load_w * ctx.hours_to_sunset


def decide(now: float, reading: Reading, cfg: Config, ctx: Context, st: State) -> Decision:
    """The next step. Updates st as if the decision is carried out."""
    min_a, max_a = cfg.min_a, max(cfg.min_a, cfg.max_a)
    step_w = cfg.voltage
    min_w = min_a * step_w

    def hold(reason: str, **detail) -> Decision:
        return Decision(st.charging, st.current_a, reason, False, detail)

    def set_to(charging: bool, amps: int, reason: str, **detail) -> Decision:
        amps = max(min_a, min(max_a, amps))
        changed = charging != st.charging or (charging and amps != st.current_a)
        if changed:
            st.last_change = now
            st.samples.clear()
            st.below_min_since = None
        if not charging and st.charging:
            st.cooldown_until = now + RESTART_COOLDOWN_S
        st.charging, st.current_a = charging, amps if charging else st.current_a
        return Decision(charging, amps, reason, changed, detail)

    if not reading.plugged:
        st.deficits.clear()
        st.charging = False
        return Decision(False, st.current_a, "Not plugged in")
    if reading.car_soc is not None and reading.car_soc >= cfg.car_target_soc:
        return set_to(False, st.current_a, "Car reached its target")

    low_car = reading.car_soc is not None and reading.car_soc < cfg.car_min_soc
    grid_floor = cfg.grid_charge and low_car

    if ctx.phase != MORNING:
        st.cloudy = False
    if ctx.phase == NIGHT:
        if grid_floor:
            return set_to(True, min_a, "Night: grid top-up to the minimum battery")
        return set_to(False, st.current_a, "Night: waiting for the sun")

    if now - st.last_change >= SAMPLE_AFTER_S:
        st.samples.append((now, reading))
    while st.samples and now - st.samples[0][0] > 60:
        st.samples.popleft()
    if now - st.last_change < SETTLE_S or not st.samples:
        return hold("Settling after a change")
    r = _avg(st.samples)

    deficit_w = max(0.0, r.grid_w) + max(0.0, -r.hb_charge_w)
    required_w = hb_required_w(r, cfg, ctx)
    hb_full = r.hb_soc >= HB_FULL_PCT
    spare_hb_w = 0.0 if hb_full else r.hb_charge_w - required_w
    export_w = max(0.0, -r.grid_w)
    # Known room: exported power, and what the house battery takes beyond its need.
    known_w = export_w + max(0.0, spare_hb_w)
    # With the house battery full and nothing imported, production may be
    # held back to the load; there may be more, up to the array's maximum.
    # A house battery still charging soaks up the surplus, so nothing is held
    # back then and what it takes beyond its need is already in known_w.
    curtailed = hb_full and deficit_w <= cfg.tolerance_w
    ceiling_w = cfg.solar_max_w
    if r.forecast_now_w is not None:
        ceiling_w = min(ceiling_w, r.forecast_now_w * FORECAST_HEADROOM)
    probe_room_w = max(0.0, ceiling_w - r.solar_w) if curtailed else 0.0
    poor = poor_day(r, cfg, ctx, st.current_a * step_w if st.charging else 0.0)
    detail = {
        "deficit_w": round(deficit_w),
        "house_battery_needs_w": round(required_w),
        "spare_w": round(known_w),
        "solar_room_w": round(probe_room_w),
    }
    if poor is not None:
        detail["forecast_poor_day"] = poor

    # A really cloudy morning: the grid or the house battery pays for a large
    # share of the car, sustained. Judged only while charging in daylight.
    if st.charging:
        st.deficits.append((now, deficit_w))
    while st.deficits and now - st.deficits[0][0] > CLOUDY_WINDOW_S:
        st.deficits.popleft()
    cloudy = bool(poor) or (
        st.charging
        and len(st.deficits) >= 2
        and now - st.deficits[0][0] >= CLOUDY_WINDOW_S * 0.9
        and sum(d for _, d in st.deficits) / len(st.deficits) > CLOUDY_SHARE * st.current_a * step_w
    )

    if low_car:
        st.cloudy = False
    # A cloudy (or poorly forecast) morning ends the morning's no-stop rule for
    # the rest of the morning; the car then only takes real surplus.
    if ctx.phase == MORNING and cloudy and not low_car and not st.cloudy:
        st.cloudy = True
        st.deficits.clear()
        if st.charging and not grid_floor:
            why = "Morning: poor forecast" if poor else "Morning: too cloudy"
            return set_to(False, st.current_a, why + ", car above its minimum", **detail)
    morning_floor = ctx.phase == MORNING and not st.cloudy
    floor = grid_floor or morning_floor

    if not st.charging:
        if now < st.cooldown_until and not floor:
            return hold("Waiting before trying again", **detail)
        if floor:
            start_a = max(min_a, math.floor(known_w / step_w))
            why = "Grid top-up to the minimum battery" if grid_floor else "Morning: charging before departure"
            st.deficits.clear()
            return set_to(True, min(start_a, min_a + MAX_STEP_UP_A), why, **detail)
        if known_w >= min_w or (curtailed and probe_room_w >= min_w):
            start_a = max(min_a, math.floor(known_w / step_w))
            st.deficits.clear()
            return set_to(True, min(start_a, min_a + MAX_STEP_UP_A), "Solar: trying to start", **detail)
        if st.cloudy:
            why = "Morning: poor forecast" if poor else "Morning: too cloudy"
            return hold(why + ", only spare solar", **detail)
        return hold("Solar: not enough to start", **detail)

    # Over: something other than spare solar is paying, or the house battery is
    # getting less than it needs for sunset.
    short_w = deficit_w + max(0.0, -spare_hb_w)
    if deficit_w > cfg.tolerance_w or spare_hb_w < -step_w / 2:
        if now - st.last_probe < SETTLE_S + 120:
            st.probe_pause = min(PROBE_PAUSE_MAX_S, st.probe_pause * 2)
        else:
            st.probe_pause = PROBE_PAUSE_S
        st.probe_after = now + st.probe_pause
        down_a = max(1, math.ceil(short_w / step_w))
        target = st.current_a - down_a
        if target >= min_a:
            return set_to(True, target, "Solar: easing off", **detail)
        if floor:
            if st.current_a != min_a:
                return set_to(True, min_a, "Holding the minimum current", **detail)
            return hold("Holding the minimum current", **detail)
        if st.below_min_since is None:
            st.below_min_since = now
        if now - st.below_min_since >= BELOW_MIN_STOP_S:
            return set_to(False, st.current_a, "Solar: not enough, stopped", **detail)
        if st.current_a != min_a:
            st.current_a = min_a
            st.last_change = now
            st.samples.clear()
            return Decision(True, min_a, "Solar: at the minimum, watching", True, detail)
        return hold("Solar: at the minimum, watching", **detail)

    st.below_min_since = None
    if st.current_a >= max_a:
        return hold("At the maximum current", **detail)
    if known_w >= step_w:
        up_a = min(MAX_STEP_UP_A, math.floor(known_w / step_w))
        return set_to(True, st.current_a + up_a, "Solar: using the surplus", **detail)
    if curtailed and probe_room_w >= step_w and now >= st.probe_after:
        st.last_probe = now
        return set_to(True, st.current_a + 1, "Solar: probing for more", **detail)
    return hold("Steady", **detail)
