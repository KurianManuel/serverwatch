"""CPU collector."""

import os
import platform

from app.collectors.base import Collector


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
        self._prev_total: float | None = None
        self._prev_idle: float | None = None
        self._prev_per_core: list[tuple[float, float]] | None = None
        self._cpu_model: str = ""
        self._initialize_static_info()

    def _initialize_static_info(self) -> None:
        """Initialize static CPU information that doesn't change."""
        try:
            self._cpu_model = self._get_cpu_model()
        except Exception:
            self._cpu_model = ""

    def _get_cpu_model(self) -> str:
        """Get CPU model from /proc/cpuinfo."""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return platform.processor() or ""

    def _read_cpu_stat(self) -> tuple[float, float, list[tuple[float, float]], int]:
        """
        Read /proc/stat and return (total_time, idle_time, per_core_data, cpu_count).

        per_core_data is list of (total, idle) for each CPU core.
        Returns zeros if /proc/stat is unavailable.
        """
        total = 0.0
        idle = 0.0
        per_core: list[tuple[float, float]] = []
        cpu_count = 0

        try:
            with open("/proc/stat") as f:
                for line in f:
                    if line.startswith("cpu "):
                        # Aggregate line: cpu  user nice system idle iowait irq softirq steal guest guest_nice
                        parts = line.split()
                        if len(parts) >= 5:
                            user = float(parts[1])
                            nice = float(parts[2])
                            system = float(parts[3])
                            idle_time = float(parts[4])
                            iowait = float(parts[5]) if len(parts) > 5 else 0.0
                            irq = float(parts[6]) if len(parts) > 6 else 0.0
                            softirq = float(parts[7]) if len(parts) > 7 else 0.0
                            steal = float(parts[8]) if len(parts) > 8 else 0.0
                            guest = float(parts[9]) if len(parts) > 9 else 0.0
                            guest_nice = float(parts[10]) if len(parts) > 10 else 0.0

                            total = user + nice + system + idle_time + iowait + irq + softirq + steal + guest + guest_nice
                            idle = idle_time + iowait
                    elif line.startswith("cpu") and line[3].isdigit():
                        # Per-core lines: cpu0, cpu1, etc.
                        parts = line.split()
                        if len(parts) >= 5:
                            user = float(parts[1])
                            nice = float(parts[2])
                            system = float(parts[3])
                            idle_time = float(parts[4])
                            iowait = float(parts[5]) if len(parts) > 5 else 0.0
                            irq = float(parts[6]) if len(parts) > 6 else 0.0
                            softirq = float(parts[7]) if len(parts) > 7 else 0.0
                            steal = float(parts[8]) if len(parts) > 8 else 0.0
                            guest = float(parts[9]) if len(parts) > 9 else 0.0
                            guest_nice = float(parts[10]) if len(parts) > 10 else 0.0

                            core_total = user + nice + system + idle_time + iowait + irq + softirq + steal + guest + guest_nice
                            core_idle = idle_time + iowait
                            per_core.append((core_total, core_idle))
                            cpu_count += 1
        except FileNotFoundError:
            # /proc/stat not available (non-Linux)
            return 0.0, 0.0, [], 0
        except Exception as e:
            raise RuntimeError(f"Failed to read /proc/stat: {e}") from e

        return total, idle, per_core, cpu_count

    def _read_load_average(self) -> tuple[float, float, float]:
        """Read load average from /proc/loadavg."""
        try:
            with open("/proc/loadavg") as f:
                line = f.read().strip()
                parts = line.split()
                if len(parts) >= 3:
                    return float(parts[0]), float(parts[1]), float(parts[2])
        except Exception:
            pass
        return (0.0, 0.0, 0.0)

    def _read_cpu_count(self) -> tuple[int, int]:
        """Get CPU counts from os module."""
        try:
            logical = os.cpu_count() or 0
        except Exception:
            logical = 0
        return (0, logical)  # Physical count requires parsing /proc/cpuinfo

    async def _collect(self) -> CPUData:
        data = CPUData()

        # Read load average
        data.load_average = self._read_load_average()

        # Read CPU counts
        physical, logical = self._read_cpu_count()
        data.cpu_count = logical
        data.logical_count = logical

        # Read /proc/stat for utilization calculation
        total, idle, per_core, cpu_count = self._read_cpu_stat()

        if cpu_count > 0:
            data.cpu_count = cpu_count
            if data.logical_count == 0:
                data.logical_count = cpu_count

        # Calculate total CPU utilization
        if self._prev_total is not None and self._prev_idle is not None:
            total_delta = total - self._prev_total
            idle_delta = idle - self._prev_idle

            if total_delta > 0:
                utilization = (total_delta - idle_delta) / total_delta * 100.0
                data.total_utilization = max(0.0, min(100.0, utilization))

        # Store current values for next delta calculation
        self._prev_total = total
        self._prev_idle = idle

        # Calculate per-core utilization
        if self._prev_per_core is not None and len(self._prev_per_core) == len(per_core):
            per_core_util: list[float] = []
            for i, (curr_total, curr_idle) in enumerate(per_core):
                prev_total, prev_idle = self._prev_per_core[i]
                core_total_delta = curr_total - prev_total
                core_idle_delta = curr_idle - prev_idle
                if core_total_delta > 0:
                    core_util = (core_total_delta - core_idle_delta) / core_total_delta * 100.0
                    per_core_util.append(max(0.0, min(100.0, core_util)))
                else:
                    per_core_util.append(0.0)
            data.per_core = per_core_util
        else:
            # First run or core count changed
            data.per_core = [0.0] * len(per_core)

        self._prev_per_core = per_core

        # Set static info
        data.cpu_model = self._cpu_model

        # Also store raw counters for debugging
        data.user_time = 0.0  # Not easily separated from /proc/stat aggregate
        data.system_time = 0.0
        data.idle_time = idle
        data.iowait_time = 0.0

        return data
