"""Temperature collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus


class TemperatureSensorData:
    """Temperature sensor data structure."""

    def __init__(self) -> None:
        self.name: str = ""
        self.label: str = ""
        self.current: float = 0.0
        self.high: float | None = None
        self.critical: float | None = None
        self.unit: str = "celsius"


class TemperatureCollector(Collector[list[TemperatureSensorData]]):
    """Temperature metrics collector."""

    name = "temperature"

    def __init__(self, interval_seconds: float = 10.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> list[TemperatureSensorData]:
        data: list[TemperatureSensorData] = []
        # TODO: Implement /sys/class/thermal and /sys/class/hwmon reading
        self._status = CollectorStatus.RUNNING
        return data