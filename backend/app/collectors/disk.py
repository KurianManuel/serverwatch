"""Disk I/O collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus


class DiskData:
    """Disk I/O data structure per device."""

    def __init__(self) -> None:
        self.device: str = ""
        self.read_bytes: int = 0
        self.write_bytes: int = 0
        self.read_ops: int = 0
        self.write_ops: int = 0
        self.read_throughput: float = 0.0
        self.write_throughput: float = 0.0
        self.iops: float = 0.0


class DiskCollector(Collector[list[DiskData]]):
    """Disk I/O metrics collector."""

    name = "disk"

    def __init__(self, interval_seconds: float = 5.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> list[DiskData]:
        data: list[DiskData] = []
        # TODO: Implement /proc/diskstats and /sys/block reading
        self._status = CollectorStatus.RUNNING
        return data