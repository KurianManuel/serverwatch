"""Metric rollup processor - aggregates raw samples into rollups and manages retention."""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from app.database.config import DBConfig, get_db_config
from app.database.connection import database_connection
from app.database.writer import DatabaseWriter, WritePriority


@dataclass(frozen=True)
class RollupConfig:
    """Configuration for a single rollup interval."""
    interval_type: str
    interval_seconds: int
    source_interval_type: str | None  # If None, source is raw samples


@dataclass
class RollupDefinition:
    """Defines a metric to roll up."""
    metric_name: str
    source_table: str
    source_column: str
    # Optional: filter for device/interface/mount_point/sensor_name
    dimension_column: str | None = None


# Rollup interval hierarchy (from finest to coarsest)
ROLLUP_INTERVALS: list[RollupConfig] = [
    RollupConfig("1m", 60, None),       # Raw samples -> 1m
    RollupConfig("5m", 300, "1m"),      # 1m rollups -> 5m
    RollupConfig("1h", 3600, "5m"),     # 5m rollups -> 1h
    RollupConfig("1d", 86400, "1h"),    # 1h rollups -> 1d
]

# Metrics to roll up (metric_name, source_table, source_column, dimension_column)
ROLLUP_DEFINITIONS: list[RollupDefinition] = [
    # CPU
    RollupDefinition("cpu.total_utilization", "cpu_samples", "total_utilization"),
    RollupDefinition("cpu.load_1min", "cpu_samples", "load_1min"),
    RollupDefinition("cpu.load_5min", "cpu_samples", "load_5min"),
    RollupDefinition("cpu.load_15min", "cpu_samples", "load_15min"),
    # Memory
    RollupDefinition("memory.total_bytes", "memory_samples", "total_bytes"),
    RollupDefinition("memory.available_bytes", "memory_samples", "available_bytes"),
    RollupDefinition("memory.used_bytes", "memory_samples", "used_bytes"),
    RollupDefinition("memory.swap_used_bytes", "memory_samples", "swap_used_bytes"),
    # Disk (per device)
    RollupDefinition("disk.read_bytes", "disk_samples", "read_bytes", "device"),
    RollupDefinition("disk.write_bytes", "disk_samples", "write_bytes", "device"),
    RollupDefinition("disk.read_ops", "disk_samples", "read_ops", "device"),
    RollupDefinition("disk.write_ops", "disk_samples", "write_ops", "device"),
    RollupDefinition("disk.read_throughput", "disk_samples", "read_throughput", "device"),
    RollupDefinition("disk.write_throughput", "disk_samples", "write_throughput", "device"),
    RollupDefinition("disk.iops", "disk_samples", "iops", "device"),
    # Network (per interface)
    RollupDefinition("network.rx_bytes", "network_samples", "rx_bytes", "interface"),
    RollupDefinition("network.tx_bytes", "network_samples", "tx_bytes", "interface"),
    RollupDefinition("network.rx_packets", "network_samples", "rx_packets", "interface"),
    RollupDefinition("network.tx_packets", "network_samples", "tx_packets", "interface"),
    # Filesystem (per mount_point)
    RollupDefinition("filesystem.used_percent", "filesystem_samples", "used_percent", "mount_point"),
    RollupDefinition("filesystem.total_bytes", "filesystem_samples", "total_bytes", "mount_point"),
    RollupDefinition("filesystem.used_bytes", "filesystem_samples", "used_bytes", "mount_point"),
    # Temperature (per sensor)
    RollupDefinition("temperature.temperature_celsius", "temperature_samples", "temperature_celsius", "sensor_name"),
]


def _iso_to_unix(ts_str: str) -> int:
    """Convert ISO timestamp string to Unix timestamp (seconds)."""
    # Handle "2026-10-18T10:00:00Z" or "2026-10-18T10:00:00.123Z" or "2026-10-18T10:00:00+00:00"
    ts_str = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts_str)
    return int(dt.timestamp())


def _unix_to_iso(ts: int) -> str:
    """Convert Unix timestamp to ISO format with Z suffix."""
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _align_to_interval(ts: int, interval_seconds: int) -> int:
    """Align timestamp to interval boundary (floor)."""
    return (ts // interval_seconds) * interval_seconds


class RollupProcessor:
    """
    Background processor that aggregates raw samples into rollups
    and manages retention cleanup.
    """

    def __init__(
        self,
        db_writer: DatabaseWriter,
        db_config: DBConfig | None = None,
        server_id: str = "local",
        rollup_interval: float = 60.0,
        max_batches_per_cycle: int = 100,
        retention_batch_size: int = 1000,
    ) -> None:
        self._db_writer = db_writer
        self._db_config = db_config or get_db_config()
        self._server_id = server_id
        self._rollup_interval = rollup_interval
        self._max_batches_per_cycle = max_batches_per_cycle
        self._retention_batch_size = retention_batch_size

        self._running = False
        self._rollup_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._failure_count = 0
        self._max_consecutive_failures = 10

        # Track committed rollups: (metric_name, interval_type) -> highest committed window_end timestamp
        # Only windows <= this value have durably committed rollups
        self._committed_windows: dict[tuple[str, str], float] = {}
        # Track pending write futures for commit confirmation
        self._pending_futures: list[asyncio.Future[bool]] = []
        # Type ignore for mypy - we reassign this variable with a set later
        # self._pending_futures: list[asyncio.Future[bool]] | set[asyncio.Future[bool]] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def start(self) -> None:
        """Start the rollup processor."""
        if self._running:
            return

        self._running = True
        self._failure_count = 0
        self._shutdown_event.clear()
        self._rollup_task = asyncio.create_task(self._rollup_loop(), name="serverwatch-rollup")

    async def stop(self) -> None:
        """Stop the rollup processor."""
        if not self._running:
            return

        # Signal shutdown
        self._shutdown_event.set()
        self._running = False

        # Do final processing synchronously before waiting for task
        # This ensures pending rollups are processed even if the task hasn't run yet
        try:
            await self._process_rollups(shutdown=True)
            commits_confirmed = await self._wait_for_pending_commits()
            if commits_confirmed:
                await self._process_retention()
            # If commits not confirmed, skip retention (fail closed)
        except Exception:
            pass

        # Wait for rollup task to finish
        if self._rollup_task:
            try:
                await asyncio.wait_for(self._rollup_task, timeout=10.0)
            except TimeoutError:
                self._rollup_task.cancel()
                try:
                    await self._rollup_task
                except asyncio.CancelledError:
                    pass

    async def _rollup_loop(self) -> None:
        """Main rollup loop - runs at configured interval."""
        while self._running:
            try:
                # Wait for either shutdown event or rollup interval
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=self._rollup_interval)
                except TimeoutError:
                    # Normal interval expiry - continue to process
                    pass

                await self._process_rollups()
                # Wait for all pending rollup writes to commit before running retention
                commits_confirmed = await self._wait_for_pending_commits()
                if commits_confirmed:
                    await self._process_retention()
                # If commits not confirmed, skip retention for this cycle (fail closed)
                self._failure_count = 0  # Reset on success

            except Exception:
                self._failure_count += 1
                if self._failure_count >= self._max_consecutive_failures:
                    # Too many failures - could alert or degrade
                    pass

        # Final processing on shutdown (if shutdown_event was set while running)
        if self._shutdown_event.is_set():
            try:
                await self._process_rollups()
                commits_confirmed = await self._wait_for_pending_commits()
                if commits_confirmed:
                    await self._process_retention()
            except Exception:
                pass

    async def _wait_for_pending_commits(self) -> bool:
        """
        Wait for all pending write futures to complete and verify committed windows.

        Returns:
            True if all pending commits are confirmed and committed state is refreshed.
            False if timeout or error - retention should be skipped for this cycle.
        """
        # Wait for all pending write futures to complete
        max_wait = 30.0  # Maximum time to wait for commits
        start_time = time.monotonic()

        # Wait for all pending futures to complete
        pending_futures: list[asyncio.Future[bool]] = list(self._pending_futures)
        self._pending_futures.clear()

        still_pending = set(pending_futures)

        while still_pending:
            if time.monotonic() - start_time > max_wait:
                # Timeout - fail closed: don't proceed with retention
                return False
            done, still_pending = await asyncio.wait(
                still_pending,
                timeout=0.1,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for fut in done:
                try:
                    if not fut.result():
                        # A write failed - log but continue
                        pass
                except Exception:
                    pass

        # Verify committed windows by querying the database
        # This confirms which windows have actually been durably committed
        try:
            await self._refresh_committed_windows()
        except Exception:
            # Refresh failed - fail closed
            return False

        return True

    async def _refresh_committed_windows(self) -> None:
        """Query the database to find the highest committed window_end for each metric/interval."""
        for definition in ROLLUP_DEFINITIONS:
            for interval_config in ROLLUP_INTERVALS:
                key = (definition.metric_name, interval_config.interval_type)
                with database_connection(self._db_config.db_path) as conn:
                    cursor = conn.execute(
                        """
                        SELECT MAX(window_end) FROM metric_rollups
                        WHERE server_id = ? AND metric_name = ? AND interval_type = ?
                        """,
                        (self._server_id, definition.metric_name, interval_config.interval_type),
                    )
                    row = cursor.fetchone()
                    if row and row[0] is not None:
                        window_end_ts = _iso_to_unix(row[0])
                        # Only update if this is newer than what we have
                        if key not in self._committed_windows or window_end_ts > self._committed_windows[key]:
                            self._committed_windows[key] = window_end_ts

    async def _process_rollups(self, shutdown: bool = False) -> None:
        """Process rollups for all intervals and metrics."""
        for interval_config in ROLLUP_INTERVALS:
            if not self._running and not shutdown:
                break
            await self._process_interval(interval_config, shutdown)

    async def _process_interval(self, interval_config: RollupConfig, shutdown: bool = False) -> None:
        """Process all metrics for a single interval."""
        # Determine source table and time range
        source_is_raw = interval_config.source_interval_type is None

        # For each metric definition, compute rollups
        for definition in ROLLUP_DEFINITIONS:
            if not self._running and not shutdown:
                break

            batches_processed = 0
            while batches_processed < self._max_batches_per_cycle:
                if not self._running and not shutdown:
                    break

                processed = await self._compute_and_write_rollups(
                    definition, interval_config, source_is_raw
                )
                if not processed:
                    break  # No more work for this metric/interval
                batches_processed += processed

    async def _compute_and_write_rollups(
        self,
        definition: RollupDefinition,
        interval_config: RollupConfig,
        source_is_raw: bool,
    ) -> int:
        """
        Compute rollups for a single metric/interval and write to database.

        Returns number of batches processed (0 or 1 for this implementation).
        """
        try:
            # Determine the cutoff time (now - buffer to avoid partial buckets)
            # A window is complete when its window_end <= now
            # For hierarchical rollups, we must wait for source rollups to complete
            now = datetime.now(UTC)
            now_ts = now.timestamp()
            if interval_config.source_interval_type is not None:
                # Hierarchical: wait for source interval + one source interval buffer
                source_seconds = next(
                    ri.interval_seconds for ri in ROLLUP_INTERVALS if ri.interval_type == interval_config.source_interval_type
                )
                cutoff = now_ts - source_seconds
            else:
                # Raw samples: window is complete when window_end <= now
                cutoff = now_ts

            # Find the earliest data timestamp to start from
            start_window = await self._get_earliest_data_window(
                definition, interval_config, source_is_raw
            )
            if start_window is None:
                return 0  # No data yet

            # Check if there's anything to process
            if start_window >= cutoff:
                return 0  # Nothing to process yet

            # Process one batch of windows (up to 100 windows at a time)
            max_windows = 100
            end_window = min(start_window + max_windows * interval_config.interval_seconds, cutoff)

            # Find missing windows in the range and process each
            missing_windows = await self._get_missing_windows(
                definition, interval_config, source_is_raw, start_window, end_window
            )
            if not missing_windows:
                return 0  # Nothing missing in this range

            # Process each missing window individually
            for window_start in missing_windows:
                window_end = window_start + interval_config.interval_seconds
                await self._aggregate_and_write(
                    definition, interval_config, source_is_raw, window_start, window_end
                )

            return len(missing_windows)

        except Exception:
            # Log and continue - don't let one metric failure stop others
            return 0

    async def _get_latest_rollup_window_end(
        self, metric_name: str, interval_type: str
    ) -> float | None:
        """Get the latest window_end for a metric/interval combination."""
        with database_connection(self._db_config.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT MAX(window_end) FROM metric_rollups
                WHERE server_id = ? AND metric_name = ? AND interval_type = ?
                """,
                (self._server_id, metric_name, interval_type),
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                # Parse ISO timestamp to Unix timestamp
                return _iso_to_unix(row[0])
            return None

    async def _get_missing_windows(
        self,
        definition: RollupDefinition,
        interval_config: RollupConfig,
        source_is_raw: bool,
        start_window: float,
        end_window: float,
    ) -> list[float]:
        """Find missing windows in the given range that need to be processed."""
        # Query all committed windows in the range
        with database_connection(self._db_config.db_path) as conn:
            conn.create_function("_iso_to_unix", 1, _iso_to_unix)
            if source_is_raw:
                # For raw samples, check what's already been committed
                cursor = conn.execute(
                    """
                    SELECT _iso_to_unix(window_end) as window_end_ts FROM metric_rollups
                    WHERE server_id = ? AND metric_name = ? AND interval_type = ?
                    AND _iso_to_unix(window_end) > ? AND _iso_to_unix(window_end) <= ?
                    ORDER BY window_end
                    """,
                    (self._server_id, definition.metric_name, interval_config.interval_type, start_window, end_window),
                )
            else:
                # For hierarchical, check child interval
                cursor = conn.execute(
                    """
                    SELECT _iso_to_unix(window_end) as window_end_ts FROM metric_rollups
                    WHERE server_id = ? AND metric_name = ? AND interval_type = ?
                    AND _iso_to_unix(window_end) > ? AND _iso_to_unix(window_end) <= ?
                    ORDER BY window_end
                    """,
                    (self._server_id, definition.metric_name, interval_config.interval_type, start_window, end_window),
                )
            rows = cursor.fetchall()
            committed_ends = {row[0] for row in rows}

        # Find missing windows
        missing = []
        window = start_window
        interval_seconds = interval_config.interval_seconds
        while window < end_window:
            window_end = window + interval_seconds
            if window_end not in committed_ends:
                missing.append(window)
            window = window_end

        return missing

    async def _get_earliest_data_window(
        self,
        definition: RollupDefinition,
        interval_config: RollupConfig,
        source_is_raw: bool,
    ) -> float | None:
        """Find the earliest data timestamp and align to interval boundary."""
        source_table = definition.source_table if source_is_raw else "metric_rollups"
        column = definition.source_column
        dim_col = definition.dimension_column

        with database_connection(self._db_config.db_path) as conn:
            if source_is_raw:
                if dim_col:
                    cursor = conn.execute(
                        f"""
                        SELECT MIN(timestamp) FROM {source_table}
                        WHERE server_id = ? AND {column} IS NOT NULL
                        """,
                        (self._server_id,),
                    )
                else:
                    cursor = conn.execute(
                        f"""
                        SELECT MIN(timestamp) FROM {source_table}
                        WHERE server_id = ? AND {column} IS NOT NULL
                        """,
                        (self._server_id,),
                    )
            else:
                cursor = conn.execute(
                    """
                    SELECT MIN(window_start) FROM metric_rollups
                    WHERE server_id = ? AND metric_name = ? AND interval_type = ?
                    """,
                    (self._server_id, definition.metric_name, interval_config.source_interval_type),
                )

            row = cursor.fetchone()
            if row and row[0] is not None:
                dt = _iso_to_unix(row[0])
                # Align to interval boundary
                return _align_to_interval(dt, interval_config.interval_seconds)
            return None

    async def _aggregate_and_write(
        self,
        definition: RollupDefinition,
        interval_config: RollupConfig,
        source_is_raw: bool,
        start_window: float,
        end_window: float,
    ) -> None:
        """Execute aggregation query and write results via DatabaseWriter."""
        source_table = definition.source_table if source_is_raw else "metric_rollups"
        column = definition.source_column
        dim_col = definition.dimension_column
        interval_seconds = interval_config.interval_seconds

        with database_connection(self._db_config.db_path) as conn:
            if source_is_raw:
                if dim_col:
                    # Raw samples with dimension (device, interface, mount_point, sensor_name)
                    query = f"""
                        SELECT
                            {dim_col} as dimension,
                            COUNT(*) as cnt,
                            MIN({column}) as min_val,
                            AVG({column}) as avg_val,
                            MAX({column}) as max_val,
                            (_iso_to_unix(timestamp) / ?) * ? as window_start
                        FROM {source_table}
                        WHERE server_id = ?
                            AND {column} IS NOT NULL
                            AND _iso_to_unix(timestamp) >= ?
                            AND _iso_to_unix(timestamp) < ?
                        GROUP BY dimension, window_start
                        ORDER BY window_start
                    """
                    params: tuple[int, int, str, float, float] | tuple[str, str, str | None, float, float] = (interval_seconds, interval_seconds, self._server_id, start_window, end_window)
                else:
                    # Raw samples without dimension
                    query = f"""
                        SELECT
                            COUNT(*) as cnt,
                            MIN({column}) as min_val,
                            AVG({column}) as avg_val,
                            MAX({column}) as max_val,
                            (_iso_to_unix(timestamp) / ?) * ? as window_start
                        FROM {source_table}
                        WHERE server_id = ?
                            AND {column} IS NOT NULL
                            AND _iso_to_unix(timestamp) >= ?
                            AND _iso_to_unix(timestamp) < ?
                        GROUP BY window_start
                        ORDER BY window_start
                    """
                    params = (interval_seconds, interval_seconds, self._server_id, start_window, end_window)
            else:
                # Source is rollups - aggregate from rollup table
                if dim_col:
                    # Rollups don't have dimension column in current schema
                    # For now, skip dimension aggregation from rollups
                    return
                # Hierarchical aggregation: group child rollups into parent interval buckets
                # Use weighted average: SUM(avg_value * count) / SUM(count)
                # Sum counts, min of mins, max of maxs
                parent_interval_seconds = interval_config.interval_seconds
                # Use integer division: (x / y) with CAST to INTEGER for proper bucket grouping
                query = f"""
                    SELECT
                        SUM(count) as cnt,
                        MIN(min_value) as min_val,
                        SUM(avg_value * count) / SUM(count) as avg_val,
                        MAX(max_value) as max_val,
                        CAST(_iso_to_unix(window_start) / {parent_interval_seconds} AS INTEGER) * {parent_interval_seconds} as window_start
                    FROM metric_rollups
                    WHERE server_id = ?
                        AND metric_name = ?
                        AND interval_type = ?
                        AND _iso_to_unix(window_start) >= ?
                        AND _iso_to_unix(window_start) < ?
                    GROUP BY CAST(_iso_to_unix(window_start) / {parent_interval_seconds} AS INTEGER)
                    ORDER BY window_start
                """
                params = (
                    self._server_id,
                    definition.metric_name,
                    interval_config.source_interval_type,
                    start_window,
                    end_window,
                )

            # Register the helper function for this connection
            conn.create_function("_iso_to_unix", 1, _iso_to_unix)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        if not rows:
            return

        # Write rollups via DatabaseWriter (idempotent via UNIQUE constraint)
        for row in rows:
            if dim_col:
                _, cnt, min_val, avg_val, max_val, window_start = row
            else:
                cnt, min_val, avg_val, max_val, window_start = row

            window_start_dt = datetime.fromtimestamp(window_start, tz=UTC)
            window_end_dt = datetime.fromtimestamp(window_start + interval_seconds, tz=UTC)

            rollup_data = {
                "server_id": self._server_id,
                "metric_name": definition.metric_name,
                "interval_type": interval_config.interval_type,
                "window_start": window_start_dt.isoformat().replace("+00:00", "Z"),
                "window_end": window_end_dt.isoformat().replace("+00:00", "Z"),
                "count": cnt,
                "min_value": min_val,
                "avg_value": avg_val,
                "max_value": max_val,
            }

            # Add dimension if applicable (would need schema change to support)
            # For now, we skip dimension in rollups to match current schema

            # Use DatabaseWriter - the UNIQUE constraint on (server_id, metric_name, interval_type, window_start)
            # ensures idempotency. DatabaseWriter will enqueue and the writer thread will handle conflicts.
            # Capture the future to track commit confirmation.
            enqueued, future = await self._db_writer.write(
                "metric_rollups",
                rollup_data,
                priority=WritePriority.NORMAL,
            )

            if enqueued:
                # Track the future to await commit confirmation
                self._pending_futures.append(future)

            # Do NOT optimistically update _committed_windows here.
            # It will be updated by _refresh_committed_windows() after commits are confirmed.
            # This prevents gaps where a later window appears committed before an earlier failed one.

    async def _process_retention(self) -> None:
        """Process retention cleanup for all tables using committed window boundaries."""
        now = datetime.now(UTC)
        now_ts = now.timestamp()

        # Compute safe deletion boundaries based on committed windows
        # Raw samples: only delete data older than the oldest committed 1m window
        raw_cutoff = self._get_raw_retention_cutoff(now_ts)
        await self._cleanup_table("cpu_samples", raw_cutoff)
        await self._cleanup_table("memory_samples", raw_cutoff)
        await self._cleanup_table("disk_samples", raw_cutoff)
        await self._cleanup_table("network_samples", raw_cutoff)
        await self._cleanup_table("filesystem_samples", raw_cutoff)
        await self._cleanup_table("temperature_samples", raw_cutoff)

        # Rollup retentions: each interval can only be deleted up to the next interval's committed windows
        await self._cleanup_rollups("1m", self._get_rollup_retention_cutoff("1m", "5m", now_ts))
        await self._cleanup_rollups("5m", self._get_rollup_retention_cutoff("5m", "1h", now_ts))
        await self._cleanup_rollups("1h", self._get_rollup_retention_cutoff("1h", "1d", now_ts))
        await self._cleanup_rollups("1d", self._get_rollup_retention_cutoff("1d", None, now_ts))

    def _get_raw_retention_cutoff(self, now_ts: float) -> float:
        """Get the safe cutoff for raw sample deletion based on committed 1m windows."""
        # Find the minimum committed 1m window_end across all metrics that use raw tables
        min_committed = None
        for definition in ROLLUP_DEFINITIONS:
            if definition.source_table in {
                "cpu_samples", "memory_samples", "disk_samples",
                "network_samples", "filesystem_samples", "temperature_samples"
            }:
                key = (definition.metric_name, "1m")
                if key in self._committed_windows:
                    committed = self._committed_windows[key]
                    if min_committed is None or committed < min_committed:
                        min_committed = committed

        if min_committed is not None:
            # Apply retention period as maximum - don't delete data newer than retention period
            retention_cutoff = now_ts - self._db_config.retention_raw_hours * 3600
            return min(min_committed, retention_cutoff)

        # No committed windows yet - use retention period
        return now_ts - self._db_config.retention_raw_hours * 3600

    def _get_rollup_retention_cutoff(self, current_interval: str, next_interval: str | None, now_ts: float) -> float:
        """Get the safe cutoff for rollup deletion based on committed next-interval windows."""
        if next_interval is None:
            # Highest interval - use its own retention period
            retention_days = {
                "1m": self._db_config.retention_1min_days,
                "5m": self._db_config.retention_5min_days,
                "1h": self._db_config.retention_1h_days,
                "1d": self._db_config.retention_1d_days,
            }.get(current_interval, 7)
            return now_ts - retention_days * 86400

        # Find minimum committed window_end for the next interval across all metrics
        min_committed = None
        for definition in ROLLUP_DEFINITIONS:
            key = (definition.metric_name, next_interval)
            if key in self._committed_windows:
                committed = self._committed_windows[key]
                if min_committed is None or committed < min_committed:
                    min_committed = committed

        if min_committed is not None:
            # Apply retention period as maximum
            retention_days = {
                "1m": self._db_config.retention_1min_days,
                "5m": self._db_config.retention_5min_days,
                "1h": self._db_config.retention_1h_days,
                "1d": self._db_config.retention_1d_days,
            }.get(current_interval, 7)
            retention_cutoff = now_ts - retention_days * 86400
            return min(min_committed, retention_cutoff)

        # No committed windows for next interval yet - use retention period
        retention_days = {
            "1m": self._db_config.retention_1min_days,
            "5m": self._db_config.retention_5min_days,
            "1h": self._db_config.retention_1h_days,
            "1d": self._db_config.retention_1d_days,
        }.get(current_interval, 7)
        return now_ts - retention_days * 86400

    async def _cleanup_table(self, table: str, cutoff_ts: float) -> None:
        """Delete old raw samples up to cutoff, in bounded batches."""
        deleted = 0
        while deleted < self._retention_batch_size:
            with database_connection(self._db_config.db_path) as conn:
                conn.create_function("_iso_to_unix", 1, _iso_to_unix)
                # SQLite doesn't support LIMIT in DELETE directly.
                # Use a subquery to limit the number of rows deleted.
                cursor = conn.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE id IN (
                        SELECT id FROM {table}
                        WHERE server_id = ? AND _iso_to_unix(timestamp) < ?
                        LIMIT ?
                    )
                    """,
                    (self._server_id, cutoff_ts, self._retention_batch_size),
                )
                deleted = cursor.rowcount
                if deleted == 0:
                    break

    async def _cleanup_rollups(self, interval_type: str, cutoff_ts: float) -> None:
        """Delete old rollups up to cutoff, in bounded batches."""
        deleted = 0
        while deleted < self._retention_batch_size:
            with database_connection(self._db_config.db_path) as conn:
                conn.create_function("_iso_to_unix", 1, _iso_to_unix)
                cursor = conn.execute(
                    """
                    DELETE FROM metric_rollups
                    WHERE id IN (
                        SELECT id FROM metric_rollups
                        WHERE server_id = ? AND interval_type = ? AND _iso_to_unix(window_start) < ?
                        LIMIT ?
                    )
                    """,
                    (self._server_id, interval_type, cutoff_ts, self._retention_batch_size),
                )
                deleted = cursor.rowcount
                if deleted == 0:
                    break


# Global rollup processor instance
_rollup_processor: RollupProcessor | None = None
_rollup_lock = asyncio.Lock()


async def get_rollup_processor(
    db_writer: DatabaseWriter,
    server_id: str = "local",
    rollup_interval: float = 60.0,
) -> RollupProcessor:
    """Get or create the global rollup processor."""
    global _rollup_processor
    async with _rollup_lock:
        if _rollup_processor is None:
            _rollup_processor = RollupProcessor(
                db_writer=db_writer,
                server_id=server_id,
                rollup_interval=rollup_interval,
            )
        return _rollup_processor


async def start_rollup_processor(
    db_writer: DatabaseWriter,
    server_id: str = "local",
    rollup_interval: float = 60.0,
) -> None:
    """Start the global rollup processor."""
    processor = await get_rollup_processor(db_writer, server_id, rollup_interval)
    await processor.start()


async def stop_rollup_processor() -> None:
    """Stop the global rollup processor."""
    global _rollup_processor
    async with _rollup_lock:
        if _rollup_processor is not None:
            await _rollup_processor.stop()
            _rollup_processor = None
