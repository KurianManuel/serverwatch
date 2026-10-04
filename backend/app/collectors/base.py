"""Base collector classes and protocols."""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar


class CollectorStatus(StrEnum):
    """Collector status states."""

    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    DISABLED = "DISABLED"


T = TypeVar("T")


@dataclass
class CollectorResult(Generic[T]):
    """Result of a collection operation."""

    collector_name: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: CollectorStatus = CollectorStatus.RUNNING
    data: T | None = None
    error: str | None = None
    duration_ms: float = 0.0


class Collector(ABC, Generic[T]):
    """Abstract base class for all collectors."""

    name: str
    interval_seconds: float

    def __init__(self, interval_seconds: float):
        self.interval_seconds = interval_seconds
        self._status = CollectorStatus.INITIALIZING
        self._last_result: CollectorResult[T] | None = None
        self._consecutive_failures = 0

    @property
    def status(self) -> CollectorStatus:
        return self._status

    @property
    def last_result(self) -> CollectorResult[T] | None:
        return self._last_result

    async def collect(self) -> CollectorResult[T]:
        """Execute collection with timing and error handling."""
        start = time.perf_counter()
        try:
            self._status = CollectorStatus.RUNNING
            data = await self._collect()
            self._consecutive_failures = 0
            self._status = CollectorStatus.RUNNING
            result = CollectorResult(
                collector_name=self.name,
                status=CollectorStatus.RUNNING,
                data=data,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._status = CollectorStatus.FAILED
            else:
                self._status = CollectorStatus.DEGRADED
            result = CollectorResult(
                collector_name=self.name,
                status=self._status,
                error=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        self._last_result = result
        return result

    @abstractmethod
    async def _collect(self) -> T:
        """Implement collection logic."""
        ...
