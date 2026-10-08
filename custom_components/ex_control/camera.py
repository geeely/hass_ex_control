"""The car's live camera as a Home Assistant camera entity."""

from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_STREAM, DOMAIN, LIVE_PATH
from .entity import car_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([CarCamera(hass, entry)])


class CarCamera(Camera):
    """Plays whatever the car is sending; idle when it is not."""

    _attr_has_entity_name = True
    _attr_name = "Live camera"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__()
        self._hub = hass.data[DOMAIN]["hub"]
        self._stream_name = entry.data[CONF_STREAM]
        self._attr_unique_id = f"{entry.entry_id}_camera"
        # On the car's own device when the car talks to the integration.
        self._attr_device_info = car_device_info(entry)

    async def async_added_to_hass(self) -> None:
        self._hub.listeners.append(self._changed)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.listeners.remove(self._changed)

    @callback
    def _changed(self) -> None:
        if not self.is_streaming and self.stream is not None:
            # Home Assistant's player would retry the ended stream, fail, and
            # mark the camera unavailable; it is rebuilt on the next view.
            stream, self.stream = self.stream, None
            self.hass.async_create_task(stream.stop())
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        # Idle between requests is normal, not a fault.
        return True

    @property
    def is_streaming(self) -> bool:
        s = self._hub.streams.get(self._stream_name)
        return bool(s and s.live)

    @property
    def extra_state_attributes(self) -> dict:
        return {"stream": self._stream_name, "car_sending": self.is_streaming}

    def _local_url(self) -> str:
        # Read back over loopback: go2rtc runs beside Home Assistant.
        api = self.hass.config.api
        scheme = "https" if api and api.use_ssl else "http"
        port = api.port if api else 8123
        path = LIVE_PATH.format(stream=self._stream_name)
        return f"{scheme}://127.0.0.1:{port}{path}?k={self._hub.secret}"

    async def stream_source(self) -> str | None:
        return self._local_url()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if not self.is_streaming:
            return None
        return await async_get_image(self.hass, self._local_url(), width=width, height=height)
