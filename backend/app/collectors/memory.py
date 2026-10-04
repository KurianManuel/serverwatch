"""Memory collector."""

import os

from app.collectors.base import Collector


class MemoryData:
    """Memory data structure."""

    def __init__(self) -> None:
        self.total: int = 0
        self.available: int = 0
        self.used: int = 0
        self.free: int = 0
        self.buffers: int = 0
        self.cached: int = 0
        self.swap_total: int = 0
        self.swap_used: int = 0
        self.swap_free: int = 0


class MemoryCollector(Collector[MemoryData]):
    """Memory metrics collector."""

    name = "memory"

    def __init__(self, interval_seconds: float = 5.0) -> None:
        super().__init__(interval_seconds)
        self._page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

    def _parse_meminfo(self) -> dict[str, int]:
        """Parse /proc/meminfo and return dict of values in bytes.
        Returns empty dict if /proc/meminfo is unavailable or malformed.
        """
        meminfo: dict[str, int] = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    # Convert kB to bytes
                    if value.endswith(" kB"):
                        try:
                            meminfo[key] = int(value[:-3]) * 1024
                        except ValueError:
                            # Skip malformed values
                            pass
                    else:
                        try:
                            meminfo[key] = int(value)
                        except ValueError:
                            # Skip malformed values
                            pass
        except FileNotFoundError:
            # /proc/meminfo not available (non-Linux)
            return {}
        except Exception:
            # Other errors (permission, etc.) - return partial data
            pass
        return meminfo

    async def _collect(self) -> MemoryData:
        data = MemoryData()
        meminfo = self._parse_meminfo()

        # Total memory
        data.total = meminfo.get("MemTotal", 0)

        # Available memory (preferred for practical availability)
        data.available = meminfo.get("MemAvailable", 0)

        # Free memory
        data.free = meminfo.get("MemFree", 0)

        # Buffers and cached
        data.buffers = meminfo.get("Buffers", 0)
        data.cached = meminfo.get("Cached", 0)

        # Calculate used memory
        if data.total > 0 and data.available > 0:
            data.used = data.total - data.available
        else:
            # Fallback calculation
            data.used = data.total - data.free - data.buffers - data.cached

        # Swap
        data.swap_total = meminfo.get("SwapTotal", 0)
        data.swap_free = meminfo.get("SwapFree", 0)
        if data.swap_total > 0:
            data.swap_used = data.swap_total - data.swap_free
        else:
            data.swap_used = 0

        return data
