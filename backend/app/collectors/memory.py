"""Memory collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus


class MemoryData:
    """Memory data structure."""

    def __init__(self) -> None:
        self.total: int = 0
        self.available: int = 0
        self.used: int = 0
        self.free: int = 0
        self.buffers: int = 0
        self.cached: int = 0
        self.swap_total: int = 0
        self.swap_used: int = 0
        self.swap_free: int = 0


class MemoryCollector(Collector[MemoryData]):
    """Memory metrics collector."""

    name = "memory"

    def __init__(self, interval_seconds: float = 5.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> MemoryData:
        data = MemoryData()
        # TODO: Implement /proc/meminfo reading
        self._status = CollectorStatus.RUNNING
        return data