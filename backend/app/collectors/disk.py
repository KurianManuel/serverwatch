"""Disk I/O collector."""

import time

from app.collectors.base import Collector


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
        self._prev_data: dict[str, tuple[int, int, int, int, float]] = {}  # device -> (read_bytes, write_bytes, read_ops, write_ops, timestamp)
        self._interval = interval_seconds

    def _read_diskstats(self) -> dict[str, tuple[int, int, int, int]]:
        """
        Read /proc/diskstats and return device stats.

        Returns dict of device -> (read_bytes, write_bytes, read_ops, write_ops)
        Returns empty dict if /proc/diskstats is unavailable.
        """
        stats: dict[str, tuple[int, int, int, int]] = {}
        try:
            with open("/proc/diskstats") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 14:
                        continue
                    # /proc/diskstats format:
                    # major minor name reads reads_merged sectors_read ms_reading writes writes_merged sectors_written ms_writing ios_in_progress ms_doing_io weighted_ms_doing_io
                    device = parts[2]
                    reads = int(parts[3])
                    sectors_read = int(parts[5])
                    writes = int(parts[7])
                    sectors_written = int(parts[9])

                    # Convert sectors to bytes (sector = 512 bytes)
                    read_bytes = sectors_read * 512
                    write_bytes = sectors_written * 512

                    # Skip loop devices and ram devices, but keep physical and virtual block devices
                    if device.startswith("loop") or device.startswith("ram"):
                        continue

                    stats[device] = (read_bytes, write_bytes, reads, writes)
        except FileNotFoundError:
            # /proc/diskstats not available (non-Linux)
            return {}
        except Exception as e:
            raise RuntimeError(f"Failed to read /proc/diskstats: {e}") from e
        return stats

    async def _collect(self) -> list[DiskData]:
        current_time = time.monotonic()
        current_stats = self._read_diskstats()

        result: list[DiskData] = []

        for device, (read_bytes, write_bytes, read_ops, write_ops) in current_stats.items():
            disk_data = DiskData()
            disk_data.device = device
            disk_data.read_bytes = read_bytes
            disk_data.write_bytes = write_bytes
            disk_data.read_ops = read_ops
            disk_data.write_ops = write_ops

            # Calculate rates if we have previous data
            if device in self._prev_data:
                prev_read_bytes, prev_write_bytes, prev_read_ops, prev_write_ops, prev_time = self._prev_data[device]
                elapsed = current_time - prev_time

                if elapsed > 0:
                    # Handle counter resets (values should never decrease, but handle just in case)
                    read_delta = max(0, read_bytes - prev_read_bytes)
                    write_delta = max(0, write_bytes - prev_write_bytes)
                    read_ops_delta = max(0, read_ops - prev_read_ops)
                    write_ops_delta = max(0, write_ops - prev_write_ops)

                    disk_data.read_throughput = read_delta / elapsed
                    disk_data.write_throughput = write_delta / elapsed
                    disk_data.iops = (read_ops_delta + write_ops_delta) / elapsed

            # Store current data for next iteration
            self._prev_data[device] = (read_bytes, write_bytes, read_ops, write_ops, current_time)
            result.append(disk_data)

        # Clean up devices that no longer exist
        devices_to_remove = [dev for dev in self._prev_data if dev not in current_stats]
        for dev in devices_to_remove:
            del self._prev_data[dev]

        return result
