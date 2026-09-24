"""Systemd services collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus
from datetime import datetime


class ServiceData:
    """Service data structure."""

    def __init__(self) -> None:
        self.name: str = ""
        self.description: str = ""
        self.active_state: str = ""  # active, inactive, activating, deactivating, failed
        self.sub_state: str = ""
        self.load_state: str = ""  # loaded, not-found, error, etc.
        self.unit_file_state: str = ""  # enabled, disabled, static, etc.
        self.main_pid: int = 0
        self.active_enter_timestamp: datetime | None = None
        self.inactive_enter_timestamp: datetime | None = None


class ServicesCollector(Collector[list[ServiceData]]):
    """Systemd services collector."""

    name = "services"

    def __init__(self, interval_seconds: float = 10.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> list[ServiceData]:
        data: list[ServiceData] = []
        # TODO: Implement systemd D-Bus API reading
        self._status = CollectorStatus.RUNNING
        return data