"""Processes collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus


class ProcessData:
    """Process data structure."""

    def __init__(self) -> None:
        self.pid: int = 0
        self.name: str = ""
        self.exe: str = ""
        self.cmdline: list[str] = []
        self.cpu_percent: float = 0.0
        self.memory_percent: float = 0.0
        self.rss: int = 0
        self.vms: int = 0
        self.status: str = ""
        self.create_time: float = 0.0
        self.username: str = ""


class ProcessesCollector(Collector[list[ProcessData]]):
    """Processes metrics collector."""

    name = "processes"

    def __init__(self, interval_seconds: float = 10.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> list[ProcessData]:
        data: list[ProcessData] = []
        # TODO: Implement psutil process enumeration
        self._status = CollectorStatus.RUNNING
        return data