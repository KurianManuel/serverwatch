"""Sequence number management for WebSocket updates."""

import asyncio
from typing import Optional


class SequenceManager:
    """Manages monotonically increasing sequence numbers."""

    def __init__(self) -> None:
        self._sequence = 0
        self._lock = asyncio.Lock()

    @property
    def current(self) -> int:
        return self._sequence

    async def next(self) -> int:
        """Get the next sequence number."""
        async with self._lock:
            self._sequence += 1
            return self._sequence

    async def set(self, sequence: int) -> None:
        """Set sequence number (for reconnection sync)."""
        async with self._lock:
            if sequence > self._sequence:
                self._sequence = sequence