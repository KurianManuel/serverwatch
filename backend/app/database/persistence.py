"""Persistence adapter - bridges StateManager snapshots to DatabaseWriter."""

import asyncio
from datetime import datetime
from typing import Any

from app.database.writer import (
    DatabaseWriter,
    WritePriority,
    get_db_writer,
    start_db_writer,
)
from app.state.manager import StateManager
from app.state.models import (
    CPUState,
    DiskState,
    FilesystemState,
    MemoryState,
    MetricValue,
    NetworkState,
    StateTransition,
    SystemStateSnapshot,
    TemperatureState,
)


def _serialize_metric_value(value: Any) -> Any:
    """Serialize a metric value for database storage."""
    if isinstance(value, (list, dict, tuple)):
        import json

        return json.dumps(value)
    return value


def _extract_metric(metric: MetricValue | None) -> Any:
    """Extract raw value from MetricValue, returning None if unavailable."""
    if metric is None:
        return None
    if metric.status.value in ("unavailable", "failed"):
        return None
    return metric.value


def _metric_timestamp(metric: MetricValue | None) -> datetime | None:
    """Get timestamp from metric, or None if unavailable."""
    if metric is None:
        return None
    if metric.status.value in ("unavailable", "failed"):
        return None
    return metric.timestamp


class PersistenceAdapter:
    """
    Bridges StateManager live state to DatabaseWriter for historical persistence.

    Subscribes to StateManager snapshot commits and writes relevant metrics
    to the appropriate sample tables via the DatabaseWriter.
    """

    def __init__(
        self,
        state_manager: StateManager,
        db_writer: DatabaseWriter | None = None,
        server_id: str = "local",
        persist_interval: float = 5.0,
    ) -> None:
        self._state_manager = state_manager
        self._db_writer = db_writer
        self._server_id = server_id
        self._persist_interval = persist_interval
        self._running = False
        self._persist_task: asyncio.Task[None] | None = None
        self._last_persisted_sequence = 0
        self._failure_count = 0
        self._max_consecutive_failures = 10
        self._shutdown_event = asyncio.Event()
        self._server_written = False  # Track if server record has been written

        # Register for state transitions
        self._state_manager.register_transition_callback(self._on_state_transition)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def last_persisted_sequence(self) -> int:
        return self._last_persisted_sequence

    async def start(self) -> None:
        """Start the persistence adapter."""
        if self._running:
            return

        # Initialize database writer if not provided
        if self._db_writer is None:
            # Check if a global writer is already configured (for testing)
            import app.database.writer as writer_module
            if writer_module._db_writer is not None:
                self._db_writer = writer_module._db_writer
                # Ensure the writer is started
                if not self._db_writer._running:
                    self._db_writer.start()
            else:
                self._db_writer = get_db_writer()
                await start_db_writer()

        self._running = True
        self._failure_count = 0
        self._shutdown_event.clear()
        self._persist_task = asyncio.create_task(self._persist_loop(), name="serverwatch-persistence")

    async def stop(self) -> None:
        """Stop the persistence adapter."""
        if not self._running:
            return

        # Signal shutdown
        self._shutdown_event.set()
        self._running = False

        # Ensure final persist happens (the persist task will also do this, but do it synchronously to be sure)
        try:
            await self._persist_snapshot()
        except Exception:
            pass

        # Wait for persist task to finish
        if self._persist_task:
            try:
                await asyncio.wait_for(self._persist_task, timeout=5.0)
            except TimeoutError:
                self._persist_task.cancel()
                try:
                    await self._persist_task
                except asyncio.CancelledError:
                    pass

        # Unregister callback
        self._state_manager.unregister_transition_callback(self._on_state_transition)

    def _on_state_transition(self, transitions: list[StateTransition]) -> None:
        """Callback for state transitions - currently no-op, could trigger immediate persist for critical transitions."""
        # Could implement: if any transition is health-related (FAILED/RECOVERED), trigger immediate persist
        pass

    async def _persist_loop(self) -> None:
        """Main persistence loop - runs at configured interval."""
        while self._running:
            try:
                # Wait for either shutdown event or persist interval
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=self._persist_interval)
                except TimeoutError:
                    # Normal interval expiry - continue to persist
                    pass

                await self._persist_snapshot()
                self._failure_count = 0  # Reset on success

            except Exception:
                self._failure_count += 1
                if self._failure_count >= self._max_consecutive_failures:
                    # Too many failures - could alert or degrade
                    pass

        # Final persist on shutdown (if shutdown_event was set while running)
        if self._shutdown_event.is_set():
            try:
                await self._persist_snapshot()
            except Exception:
                pass
            except TimeoutError:
                pass  # Normal interval expiry

    async def _persist_snapshot(self) -> None:
        """Persist the current state snapshot to database."""
        writer = self._db_writer
        if writer is None:
            return

        snapshot = self._state_manager.current_state

        # Only persist if we have a new snapshot
        if snapshot.sequence <= self._last_persisted_sequence:
            return

        # Write server info (upsert)
        await self._write_server(snapshot, writer)

        # Write metric samples
        await self._write_cpu_samples(snapshot, writer)
        await self._write_memory_samples(snapshot, writer)
        await self._write_disk_samples(snapshot, writer)
        await self._write_network_samples(snapshot, writer)
        await self._write_filesystem_samples(snapshot, writer)
        await self._write_temperature_samples(snapshot, writer)

        self._last_persisted_sequence = snapshot.sequence

    async def _write_server(self, snapshot: SystemStateSnapshot, writer: DatabaseWriter) -> None:
        """Write server static info (only once per adapter lifetime)."""
        if self._server_written:
            return
        system = snapshot.system
        _, _ = await writer.write(
            "servers",
            {
                "id": self._server_id,
                "hostname": _extract_metric(system.hostname) or "unknown",
                "display_name": _extract_metric(system.hostname) or "unknown",
                "os_name": _extract_metric(system.os_name),
                "os_version": _extract_metric(system.os_version),
                "kernel_version": _extract_metric(system.kernel_version),
                "architecture": _extract_metric(system.architecture),
            },
            priority=WritePriority.CRITICAL,  # Must be written first for FK references
        )
        self._server_written = True

    async def _write_cpu_samples(self, snapshot: SystemStateSnapshot, writer: DatabaseWriter) -> None:
        """Write CPU samples."""
        cpu: CPUState = snapshot.cpu

        total_util = _extract_metric(cpu.total_utilization)
        if total_util is None:
            return

        per_core = cpu.per_core
        per_core_values = [_extract_metric(m) for m in per_core] if per_core else []

        load_avg = _extract_metric(cpu.load_average)
        load_1min = load_avg[0] if load_avg and isinstance(load_avg, (list, tuple)) and len(load_avg) > 0 else None
        load_5min = load_avg[1] if load_avg and isinstance(load_avg, (list, tuple)) and len(load_avg) > 1 else None
        load_15min = load_avg[2] if load_avg and isinstance(load_avg, (list, tuple)) and len(load_avg) > 2 else None

        cpu_count = _extract_metric(cpu.cpu_count)

        timestamp = _metric_timestamp(cpu.total_utilization) or datetime.utcnow()

        _, _ = await writer.write(
            "cpu_samples",
            {
                "server_id": self._server_id,
                "timestamp": timestamp.isoformat() + "Z",
                "total_utilization": total_util,
                "per_core": _serialize_metric_value(per_core_values),
                "load_1min": load_1min,
                "load_5min": load_5min,
                "load_15min": load_15min,
                "cpu_count": cpu_count,
            },
            priority=WritePriority.NORMAL,
        )

    async def _write_memory_samples(self, snapshot: SystemStateSnapshot, writer: DatabaseWriter) -> None:
        """Write memory samples."""
        mem: MemoryState = snapshot.memory

        total = _extract_metric(mem.total)
        available = _extract_metric(mem.available)
        used = _extract_metric(mem.used)

        if total is None or available is None or used is None:
            return

        timestamp = _metric_timestamp(mem.total) or datetime.utcnow()

        _, _ = await writer.write(
            "memory_samples",
            {
                "server_id": self._server_id,
                "timestamp": timestamp.isoformat() + "Z",
                "total_bytes": total,
                "available_bytes": available,
                "used_bytes": used,
                "free_bytes": _extract_metric(mem.free),
                "buffers_bytes": None,  # Not currently collected
                "cached_bytes": None,
                "swap_total_bytes": _extract_metric(mem.swap_total),
                "swap_used_bytes": _extract_metric(mem.swap_used),
                "swap_free_bytes": _extract_metric(mem.swap_free),
            },
            priority=WritePriority.NORMAL,
        )

    async def _write_disk_samples(self, snapshot: SystemStateSnapshot, writer: DatabaseWriter) -> None:
        """Write disk I/O samples per device."""
        disk: DiskState = snapshot.disk

        for device, metrics in disk.devices.items():
            read_bytes = _extract_metric(metrics.get("read_bytes"))
            write_bytes = _extract_metric(metrics.get("write_bytes"))
            read_ops = _extract_metric(metrics.get("read_ops"))
            write_ops = _extract_metric(metrics.get("write_ops"))
            read_throughput = _extract_metric(metrics.get("read_throughput"))
            write_throughput = _extract_metric(metrics.get("write_throughput"))
            iops = _extract_metric(metrics.get("iops"))

            # Skip if no data
            if all(v is None for v in [read_bytes, write_bytes, read_ops, write_ops]):
                continue

            # Get timestamp from any available metric
            timestamp = None
            for m in metrics.values():
                ts = _metric_timestamp(m)
                if ts:
                    timestamp = ts
                    break
            if timestamp is None:
                timestamp = datetime.utcnow()

            _, _ = await writer.write(
                "disk_samples",
                {
                    "server_id": self._server_id,
                    "timestamp": timestamp.isoformat() + "Z",
                    "device": device,
                    "read_bytes": read_bytes,
                    "write_bytes": write_bytes,
                    "read_ops": read_ops,
                    "write_ops": write_ops,
                    "read_throughput": read_throughput,
                    "write_throughput": write_throughput,
                    "iops": iops,
                },
                priority=WritePriority.NORMAL,
            )

    async def _write_network_samples(self, snapshot: SystemStateSnapshot, writer: DatabaseWriter) -> None:
        """Write network samples per interface."""
        network: NetworkState = snapshot.network

        for interface, metrics in network.interfaces.items():
            rx_bytes = _extract_metric(metrics.get("rx_bytes"))
            tx_bytes = _extract_metric(metrics.get("tx_bytes"))
            rx_packets = _extract_metric(metrics.get("rx_packets"))
            tx_packets = _extract_metric(metrics.get("tx_packets"))
            rx_errors = _extract_metric(metrics.get("rx_errors"))
            tx_errors = _extract_metric(metrics.get("tx_errors"))
            rx_dropped = _extract_metric(metrics.get("rx_dropped"))
            tx_dropped = _extract_metric(metrics.get("tx_dropped"))

            # Skip if no data
            if all(v is None for v in [rx_bytes, tx_bytes, rx_packets, tx_packets]):
                continue

            timestamp = None
            for m in metrics.values():
                ts = _metric_timestamp(m)
                if ts:
                    timestamp = ts
                    break
            if timestamp is None:
                timestamp = datetime.utcnow()

            _, _ = await writer.write(
                "network_samples",
                {
                    "server_id": self._server_id,
                    "timestamp": timestamp.isoformat() + "Z",
                    "interface": interface,
                    "rx_bytes": rx_bytes,
                    "tx_bytes": tx_bytes,
                    "rx_packets": rx_packets,
                    "tx_packets": tx_packets,
                    "rx_errors": rx_errors,
                    "tx_errors": tx_errors,
                    "rx_drops": rx_dropped,
                    "tx_drops": tx_dropped,
                },
                priority=WritePriority.NORMAL,
            )

    async def _write_filesystem_samples(self, snapshot: SystemStateSnapshot, writer: DatabaseWriter) -> None:
        """Write filesystem samples per mount."""
        fs: FilesystemState = snapshot.filesystem

        for mount_point, metrics in fs.mounts.items():
            total = _extract_metric(metrics.get("total"))
            used = _extract_metric(metrics.get("used"))
            available = _extract_metric(metrics.get("available"))
            free = _extract_metric(metrics.get("free"))
            utilization_pct = _extract_metric(metrics.get("utilization_pct"))
            inodes_total = _extract_metric(metrics.get("inodes_total"))
            inodes_free = _extract_metric(metrics.get("inodes_free"))
            device = _extract_metric(metrics.get("device"))
            fstype = _extract_metric(metrics.get("fstype"))

            # Skip if no data
            if all(v is None for v in [total, used, available, free]):
                continue

            timestamp = None
            for m in metrics.values():
                ts = _metric_timestamp(m)
                if ts:
                    timestamp = ts
                    break
            if timestamp is None:
                timestamp = datetime.utcnow()

            _, _ = await writer.write(
                "filesystem_samples",
                {
                    "server_id": self._server_id,
                    "timestamp": timestamp.isoformat() + "Z",
                    "mount_point": mount_point,
                    "device": device,
                    "fstype": fstype,
                    "total_bytes": total,
                    "free_bytes": free,
                    "available_bytes": available,
                    "used_bytes": used,
                    "used_percent": utilization_pct,
                    "inodes_total": inodes_total,
                    "inodes_free": inodes_free,
                },
                priority=WritePriority.NORMAL,
            )

    async def _write_temperature_samples(self, snapshot: SystemStateSnapshot, writer: DatabaseWriter) -> None:
        """Write temperature samples per sensor."""
        temp: TemperatureState = snapshot.temperature

        for sensor_name, metric in temp.sensors.items():
            temperature = _extract_metric(metric)
            if temperature is None:
                continue

            threshold_high, threshold_critical = temp.thresholds.get(sensor_name, (None, None))

            timestamp = _metric_timestamp(metric) or datetime.utcnow()

            _, _ = await writer.write(
                "temperature_samples",
                {
                    "server_id": self._server_id,
                    "timestamp": timestamp.isoformat() + "Z",
                    "sensor_name": sensor_name,
                    "sensor_label": sensor_name,
                    "temperature_celsius": temperature,
                    "high_threshold": threshold_high,
                    "critical_threshold": threshold_critical,
                },
                priority=WritePriority.NORMAL,
            )


# Global persistence adapter instance
_persistence_adapter: PersistenceAdapter | None = None
_persistence_lock = asyncio.Lock()


async def get_persistence_adapter(state_manager: StateManager, persist_interval: float = 5.0) -> PersistenceAdapter:
    """Get or create the global persistence adapter."""
    global _persistence_adapter
    async with _persistence_lock:
        if _persistence_adapter is None:
            _persistence_adapter = PersistenceAdapter(state_manager=state_manager, persist_interval=persist_interval)
        return _persistence_adapter


async def start_persistence(state_manager: StateManager, persist_interval: float = 5.0) -> None:
    """Start the global persistence adapter."""
    adapter = await get_persistence_adapter(state_manager, persist_interval=persist_interval)
    await adapter.start()


async def stop_persistence() -> None:
    """Stop the global persistence adapter."""
    global _persistence_adapter
    async with _persistence_lock:
        if _persistence_adapter is not None:
            await _persistence_adapter.stop()
            _persistence_adapter = None
