"""Solar charging rules, against a simulated house.

The house: panels that can give `sun_w` but only produce what is used, a house
load, a house battery that soaks up surplus (and covers a shortfall before the
grid does), and the car drawing its current while charging.
"""

from dataclasses import dataclass

from custom_components.ex_control import solar_logic as sl

TICK = 15


@dataclass
class House:
    sun_w: float
    load_w: float = 300.0
    hb_soc: float = 100.0
    hb_max_w: float = 5000.0
    car_soc: float = 50.0
    plugged: bool = True

    def read(self, st: sl.State) -> sl.Reading:
        car_w = st.current_a * 230.0 if st.charging else 0.0
        want = self.load_w + car_w
        hb_room = self.hb_max_w if self.hb_soc < 100 else 0.0
        solar = min(self.sun_w, want + hb_room)
        hb_charge = max(0.0, solar - want)
        short = max(0.0, want - solar)
        hb_dis = min(short, self.hb_max_w) if self.hb_soc > 10 else 0.0
        grid = short - hb_dis
        return sl.Reading(grid, solar, self.hb_soc, hb_charge - hb_dis, self.car_soc, self.plugged)


def cfg(**kw) -> sl.Config:
    base = dict(min_a=6, max_a=16, solar_max_w=5000, hb_capacity_kwh=10, car_min_soc=30)
    return sl.Config(**{**base, **kw})


def run(house: House, ctx: sl.Context, c: sl.Config, minutes: float, st: sl.State | None = None, t: float = 0.0):
    """Runs from time t; pass the last log's time on to continue a run."""
    st = st or sl.State()
    end, log = t + minutes * 60, []
    while t < end:
        r = house.read(st)
        d = sl.decide(t, r, c, ctx, st)
        log.append((t, d, r))
        t += TICK
    return st, log


def test_full_battery_finds_held_back_solar() -> None:
    """House battery full, production held to the load: probing finds the rest."""
    house = House(sun_w=3000)
    st, log = run(house, sl.Context(sl.AFTERNOON, 4), cfg(), 30)
    assert st.charging
    # (3000 - 300) / 230 = 11.7 A; it settles at 11, just under.
    assert st.current_a == 11
    # Over-reaching by one amp is caught and taken back: never a sustained import.
    tail = [r.grid_w for _, _, r in log[-20:]]
    assert max(tail) <= 230


def test_afternoon_house_battery_first() -> None:
    """Half-full house battery, four hours of sun left: it needs ~1.7 kW."""
    weak = House(sun_w=3000, hb_soc=50)
    st, _ = run(weak, sl.Context(sl.AFTERNOON, 4), cfg(), 20)
    assert not st.charging  # 2.7 kW spare, the house battery needs 1.7: not enough for 6 A

    strong = House(sun_w=4500, hb_soc=50)
    st, log = run(strong, sl.Context(sl.AFTERNOON, 4), cfg(), 20)
    assert st.charging
    r = log[-1][2]
    assert r.hb_charge_w >= sl.hb_required_w(r, cfg(), sl.Context(sl.AFTERNOON, 4)) - 230
    assert r.grid_w <= 0


def test_morning_keeps_charging_on_a_middling_day() -> None:
    """Some sun but not enough for the minimum: morning holds 6 A anyway."""
    house = House(sun_w=1200, hb_soc=100)
    st, log = run(house, sl.Context(sl.MORNING, 8), cfg(), 10)
    assert st.charging and st.current_a == 6


def test_cloudy_morning_stops_above_minimum() -> None:
    house = House(sun_w=300, hb_soc=60, car_soc=70)
    st, log = run(house, sl.Context(sl.MORNING, 8), cfg(), 25)
    assert not st.charging
    assert any("cloudy" in d.reason for _, d, _ in log)
    # And it does not jump straight back on.
    st, log = run(house, sl.Context(sl.MORNING, 8), cfg(), 30, st, log[-1][0] + TICK)
    assert not st.charging


def test_cloudy_morning_keeps_charging_below_minimum() -> None:
    house = House(sun_w=300, hb_soc=60, car_soc=20)
    st, _ = run(house, sl.Context(sl.MORNING, 8), cfg(), 25)
    assert st.charging and st.current_a == 6


def test_night() -> None:
    low = House(sun_w=0, car_soc=20)
    st, _ = run(low, sl.Context(sl.NIGHT, 0), cfg(grid_charge=True), 5)
    assert st.charging and st.current_a == 6
    st, _ = run(low, sl.Context(sl.NIGHT, 0), cfg(grid_charge=False), 5)
    assert not st.charging
    ok = House(sun_w=0, car_soc=50)
    st, _ = run(ok, sl.Context(sl.NIGHT, 0), cfg(grid_charge=True), 5)
    assert not st.charging


def test_afternoon_stops_when_the_sun_goes() -> None:
    house = House(sun_w=3000)
    st, log = run(house, sl.Context(sl.AFTERNOON, 4), cfg(), 20)
    assert st.charging
    house.sun_w = 600
    st, log = run(house, sl.Context(sl.AFTERNOON, 4), cfg(), 15, st, log[-1][0] + TICK)
    assert not st.charging


def test_target_and_unplugged() -> None:
    st, log = run(House(sun_w=3000, car_soc=100), sl.Context(sl.AFTERNOON, 4), cfg(), 2)
    assert not st.charging and log[-1][1].reason == "Car reached its target"
    st, log = run(House(sun_w=3000, plugged=False), sl.Context(sl.MORNING, 8), cfg(), 2)
    assert not st.charging and log[-1][1].reason == "Not plugged in"


def test_never_above_max() -> None:
    st, log = run(House(sun_w=10000), sl.Context(sl.AFTERNOON, 4), cfg(max_a=10, solar_max_w=10000), 30)
    assert max(d.current_a for _, d, _ in log) == 10


def test_poor_forecast_stops_a_morning_at_once() -> None:
    """Forecast says the rest of today cannot fill the house battery: no 15-minute wait."""
    house = House(sun_w=1200, hb_soc=40, car_soc=70)
    ctx = sl.Context(sl.MORNING, 8)

    def with_forecast(remaining_wh):
        def read(st):
            r = House.read(house, st)
            r.forecast_remaining_wh = remaining_wh
            return r
        return read

    house.read = with_forecast(4000)  # needs 6 kWh * 1.2 for the house battery alone
    st, log = run(house, ctx, cfg(), 3)
    assert not st.charging
    assert any("poor forecast" in d.reason for _, d, _ in log)

    # A good forecast: the morning rule holds, charging at least the minimum.
    house.read = with_forecast(40000)
    st, _ = run(house, ctx, cfg(), 3)
    assert st.charging and st.current_a >= 6


def test_forecast_caps_the_probe() -> None:
    """Battery full, forecast says ~2 kW now: probing stops near it, not at 5 kW."""
    house = House(sun_w=3000)

    def read(st):
        r = House.read(house, st)
        r.forecast_now_w = 1500
        return r

    house.read = read
    st, log = run(house, sl.Context(sl.AFTERNOON, 4), cfg(), 30)
    # 1500 * 1.5 = 2250 W ceiling: 2250 - 300 load ≈ 8 A, below the 11 A the sun allows.
    assert st.charging and st.current_a <= 9
