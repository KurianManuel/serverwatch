"""State data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from app.collectors.base import CollectorStatus


class DataStatus(str, Enum):
    """Data freshness status."""

    CURRENT = "current"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass
class MetricValue:
    """Wrapper for metric values with freshness metadata."""

    value: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: DataStatus = DataStatus.CURRENT
    collector: str = ""
    stale_threshold_seconds: float = 30.0

    def is_stale(self) -> bool:
        """Check if the value is stale."""
        if self.status != DataStatus.CURRENT:
            return True
        age = (datetime.utcnow() - self.timestamp).total_seconds()
        return age > self.stale_threshold_seconds


@dataclass
class CPUState:
    """CPU state."""

    total_utilization: MetricValue
    per_core: list[MetricValue] = field(default_factory=list)
    load_average: MetricValue = field(default_factory=lambda: MetricValue((0.0, 0.0, 0.0)))
    cpu_count: MetricValue = field(default_factory=lambda: MetricValue(0))


@dataclass
class MemoryState:
    """Memory state."""

    total: MetricValue
    available: MetricValue
    used: MetricValue
    free: MetricValue
    swap_total: MetricValue
    swap_used: MetricValue
    swap_free: MetricValue


@dataclass
class DiskState:
    """Disk I/O state per device."""

    devices: dict[str, dict[str, MetricValue]] = field(default_factory=dict)


@dataclass
class NetworkState:
    """Network state per interface."""

    interfaces: dict[str, dict[str, MetricValue]] = field(default_factory=dict)


@dataclass
class FilesystemState:
    """Filesystem state per mount."""

    mounts: dict[str, dict[str, MetricValue]] = field(default_factory=dict)


@dataclass
class TemperatureState:
    """Temperature state per sensor."""

    sensors: dict[str, MetricValue] = field(default_factory=dict)


@dataclass
class ProcessState:
    """Process state."""

    processes: list[dict[str, MetricValue]] = field(default_factory=list)


@dataclass
class ServiceState:
    """Service state."""

    services: dict[str, dict[str, MetricValue]] = field(default_factory=dict)


@dataclass
class SystemState:
    """Static system information."""

    hostname: MetricValue
    os_name: MetricValue
    os_version: MetricValue
    kernel_version: MetricValue
    architecture: MetricValue
    cpu_model: MetricValue
    cpu_cores_physical: MetricValue
    cpu_cores_logical: MetricValue
    total_memory: MetricValue


@dataclass
class ServerWatchHealth:
    """ServerWatch application health."""

    status: str = "HEALTHY"
    collectors: dict[str, CollectorStatus] = field(default_factory=dict)
    database: str = "healthy"
    websocket: str = "healthy"


@dataclass
class SystemStateSnapshot:
    """Complete system state snapshot."""

    sequence: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    cpu: CPUState = field(default_factory=lambda: CPUState(
        total_utilization=MetricValue(value=0.0),
        per_core=[],
        load_average=MetricValue(value=(0.0, 0.0, 0.0)),
        cpu_count=MetricValue(value=0),
    ))
    memory: MemoryState = field(default_factory=lambda: MemoryState(
        total=MetricValue(value=0),
        available=MetricValue(value=0),
        used=MetricValue(value=0),
        free=MetricValue(value=0),
        swap_total=MetricValue(value=0),
        swap_used=MetricValue(value=0),
        swap_free=MetricValue(value=0),
    ))
    disk: DiskState = field(default_factory=lambda: DiskState(devices={}))
    network: NetworkState = field(default_factory=lambda: NetworkState(interfaces={}))
    filesystem: FilesystemState = field(default_factory=lambda: FilesystemState(mounts={}))
    temperature: TemperatureState = field(default_factory=lambda: TemperatureState(sensors={}))
    processes: ProcessState = field(default_factory=lambda: ProcessState(processes=[]))
    services: ServiceState = field(default_factory=lambda: ServiceState(services={}))
    system: SystemState = field(default_factory=lambda: SystemState(
        hostname=MetricValue(value=""),
        os_name=MetricValue(value=""),
        os_version=MetricValue(value=""),
        kernel_version=MetricValue(value=""),
        architecture=MetricValue(value=""),
        cpu_model=MetricValue(value=""),
        cpu_cores_physical=MetricValue(value=0),
        cpu_cores_logical=MetricValue(value=0),
        total_memory=MetricValue(value=0),
    ))
    serverwatch_health: ServerWatchHealth = field(default_factory=ServerWatchHealth)