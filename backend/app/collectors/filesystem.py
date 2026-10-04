"""Filesystem collector."""

import os
from typing import Any

from app.collectors.base import Collector


class FilesystemData:
    """Filesystem data structure."""

    def __init__(self) -> None:
        self.mount_point: str = ""
        self.device: str = ""
        self.fstype: str = ""
        self.total: int = 0
        self.used: int = 0
        self.available: int = 0
        self.utilization_pct: float = 0.0
        self.inodes_total: int = 0
        self.inodes_used: int = 0
        self.inodes_free: int = 0


class FilesystemCollector(Collector[list[FilesystemData]]):
    """Filesystem metrics collector."""

    name = "filesystem"

    def __init__(self, interval_seconds: float = 30.0) -> None:
        super().__init__(interval_seconds)
        # Use psutil if available for cross-platform support, fallback to os.statvfs
        self._use_psutil = False
        self._psutil: Any = None
        try:
            import psutil  # type: ignore[import-untyped]
            self._psutil = psutil
            self._use_psutil = True
        except ImportError:
            pass

    def _get_mounts(self) -> list[tuple[str, str, str]]:
        """Get list of (mount_point, device, fstype) from /proc/mounts.
        Returns empty list if /proc/mounts is unavailable.
        """
        mounts: list[tuple[str, str, str]] = []
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        device = parts[0]
                        mount_point = parts[1]
                        fstype = parts[2]
                        # Skip virtual filesystems
                        if fstype in ("proc", "sysfs", "devpts", "tmpfs", "devtmpfs",
                                      "cgroup", "cgroup2", "pstore", "autofs", "mqueue",
                                      "hugetlbfs", "debugfs", "tracefs", "securityfs",
                                      "configfs", "rpc_pipefs", "nsfs", "bpf"):
                            continue
                        mounts.append((mount_point, device, fstype))
        except FileNotFoundError:
            # /proc/mounts not available (non-Linux)
            return []
        except Exception as e:
            raise RuntimeError(f"Failed to read /proc/mounts: {e}") from e
        return mounts

    def _get_statvfs(self, mount_point: str) -> Any | None:
        """Get statvfs for a mount point."""
        try:
            # os.statvfs may not exist on Windows
            return os.statvfs(mount_point)  # type: ignore[attr-defined]
        except (OSError, PermissionError, AttributeError):
            return None

    def _get_psutil_usage(self, mount_point: str) -> tuple[int, int, int, int, int, int] | None:
        """Get filesystem usage using psutil."""
        if not self._use_psutil:
            return None
        try:
            usage = self._psutil.disk_usage(mount_point)
            total = usage.total
            used = usage.used
            free = usage.free
            # psutil doesn't directly provide inode info on all platforms
            return (total, used, free, 0, 0, 0)
        except (OSError, PermissionError, AttributeError):
            return None

    async def _collect(self) -> list[FilesystemData]:
        result: list[FilesystemData] = []
        mounts = self._get_mounts()

        for mount_point, device, fstype in mounts:
            fs_data = FilesystemData()
            fs_data.mount_point = mount_point
            fs_data.device = device
            fs_data.fstype = fstype

            # Try psutil first (cross-platform, handles edge cases better)
            if self._use_psutil:
                usage = self._get_psutil_usage(mount_point)
                if usage:
                    total, used, free, inodes_total, inodes_used, inodes_free = usage
                    fs_data.total = total
                    fs_data.used = used
                    fs_data.available = free
                    if total > 0:
                        fs_data.utilization_pct = (used / total) * 100.0
                    fs_data.inodes_total = inodes_total
                    fs_data.inodes_used = inodes_used
                    fs_data.inodes_free = inodes_free
                    result.append(fs_data)
                    continue

            # Fallback to statvfs
            stat = self._get_statvfs(mount_point)
            if stat:
                fs_data.total = stat.f_blocks * stat.f_frsize
                fs_data.available = stat.f_bavail * stat.f_frsize
                fs_data.used = fs_data.total - (stat.f_bfree * stat.f_frsize)
                if fs_data.total > 0:
                    fs_data.utilization_pct = (fs_data.used / fs_data.total) * 100.0
                fs_data.inodes_total = stat.f_files
                fs_data.inodes_free = stat.f_favail
                fs_data.inodes_used = stat.f_files - stat.f_favail
                result.append(fs_data)

        return result
