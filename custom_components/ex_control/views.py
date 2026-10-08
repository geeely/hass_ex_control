"""HTTP endpoints: the car's upload in, the local stream out."""

from __future__ import annotations

import asyncio
import hmac
import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import TS_PACKET
from .hub import Hub, Stream

# Segments come about once a second; this long without one means it stopped.
SEGMENT_IDLE = 6.0

_LOGGER = logging.getLogger(__name__)


class IngestView(HomeAssistantView):
    """POST /api/ex_control/camera/{stream}: the car's live MPEG-TS.

    Signed in like any API call (the car's long-lived token), so it works
    wherever the car already reaches Home Assistant: Nabu Casa, a tunnel, or
    the home network. The body is read as it arrives, for as long as the car
    keeps sending.
    """

    url = "/api/ex_control/camera/{stream}"
    name = "api:ex_control:camera"
    requires_auth = True

    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    async def post(self, request: web.Request, stream: str) -> web.Response:
        session = request.headers.get("X-Ex-Session")
        if session:
            return await self._segment(request, stream, session)
        s = self.hub.get(stream)
        # A new upload replaces the old one (the car reconnected).
        if s.writer is not None and not s.writer.done():
            s.writer.cancel()
        s.writer = asyncio.current_task()
        s.live = True
        s.bytes_in = 0
        self.hub.changed()
        _LOGGER.info("%s: car started sending", stream)
        pending = b""
        try:
            async for chunk in request.content.iter_any():
                data = pending + chunk
                # Find the first sync byte once, then stay on packet boundaries.
                if s.bytes_in == 0 and data and data[0] != 0x47:
                    i = data.find(b"\x47")
                    data = data[i:] if i >= 0 else b""
                whole = len(data) - len(data) % TS_PACKET
                if whole:
                    s.feed(data[:whole])
                pending = data[whole:]
        except asyncio.CancelledError:
            _LOGGER.info("%s: replaced by a newer upload", stream)
            raise
        finally:
            if s.writer is asyncio.current_task():
                s.writer = None
                s.end()
                self.hub.changed()
            _LOGGER.info("%s: car stopped sending (%d KB)", stream, s.bytes_in // 1024)
        return web.Response(status=200)

    async def _segment(self, request: web.Request, stream: str, session: str) -> web.Response:
        """One short POST: about a second of video, starting at a key frame.

        The car sends this way to Home Assistant because proxies in front of
        it (nginx by default) hold a request body until it ends and cap its
        size, so an endless upload never arrives. The stream counts as live
        while segments keep coming.
        """
        body = await request.read()
        s = self.hub.get(stream)
        if s.writer is not None and not s.writer.done():
            # An endless upload is still open: let it go without ending the stream.
            old, s.writer = s.writer, None
            old.cancel()
        fresh = not s.live or s.session != session
        if fresh:
            if s.live:
                s.end()
            s.session = session
            s.live = True
            s.bytes_in = 0
            _LOGGER.info("%s: car started sending (segments)", stream)
        i = body.find(b"\x47")
        if i >= 0:
            body = body[i:]
            s.feed(body[: len(body) - len(body) % TS_PACKET])
        if s.idle is not None:
            s.idle.cancel()
        s.idle = asyncio.get_running_loop().call_later(SEGMENT_IDLE, self._idle, s)
        if fresh:
            self.hub.changed()
        return web.Response(status=200)

    def _idle(self, s: Stream) -> None:
        s.idle = None
        if s.live and s.session is not None:
            _LOGGER.info("%s: car stopped sending (%d KB)", s.name, s.bytes_in // 1024)
            s.session = None
            s.end()
            self.hub.changed()


class LiveView(HomeAssistantView):
    """GET /api/ex_control/live/{stream}.ts?k=<secret>: the stream, for go2rtc."""

    url = "/api/ex_control/live/{stream}.ts"
    name = "api:ex_control:live"
    requires_auth = False

    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    async def get(self, request: web.Request, stream: str) -> web.StreamResponse:
        if not hmac.compare_digest(request.query.get("k", ""), self.hub.secret):
            return web.Response(status=401)
        s = self.hub.streams.get(stream)
        if s is None or not s.live:
            # go2rtc retries; a 404 tells it there is nothing yet.
            return web.Response(status=404, text="not streaming")
        resp = web.StreamResponse()
        resp.content_type = "video/mp2t"
        await resp.prepare(request)
        q = s.add_reader()
        try:
            while True:
                data = await q.get()
                if data is None:
                    break
                await resp.write(data)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            s.remove_reader(q)
        return resp
