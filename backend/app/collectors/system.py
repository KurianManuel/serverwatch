"""Static system information collector."""

import os
import platform
import socket

from app.collectors.base import Collector


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
        self._initialized = False
        self._cached_data: SystemInfoData | None = None

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

    def _get_cpu_cores(self) -> tuple[int, int]:
        """Get physical and logical CPU core counts."""
        physical = 0
        logical = os.cpu_count() or 0

        try:
            with open("/proc/cpuinfo") as f:
                content = f.read()
                # Count physical IDs
                physical_ids: set[str] = set()
                for line in content.split("\n"):
                    if line.startswith("physical id"):
                        physical_ids.add(line.split(":", 1)[1].strip())
                physical = len(physical_ids) if physical_ids else 0

                # Count cores per physical ID for more accuracy
                if physical == 0:
                    # Fallback: count unique "core id" per "physical id"
                    core_ids: set[tuple[str, str]] = set()
                    current_phys: str | None = None
                    for line in content.split("\n"):
                        if line.startswith("physical id"):
                            current_phys = line.split(":", 1)[1].strip()
                        elif line.startswith("core id") and current_phys is not None:
                            core_ids.add((current_phys, line.split(":", 1)[1].strip()))
                    physical = len({p for p, _ in core_ids}) if core_ids else 0
        except Exception:
            pass

        return (physical, logical)

    def _get_total_memory(self) -> int:
        """Get total memory in bytes."""
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except Exception:
            pass
        return 0

    def _get_boot_time(self) -> float:
        """Get system boot time from /proc/stat."""
        try:
            with open("/proc/stat") as f:
                for line in f:
                    if line.startswith("btime "):
                        return float(line.split()[1])
        except Exception:
            pass
        return 0.0

    def _get_os_info(self) -> tuple[str, str]:
        """Get OS name and version."""
        os_name = platform.system()
        os_version = platform.release()

        # Try to get distro info
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip().strip('"')
                    elif line.startswith("VERSION_ID="):
                        os_version = line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass

        return (os_name, os_version)

    async def _collect(self) -> SystemInfoData:
        # Only collect once on first run, return cached data subsequently
        if self._initialized and self._cached_data is not None:
            return self._cached_data

        data = SystemInfoData()

        data.hostname = socket.gethostname()
        data.os_name, data.os_version = self._get_os_info()
        data.kernel_version = platform.release()
        data.architecture = platform.machine()
        data.boot_time = self._get_boot_time()
        data.cpu_model = self._get_cpu_model()
        data.cpu_cores_physical, data.cpu_cores_logical = self._get_cpu_cores()
        data.total_memory = self._get_total_memory()

        self._initialized = True
        self._cached_data = data
        return data
