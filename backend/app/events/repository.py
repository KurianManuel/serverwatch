"""Event repository for database operations."""

import sqlite3
from datetime import UTC, datetime, timedelta

from app.database.connection import _iso_to_unix
from app.database.writer import DatabaseWriter, WritePriority
from app.events.models import (
    Event,
    EventCreate,
    EventQueryParams,
    EventQueryResult,
    EventResponse,
)


class EventRepository:
    """Event repository for database operations.

    Uses the DatabaseWriter for all writes to ensure proper queueing,
    batching, and transaction handling. Implements 24-hour time-bounded
    deduplication using the event_deduplication table.
    """

    DEDUPLICATION_WINDOW_HOURS = 24

    def __init__(self, db_writer: DatabaseWriter) -> None:
        self._db_writer = db_writer

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        """Convert a database row to an Event model."""
        return Event(
            id=row["id"],
            server_id=row["server_id"],
            timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if isinstance(row["timestamp"], str)
            else row["timestamp"],
            event_type=row["event_type"],
            severity=row["severity"],
            source=row["source"],
            title=row["title"],
            message=row["message"] or "",
            metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
            fingerprint=row["fingerprint"],
        )

    async def create(self, event: Event | EventCreate) -> Event:
        """Create a new event with 24-hour time-bounded deduplication.

        Uses DatabaseWriter's atomic execution to ensure event insertion
        and deduplication record creation happen in a single transaction.

        Args:
            event: The event to create (Event or EventCreate).

        Returns:
            The created or existing event with its database ID.

        Raises:
            RuntimeError: If queue full or transaction fails (retryable).
        """
        event.set_fingerprint()

        enqueued, future = await self._db_writer.execute_atomic(
            lambda conn: self._create_event_transaction(conn, event),
            priority=WritePriority.HIGH,
        )

        if not enqueued:
            raise RuntimeError("Event queue full, write rejected")

        result = await future

        if result is False:
            raise RuntimeError("Event transaction failed, retryable")

        if isinstance(result, Event):
            return result

        if result is None:
            # fingerprint is guaranteed to be set after event.set_fingerprint()
            return await self._fetch_existing_event(event.fingerprint or "", event.server_id)

        raise RuntimeError(f"Unexpected transaction result: {result}")

    def _create_event_transaction(self, conn: sqlite3.Connection, event: Event | EventCreate) -> Event | None | bool:
        """Atomic transaction: check dedup, insert event + dedup record.

        Returns:
            Event if created, None if duplicate within window, False on error.
        """

        cutoff_time = datetime.now(UTC) - timedelta(hours=self.DEDUPLICATION_WINDOW_HOURS)
        cutoff_str = cutoff_time.isoformat().replace("+00:00", "Z")
        now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        # Check for existing deduplication record within 24-hour window
        cursor = conn.execute(
            """
            SELECT fingerprint FROM event_deduplication
            WHERE fingerprint = ? AND server_id = ? AND created_at >= ?
            """,
            (event.fingerprint, event.server_id, cutoff_str),
        )
        existing_dedup = cursor.fetchone()

        if existing_dedup:
            return None  # Duplicate within window

        # Try to insert dedup record (atomic check)
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO event_deduplication (fingerprint, server_id, created_at)
            VALUES (?, ?, ?)
            """,
            (event.fingerprint, event.server_id, now_str),
        )

        if cursor.rowcount == 0:
            # Dedup record exists - check if within window
            cursor = conn.execute(
                """
                SELECT created_at FROM event_deduplication
                WHERE fingerprint = ? AND server_id = ?
                """,
                (event.fingerprint, event.server_id),
            )
            row = cursor.fetchone()
            if row:
                existing_created_at = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                if existing_created_at >= cutoff_time:
                    return None  # Within window - duplicate
                else:
                    # Outside window - delete old record and proceed
                    conn.execute(
                        "DELETE FROM event_deduplication WHERE fingerprint = ? AND server_id = ?",
                        (event.fingerprint, event.server_id),
                    )

        # Insert the event
        cursor = conn.execute(
            """
            INSERT INTO events
            (server_id, timestamp, event_type, severity, source, title, message, metadata, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.server_id,
                event.timestamp.isoformat().replace("+00:00", "Z"),
                event.event_type.value,
                event.severity.value,
                event.source.value,
                event.title,
                event.message,
                event.metadata_json,
                event.fingerprint,
            ),
        )

        if cursor.rowcount > 0:
            event_id = cursor.lastrowid
            return Event(
                id=event_id,
                server_id=event.server_id,
                timestamp=event.timestamp,
                event_type=event.event_type,
                severity=event.severity,
                source=event.source,
                title=event.title,
                message=event.message,
                metadata=event.metadata,
                fingerprint=event.fingerprint,
            )

        return False

    async def _fetch_existing_event(self, fingerprint: str, server_id: str) -> Event:
        """Fetch existing event by fingerprint (fallback)."""
        db_path = self._db_writer._db_config.db_path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT id, server_id, timestamp, event_type, severity, source,
                       title, message, metadata, fingerprint
                FROM events
                WHERE fingerprint = ? AND server_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (fingerprint, server_id),
            )
            row = cursor.fetchone()
            if row is not None:
                return self._row_to_event(row)
        finally:
            conn.close()
        raise RuntimeError("Deduplication indicated but event not found")

    async def get_by_id(self, event_id: int) -> Event | None:
        """Get an event by its ID."""
        db_path = self._db_writer._db_config.db_path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT id, server_id, timestamp, event_type, severity, source,
                       title, message, metadata, fingerprint
                FROM events
                WHERE id = ?
                """,
                (event_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_event(row)
        finally:
            conn.close()

    async def query(self, params: "EventQueryParams") -> "EventQueryResult":
        """Query events with filtering and pagination."""
        from app.events.models import EventQueryParams, EventQueryResult

        if not isinstance(params, EventQueryParams):
            params = EventQueryParams(**params)

        conditions = ["server_id = ?"]
        params_list = [params.server_id]

        if params.event_type:
            conditions.append("event_type = ?")
            params_list.append(params.event_type.value)

        if params.severity:
            conditions.append("severity = ?")
            params_list.append(params.severity.value)

        if params.source:
            conditions.append("source = ?")
            params_list.append(params.source.value)

        if params.start_time:
            conditions.append("timestamp >= ?")
            params_list.append(params.start_time.isoformat().replace("+00:00", "Z"))

        if params.end_time:
            conditions.append("timestamp <= ?")
            params_list.append(params.end_time.isoformat().replace("+00:00", "Z"))

        where_clause = " AND ".join(conditions)

        db_path = self._db_writer._db_config.db_path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Get total count
            count_cursor = conn.execute(
                f"SELECT COUNT(*) FROM events WHERE {where_clause}",
                params_list,
            )
            total = count_cursor.fetchone()[0]

            # Get paginated results
            cursor = conn.execute(
                f"""
                SELECT id, server_id, timestamp, event_type, severity, source,
                       title, message, metadata, fingerprint
                FROM events
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                params_list + [params.limit, params.offset],
            )

            events = [self._row_to_event(row) for row in cursor.fetchall()]

            return EventQueryResult(
                events=[EventResponse.model_validate(e) for e in events],
                total=total,
                limit=params.limit,
                offset=params.offset,
                has_more=(params.offset + params.limit) < total,
            )
        finally:
            conn.close()

    async def count(self, server_id: str, start: datetime, end: datetime) -> int:
        """Count events in a time range."""
        db_path = self._db_writer._db_config.db_path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE server_id = ? AND timestamp >= ? AND timestamp <= ?
                """,
                (server_id, start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")),
            )
            count = cursor.fetchone()[0]
            return int(count) if count is not None else 0
        finally:
            conn.close()

    async def delete_old(self, cutoff: datetime) -> int:
        """Delete events older than the cutoff timestamp.

        Also cleans up corresponding deduplication records.

        Returns the number of rows deleted.
        """
        deleted = 0
        while deleted < 1000:  # Batch size limit
            db_path = self._db_writer._db_config.db_path
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    """
                    DELETE FROM events
                    WHERE id IN (
                        SELECT id FROM events
                        WHERE _iso_to_unix(timestamp) < ?
                        LIMIT ?
                    )
                    """,
                    (int(cutoff.timestamp()), 1000),
                )
                deleted_batch = cursor.rowcount
                deleted += deleted_batch
                if deleted_batch == 0:
                    break
            finally:
                conn.close()
        return deleted

    async def cleanup_deduplication_records(self) -> int:
        """Clean up deduplication records older than 24 hours.

        Returns the number of rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=self.DEDUPLICATION_WINDOW_HOURS)
        db_path = self._db_writer._db_config.db_path
        # Use isolation_level=None for autocommit mode
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # Register helper function for timestamp conversion
        conn.create_function("_iso_to_unix", 1, _iso_to_unix)
        try:
            cursor = conn.execute(
                """
                DELETE FROM event_deduplication
                WHERE _iso_to_unix(created_at) < ?
                """,
                (int(cutoff.timestamp()),),
            )
            deleted = cursor.rowcount
            return deleted
        finally:
            conn.close()
