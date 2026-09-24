"""Network collector."""

from app.collectors.base import Collector, CollectorResult, CollectorStatus


class NetworkInterfaceData:
    """Network interface data structure."""

    def __init__(self) -> None:
        self.name: str = ""
        self.state: str = ""  # up, down, unknown
        self.rx_bytes: int = 0
        self.tx_bytes: int = 0
        self.rx_packets: int = 0
        self.tx_packets: int = 0
        self.rx_errors: int = 0
        self.tx_errors: int = 0
        self.rx_dropped: int = 0
        self.tx_dropped: int = 0
        self.throughput_rx: float = 0.0
        self.throughput_tx: float = 0.0


class NetworkCollector(Collector[list[NetworkInterfaceData]]):
    """Network metrics collector."""

    name = "network"

    def __init__(self, interval_seconds: float = 5.0) -> None:
        super().__init__(interval_seconds)

    async def _collect(self) -> list[NetworkInterfaceData]:
        data: list[NetworkInterfaceData] = []
        # TODO: Implement /proc/net/dev reading
        self._status = CollectorStatus.RUNNING
        return data