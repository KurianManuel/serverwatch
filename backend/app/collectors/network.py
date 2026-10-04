"""Network collector."""

import time

from app.collectors.base import Collector


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
        self._prev_data: dict[str, tuple[int, int, int, int, int, int, int, int, float]] = {}
        # device -> (rx_bytes, tx_bytes, rx_packets, tx_packets, rx_errors, tx_errors, rx_dropped, tx_dropped, timestamp)

    def _read_net_dev(self) -> dict[str, tuple[int, int, int, int, int, int, int, int, str]]:
        """
        Read /proc/net/dev and return interface stats.

        Returns dict of interface -> (rx_bytes, tx_bytes, rx_packets, tx_packets,
                                     rx_errors, tx_errors, rx_dropped, tx_dropped, state)
        Returns empty dict if /proc/net/dev is unavailable.
        """
        stats: dict[str, tuple[int, int, int, int, int, int, int, int, str]] = {}
        try:
            with open("/proc/net/dev") as f:
                lines = f.readlines()
                # Skip header lines
                for line in lines[2:]:
                    if ":" not in line:
                        continue
                    name_part, data_part = line.split(":", 1)
                    interface = name_part.strip()
                    parts = data_part.split()
                    if len(parts) < 16:
                        continue

                    rx_bytes = int(parts[0])
                    rx_packets = int(parts[1])
                    rx_errors = int(parts[2])
                    rx_dropped = int(parts[3])
                    tx_bytes = int(parts[8])
                    tx_packets = int(parts[9])
                    tx_errors = int(parts[10])
                    tx_dropped = int(parts[11])

                    # Determine interface state from operstate if available
                    state = "unknown"
                    try:
                        with open(f"/sys/class/net/{interface}/operstate") as sf:
                            operstate = sf.read().strip()
                            state = operstate if operstate in ("up", "down") else "unknown"
                    except Exception:
                        # Fallback: interface with stats is probably up
                        state = "up" if (rx_bytes > 0 or tx_bytes > 0) else "down"

                    stats[interface] = (rx_bytes, tx_bytes, rx_packets, tx_packets,
                                        rx_errors, tx_errors, rx_dropped, tx_dropped, state)
        except FileNotFoundError:
            # /proc/net/dev not available (non-Linux)
            return {}
        except Exception as e:
            raise RuntimeError(f"Failed to read /proc/net/dev: {e}") from e
        return stats

    async def _collect(self) -> list[NetworkInterfaceData]:
        current_time = time.monotonic()
        current_stats = self._read_net_dev()

        result: list[NetworkInterfaceData] = []

        for interface, (rx_bytes, tx_bytes, rx_packets, tx_packets,
                        rx_errors, tx_errors, rx_dropped, tx_dropped, state) in current_stats.items():
            net_data = NetworkInterfaceData()
            net_data.name = interface
            net_data.state = state
            net_data.rx_bytes = rx_bytes
            net_data.tx_bytes = tx_bytes
            net_data.rx_packets = rx_packets
            net_data.tx_packets = tx_packets
            net_data.rx_errors = rx_errors
            net_data.tx_errors = tx_errors
            net_data.rx_dropped = rx_dropped
            net_data.tx_dropped = tx_dropped

            # Calculate rates if we have previous data
            if interface in self._prev_data:
                (prev_rx_bytes, prev_tx_bytes, prev_rx_packets, prev_tx_packets,
                 prev_rx_errors, prev_tx_errors, prev_rx_dropped, prev_tx_dropped,
                 prev_time) = self._prev_data[interface]
                elapsed = current_time - prev_time

                if elapsed > 0:
                    rx_delta = max(0, rx_bytes - prev_rx_bytes)
                    tx_delta = max(0, tx_bytes - prev_tx_bytes)

                    net_data.throughput_rx = rx_delta / elapsed
                    net_data.throughput_tx = tx_delta / elapsed

            # Store current data for next iteration
            self._prev_data[interface] = (rx_bytes, tx_bytes, rx_packets, tx_packets,
                                          rx_errors, tx_errors, rx_dropped, tx_dropped,
                                          current_time)
            result.append(net_data)

        # Clean up interfaces that no longer exist
        interfaces_to_remove = [iface for iface in self._prev_data if iface not in current_stats]
        for iface in interfaces_to_remove:
            del self._prev_data[iface]

        return result
