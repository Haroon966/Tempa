"""Per-session Xvfb + PulseAudio capture slots for concurrent Meet jobs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureSlot:
    index: int
    display: str
    pulse_sink: str
    pulse_monitor: str


def slot_for_index(index: int) -> CaptureSlot:
    """Map slot index to DISPLAY / Pulse sink names (slot 0 → :99 / meet_sink_0)."""
    if index < 0:
        raise ValueError("slot index must be >= 0")
    return CaptureSlot(
        index=index,
        display=f":{99 + index}",
        pulse_sink=f"meet_sink_{index}",
        pulse_monitor=f"meet_sink_{index}.monitor",
    )


class CaptureSlotPool:
    """Async free-list of capture slots (one Xvfb + Pulse sink each)."""

    def __init__(self, size: int) -> None:
        n = max(1, int(size))
        self._size = n
        self._free: asyncio.Queue[CaptureSlot] = asyncio.Queue(maxsize=n)
        for i in range(n):
            self._free.put_nowait(slot_for_index(i))

    @property
    def size(self) -> int:
        return self._size

    @property
    def available(self) -> int:
        return self._free.qsize()

    def try_acquire(self) -> CaptureSlot | None:
        try:
            return self._free.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def acquire(self) -> CaptureSlot:
        return await self._free.get()

    def release(self, slot: CaptureSlot) -> None:
        self._free.put_nowait(slot)
