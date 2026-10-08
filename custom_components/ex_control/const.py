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
