"""Event models for ServerWatch."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EventSeverity(StrEnum):
    """Event severity levels."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventSource(StrEnum):
    """Event source categories."""

    COLLECTOR = "collector"
    STATE_TRANSITION = "state_transition"
    SERVICE = "service"
    JOURNALD = "journald"
    SYSTEM = "system"


class EventType(StrEnum):
    """Event type categories."""

    # Collector events
    COLLECTOR_FAILURE = "collector_failure"
    COLLECTOR_RECOVERY = "collector_recovery"
    COLLECTOR_DEGRADED = "collector_degraded"

    # Service events
    SERVICE_TRANSITION = "service_transition"
    SERVICE_STARTED = "service_started"
    SERVICE_STOPPED = "service_stopped"
    SERVICE_FAILED = "service_failed"

    # Health events
    HEALTH_CHANGE = "health_change"
    HEALTH_DEGRADED = "health_degraded"
    HEALTH_FAILED = "health_failed"
    HEALTH_RECOVERED = "health_recovered"

    # System events
    SYSTEM_START = "system_start"
    SYSTEM_SHUTDOWN = "system_shutdown"
    SYSTEM_RESTART = "system_restart"


def compute_fingerprint(
    event_type: EventType,
    source: EventSource,
    server_id: str,
    key_context: dict[str, Any] | None = None,
) -> str:
    """Compute a deterministic fingerprint for event deduplication.

    Args:
        event_type: The event type
        source: The event source
        server_id: The server identifier
        key_context: Additional context fields for fingerprinting

    Returns:
        A deterministic SHA256 fingerprint string
    """
    import hashlib
    import json

    context: dict[str, Any] = {
        "event_type": event_type.value,
        "source": source.value,
        "server_id": server_id,
    }
    if key_context:
        # Sort keys for deterministic ordering
        context["key_context"] = {k: key_context[k] for k in sorted(key_context)}

    # Create deterministic JSON and hash
    json_str = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(json_str.encode()).hexdigest()


class EventBase(BaseModel):
    """Base event model with common fields."""

    server_id: str = Field(..., min_length=1, max_length=255)
    event_type: EventType
    severity: EventSeverity
    source: EventSource
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(default="", max_length=4096)
    metadata: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str | None = Field(default=None, max_length=64)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, v: Any) -> datetime:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        if isinstance(v, datetime):
            return v
        raise ValueError(f"Invalid timestamp type: {type(v)}")

    @property
    def metadata_json(self) -> str:
        """Return metadata as JSON string for database storage."""
        import json

        return json.dumps(self.metadata)

    def compute_fingerprint(self) -> str:
        """Compute the event's deduplication fingerprint."""
        return compute_fingerprint(
            event_type=self.event_type,
            source=self.source,
            server_id=self.server_id,
            key_context=self.metadata,
        )

    def set_fingerprint(self) -> None:
        """Set the fingerprint if not already set."""
        if self.fingerprint is None:
            self.fingerprint = self.compute_fingerprint()


class Event(EventBase):
    """Event model with database ID."""

    id: int | None = None

    def model_post_init(self, __context: Any) -> None:
        self.set_fingerprint()


class EventCreate(EventBase):
    """Event creation request (no ID)."""


class EventUpdate(BaseModel):
    """Event update request (partial)."""

    title: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=4096)
    metadata: dict[str, Any] | None = None
    severity: EventSeverity | None = None


class EventResponse(EventBase):
    """Event response with database ID."""

    id: int
    timestamp: datetime

    model_config = {"from_attributes": True}


class EventQueryParams(BaseModel):
    """Query parameters for event filtering."""

    server_id: str | None = None
    event_type: EventType | None = None
    severity: EventSeverity | None = None
    source: EventSource | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _parse_time(cls, v: Any) -> datetime | None:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        if isinstance(v, datetime) or v is None:
            return v
        raise ValueError(f"Invalid time type: {type(v)}")


class EventQueryResult(BaseModel):
    """Paginated event query result."""

    events: list[EventResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
