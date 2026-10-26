"""Constants for EX Control."""

DOMAIN = "ex_control"

CONF_STREAM = "stream"
DEFAULT_STREAM = "geely_camera"

# The car POSTs MPEG-TS here, signed in with its Home Assistant token.
INGEST_PATH = "/api/ex_control/camera/{stream}"
# Home Assistant's own go2rtc (and its HLS fallback) reads it back from here.
LIVE_PATH = "/api/ex_control/live/{stream}.ts"

TS_PACKET = 188

# A car talking to the integration directly (car.py, link.py).
CONF_CAR_ID = "car_id"
CONF_HUB = "hub"
CONF_NAME = "name"
CONF_MODEL = "model"
CONF_SW_VERSION = "sw_version"
CONF_SENSORS = "sensors"
CONF_CONTROLS = "controls"

# Bumped only for a change an older car or integration cannot understand.
PROTOCOL = 1

# The car's app_id in its mobile_app registration (HassDevice.APP_ID), for
# finding the older way this car reported.
CAR_APP_ID = "ex_control"

# Solar charging (solar.py), set in the car entry's options.
SOLAR_GRID = "solar_grid_entity"  # W or kW, + importing
SOLAR_PRODUCTION = "solar_production_entity"
SOLAR_HB_SOC = "solar_house_battery_soc_entity"
SOLAR_HB_POWER = "solar_house_battery_power_entity"
SOLAR_HB_POWER_SIGN = "solar_house_battery_power_sign"
SIGN_CHARGING = "charging"  # + means the house battery is charging
SIGN_DISCHARGING = "discharging"
SOLAR_CAPACITY = "solar_house_battery_kwh"
SOLAR_MAX_W = "solar_max_w"
SOLAR_MIN_A = "solar_min_a"
SOLAR_MAX_A = "solar_max_a"
SOLAR_VOLTAGE = "solar_voltage"
SOLAR_CAR_MIN_SOC = "solar_car_min_soc"
SOLAR_CAR_TARGET_SOC = "solar_car_target_soc"
SOLAR_GRID_CHARGE = "solar_grid_charge"
SOLAR_DEPARTURE = "solar_departure"
SOLAR_TOLERANCE = "solar_tolerance_w"
# Optional: a solar forecast (Open-Meteo Solar Forecast's "energy production
# today remaining" and "power production now", or any alike).
SOLAR_FORECAST_REMAINING = "solar_forecast_remaining_entity"  # Wh or kWh
SOLAR_FORECAST_NOW = "solar_forecast_now_entity"  # W or kW
