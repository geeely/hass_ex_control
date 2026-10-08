"""Relays the car's live camera from its upload to whoever is watching.

The car pushes one long MPEG-TS upload into Home Assistant (so nothing has to
be opened on the user's router: the car already reaches Home Assistant). Home
Assistant's go2rtc pulls a plain HTTP MPEG-TS stream. This module joins the
two: one writer per stream, any number of readers.

A reader that joins mid-stream needs a PAT/PMT and a key frame before it can
decode anything. The car writes PAT and PMT right before every key frame, so
the hub keeps everything since the last PAT and gives it to a new reader first.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field

from .const import TS_PACKET

_LOGGER = logging.getLogger(__name__)

# A reader this far behind is dropped rather than slowing the car down.
READER_QUEUE = 256
# Cap on the late-joiner cache: about four seconds of the grid.
GOP_CACHE_MAX = 2 * 1024 * 1024


@dataclass
class Stream:
    """One camera stream: the car's upload and its readers."""

    name: str
    readers: set[asyncio.Queue[bytes | None]] = field(default_factory=set)
    gop: bytearray = field(default_factory=bytearray)
    writer: asyncio.Task | None = None
    live: bool = False
    bytes_in: int = 0
    # Segment mode: which run of segments is current, and its idle timer.
    session: str | None = None
    idle: asyncio.TimerHandle | None = None

    def add_reader(self) -> asyncio.Queue[bytes | None]:
        q: asyncio.Queue[bytes | None] = asyncio.Queue(READER_QUEUE)
        if self.gop:
            q.put_nowait(bytes(self.gop))
        self.readers.add(q)
        return q

    def remove_reader(self, q: asyncio.Queue[bytes | None]) -> None:
        self.readers.discard(q)

    def feed(self, packets: bytes) -> None:
        """Whole 188-byte packets from the car."""
        self.bytes_in += len(packets)
        # Restart the late-joiner cache at the last PAT (PID 0) in this batch.
        for off in range(len(packets) - TS_PACKET, -1, -TS_PACKET):
            p = packets[off : off + TS_PACKET]
            if p[0] == 0x47 and (p[1] & 0x40) and ((p[1] & 0x1F) << 8 | p[2]) == 0:
                self.gop = bytearray(packets[off:])
                break
        else:
            if len(self.gop) + len(packets) <= GOP_CACHE_MAX:
                self.gop += packets
            else:
                self.gop = bytearray()
        for q in list(self.readers):
            try:
                q.put_nowait(packets)
            except asyncio.QueueFull:
                _LOGGER.debug("%s: reader too slow, dropped", self.name)
                self.readers.discard(q)
                _close(q)

    def end(self) -> None:
        self.live = False
        self.gop = bytearray()
        for q in list(self.readers):
            _close(q)
        self.readers.clear()


def _close(q: asyncio.Queue[bytes | None]) -> None:
    """Ends a reader: what it has not sent yet is useless once it falls behind."""
    while not q.empty():
        q.get_nowait()
    q.put_nowait(None)


class Hub:
    """All streams, plus the secret that guards the local read URL."""

    def __init__(self) -> None:
        self.streams: dict[str, Stream] = {}
        # The read URL is fetched by Home Assistant's own go2rtc, which cannot
        # sign in, so it carries this instead. New every start.
        self.secret = secrets.token_urlsafe(24)
        self.listeners: list = []

    def get(self, name: str) -> Stream:
        s = self.streams.get(name)
        if s is None:
            s = self.streams[name] = Stream(name)
        return s

    def changed(self) -> None:
        for cb in list(self.listeners):
            cb()
