"""State manager - owns current in-memory state."""

from datetime import datetime
from typing import Any

from app.collectors.base import CollectorResult, CollectorStatus
from app.state.models import (
    MemoryState,
    MetricValue,
    SystemState,
    SystemStateSnapshot,
)


class StateManager:
    """Manages current in-memory system state."""

    def __init__(self) -> None:
        self._state = SystemStateSnapshot(sequence=0)
        self._sequence = 0
        self._collector_status: dict[str, CollectorStatus] = {}

    @property
    def current_state(self) -> SystemStateSnapshot:
        """Get current state snapshot."""
        return self._state

    @property
    def sequence(self) -> int:
        """Get current sequence number."""
        return self._sequence

    def update_from_collector(self, result: CollectorResult[Any]) -> None:
        """Update state from a collector result."""
        self._collector_status[result.collector_name] = result.status

        if result.status == CollectorStatus.RUNNING and result.data is not None:
            self._apply_collector_data(result.collector_name, result.data)

        # Update health
        self._state.serverwatch_health.collectors = self._collector_status.copy()

    def _apply_collector_data(self, collector_name: str, data: Any) -> None:
        """Apply collector data to state."""
        if collector_name == "cpu":
            self._update_cpu(data)
        elif collector_name == "memory":
            self._update_memory(data)
        elif collector_name == "disk":
            self._update_disk(data)
        elif collector_name == "network":
            self._update_network(data)
        elif collector_name == "filesystem":
            self._update_filesystem(data)
        elif collector_name == "temperature":
            self._update_temperature(data)
        elif collector_name == "processes":
            self._update_processes(data)
        elif collector_name == "services":
            self._update_services(data)
        elif collector_name == "system":
            self._update_system(data)

        # Increment sequence on successful update
        self._sequence += 1
        self._state.sequence = self._sequence
        self._state.timestamp = datetime.utcnow()

    def _update_cpu(self, data: Any) -> None:
        self._state.cpu.total_utilization = MetricValue(
            value=data.total_utilization,
            collector="cpu",
        )
        self._state.cpu.per_core = [
            MetricValue(value=v, collector="cpu") for v in data.per_core
        ]
        self._state.cpu.load_average = MetricValue(
            value=data.load_average, collector="cpu"
        )
        self._state.cpu.cpu_count = MetricValue(value=data.cpu_count, collector="cpu")

    def _update_memory(self, data: Any) -> None:
        self._state.memory = MemoryState(
            total=MetricValue(value=data.total, collector="memory"),
            available=MetricValue(value=data.available, collector="memory"),
            used=MetricValue(value=data.used, collector="memory"),
            free=MetricValue(value=data.free, collector="memory"),
            swap_total=MetricValue(value=data.swap_total, collector="memory"),
            swap_used=MetricValue(value=data.swap_used, collector="memory"),
            swap_free=MetricValue(value=data.swap_free, collector="memory"),
        )

    def _update_disk(self, data: list[Any]) -> None:
        devices = {}
        for d in data:
            devices[d.device] = {
                "read_bytes": MetricValue(value=d.read_bytes, collector="disk"),
                "write_bytes": MetricValue(value=d.write_bytes, collector="disk"),
                "read_ops": MetricValue(value=d.read_ops, collector="disk"),
                "write_ops": MetricValue(value=d.write_ops, collector="disk"),
                "read_throughput": MetricValue(
                    value=d.read_throughput, collector="disk"
                ),
                "write_throughput": MetricValue(
                    value=d.write_throughput, collector="disk"
                ),
                "iops": MetricValue(value=d.iops, collector="disk"),
            }
        self._state.disk.devices = devices

    def _update_network(self, data: list[Any]) -> None:
        interfaces = {}
        for n in data:
            interfaces[n.name] = {
                "state": MetricValue(value=n.state, collector="network"),
                "rx_bytes": MetricValue(value=n.rx_bytes, collector="network"),
                "tx_bytes": MetricValue(value=n.tx_bytes, collector="network"),
                "rx_packets": MetricValue(value=n.rx_packets, collector="network"),
                "tx_packets": MetricValue(value=n.tx_packets, collector="network"),
                "rx_errors": MetricValue(value=n.rx_errors, collector="network"),
                "tx_errors": MetricValue(value=n.tx_errors, collector="network"),
                "rx_dropped": MetricValue(value=n.rx_dropped, collector="network"),
                "tx_dropped": MetricValue(value=n.tx_dropped, collector="network"),
                "throughput_rx": MetricValue(
                    value=n.throughput_rx, collector="network"
                ),
                "throughput_tx": MetricValue(
                    value=n.throughput_tx, collector="network"
                ),
            }
        self._state.network.interfaces = interfaces

    def _update_filesystem(self, data: list[Any]) -> None:
        mounts = {}
        for f in data:
            mounts[f.mount_point] = {
                "device": MetricValue(value=f.device, collector="filesystem"),
                "fstype": MetricValue(value=f.fstype, collector="filesystem"),
                "total": MetricValue(value=f.total, collector="filesystem"),
                "used": MetricValue(value=f.used, collector="filesystem"),
                "available": MetricValue(value=f.available, collector="filesystem"),
                "utilization_pct": MetricValue(
                    value=f.utilization_pct, collector="filesystem"
                ),
                "inodes_total": MetricValue(
                    value=f.inodes_total, collector="filesystem"
                ),
                "inodes_used": MetricValue(
                    value=f.inodes_used, collector="filesystem"
                ),
                "inodes_free": MetricValue(
                    value=f.inodes_free, collector="filesystem"
                ),
            }
        self._state.filesystem.mounts = mounts

    def _update_temperature(self, data: list[Any]) -> None:
        sensors = {}
        for t in data:
            sensors[t.name] = MetricValue(
                value=t.current, collector="temperature"
            )
        self._state.temperature.sensors = sensors

    def _update_processes(self, data: list[Any]) -> None:
        processes = []
        for p in data:
            processes.append(
                {
                    "pid": MetricValue(value=p.pid, collector="processes"),
                    "name": MetricValue(value=p.name, collector="processes"),
                    "exe": MetricValue(value=p.exe, collector="processes"),
                    "cpu_percent": MetricValue(
                        value=p.cpu_percent, collector="processes"
                    ),
                    "memory_percent": MetricValue(
                        value=p.memory_percent, collector="processes"
                    ),
                    "rss": MetricValue(value=p.rss, collector="processes"),
                    "status": MetricValue(value=p.status, collector="processes"),
                    "create_time": MetricValue(
                        value=p.create_time, collector="processes"
                    ),
                    "username": MetricValue(
                        value=p.username, collector="processes"
                    ),
                }
            )
        self._state.processes.processes = processes

    def _update_services(self, data: list[Any]) -> None:
        services = {}
        for s in data:
            services[s.name] = {
                "description": MetricValue(
                    value=s.description, collector="services"
                ),
                "active_state": MetricValue(
                    value=s.active_state, collector="services"
                ),
                "sub_state": MetricValue(value=s.sub_state, collector="services"),
                "load_state": MetricValue(
                    value=s.load_state, collector="services"
                ),
                "unit_file_state": MetricValue(
                    value=s.unit_file_state, collector="services"
                ),
                "main_pid": MetricValue(value=s.main_pid, collector="services"),
            }
        self._state.services.services = services

    def _update_system(self, data: Any) -> None:
        self._state.system = SystemState(
            hostname=MetricValue(value=data.hostname, collector="system"),
            os_name=MetricValue(value=data.os_name, collector="system"),
            os_version=MetricValue(value=data.os_version, collector="system"),
            kernel_version=MetricValue(value=data.kernel_version, collector="system"),
            architecture=MetricValue(value=data.architecture, collector="system"),
            cpu_model=MetricValue(value=data.cpu_model, collector="system"),
            cpu_cores_physical=MetricValue(
                value=data.cpu_cores_physical, collector="system"
            ),
            cpu_cores_logical=MetricValue(
                value=data.cpu_cores_logical, collector="system"
            ),
            total_memory=MetricValue(value=data.total_memory, collector="system"),
        )

    def mark_collector_failed(self, collector_name: str) -> None:
        """Mark a collector as failed and update health."""
        self._collector_status[collector_name] = CollectorStatus.FAILED
        self._state.serverwatch_health.collectors = self._collector_status.copy()

    def get_state_for_websocket(self) -> dict[str, Any]:
        """Get state formatted for WebSocket transmission."""
        # Convert to serializable format
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
