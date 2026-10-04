"""State manager - owns current in-memory state."""

import asyncio
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.collectors.base import CollectorResult, CollectorStatus
from app.state.models import (
    DataStatus,
    MemoryState,
    MetricValue,
    StateTransition,
    StateUpdate,
    SystemState,
    SystemStateSnapshot,
)


def _metric_path(prefix: str, *parts: str) -> str:
    """Build a metric path for change tracking."""
    return ".".join([prefix] + list(parts))


class StateManager:
    """Thread-safe, async-safe canonical live state manager."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state = SystemStateSnapshot(sequence=0)
        self._snapshot_sequence = 0
        self._update_counter = 0
        self._pending_results: list[CollectorResult[Any]] = []
        self._collector_status: dict[str, CollectorStatus] = {}
        self._transition_callbacks: list[Callable[[list[StateTransition]], None]] = []
        self._state_history: deque[StateUpdate] = deque(maxlen=100)
        self._metric_paths: dict[str, Any] = {}  # path -> reference for diffing

    @property
    def current_state(self) -> SystemStateSnapshot:
        """Get current state snapshot (consistent view)."""
        return self._state

    @property
    def sequence(self) -> int:
        """Get current public snapshot sequence number."""
        return self._snapshot_sequence

    @property
    def update_counter(self) -> int:
        """Get internal collector update counter."""
        return self._update_counter

    def get_collector_status(self, name: str) -> CollectorStatus:
        """Get status for a specific collector."""
        return self._collector_status.get(name, CollectorStatus.INITIALIZING)

    def get_all_collector_statuses(self) -> dict[str, CollectorStatus]:
        """Get all collector statuses."""
        return self._collector_status.copy()

    def register_transition_callback(self, callback: Callable[[list[StateTransition]], None]) -> None:
        """Register callback for state transitions. Called synchronously after state commit."""
        self._transition_callbacks.append(callback)

    def unregister_transition_callback(self, callback: Callable[[list[StateTransition]], None]) -> None:
        """Unregister transition callback."""
        try:
            self._transition_callbacks.remove(callback)
        except ValueError:
            pass

    def get_metric(self, path: str) -> MetricValue | None:
        """Get single metric by dotted path (e.g., 'cpu.total_utilization')."""
        parts = path.split(".")
        obj = self._state
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                return None
        return obj if isinstance(obj, MetricValue) else None

    async def apply_collector_result(self, result: CollectorResult[Any]) -> StateUpdate:
        """
        Apply/queue a collector result. Does not commit a snapshot.
        Returns a StateUpdate describing what was queued (sequence unchanged).
        """
        async with self._lock:
            self._pending_results.append(result)
            self._update_counter += 1
            self._collector_status[result.collector_name] = result.status

            # Create a transient StateUpdate reflecting the queued result
            return StateUpdate(
                sequence=self._snapshot_sequence,
                timestamp_wall=datetime.utcnow(),
                changed={},
                transitions=[],
            )

    async def commit_snapshot(self) -> StateUpdate:
        """
        Commit a new state snapshot from all pending results.
        Increments public snapshot sequence.
        Returns the committed StateUpdate with full snapshot and transitions.
        """
        async with self._lock:
            transitions: list[StateTransition] = []
            now_monotonic = time.monotonic()
            now_wall = datetime.utcnow()

            # Track old collector statuses from previous snapshot for transition detection
            old_statuses = self._state.serverwatch_health.collectors.copy()

            # Apply all pending results
            for result in self._pending_results:
                if result.status == CollectorStatus.RUNNING and result.data is not None:
                    self._apply_collector_data_internal(result.collector_name, result.data, now_monotonic, now_wall)
                elif result.status == CollectorStatus.RUNNING and result.data is None:
                    # RUNNING with no data: preserve existing data with CURRENT status (no-op)
                    pass
                elif result.status == CollectorStatus.RECOVERING:
                    # RECOVERING: preserve last known data, mark metrics as STALE
                    # Health computed as DEGRADED via _compute_health()
                    self._mark_collector_data_stale(result.collector_name, CollectorStatus.DEGRADED, now_monotonic, now_wall)
                elif result.status == CollectorStatus.DISABLED:
                    # DISABLED: preserve last known value if exists, mark metrics as UNAVAILABLE
                    self._mark_collector_data_unavailable(result.collector_name, now_monotonic, now_wall)
                elif result.status in (CollectorStatus.DEGRADED, CollectorStatus.FAILED):
                    # Preserve existing data but mark as STALE/FAILED
                    self._mark_collector_data_stale(result.collector_name, result.status, now_monotonic, now_wall)

            # Detect collector status transitions
            for collector_name, new_status in self._collector_status.items():
                old_status = old_statuses.get(collector_name, CollectorStatus.INITIALIZING)
                if new_status != old_status:
                    transitions.append(StateTransition(
                        sequence=self._snapshot_sequence + 1,
                        timestamp_monotonic=now_monotonic,
                        timestamp_wall=now_wall,
                        collector=collector_name,
                        changed_paths=[f"serverwatch_health.collectors.{collector_name}"],
                        old_status=old_status,
                        new_status=new_status,
                        is_health_transition=False,
                    ))

            # Compute new health
            old_health = self._state.serverwatch_health.status
            new_health = self._compute_health()
            if new_health != old_health:
                transitions.append(StateTransition(
                    sequence=self._snapshot_sequence + 1,
                    timestamp_monotonic=now_monotonic,
                    timestamp_wall=now_wall,
                    collector="state_manager",
                    changed_paths=["serverwatch_health.status"],
                    old_status=CollectorStatus.RUNNING,  # using as generic
                    new_status=CollectorStatus.RUNNING,
                    is_health_transition=True,
                ))
                self._state.serverwatch_health.status = new_health

            # Update collector statuses in health
            self._state.serverwatch_health.collectors = self._collector_status.copy()

            # Clear pending and commit snapshot
            self._pending_results.clear()
            self._snapshot_sequence += 1
            self._state.sequence = self._snapshot_sequence
            self._state.timestamp = now_wall

            # Build StateUpdate
            state_update = StateUpdate(
                sequence=self._snapshot_sequence,
                timestamp_wall=now_wall,
                snapshot=self._state,
                changed={},  # full snapshot provided
                transitions=transitions,
            )

            # Store in history for get_state_since
            self._state_history.append(state_update)

            # Fire transition callbacks
            if transitions:
                for cb in self._transition_callbacks:
                    try:
                        cb(transitions)
                    except Exception:
                        # Never crash state manager from callbacks
                        pass

            return state_update

    def _mark_collector_data_stale(self, collector_name: str, status: CollectorStatus, now_monotonic: float, now_wall: datetime) -> None:
        """Mark existing collector data as STALE or FAILED when collector degrades/fails."""
        target_status = DataStatus.STALE if status == CollectorStatus.DEGRADED else DataStatus.FAILED

        # Update metrics for this collector based on collector name
        if collector_name == "cpu":
            for metric in [self._state.cpu.total_utilization, self._state.cpu.load_average, self._state.cpu.cpu_count]:
                if metric and isinstance(metric, MetricValue):
                    metric.status = target_status
            for m in self._state.cpu.per_core:
                if isinstance(m, MetricValue):
                    m.status = target_status
        elif collector_name == "memory":
            for metric in [self._state.memory.total, self._state.memory.available, self._state.memory.used,
                          self._state.memory.free, self._state.memory.swap_total, self._state.memory.swap_used,
                          self._state.memory.swap_free]:
                if isinstance(metric, MetricValue):
                    metric.status = target_status
        elif collector_name == "disk":
            for dev in self._state.disk.devices.values():
                for m in dev.values():
                    if isinstance(m, MetricValue):
                        m.status = target_status
        elif collector_name == "network":
            for iface in self._state.network.interfaces.values():
                for m in iface.values():
                    if isinstance(m, MetricValue):
                        m.status = target_status
        elif collector_name == "filesystem":
            for mount in self._state.filesystem.mounts.values():
                for m in mount.values():
                    if isinstance(m, MetricValue):
                        m.status = target_status
        elif collector_name == "temperature":
            for m in self._state.temperature.sensors.values():
                if isinstance(m, MetricValue):
                    m.status = target_status
        elif collector_name == "processes":
            for proc in self._state.processes.processes:
                for m in proc.values():
                    if isinstance(m, MetricValue):
                        m.status = target_status
        elif collector_name == "services":
            for svc in self._state.services.services.values():
                for m in svc.values():
                    if isinstance(m, MetricValue):
                        m.status = target_status
        elif collector_name == "system":
            for metric in [self._state.system.hostname, self._state.system.os_name, self._state.system.os_version,
                          self._state.system.kernel_version, self._state.system.architecture,
                          self._state.system.cpu_model, self._state.system.cpu_cores_physical,
                          self._state.system.cpu_cores_logical, self._state.system.total_memory]:
                if isinstance(metric, MetricValue):
                    metric.status = target_status

    def _mark_collector_data_unavailable(self, collector_name: str, now_monotonic: float, now_wall: datetime) -> None:
        """Mark existing collector data as UNAVAILABLE when collector is disabled."""
        # Update metrics for this collector based on collector name
        if collector_name == "cpu":
            for metric in [self._state.cpu.total_utilization, self._state.cpu.load_average, self._state.cpu.cpu_count]:
                if metric and isinstance(metric, MetricValue):
                    metric.status = DataStatus.UNAVAILABLE
            for m in self._state.cpu.per_core:
                if isinstance(m, MetricValue):
                    m.status = DataStatus.UNAVAILABLE
        elif collector_name == "memory":
            for metric in [self._state.memory.total, self._state.memory.available, self._state.memory.used,
                          self._state.memory.free, self._state.memory.swap_total, self._state.memory.swap_used,
                          self._state.memory.swap_free]:
                if isinstance(metric, MetricValue):
                    metric.status = DataStatus.UNAVAILABLE
        elif collector_name == "disk":
            for dev in self._state.disk.devices.values():
                for m in dev.values():
                    if isinstance(m, MetricValue):
                        m.status = DataStatus.UNAVAILABLE
        elif collector_name == "network":
            for iface in self._state.network.interfaces.values():
                for m in iface.values():
                    if isinstance(m, MetricValue):
                        m.status = DataStatus.UNAVAILABLE
        elif collector_name == "filesystem":
            for mount in self._state.filesystem.mounts.values():
                for m in mount.values():
                    if isinstance(m, MetricValue):
                        m.status = DataStatus.UNAVAILABLE
        elif collector_name == "temperature":
            for m in self._state.temperature.sensors.values():
                if isinstance(m, MetricValue):
                    m.status = DataStatus.UNAVAILABLE
        elif collector_name == "processes":
            for proc in self._state.processes.processes:
                for m in proc.values():
                    if isinstance(m, MetricValue):
                        m.status = DataStatus.UNAVAILABLE
        elif collector_name == "services":
            for svc in self._state.services.services.values():
                for m in svc.values():
                    if isinstance(m, MetricValue):
                        m.status = DataStatus.UNAVAILABLE
        elif collector_name == "system":
            for metric in [self._state.system.hostname, self._state.system.os_name, self._state.system.os_version,
                          self._state.system.kernel_version, self._state.system.architecture,
                          self._state.system.cpu_model, self._state.system.cpu_cores_physical,
                          self._state.system.cpu_cores_logical, self._state.system.total_memory]:
                if isinstance(metric, MetricValue):
                    metric.status = DataStatus.UNAVAILABLE

    def get_state_since(self, sequence: int) -> StateUpdate | None:
        """
        Return incremental update since given sequence.
        Returns None if sequence is too old or invalid.
        Sequence 0 is invalid (snapshots start at 1).
        """
        if sequence <= 0 or sequence > self._snapshot_sequence:
            return None

        # Find the update with matching sequence
        for update in reversed(self._state_history):
            if update.sequence == sequence:
                return update

        # If not in history (too old), return current snapshot as full resync
        return StateUpdate(
            sequence=self._snapshot_sequence,
            timestamp_wall=self._state.timestamp,
            snapshot=self._state,
            changed={},
            transitions=[],
        )

    def _apply_collector_data_internal(
        self,
        collector_name: str,
        data: Any,
        now_monotonic: float,
        now_wall: datetime,
    ) -> None:
        """Apply collector data to state (must hold lock)."""
        if collector_name == "cpu":
            self._update_cpu(data, now_monotonic, now_wall)
        elif collector_name == "memory":
            self._update_memory(data, now_monotonic, now_wall)
        elif collector_name == "disk":
            self._update_disk(data, now_monotonic, now_wall)
        elif collector_name == "network":
            self._update_network(data, now_monotonic, now_wall)
        elif collector_name == "filesystem":
            self._update_filesystem(data, now_monotonic, now_wall)
        elif collector_name == "temperature":
            self._update_temperature(data, now_monotonic, now_wall)
        elif collector_name == "processes":
            self._update_processes(data, now_monotonic, now_wall)
        elif collector_name == "services":
            self._update_services(data, now_monotonic, now_wall)
        elif collector_name == "system":
            self._update_system(data, now_monotonic, now_wall)

    def _make_metric(self, value: Any, collector: str, now_monotonic: float, now_wall: datetime) -> MetricValue:
        return MetricValue(
            value=value,
            timestamp=now_wall,
            monotonic_timestamp=now_monotonic,
            status=DataStatus.CURRENT,
            collector=collector,
        )

    def _update_cpu(self, data: Any, now_monotonic: float, now_wall: datetime) -> None:
        self._state.cpu.total_utilization = self._make_metric(data.total_utilization, "cpu", now_monotonic, now_wall)
        self._state.cpu.per_core = [
            self._make_metric(v, "cpu", now_monotonic, now_wall) for v in data.per_core
        ]
        self._state.cpu.load_average = self._make_metric(data.load_average, "cpu", now_monotonic, now_wall)
        self._state.cpu.cpu_count = self._make_metric(data.cpu_count, "cpu", now_monotonic, now_wall)

    def _update_memory(self, data: Any, now_monotonic: float, now_wall: datetime) -> None:
        self._state.memory = MemoryState(
            total=self._make_metric(data.total, "memory", now_monotonic, now_wall),
            available=self._make_metric(data.available, "memory", now_monotonic, now_wall),
            used=self._make_metric(data.used, "memory", now_monotonic, now_wall),
            free=self._make_metric(data.free, "memory", now_monotonic, now_wall),
            swap_total=self._make_metric(data.swap_total, "memory", now_monotonic, now_wall),
            swap_used=self._make_metric(data.swap_used, "memory", now_monotonic, now_wall),
            swap_free=self._make_metric(data.swap_free, "memory", now_monotonic, now_wall),
        )

    def _update_disk(self, data: list[Any], now_monotonic: float, now_wall: datetime) -> None:
        devices = {}
        for d in data:
            devices[d.device] = {
                "read_bytes": self._make_metric(d.read_bytes, "disk", now_monotonic, now_wall),
                "write_bytes": self._make_metric(d.write_bytes, "disk", now_monotonic, now_wall),
                "read_ops": self._make_metric(d.read_ops, "disk", now_monotonic, now_wall),
                "write_ops": self._make_metric(d.write_ops, "disk", now_monotonic, now_wall),
                "read_throughput": self._make_metric(d.read_throughput, "disk", now_monotonic, now_wall),
                "write_throughput": self._make_metric(d.write_throughput, "disk", now_monotonic, now_wall),
                "iops": self._make_metric(d.iops, "disk", now_monotonic, now_wall),
            }
        self._state.disk.devices = devices

    def _update_network(self, data: list[Any], now_monotonic: float, now_wall: datetime) -> None:
        interfaces = {}
        for n in data:
            interfaces[n.name] = {
                "state": self._make_metric(n.state, "network", now_monotonic, now_wall),
                "rx_bytes": self._make_metric(n.rx_bytes, "network", now_monotonic, now_wall),
                "tx_bytes": self._make_metric(n.tx_bytes, "network", now_monotonic, now_wall),
                "rx_packets": self._make_metric(n.rx_packets, "network", now_monotonic, now_wall),
                "tx_packets": self._make_metric(n.tx_packets, "network", now_monotonic, now_wall),
                "rx_errors": self._make_metric(n.rx_errors, "network", now_monotonic, now_wall),
                "tx_errors": self._make_metric(n.tx_errors, "network", now_monotonic, now_wall),
                "rx_dropped": self._make_metric(n.rx_dropped, "network", now_monotonic, now_wall),
                "tx_dropped": self._make_metric(n.tx_dropped, "network", now_monotonic, now_wall),
                "throughput_rx": self._make_metric(n.throughput_rx, "network", now_monotonic, now_wall),
                "throughput_tx": self._make_metric(n.throughput_tx, "network", now_monotonic, now_wall),
            }
        self._state.network.interfaces = interfaces

    def _update_filesystem(self, data: list[Any], now_monotonic: float, now_wall: datetime) -> None:
        mounts = {}
        for f in data:
            mounts[f.mount_point] = {
                "device": self._make_metric(f.device, "filesystem", now_monotonic, now_wall),
                "fstype": self._make_metric(f.fstype, "filesystem", now_monotonic, now_wall),
                "total": self._make_metric(f.total, "filesystem", now_monotonic, now_wall),
                "used": self._make_metric(f.used, "filesystem", now_monotonic, now_wall),
                "available": self._make_metric(f.available, "filesystem", now_monotonic, now_wall),
                "utilization_pct": self._make_metric(f.utilization_pct, "filesystem", now_monotonic, now_wall),
                "inodes_total": self._make_metric(f.inodes_total, "filesystem", now_monotonic, now_wall),
                "inodes_used": self._make_metric(f.inodes_used, "filesystem", now_monotonic, now_wall),
                "inodes_free": self._make_metric(f.inodes_free, "filesystem", now_monotonic, now_wall),
            }
        self._state.filesystem.mounts = mounts

    def _update_temperature(self, data: list[Any], now_monotonic: float, now_wall: datetime) -> None:
        sensors = {}
        thresholds = {}
        for t in data:
            sensors[t.name] = self._make_metric(t.current, "temperature", now_monotonic, now_wall)
            thresholds[t.name] = (t.high, t.critical)
        self._state.temperature.sensors = sensors
        self._state.temperature.thresholds = thresholds

    def _update_processes(self, data: list[Any], now_monotonic: float, now_wall: datetime) -> None:
        processes = []
        for p in data:
            processes.append({
                "pid": self._make_metric(p.pid, "processes", now_monotonic, now_wall),
                "name": self._make_metric(p.name, "processes", now_monotonic, now_wall),
                "exe": self._make_metric(p.exe, "processes", now_monotonic, now_wall),
                "cpu_percent": self._make_metric(p.cpu_percent, "processes", now_monotonic, now_wall),
                "memory_percent": self._make_metric(p.memory_percent, "processes", now_monotonic, now_wall),
                "rss": self._make_metric(p.rss, "processes", now_monotonic, now_wall),
                "status": self._make_metric(p.status, "processes", now_monotonic, now_wall),
                "create_time": self._make_metric(p.create_time, "processes", now_monotonic, now_wall),
                "username": self._make_metric(p.username, "processes", now_monotonic, now_wall),
            })
        self._state.processes.processes = processes

    def _update_services(self, data: list[Any], now_monotonic: float, now_wall: datetime) -> None:
        services = {}
        for s in data:
            services[s.name] = {
                "description": self._make_metric(s.description, "services", now_monotonic, now_wall),
                "active_state": self._make_metric(s.active_state, "services", now_monotonic, now_wall),
                "sub_state": self._make_metric(s.sub_state, "services", now_monotonic, now_wall),
                "load_state": self._make_metric(s.load_state, "services", now_monotonic, now_wall),
                "unit_file_state": self._make_metric(s.unit_file_state, "services", now_monotonic, now_wall),
                "main_pid": self._make_metric(s.main_pid, "services", now_monotonic, now_wall),
                "active_enter_timestamp": self._make_metric(s.active_enter_timestamp, "services", now_monotonic, now_wall),
                "inactive_enter_timestamp": self._make_metric(s.inactive_enter_timestamp, "services", now_monotonic, now_wall),
            }
        self._state.services.services = services

    def _update_system(self, data: Any, now_monotonic: float, now_wall: datetime) -> None:
        self._state.system = SystemState(
            hostname=self._make_metric(data.hostname, "system", now_monotonic, now_wall),
            os_name=self._make_metric(data.os_name, "system", now_monotonic, now_wall),
            os_version=self._make_metric(data.os_version, "system", now_monotonic, now_wall),
            kernel_version=self._make_metric(data.kernel_version, "system", now_monotonic, now_wall),
            architecture=self._make_metric(data.architecture, "system", now_monotonic, now_wall),
            cpu_model=self._make_metric(data.cpu_model, "system", now_monotonic, now_wall),
            cpu_cores_physical=self._make_metric(data.cpu_cores_physical, "system", now_monotonic, now_wall),
            cpu_cores_logical=self._make_metric(data.cpu_cores_logical, "system", now_monotonic, now_wall),
            total_memory=self._make_metric(data.total_memory, "system", now_monotonic, now_wall),
        )

    def _compute_health(self) -> str:
        """Compute ServerWatch health from collector statuses."""
        statuses = self._collector_status.values()
        if CollectorStatus.FAILED in statuses:
            return "FAILED"
        if CollectorStatus.DEGRADED in statuses or CollectorStatus.RECOVERING in statuses:
            return "DEGRADED"
        if all(s == CollectorStatus.RUNNING for s in statuses):
            return "HEALTHY"
        return "DEGRADED"  # some INITIALIZING/DISABLED

    async def mark_collector_failed(self, collector_name: str) -> None:
        """Mark a collector as failed (async, for external use). Thread-safe via lock."""
        async with self._lock:
            self._collector_status[collector_name] = CollectorStatus.FAILED
            self._state.serverwatch_health.collectors = self._collector_status.copy()
            self._state.serverwatch_health.status = self._compute_health()

    def get_state_for_websocket(self) -> dict[str, Any]:
        """Get state formatted for WebSocket transmission."""
        def serialize_metric(m: MetricValue) -> dict[str, Any]:
            return {
                "value": m.value,
                "timestamp": m.timestamp.isoformat() + "Z",
                "status": m.status.value,
                "collector": m.collector,
                "stale": m.is_stale(),
            }

        return {
            "sequence": self._state.sequence,
            "timestamp": self._state.timestamp.isoformat() + "Z",
            "cpu": {
                "total_utilization": serialize_metric(self._state.cpu.total_utilization),
                "per_core": [serialize_metric(v) for v in self._state.cpu.per_core],
                "load_average": serialize_metric(self._state.cpu.load_average),
                "cpu_count": serialize_metric(self._state.cpu.cpu_count),
            },
            "memory": {
                "total": serialize_metric(self._state.memory.total),
                "available": serialize_metric(self._state.memory.available),
                "used": serialize_metric(self._state.memory.used),
                "free": serialize_metric(self._state.memory.free),
                "swap_total": serialize_metric(self._state.memory.swap_total),
                "swap_used": serialize_metric(self._state.memory.swap_used),
                "swap_free": serialize_metric(self._state.memory.swap_free),
            },
            "disk": {
                "devices": {
                    k: {k2: serialize_metric(v2) for k2, v2 in v.items()}
                    for k, v in self._state.disk.devices.items()
                }
            },
            "network": {
                "interfaces": {
                    k: {k2: serialize_metric(v2) for k2, v2 in v.items()}
                    for k, v in self._state.network.interfaces.items()
                }
            },
            "filesystem": {
                "mounts": {
                    k: {k2: serialize_metric(v2) for k2, v2 in v.items()}
                    for k, v in self._state.filesystem.mounts.items()
                }
            },
            "temperature": {
                "sensors": {
                    k: serialize_metric(v)
                    for k, v in self._state.temperature.sensors.items()
                }
            },
            "processes": {
                "processes": [
                    {k2: serialize_metric(v2) for k2, v2 in p.items()}
                    for p in self._state.processes.processes
                ]
            },
            "services": {
                "services": {
                    k: {k2: serialize_metric(v2) for k2, v2 in v.items()}
                    for k, v in self._state.services.services.items()
                }
            },
            "serverwatch_health": {
                "status": self._state.serverwatch_health.status,
                "collectors": {
                    k: v.value for k, v in self._state.serverwatch_health.collectors.items()
                },
            },
        }
