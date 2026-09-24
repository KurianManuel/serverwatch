"""Static system information collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus
import platform


class SystemInfoData:
    """Static system information."""

    def __init__(self) -> None:
        self.hostname: str = ""
        self.os_name: str = ""
        self.os_version: str = ""
        self.kernel_version: str = ""
        self.architecture: str = ""
        self.boot_time: float = 0.0
        self.cpu_model: str = ""
        self.cpu_cores_physical: int = 0
        self.cpu_cores_logical: int = 0
        self.total_memory: int = 0


class SystemCollector(Collector[SystemInfoData]):
    """Static system information collector (runs once at startup)."""

    name = "system"

    def __init__(self, interval_seconds: float = 3600.0) -> None:  # Run once per hour
        super().__init__(interval_seconds)

    async def _collect(self) -> SystemInfoData:
        data = SystemInfoData()
        data.hostname = platform.node()
        data.os_name = platform.system()
        data.os_version = platform.release()
        data.kernel_version = platform.version()
        data.architecture = platform.machine()
        # TODO: Fill remaining fields from /proc/cpuinfo, /proc/meminfo, etc.
        self._status = CollectorStatus.RUNNING
        return data