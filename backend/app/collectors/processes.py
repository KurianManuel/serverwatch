"""Processes collector."""

import os
import time
from typing import Any

from app.collectors.base import Collector


class ProcessData:
    """Process data structure."""

    def __init__(self) -> None:
        self.pid: int = 0
        self.name: str = ""
        self.exe: str = ""
        self.cmdline: list[str] = []
        self.cpu_percent: float = 0.0
        self.memory_percent: float = 0.0
        self.rss: int = 0
        self.vms: int = 0
        self.status: str = ""
        self.create_time: float = 0.0
        self.username: str = ""


class ProcessesCollector(Collector[list[ProcessData]]):
    """Processes metrics collector."""

    name = "processes"

    def __init__(self, interval_seconds: float = 10.0) -> None:
        super().__init__(interval_seconds)
        self._prev_cpu_times: dict[int, tuple[float, float, float]] = {}  # pid -> (user, system, timestamp)
        self._page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        self._clk_tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self._total_memory = self._get_total_memory()
        self._use_psutil = False
        self._psutil: Any = None
        try:
            import psutil  # type: ignore[import-untyped]
            self._psutil = psutil
            self._use_psutil = True
        except ImportError:
            pass

    def _get_total_memory(self) -> int:
        """Get total system memory in bytes."""
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except Exception:
            pass
        return 0

    def _get_pids(self) -> list[int]:
        """Get list of PIDs from /proc."""
        pids: list[int] = []
        try:
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    pids.append(int(entry))
        except Exception:
            pass
        return pids

    def _read_stat(self, pid: int) -> tuple[float, float, int, int, str, float, float] | None:
        """
        Read /proc/[pid]/stat and return (utime, stime, rss_pages, vms_pages, status, create_time, starttime).

        Returns None if process disappeared or access denied.
        """
        stat_path = f"/proc/{pid}/stat"
        try:
            with open(stat_path) as f:
                content = f.read()
        except (FileNotFoundError, PermissionError, OSError):
            return None

        # Parse stat - the command name is in parentheses and may contain spaces
        # Find the last ')' to split properly
        last_paren = content.rfind(")")
        if last_paren == -1:
            return None

        post = content[last_paren + 1:].strip().split()

        # pre contains: pid (comm) state ...
        # post contains: ppid pgrp session tty_nr tpgid flags minflt cminflt majflt cmajflt
        #              utime stime cutime cstime priority nice num_threads itrealvalue starttime
        if len(post) < 14:
            return None

        try:
            state = post[0] if post[0] else "?"
            utime = float(post[11]) / self._clk_tck
            stime = float(post[12]) / self._clk_tck
            rss_pages = int(post[21])  # resident set size in pages
            vms_pages = int(post[20])  # virtual memory size in pages
            starttime = float(post[19]) / self._clk_tck

            # Calculate process start time
            boot_time = self._get_boot_time()
            create_time = boot_time + starttime if boot_time > 0 else 0.0

            return (utime, stime, rss_pages, vms_pages, state, create_time, starttime)
        except (IndexError, ValueError):
            return None

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

    def _read_cmdline(self, pid: int) -> list[str]:
        """Read command line from /proc/[pid]/cmdline."""
        try:
            with open(f"/proc/{pid}/cmdline") as f:
                content = f.read()
                if content:
                    return [arg for arg in content.split("\x00") if arg]
        except (FileNotFoundError, PermissionError, OSError):
            pass
        return []

    def _read_exe(self, pid: int) -> str:
        """Read executable path from /proc/[pid]/exe."""
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except (FileNotFoundError, PermissionError, OSError):
            return ""

    def _read_username(self, pid: int) -> str:
        """Get username for process from /proc/[pid]/status."""
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("Uid:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            uid = int(parts[1])
                            return self._uid_to_username(uid)
        except Exception:
            pass
        return ""

    def _uid_to_username(self, uid: int) -> str:
        """Convert UID to username."""
        try:
            import pwd
            return pwd.getpwuid(uid).pw_name  # type: ignore[no-any-return,attr-defined]
        except Exception:
            return str(uid)

    def _read_stat_psutil(self, pid: int) -> tuple[float, float, int, int, str, float, float] | None:
        """Read process info using psutil."""
        if not self._use_psutil:
            return None
        try:
            proc = self._psutil.Process(pid)
            with proc.oneshot():
                cpu_times = proc.cpu_times()
                utime = cpu_times.user
                stime = cpu_times.system
                mem_info = proc.memory_info()
                rss = mem_info.rss
                vms = mem_info.vms
                status = proc.status()
                create_time = proc.create_time()
                return (utime, stime, rss, vms, status, create_time, create_time)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, self._psutil.ZombieProcess, OSError):
            return None
        except Exception:
            return None

    async def _collect(self) -> list[ProcessData]:
        current_time = time.monotonic()
        result: list[ProcessData] = []

        pids = self._get_pids()

        for pid in pids:
            proc_data = ProcessData()
            proc_data.pid = pid

            # Try psutil first, fallback to /proc
            stat_data = None
            if self._use_psutil:
                stat_data = self._read_stat_psutil(pid)

            if stat_data is None:
                stat_data = self._read_stat(pid)

            if stat_data is None:
                continue

            utime, stime, rss_pages_or_bytes, vms_pages_or_bytes, status, create_time, starttime = stat_data

            # If psutil was used, rss/vms are in bytes; otherwise in pages
            if self._use_psutil:
                proc_data.rss = int(rss_pages_or_bytes)
                proc_data.vms = int(vms_pages_or_bytes)
            else:
                proc_data.rss = int(rss_pages_or_bytes) * self._page_size
                proc_data.vms = int(vms_pages_or_bytes) * self._page_size

            proc_data.status = status
            proc_data.create_time = create_time

            # Calculate CPU percent using delta
            if pid in self._prev_cpu_times:
                prev_utime, prev_stime, prev_time = self._prev_cpu_times[pid]
                elapsed = current_time - prev_time
                if elapsed > 0:
                    cpu_delta = (utime - prev_utime) + (stime - prev_stime)
                    cpu_percent = (cpu_delta / elapsed) * 100.0
                    cpu_count = os.cpu_count() or 1
                    proc_data.cpu_percent = max(0.0, min(cpu_percent, 100.0 * cpu_count))

            self._prev_cpu_times[pid] = (utime, stime, current_time)

            # Memory percent
            if self._total_memory > 0:
                proc_data.memory_percent = (proc_data.rss / self._total_memory) * 100.0

            # Read additional info
            proc_data.name = os.path.basename(self._read_exe(pid)) if self._read_exe(pid) else ""
            if not proc_data.name:
                # Fallback to first cmdline arg
                cmdline = self._read_cmdline(pid)
                if cmdline:
                    proc_data.name = os.path.basename(cmdline[0])
                else:
                    proc_data.name = f"pid-{pid}"

            proc_data.exe = self._read_exe(pid)
            proc_data.cmdline = self._read_cmdline(pid)
            proc_data.username = self._read_username(pid)

            result.append(proc_data)

        # Clean up old PIDs
        current_pids = set(pids)
        old_pids = [pid for pid in self._prev_cpu_times if pid not in current_pids]
        for pid in old_pids:
            del self._prev_cpu_times[pid]

        # Sort by CPU percent descending
        result.sort(key=lambda p: p.cpu_percent, reverse=True)

        return result
