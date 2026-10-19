"""Database writer - batched persistence on dedicated thread."""

import asyncio
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any

from app.database.config import DBConfig, get_db_config
from app.database.connection import _apply_pragmas

# Valid table names for SQL injection prevention
VALID_TABLES = {
    "servers",
    "cpu_samples",
    "memory_samples",
    "disk_samples",
    "network_samples",
    "filesystem_samples",
    "temperature_samples",
    "events",
    "alerts",
    "metric_rollups",
}

# Valid columns per table (for validation)
# MUST match the schema in migrations.py exactly
VALID_COLUMNS = {
    "servers": {
        "id", "hostname", "display_name", "os_name", "os_version",
        "kernel_version", "architecture", "created_at", "updated_at"
    },
    "cpu_samples": {
        "id", "server_id", "timestamp", "total_utilization", "per_core",
        "load_1min", "load_5min", "load_15min", "cpu_count"
    },
    "memory_samples": {
        "id", "server_id", "timestamp", "total_bytes", "available_bytes",
        "used_bytes", "free_bytes", "buffers_bytes", "cached_bytes",
        "swap_total_bytes", "swap_used_bytes", "swap_free_bytes"
    },
    "disk_samples": {
        "id", "server_id", "timestamp", "device", "read_bytes", "write_bytes",
        "read_ops", "write_ops", "read_throughput", "write_throughput", "iops"
    },
    "network_samples": {
        "id", "server_id", "timestamp", "interface", "rx_bytes", "tx_bytes",
        "rx_packets", "tx_packets", "rx_errors", "tx_errors", "rx_drops", "tx_drops"
    },
    "filesystem_samples": {
        "id", "server_id", "timestamp", "mount_point", "device", "fstype",
        "total_bytes", "free_bytes", "available_bytes", "used_bytes",
        "used_percent", "inodes_total", "inodes_free"
    },
    "temperature_samples": {
        "id", "server_id", "timestamp", "sensor_name", "sensor_label",
        "temperature_celsius", "high_threshold", "critical_threshold"
    },
    "events": {
        "id", "server_id", "timestamp", "event_type", "severity", "source",
        "title", "message", "metadata"
    },
    "alerts": {
        "id", "server_id", "rule_id", "state", "severity", "condition",
        "current_value", "threshold", "first_seen", "last_seen",
        "acknowledged_at", "acknowledged_by", "resolved_at"
    },
    "metric_rollups": {
        "id", "server_id", "metric_name", "interval_type", "window_start",
        "window_end", "count", "min_value", "avg_value", "max_value"
    },
}


class WritePriority(IntEnum):
    """Write priority levels. Higher value = higher priority."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass(order=True)
class WriteTask:
    """A single database write task."""
    sort_key: tuple[int, int] = field(init=False, compare=True)
    priority: WritePriority
    sequence: int
    table: str
    data: dict[str, Any]
    future: asyncio.Future[bool] | None = field(default=None, compare=False)
    timestamp: datetime = field(default_factory=datetime.utcnow, compare=False)

    def __post_init__(self) -> None:
        # Negative priority for max-heap behavior (higher priority first)
        # Sequence ensures FIFO within same priority
        self.sort_key = (-self.priority.value, self.sequence)


@dataclass
class WriterMetrics:
    """Runtime metrics for the database writer."""
    enqueued: int = 0
    successful: int = 0
    failed: int = 0
    dropped: int = 0
    last_error: str | None = None
    last_error_time: datetime | None = None


class DatabaseWriter:
    """
    Dedicated thread for batched SQLite persistence.

    Producers submit writes via the async `write()` method which enqueues
    to a thread-safe bounded queue. The writer thread processes tasks in
    priority order, batching them into transactions.

    Returns True if the task was successfully enqueued.
    Write failures are recorded in metrics, not returned from write().
    """

    def __init__(
        self,
        db_config: DBConfig | None = None,
        queue_size: int = 1000,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        shutdown_drain_timeout: float = 5.0,
    ) -> None:
        self._db_config = db_config or get_db_config()
        self._queue: queue.PriorityQueue[WriteTask] = queue.PriorityQueue(maxsize=queue_size)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._shutdown_drain_timeout = shutdown_drain_timeout

        self._running = False
        self._shutdown_event = threading.Event()
        self._drain_complete = threading.Event()
        self._writer_thread: threading.Thread | None = None
        self._sequence_counter = 0
        self._sequence_lock = threading.Lock()
        self._metrics = WriterMetrics()
        self._metrics_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        # Lock for queue mutations that must be atomic (eviction/rebuild)
        self._queue_lock = threading.Lock()

    def start(self) -> None:
        """Start the writer thread."""
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._drain_complete.clear()
        # Event loop captured lazily on first write()
        self._writer_thread = threading.Thread(target=self._writer_loop, name="serverwatch-db-writer", daemon=False)
        self._writer_thread.start()

    def stop(self, timeout: float | None = None) -> bool:
        """
        Stop the writer thread and drain pending work.

        Args:
            timeout: Maximum time to wait for drain. Defaults to configured drain timeout.

        Returns:
            True if all pending work was drained, False if timeout occurred.
        """
        if not self._running and self._writer_thread is None:
            return True

        self._running = False
        self._shutdown_event.set()

        drain_timeout = timeout if timeout is not None else self._shutdown_drain_timeout
        drained = self._drain_complete.wait(timeout=drain_timeout)

        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1.0)

        self._writer_thread = None
        self._loop = None
        return drained

    async def write(
        self,
        table: str,
        data: dict[str, Any],
        priority: WritePriority = WritePriority.NORMAL,
        timeout: float = 1.0,
    ) -> tuple[bool, asyncio.Future[bool]]:
        """
        Enqueue a write task.

        Args:
            table: Target table name.
            data: Column-value mapping for INSERT.
            priority: Write priority for queue ordering.
            timeout: Maximum time to wait for queue space (not used, kept for API compatibility).

        Returns:
            Tuple of (enqueued: bool, future: asyncio.Future[bool]).
            enqueued is True if enqueued successfully, False if queue full or writer stopped.
            future resolves to True if the write commits, False if it fails or is rolled back.
            Write failures are recorded in metrics, not returned here.
        """
        if not self._running:
            fut = self._loop.create_future() if self._loop else asyncio.get_running_loop().create_future()
            fut.set_result(False)
            return False, fut

        # Capture event loop on first write
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        # Validate table and columns
        if not self._validate_table_and_columns(table, data):
            self._record_drop()
            fut = self._loop.create_future()
            fut.set_result(False)
            return False, fut

        task = WriteTask(
            priority=priority,
            sequence=self._next_sequence(),
            table=table,
            data=data,
            future=self._loop.create_future(),
        )

        try:
            # Direct call - put_nowait is non-blocking
            self._enqueue_task(task)
        except queue.Full:
            self._record_drop()
            if task.future and not task.future.done():
                task.future.set_result(False)
            return False, task.future  # type: ignore[return-value]

        self._record_enqueued()
        return True, task.future  # type: ignore[return-value]

    def _validate_table_and_columns(self, table: str, data: dict[str, Any]) -> bool:
        """Validate table name and column names against allowlist."""
        if table not in VALID_TABLES:
            return False
        valid_cols = VALID_COLUMNS.get(table, set())
        for col in data.keys():
            if col not in valid_cols:
                return False
        return True

    def _enqueue_task(self, task: WriteTask) -> None:
        """Enqueue task with priority-based eviction when full."""
        # Fast path: try non-blocking put
        try:
            self._queue.put_nowait(task)
            return
        except queue.Full:
            pass

        # Slow path: queue full, need eviction logic - must be atomic
        with self._queue_lock:
            # Re-check queue state after acquiring lock
            try:
                self._queue.put_nowait(task)
                return
            except queue.Full:
                pass

            # Queue full - try to evict lowest priority task if new task has higher priority
            if task.priority <= WritePriority.NORMAL:
                raise queue.Full("Queue full and priority not high enough for eviction") from None

            # Priority queue doesn't support direct inspection of lowest priority item.
            # Drain queue, remove lowest priority, re-insert remaining + new task.
            items: list[WriteTask] = []
            while not self._queue.empty():
                try:
                    items.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            if not items:
                raise queue.Full("Queue full") from None

            # Find item with lowest priority (highest sort_key since negative priority)
            lowest_idx = max(range(len(items)), key=lambda i: items[i].sort_key)
            evicted = items.pop(lowest_idx)

            # Mark evicted task as failed - use thread-safe call_soon_threadsafe
            if evicted.future and not evicted.future.done() and self._loop:
                self._loop.call_soon_threadsafe(evicted.future.set_result, False)
            self._record_drop()

            # Re-insert remaining items
            for item in items:
                self._queue.put_nowait(item)

            # Insert new higher-priority task
            self._queue.put_nowait(task)

    def _next_sequence(self) -> int:
        with self._sequence_lock:
            self._sequence_counter += 1
            return self._sequence_counter

    def _record_enqueued(self) -> None:
        with self._metrics_lock:
            self._metrics.enqueued += 1

    def _record_success(self) -> None:
        with self._metrics_lock:
            self._metrics.successful += 1

    def _record_failure(self, error: str) -> None:
        with self._metrics_lock:
            self._metrics.failed += 1
            self._metrics.last_error = error
            self._metrics.last_error_time = datetime.utcnow()

    def _record_drop(self) -> None:
        with self._metrics_lock:
            self._metrics.dropped += 1

    def get_metrics(self) -> WriterMetrics:
        """Get a snapshot of current metrics."""
        with self._metrics_lock:
            return WriterMetrics(
                enqueued=self._metrics.enqueued,
                successful=self._metrics.successful,
                failed=self._metrics.failed,
                dropped=self._metrics.dropped,
                last_error=self._metrics.last_error,
                last_error_time=self._metrics.last_error_time,
            )

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def is_healthy(self) -> bool:
        return self._running and self.queue_depth < self._queue.maxsize * 0.9

    def _writer_loop(self) -> None:
        """Main writer thread loop."""
        conn: sqlite3.Connection | None = None
        try:
            conn = self._open_connection()
            self._process_loop(conn)
        except Exception as e:
            self._record_failure(f"Writer thread fatal error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            self._drain_complete.set()

    def _open_connection(self) -> sqlite3.Connection:
        """Open a new database connection with PRAGMAs."""
        conn = sqlite3.connect(self._db_config.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        _apply_pragmas(conn)
        return conn

    def _process_loop(self, conn: sqlite3.Connection) -> None:
        """Process tasks from the queue in batches."""
        last_flush = time.monotonic()

        while self._running or not self._queue.empty():
            # Check for shutdown signal
            if self._shutdown_event.is_set() and self._queue.empty():
                break

            # Collect batch
            batch = self._collect_batch()
            if not batch:
                # No work available, wait briefly
                time.sleep(min(0.1, self._flush_interval))
                continue

            # Process batch
            self._flush_batch(conn, batch)

            # Periodic flush even if batch not full
            now = time.monotonic()
            if now - last_flush >= self._flush_interval:
                last_flush = now

    def _collect_batch(self) -> list[WriteTask]:
        """Collect up to batch_size tasks from the queue.

        Acquires _queue_lock to synchronize with eviction logic.
        """
        batch: list[WriteTask] = []
        deadline = time.monotonic() + self._flush_interval

        with self._queue_lock:
            while len(batch) < self._batch_size:
                try:
                    # Non-blocking get with short timeout to check shutdown
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    task = self._queue.get(timeout=min(0.1, remaining))
                    batch.append(task)
                except queue.Empty:
                    break

        return batch

    def _flush_batch(self, conn: sqlite3.Connection, batch: list[WriteTask]) -> None:
        """Execute a batch of writes in a single transaction.

        All tasks in the batch succeed or fail together (atomic).
        """
        if not batch:
            return

        try:
            conn.execute("BEGIN IMMEDIATE TRANSACTION;")
            # Execute all inserts first - if any fails, we rollback
            for task in batch:
                self._execute_insert(conn, task.table, task.data)
            # All inserts succeeded - commit
            conn.execute("COMMIT;")
            # Now mark all tasks as successful
            for task in batch:
                self._resolve_future(task, True)
                self._record_success()
        except Exception as e:
            # Any failure - rollback entire transaction
            try:
                conn.execute("ROLLBACK;")
            except sqlite3.OperationalError:
                pass
            error_msg = f"Transaction failed: {e}"
            # Record failure for EACH task in the batch (atomic rollback)
            for _ in batch:
                self._record_failure(error_msg)
            for task in batch:
                self._resolve_future(task, False)

    def _resolve_future(self, task: WriteTask, result: bool) -> None:
        """Thread-safely resolve the task's future."""
        if task.future and not task.future.done() and self._loop:
            self._loop.call_soon_threadsafe(task.future.set_result, result)

    def _execute_insert(self, conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> None:
        """Execute a single INSERT statement with validated identifiers."""
        # Table and columns already validated in write()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        values = tuple(data.values())
        # Use INSERT OR REPLACE for metric_rollups to handle idempotency
        if table == "metric_rollups":
            conn.execute(f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})", values)
        else:
            conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values)


# Global writer instance (lazy initialization)
_db_writer: DatabaseWriter | None = None
_db_writer_lock = threading.Lock()


def get_db_writer() -> DatabaseWriter:
    """Get or create the global database writer instance."""
    global _db_writer
    with _db_writer_lock:
        if _db_writer is None:
            config = get_db_config()
            _db_writer = DatabaseWriter(
                db_config=config,
                queue_size=config.queue_size,
                batch_size=config.batch_size,
                flush_interval=config.flush_interval,
            )
        return _db_writer


async def start_db_writer() -> None:
    """Start the global database writer."""
    writer = get_db_writer()
    writer.start()


async def stop_db_writer(timeout: float | None = None) -> bool:
    """Stop the global database writer."""
    global _db_writer
    with _db_writer_lock:
        if _db_writer is not None:
            result = _db_writer.stop(timeout)
            _db_writer = None
            return result
    return True
