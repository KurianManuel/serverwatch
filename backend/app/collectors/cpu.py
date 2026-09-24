"""CPU collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus


class CPUData:
    """CPU data structure."""

    def __init__(self) -> None:
        self.total_utilization: float = 0.0
        self.per_core: list[float] = []
        self.user_time: float = 0.0
        self.system_time: float = 0.0
        self.idle_time: float = 0.0
        self.iowait_time: float = 0.0
        self.cpu_count: int = 0
        self.logical_count: int = 0
        self.load_average: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.cpu_model: str = ""


class CPUCollector(Collector[CPUData]):
    """CPU metrics collector."""

    name = "cpu"

    def __init__(self, interval_seconds: float = 5.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> CPUData:
        data = CPUData()
        # TODO: Implement /proc/stat reading
        self._status = CollectorStatus.RUNNING
        return data