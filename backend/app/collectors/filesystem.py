"""Filesystem collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus


class FilesystemData:
    """Filesystem data structure."""

    def __init__(self) -> None:
        self.mount_point: str = ""
        self.device: str = ""
        self.fstype: str = ""
        self.total: int = 0
        self.used: int = 0
        self.available: int = 0
        self.utilization_pct: float = 0.0
        self.inodes_total: int = 0
        self.inodes_used: int = 0
        self.inodes_free: int = 0


class FilesystemCollector(Collector[list[FilesystemData]]):
    """Filesystem metrics collector."""

    name = "filesystem"

    def __init__(self, interval_seconds: float = 30.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> list[FilesystemData]:
        data: list[FilesystemData] = []
        # TODO: Implement psutil/statvfs reading
        self._status = CollectorStatus.RUNNING
        return data