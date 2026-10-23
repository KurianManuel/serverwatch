"""Event engine - processes and normalizes events from various sources.

Sources of events:
- State Manager transition callbacks (collector status, health changes)
- Service state changes (via service collector)
- Journald entries (Stage 5.2)
- Direct event emission (collector failures, etc.)
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.collectors.base import CollectorStatus
from app.config import settings
from app.database.writer import DatabaseWriter
from app.events.journal import JournalReader, get_journal_reader, start_journal_reader, stop_journal_reader
from app.events.models import (
    Event,
    EventCreate,
    EventSeverity,
    EventSource,
    EventType,
)
from app.events.repository import EventRepository
from app.state.manager import StateManager
from app.state.models import StateTransition

logger = logging.getLogger(__name__)


class EventEngine:
    """Event engine - normalizes, deduplicates, and persists events.

    Consumes StateManager transitions and emits normalized events
    with 24-hour time-bounded deduplication.
    """

    # Bounded processing configuration
    MAX_QUEUE_SIZE = 100
    MAX_WORKERS = 4
    SHUTDOWN_DRAIN_TIMEOUT = 10.0

    def __init__(
        self,
        state_manager: StateManager,
        event_repository: EventRepository,
        db_writer: DatabaseWriter,
        server_id: str = "local",
    ) -> None:
        self._state_manager = state_manager
        self._event_repo = event_repository
        self._db_writer = db_writer
        self._server_id = server_id

        self._running = False
        self._shutdown_event = asyncio.Event()

        # Bounded queue for transition processing
        self._transition_queue: asyncio.Queue[StateTransition] = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._workers: list[asyncio.Task[None]] = []
        self._dropped_transitions = 0
        self._processed_transitions = 0
        self._failed_transitions = 0

        # Background cleanup task
        self._cleanup_task: asyncio.Task[None] | None = None

        # Journal reader (optional)
        self._journal_reader: JournalReader | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def queue_size(self) -> int:
        return self._transition_queue.qsize()

    @property
    def dropped_transitions(self) -> int:
        return self._dropped_transitions

    @property
    def journal_reader(self) -> JournalReader | None:
        return self._journal_reader

    @property
    def processed_transitions(self) -> int:
        return self._processed_transitions

    @property
    def failed_transitions(self) -> int:
        return self._failed_transitions

    async def start(self) -> None:
        """Start the event engine."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._dropped_transitions = 0
        self._processed_transitions = 0
        self._failed_transitions = 0

        # Register for StateManager transitions
        self._state_manager.register_transition_callback(self._on_state_transition)

        # Start worker tasks
        for i in range(self.MAX_WORKERS):
            worker = asyncio.create_task(self._worker_loop(i), name=f"serverwatch-event-worker-{i}")
            self._workers.append(worker)

        # Start background cleanup task
        self._cleanup_task = asyncio.create_task(self._process_loop(), name="serverwatch-event-cleanup")

        # Start journal reader if enabled
        if settings.journal_enabled:
            self._journal_reader = JournalReader(
                event_repository=self._event_repo,
                db_writer=self._db_writer,
                server_id=self._server_id,
                units=settings.journal_units,
                priority=settings.journal_priority,
                max_entries_per_poll=settings.journal_max_entries_per_poll,
                seek_tail=settings.journal_seek_tail,
            )
            try:
                await self._journal_reader.start()
            except Exception as e:
                logger.warning("Failed to start journal reader: %s", e)
                self._journal_reader = None

    async def stop(self) -> None:
        """Stop the event engine."""
        if not self._running:
            return

        self._shutdown_event.set()
        self._running = False

        # Unregister callback
        self._state_manager.unregister_transition_callback(self._on_state_transition)

        # Signal workers to stop by putting None sentinels
        for _ in self._workers:
            try:
                self._transition_queue.put_nowait(None)  # type: ignore[arg-type]
            except asyncio.QueueFull:
                pass

        # Wait for workers to finish with timeout
        if self._workers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._workers, return_exceptions=True),
                    timeout=self.SHUTDOWN_DRAIN_TIMEOUT,
                )
            except TimeoutError:
                for w in self._workers:
                    w.cancel()
                await asyncio.gather(*self._workers, return_exceptions=True)

        self._workers.clear()

        # Stop cleanup task
        if self._cleanup_task:
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0)
            except TimeoutError:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
            self._cleanup_task = None

        # Stop journal reader
        if self._journal_reader:
            try:
                await self._journal_reader.stop()
            except Exception as e:
                logger.warning("Error stopping journal reader: %s", e)
            self._journal_reader = None

        # Log final stats
        logger.info(
            "Event engine stopped: processed=%d, failed=%d, dropped=%d",
            self._processed_transitions,
            self._failed_transitions,
            self._dropped_transitions,
        )

    def _on_state_transition(self, transitions: list[StateTransition]) -> None:
        """Callback for StateManager transitions - enqueues for bounded processing."""
        for transition in transitions:
            if not self._running:
                break
            try:
                self._transition_queue.put_nowait(transition)
            except asyncio.QueueFull:
                self._dropped_transitions += 1
                logger.warning(
                    "Event transition queue full, dropped transition: %s -> %s",
                    transition.collector,
                    transition.new_status.value if hasattr(transition.new_status, 'value') else transition.new_status,
                )

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker loop for processing transitions."""
        logger.debug("Event worker %d started", worker_id)

        while self._running:
            try:
                # Wait for transition with timeout to check shutdown
                try:
                    transition = await asyncio.wait_for(self._transition_queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                # None sentinel means shutdown
                if transition is None:
                    self._transition_queue.task_done()
                    break

                # Process the transition
                await self._process_transition(transition)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Event worker %d error: %s", worker_id, e)

        logger.debug("Event worker %d stopped", worker_id)

    async def _process_transition(self, transition: StateTransition) -> None:
        """Process a single transition."""
        try:
            event = self._normalize_transition(transition)
            if event:
                result = await self._event_repo.create(event)
                fp = event.fingerprint or "unknown"
                self._processed_transitions += 1
                logger.debug("Event processed: %s (%s) - id=%s", event.event_type.value, fp[:16], result.id)
        except RuntimeError as e:
            # Queue full or transaction failure - these are retryable
            self._failed_transitions += 1
            logger.warning("Event processing failed (retryable): %s", e)
        except Exception as e:
            # Unexpected error
            self._failed_transitions += 1
            logger.exception("Failed to create event from transition: %s", e)
        finally:
            self._transition_queue.task_done()

    def _normalize_transition(self, transition: StateTransition) -> EventCreate | None:
        """Convert a StateTransition to an EventCreate."""
        if transition.is_health_transition:
            return self._create_health_event(transition)
        else:
            return self._create_collector_event(transition)

    def _create_collector_event(self, transition: StateTransition) -> EventCreate | None:
        """Create event for collector status transition."""
        old_status = transition.old_status
        new_status = transition.new_status
        collector = transition.collector

        # Map collector status transitions to event types
        if new_status == CollectorStatus.FAILED and old_status != CollectorStatus.FAILED:
            event_type = EventType.COLLECTOR_FAILURE
            severity = EventSeverity.ERROR
        elif new_status == CollectorStatus.RUNNING and old_status == CollectorStatus.FAILED:
            event_type = EventType.COLLECTOR_RECOVERY
            severity = EventSeverity.INFO
        elif new_status == CollectorStatus.DEGRADED and old_status == CollectorStatus.RUNNING:
            event_type = EventType.COLLECTOR_DEGRADED
            severity = EventSeverity.WARNING
        elif new_status == CollectorStatus.RUNNING and old_status == CollectorStatus.DEGRADED:
            event_type = EventType.COLLECTOR_RECOVERY
            severity = EventSeverity.INFO
        elif new_status == CollectorStatus.INITIALIZING:
            # Don't emit events for initial startup
            return None
        else:
            # Other transitions (DISABLED, RECOVERING, etc.) - log but don't create event
            return None

        return EventCreate(
            server_id=self._server_id,
            event_type=event_type,
            severity=severity,
            source=EventSource.COLLECTOR,
            title=f"Collector {collector} {new_status.value.lower()}",
            message=f"Collector '{collector}' transitioned from {old_status.value} to {new_status.value}",
            metadata={
                "collector": collector,
                "old_status": old_status.value,
                "new_status": new_status.value,
                "sequence": transition.sequence,
            },
            timestamp=transition.timestamp_wall,
        )

    def _create_health_event(self, transition: StateTransition) -> EventCreate | None:
        """Create event for ServerWatch health transition."""
        # The health status is stored in old_status/new_status as strings
        # but the transition uses CollectorStatus as generic container
        old_health = transition.old_status.value if hasattr(transition.old_status, 'value') else str(transition.old_status)
        new_health = transition.new_status.value if hasattr(transition.new_status, 'value') else str(transition.new_status)

        if new_health == "FAILED" and old_health != "FAILED":
            event_type = EventType.HEALTH_FAILED
            severity = EventSeverity.CRITICAL
        elif new_health == "HEALTHY" and old_health != "HEALTHY":
            event_type = EventType.HEALTH_RECOVERED
            severity = EventSeverity.INFO
        elif new_health == "DEGRADED" and old_health == "HEALTHY":
            event_type = EventType.HEALTH_DEGRADED
            severity = EventSeverity.WARNING
        elif new_health == "DEGRADED" and old_health == "FAILED":
            event_type = EventType.HEALTH_RECOVERED
            severity = EventSeverity.INFO
        else:
            return None

        return EventCreate(
            server_id=self._server_id,
            event_type=event_type,
            severity=severity,
            source=EventSource.STATE_TRANSITION,
            title=f"ServerWatch health changed to {new_health}",
            message=f"ServerWatch health transitioned from {old_health} to {new_health}",
            metadata={
                "old_health": old_health,
                "new_health": new_health,
                "sequence": transition.sequence,
            },
            timestamp=transition.timestamp_wall,
        )

    async def _process_loop(self) -> None:
        """Background processing loop for periodic tasks."""
        while self._running:
            try:
                # Wait for shutdown or interval (run cleanup every hour)
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=3600.0)
                except TimeoutError:
                    pass

                if not self._running:
                    break

                # Clean up old deduplication records
                deleted = await self._event_repo.cleanup_deduplication_records()
                if deleted:
                    logger.info("Cleaned up %d expired deduplication records", deleted)

            except Exception as e:
                logger.exception("Error in event engine process loop: %s", e)

    # Direct event emission methods for external use

    async def emit_collector_failure(self, collector: str, error: str) -> Event:
        """Emit a collector failure event directly."""
        event = EventCreate(
            server_id=self._server_id,
            event_type=EventType.COLLECTOR_FAILURE,
            severity=EventSeverity.ERROR,
            source=EventSource.COLLECTOR,
            title=f"Collector {collector} failed",
            message=f"Collector '{collector}' reported failure: {error}",
            metadata={"collector": collector, "error": error},
            timestamp=datetime.now(UTC),
        )
        return await self._event_repo.create(event)

    async def emit_collector_recovery(self, collector: str) -> Event:
        """Emit a collector recovery event directly."""
        event = EventCreate(
            server_id=self._server_id,
            event_type=EventType.COLLECTOR_RECOVERY,
            severity=EventSeverity.INFO,
            source=EventSource.COLLECTOR,
            title=f"Collector {collector} recovered",
            message=f"Collector '{collector}' recovered and is running normally",
            metadata={"collector": collector},
            timestamp=datetime.now(UTC),
        )
        return await self._event_repo.create(event)

    async def emit_service_transition(
        self,
        service_name: str,
        old_state: str,
        new_state: str,
    ) -> Event:
        """Emit a service state transition event."""
        if new_state == "failed" and old_state != "failed":
            event_type = EventType.SERVICE_FAILED
            severity = EventSeverity.ERROR
        elif new_state == "active" and old_state in ("inactive", "failed", "activating"):
            event_type = EventType.SERVICE_STARTED
            severity = EventSeverity.INFO
        elif new_state in ("inactive", "deactivating") and old_state == "active":
            event_type = EventType.SERVICE_STOPPED
            severity = EventSeverity.WARNING
        else:
            event_type = EventType.SERVICE_TRANSITION
            severity = EventSeverity.INFO

        event = EventCreate(
            server_id=self._server_id,
            event_type=event_type,
            severity=severity,
            source=EventSource.SERVICE,
            title=f"Service {service_name} {new_state}",
            message=f"Service '{service_name}' transitioned from {old_state} to {new_state}",
            metadata={
                "service": service_name,
                "old_state": old_state,
                "new_state": new_state,
            },
            timestamp=datetime.now(UTC),
        )
        return await self._event_repo.create(event)

    async def emit_system_event(self, event_type: EventType, title: str, message: str, metadata: dict[str, Any] | None = None) -> Event:
        """Emit a generic system event."""
        event = EventCreate(
            server_id=self._server_id,
            event_type=event_type,
            severity=EventSeverity.INFO,
            source=EventSource.SYSTEM,
            title=title,
            message=message,
            metadata=metadata or {},
            timestamp=datetime.now(UTC),
        )
        return await self._event_repo.create(event)


# Global event engine instance
_event_engine: EventEngine | None = None
_event_engine_lock = asyncio.Lock()


async def get_event_engine(
    state_manager: StateManager,
    event_repository: EventRepository,
    db_writer: DatabaseWriter,
    server_id: str = "local",
) -> EventEngine:
    """Get or create the global event engine."""
    global _event_engine
    async with _event_engine_lock:
        if _event_engine is None:
            _event_engine = EventEngine(
                state_manager=state_manager,
                event_repository=event_repository,
                db_writer=db_writer,
                server_id=server_id,
            )
        return _event_engine


async def start_event_engine(
    state_manager: StateManager,
    event_repository: EventRepository,
    db_writer: DatabaseWriter,
    server_id: str = "local",
) -> None:
    """Start the global event engine."""
    engine = await get_event_engine(state_manager, event_repository, db_writer, server_id)
    await engine.start()


async def stop_event_engine() -> None:
    """Stop the global event engine."""
    global _event_engine
    async with _event_engine_lock:
        if _event_engine is not None:
            await _event_engine.stop()
            _event_engine = None
