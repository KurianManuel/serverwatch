"""Journald reader - reads structured journal entries and converts to events."""

import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

try:
    from systemd import journal  # type: ignore[import-not-found]
except ImportError:
    journal = None

# Allow tests to inject a mock journal module
_journal_module = journal


def set_journal_module(module: Any) -> None:
    """Set the journal module (for testing)."""
    global _journal_module
    _journal_module = module


def get_journal_module() -> Any:
    """Get the journal module (real or mock)."""
    return _journal_module

from app.config import settings
from app.database.writer import DatabaseWriter, WritePriority
from app.events.models import (
    Event,
    EventCreate,
    EventSeverity,
    EventSource,
    EventType,
)
from app.events.repository import EventRepository

logger = logging.getLogger(__name__)


# Journal priority mapping (systemd uses 0-7, we use standard syslog priorities)
_JOURNAL_PRIORITY_TO_SEVERITY = {
    0: EventSeverity.CRITICAL,  # emerg
    1: EventSeverity.CRITICAL,  # alert
    2: EventSeverity.CRITICAL,  # crit
    3: EventSeverity.ERROR,     # err
    4: EventSeverity.WARNING,   # warning
    5: EventSeverity.INFO,      # notice
    6: EventSeverity.INFO,      # info
    7: EventSeverity.INFO,      # debug
}


def _journal_priority_to_severity(priority: int) -> EventSeverity:
    """Map journal priority (0-7) to EventSeverity."""
    return _JOURNAL_PRIORITY_TO_SEVERITY.get(priority, EventSeverity.INFO)


def _journal_entry_to_event(
    entry: dict[str, Any],
    server_id: str,
) -> EventCreate | None:
    """Convert a journal entry to an EventCreate.

    Returns None if the entry should be skipped.
    """
    # Skip entries without a message
    message = entry.get("MESSAGE", "").strip()
    if not message:
        return None

    # Get priority and map to severity
    priority = entry.get("PRIORITY")
    try:
        priority_int = int(priority) if priority is not None else 6
    except (ValueError, TypeError):
        priority_int = 6
    severity = _journal_priority_to_severity(priority_int)

    # Get unit name (systemd service unit)
    unit = entry.get("_SYSTEMD_UNIT", entry.get("UNIT", "unknown"))

    # Get timestamp
    # Journal entries have __REALTIME_TIMESTAMP in microseconds since epoch
    ts_usec = entry.get("__REALTIME_TIMESTAMP")
    if ts_usec is not None:
        try:
            timestamp = datetime.fromtimestamp(int(ts_usec) / 1_000_000, tz=UTC)
        except (ValueError, TypeError):
            timestamp = datetime.now(UTC)
    else:
        timestamp = datetime.now(UTC)

    # Get cursor for deduplication/checkpointing
    cursor = entry.get("__CURSOR", "")

    # Build metadata with useful journal fields
    metadata: dict[str, Any] = {
        "cursor": cursor,
        "unit": unit,
        "priority": priority_int,
        "priority_name": _priority_to_name(priority_int),
    }

    # Add optional fields if present
    for key in ("_PID", "_UID", "_GID", "_COMM", "_EXE", "_CMDLINE", "_SYSTEMD_CGROUP", "_SYSTEMD_SLICE"):
        if key in entry:
            metadata[key.lower().lstrip("_")] = entry[key]

    # Determine event type based on priority and unit
    event_type = _determine_event_type(priority_int, unit)

    # Truncate message if too long
    message_truncated = message[:4096]

    return EventCreate(
        server_id=server_id,
        event_type=event_type,
        severity=severity,
        source=EventSource.JOURNALD,
        title=f"Journal: {unit}",
        message=message_truncated,
        metadata=metadata,
        timestamp=datetime.now(UTC),
    )


def _priority_to_name(priority: int) -> str:
    """Map journal priority to name."""
    names = {
        0: "emerg",
        1: "alert",
        2: "crit",
        3: "err",
        4: "warning",
        5: "notice",
        6: "info",
        7: "debug",
    }
    return names.get(priority, "unknown")


def _determine_event_type(priority: int, unit: str) -> EventType:
    """Determine event type based on priority and unit."""
    # High priority system events
    if priority <= 3:  # emerg, alert, crit, err
        if "systemd" in unit or "kernel" in unit.lower():
            return EventType.SYSTEM_START  # closest match for critical system events
        return EventType.SERVICE_FAILED  # treat as service failure

    # Service-related events
    if priority == 4:  # warning
        return EventType.SERVICE_TRANSITION

    return EventType.SERVICE_TRANSITION


class JournalReader:
    """Reads journal entries and converts them to events.

    Uses systemd.journal for structured journal access.
    Implements cursor-based incremental reading with checkpointing.
    """

    def __init__(
        self,
        event_repository: EventRepository,
        db_writer: DatabaseWriter,
        server_id: str = "local",
        units: list[str] | None = None,
        priority: int = 6,
        max_entries_per_poll: int = 100,
        seek_tail: int = 100,
        journal_module: Any | None = None,
    ) -> None:
        self._event_repo = event_repository
        self._db_writer = db_writer
        self._server_id = server_id
        self._units = units or []
        self._priority = max(0, min(7, priority))
        self._max_entries = max(1, min(1000, max_entries_per_poll))
        self._seek_tail = max(0, min(10000, seek_tail))
        self._journal_module = journal_module or _journal_module

        self._running = False
        self._reader_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._cursor: str | None = None
        self._processed_count = 0
        self._failed_count = 0
        self._dropped_count = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cursor(self) -> str | None:
        return self._cursor

    @property
    def processed_count(self) -> int:
        return self._processed_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    async def start(self) -> None:
        """Start the journal reader."""
        if self._running:
            return

        if not settings.journal_enabled:
            logger.info("Journald integration disabled in configuration")
            return

        if self._journal_module is None:
            logger.warning("systemd-python not available, journal reader disabled")
            return

        self._running = True
        self._shutdown_event.clear()

        # Initialize journal reader
        try:
            self._journal_reader = self._journal_module.Reader()
            self._journal_reader.this_boot_only()
            self._journal_reader.log_level(self._priority)

            # Add unit filters if specified
            for unit in self._units:
                self._journal_reader.add_match(_SYSTEMD_UNIT=unit)

            # Seek to tail on startup
            if self._seek_tail > 0:
                self._journal_reader.seek_tail()
                for _ in range(self._seek_tail):
                    if self._journal_reader.get_previous() is None:
                        break
            else:
                # Seek to end (only process new entries)
                self._journal_reader.seek_tail()
                self._journal_reader.get_previous()

            # Save initial cursor
            self._cursor = self._journal_reader.get_cursor()

        except Exception as e:
            logger.error("Failed to initialize journal reader: %s", e)
            self._running = False
            raise

        # Start background reader task
        self._reader_task = asyncio.create_task(self._reader_loop(), name="serverwatch-journal-reader")

    async def stop(self) -> None:
        """Stop the journal reader."""
        if not self._running:
            return

        self._shutdown_event.set()
        self._running = False

        # Wait for reader task to finish
        if self._reader_task:
            try:
                await asyncio.wait_for(self._reader_task, timeout=10.0)
            except TimeoutError:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass

        # Save final cursor
        try:
            if hasattr(self, "_journal_reader"):
                self._cursor = self._journal_reader.get_cursor()
        except Exception:
            pass

        logger.info(
            "Journal reader stopped: processed=%d, failed=%d, dropped=%d",
            self._processed_count,
            self._failed_count,
            self._dropped_count,
        )

    async def _reader_loop(self) -> None:
        """Main reader loop - polls journal for new entries."""
        while self._running:
            try:
                # Wait for shutdown or poll interval
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=settings.journal_interval)
                except TimeoutError:
                    pass

                if not self._running:
                    break

                # Process new entries
                await self._process_entries()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in journal reader loop: %s", e)
                await asyncio.sleep(1.0)  # Back off on error

    async def _process_entries(self) -> None:
        """Process new journal entries up to max_entries_per_poll."""
        processed = 0

        try:
            while processed < self._max_entries:
                # Check for shutdown
                if not self._running:
                    break

                # Get next entry
                entry = self._journal_reader.get_next()
                if entry is None:
                    # No more entries, update cursor and break
                    self._cursor = self._journal_reader.get_cursor()
                    break

                # Convert to event
                event = _journal_entry_to_event(entry, self._server_id)
                if event is None:
                    continue

                # Persist event
                try:
                    await self._event_repo.create(event)
                    self._processed_count += 1
                    processed += 1
                except RuntimeError as e:
                    # Queue full or transaction failure
                    self._failed_count += 1
                    logger.warning("Failed to persist journal event: %s", e)
                except Exception as e:
                    self._failed_count += 1
                    logger.exception("Unexpected error persisting journal event: %s", e)

        except Exception as e:
            logger.exception("Error processing journal entries: %s", e)

        finally:
            # Always update cursor
            try:
                self._cursor = self._journal_reader.get_cursor()
            except Exception:
                pass

    def get_stats(self) -> dict[str, Any]:
        """Get reader statistics."""
        return {
            "running": self._running,
            "cursor": self._cursor,
            "processed": self._processed_count,
            "failed": self._failed_count,
            "dropped": self._dropped_count,
            "units": self._units,
            "priority": self._priority,
        }


# Global journal reader instance
_journal_reader: JournalReader | None = None
_journal_lock = asyncio.Lock()


async def get_journal_reader(
    event_repository: EventRepository,
    db_writer: DatabaseWriter,
    server_id: str = "local",
) -> JournalReader:
    """Get or create the global journal reader."""
    global _journal_reader
    async with _journal_lock:
        if _journal_reader is None:
            _journal_reader = JournalReader(
                event_repository=event_repository,
                db_writer=db_writer,
                server_id=server_id,
                units=settings.journal_units,
                priority=settings.journal_priority,
                max_entries_per_poll=settings.journal_max_entries_per_poll,
                seek_tail=settings.journal_seek_tail,
            )
        return _journal_reader


async def start_journal_reader(
    event_repository: EventRepository,
    db_writer: DatabaseWriter,
    server_id: str = "local",
) -> None:
    """Start the global journal reader."""
    reader = await get_journal_reader(event_repository, db_writer, server_id)
    await reader.start()


async def stop_journal_reader() -> None:
    """Stop the global journal reader."""
    global _journal_reader
    async with _journal_lock:
        if _journal_reader is not None:
            await _journal_reader.stop()
            _journal_reader = None