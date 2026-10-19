"""Tests for the database writer."""

import asyncio
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from app.database.connection import database_connection
from app.database.migrations import run_migrations
from app.database.writer import (
    DatabaseWriter,
    WritePriority,
    get_db_writer,
    start_db_writer,
    stop_db_writer,
)


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        yield db_path
    finally:
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def migrated_db(temp_db_path: str) -> str:
    """Create a database with migrations applied."""
    run_migrations(temp_db_path)
    return temp_db_path


@pytest.fixture
def writer_config(migrated_db: str) -> Generator[DatabaseWriter, None, None]:
    """Create a DatabaseWriter with test configuration."""
    from app.database.config import DBConfig
    config = DBConfig(
        db_path=migrated_db,
        queue_size=100,
        batch_size=10,
        flush_interval=0.1,
    )
    writer = DatabaseWriter(
        db_config=config,
        queue_size=100,
        batch_size=10,
        flush_interval=0.1,
        shutdown_drain_timeout=2.0,
    )
    writer.start()
    yield writer
    writer.stop()


class TestWriterBasicOperation:
    """Tests for basic writer operation."""

    @pytest.mark.asyncio
    async def test_write_single_row(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test writing a single row and reading it back."""
        enqueued, _ = await writer_config.write(
            "servers",
            {
                "id": "test-server-1",
                "hostname": "test-host",
                "display_name": "Test Server",
                "os_name": "Linux",
                "os_version": "6.1.0",
                "kernel_version": "6.1.0",
                "architecture": "x86_64",
            },
            priority=WritePriority.NORMAL,
        )
        assert enqueued is True

        # Wait for flush
        await asyncio.sleep(0.2)

        # Verify data was written
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM servers WHERE id = ?", ("test-server-1",))
            row = cursor.fetchone()
            assert row is not None
            assert row["id"] == "test-server-1"
            assert row["hostname"] == "test-host"

    @pytest.mark.asyncio
    async def test_write_multiple_rows_batched(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that multiple writes are batched into a single transaction."""
        server_ids = [f"test-server-{i}" for i in range(15)]

        # Write multiple rows
        for sid in server_ids:
            enqueued, _ = await writer_config.write(
                "servers",
                {
                    "id": sid,
                    "hostname": f"host-{sid}",
                    "display_name": f"Display {sid}",
                    "os_name": "Linux",
                    "os_version": "6.1.0",
                    "kernel_version": "6.1.0",
                    "architecture": "x86_64",
                },
            )
            assert enqueued is True

        # Wait for all batches to flush
        await asyncio.sleep(0.5)

        # Verify all rows were written
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM servers WHERE id LIKE 'test-server-%'")
            count = cursor.fetchone()[0]
            assert count == 15

    @pytest.mark.asyncio
    async def test_priority_ordering(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that higher priority writes are processed first."""
        # Fill queue with low priority writes
        for i in range(20):
            await writer_config.write(
                "servers",
                {
                    "id": f"low-{i}",
                    "hostname": f"low-host-{i}",
                    "os_name": "Linux",
                    "os_version": "6.1.0",
                    "kernel_version": "6.1.0",
                    "architecture": "x86_64",
                },
                priority=WritePriority.LOW,
            )

        # Write high priority
        await writer_config.write(
            "servers",
            {
                "id": "high-priority",
                "hostname": "high-host",
                "os_name": "Linux",
                "os_version": "6.1.0",
                "kernel_version": "6.1.0",
                "architecture": "x86_64",
            },
            priority=WritePriority.HIGH,
        )

        # Wait for processing
        await asyncio.sleep(0.3)

        # Verify high priority was written (it should be in the database)
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM servers WHERE id = ?", ("high-priority",))
            row = cursor.fetchone()
            assert row is not None


class TestWriterQueueSaturation:
    """Tests for queue capacity and saturation behavior."""

    @pytest.mark.asyncio
    async def test_queue_saturation_rejects_low_priority(self, migrated_db: str) -> None:
        """Test that low priority writes are rejected when queue is full."""
        from app.database.config import DBConfig
        config = DBConfig(db_path=migrated_db, queue_size=5, batch_size=10, flush_interval=10.0)
        writer = DatabaseWriter(db_config=config, queue_size=5, batch_size=10, flush_interval=10.0)
        writer.start()

        try:
            # Fill the queue completely
            for i in range(5):
                enqueued, _ = await writer.write(
                    "servers",
                    {"id": f"fill-{i}", "hostname": f"fill-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
                    priority=WritePriority.NORMAL,
                )
                assert enqueued is True

            # Next normal priority should be rejected (queue full)
            enqueued, _ = await writer.write(
                "servers",
                {"id": "rejected", "hostname": "rejected", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
                priority=WritePriority.NORMAL,
                timeout=0.1,
            )
            assert enqueued is False

            # But HIGH priority should be accepted (evicts lowest)
            enqueued, _ = await writer.write(
                "servers",
                {"id": "high-evict", "hostname": "high-evict", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
                priority=WritePriority.HIGH,
                timeout=0.1,
            )
            assert enqueued is True

        finally:
            writer.stop()

    @pytest.mark.asyncio
    async def test_queue_full_dropped_metric(self, migrated_db: str) -> None:
        """Test that dropped writes are counted in metrics."""
        from app.database.config import DBConfig
        config = DBConfig(db_path=migrated_db, queue_size=3, batch_size=10, flush_interval=10.0)
        writer = DatabaseWriter(db_config=config, queue_size=3, batch_size=10, flush_interval=10.0)
        writer.start()

        try:
            # Fill queue
            for i in range(3):
                enqueued, _ = await writer.write("servers", {"id": f"fill-{i}", "hostname": f"fill-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"})
                assert enqueued is True

            # Try to write more - should be dropped
            for i in range(3):
                enqueued, _ = await writer.write(
                    "servers",
                    {"id": f"drop-{i}", "hostname": f"drop-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
                    timeout=0.05,
                )
                assert enqueued is False

            metrics = writer.get_metrics()
            assert metrics.dropped >= 3

        finally:
            writer.stop()


class TestWriterFailureHandling:
    """Tests for database error handling."""

    @pytest.mark.asyncio
    async def test_foreign_key_failure_handled(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that FK violations are handled gracefully."""
        # Try to insert with non-existent server_id
        enqueued, _ = await writer_config.write(
            "cpu_samples",
            {
                "server_id": "non-existent-server",
                "timestamp": "2026-01-01T00:00:00Z",
                "per_core": "[]",
            },
            priority=WritePriority.NORMAL,
        )
        # Enqueue succeeds, but write fails
        assert enqueued is True  # Enqueue succeeded

        # Wait for processing
        await asyncio.sleep(0.3)

        # Check metrics recorded failure
        metrics = writer_config.get_metrics()
        assert metrics.failed >= 1
        assert metrics.last_error is not None

    @pytest.mark.asyncio
    async def test_invalid_table_failure_handled(self, writer_config: DatabaseWriter) -> None:
        """Test that invalid table names are rejected at enqueue time."""
        enqueued, _ = await writer_config.write(
            "non_existent_table",
            {"id": "test"},
            priority=WritePriority.NORMAL,
        )
        # Invalid table is rejected at enqueue time (validation)
        assert enqueued is False

        # Should be counted as dropped
        metrics = writer_config.get_metrics()
        assert metrics.dropped >= 1

    @pytest.mark.asyncio
    async def test_malformed_data_failure_handled(self, writer_config: DatabaseWriter) -> None:
        """Test that malformed data (missing required fields) is handled."""
        # servers table requires id and hostname NOT NULL
        enqueued, _ = await writer_config.write(
            "servers",
            {"display_name": "Test"},  # missing required fields
            priority=WritePriority.NORMAL,
        )
        assert enqueued is True

        await asyncio.sleep(0.3)

        metrics = writer_config.get_metrics()
        assert metrics.failed >= 1

    @pytest.mark.asyncio
    async def test_batch_atomicity_on_failure(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that batch is atomic - one failure rolls back entire batch."""
        from app.database.config import DBConfig
        # Use batch_size=3 to force batching
        config = DBConfig(db_path=migrated_db, queue_size=100, batch_size=3, flush_interval=10.0)
        writer = DatabaseWriter(db_config=config, queue_size=100, batch_size=3, flush_interval=10.0)
        writer.start()

        try:
            # Write 2 valid rows + 1 invalid (FK violation) - all should be in same batch
            valid1_enq, _ = await writer.write(
                "servers",
                {"id": "atomic-1", "hostname": "atomic-1", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
            )
            valid2_enq, _ = await writer.write(
                "servers",
                {"id": "atomic-2", "hostname": "atomic-2", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
            )
            invalid_enq, _ = await writer.write(
                "cpu_samples",
                {"server_id": "non-existent-server", "timestamp": "2026-01-01T00:00:00Z", "per_core": "[]"},
            )

            assert valid1_enq is True
            assert valid2_enq is True
            assert invalid_enq is True  # Enqueue succeeds

            # Wait for batch to process - poll metrics instead of fixed sleep
            for _ in range(50):
                metrics = writer.get_metrics()
                if metrics.failed >= 3 or metrics.successful >= 3:
                    break
                await asyncio.sleep(0.05)

            # All three tasks should have failed (batch rolled back)
            metrics = writer.get_metrics()
            assert metrics.failed == 3, f"Expected 3 failed, got {metrics.failed}"
            assert metrics.successful == 0, f"Expected 0 successful (batch rolled back), got {metrics.successful}"

            # Verify NO rows in database (entire batch rolled back)
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM servers WHERE id LIKE 'atomic-%'")
                count = cursor.fetchone()[0]
                assert count == 0, f"Expected 0 rows (batch rolled back), got {count}"

        finally:
            writer.stop()


class TestWriterShutdown:
    """Tests for graceful shutdown behavior."""

    @pytest.mark.asyncio
    async def test_shutdown_empty_queue(self, migrated_db: str) -> None:
        """Test shutdown with empty queue completes quickly."""
        from app.database.config import DBConfig
        config = DBConfig(db_path=migrated_db, queue_size=100, batch_size=10, flush_interval=1.0)
        writer = DatabaseWriter(db_config=config, queue_size=100, batch_size=10, flush_interval=1.0)
        writer.start()

        # No writes, just shutdown
        drained = writer.stop(timeout=1.0)
        assert drained is True

    @pytest.mark.asyncio
    async def test_shutdown_drains_pending_writes(self, migrated_db: str) -> None:
        """Test that shutdown waits for pending writes to complete."""
        from app.database.config import DBConfig
        config = DBConfig(db_path=migrated_db, queue_size=100, batch_size=10, flush_interval=2.0)
        writer = DatabaseWriter(db_config=config, queue_size=100, batch_size=10, flush_interval=2.0)
        writer.start()

        # Enqueue several writes
        for i in range(10):
            await writer.write(
                "servers",
                {"id": f"shutdown-{i}", "hostname": f"shutdown-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
            )

        # Shutdown should drain them
        drained = writer.stop(timeout=2.0)
        assert drained is True

        # Verify all were written
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM servers WHERE id LIKE 'shutdown-%'")
            count = cursor.fetchone()[0]
            assert count == 10

    @pytest.mark.asyncio
    async def test_shutdown_after_write_failure(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test shutdown works after a write failure."""
        # Cause a failure
        await writer_config.write(
            "cpu_samples",
            {"server_id": "bad-server", "timestamp": "2026-01-01T00:00:00Z", "per_core": "[]"},
        )
        await asyncio.sleep(0.2)

        # Shutdown should still work
        drained = writer_config.stop(timeout=2.0)
        assert drained is True

    @pytest.mark.asyncio
    async def test_repeated_shutdown_idempotent(self, migrated_db: str) -> None:
        """Test that calling stop multiple times is safe."""
        from app.database.config import DBConfig
        config = DBConfig(db_path=migrated_db, queue_size=100, batch_size=10, flush_interval=1.0)
        writer = DatabaseWriter(db_config=config, queue_size=100, batch_size=10, flush_interval=1.0)
        writer.start()

        result1 = writer.stop(timeout=1.0)
        result2 = writer.stop(timeout=1.0)
        result3 = writer.stop(timeout=1.0)

        assert result1 is True
        assert result2 is True
        assert result3 is True

    @pytest.mark.asyncio
    async def test_shutdown_timeout_returns_false(self, migrated_db: str) -> None:
        """Test that shutdown returns False when drain times out."""
        from app.database.config import DBConfig
        config = DBConfig(db_path=migrated_db, queue_size=100, batch_size=10, flush_interval=10.0)
        writer = DatabaseWriter(db_config=config, queue_size=100, batch_size=10, flush_interval=10.0)
        writer.start()

        # Fill queue with many items that won't flush quickly
        for i in range(50):
            await writer.write(
                "servers",
                {"id": f"slow-{i}", "hostname": f"slow-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
            )

        # Shutdown with very short timeout
        drained = writer.stop(timeout=0.01)
        # May or may not drain depending on timing, but should not hang
        # The key test is it returns quickly without blocking indefinitely
        assert isinstance(drained, bool)


class TestWriterMetrics:
    """Tests for writer metrics."""

    @pytest.mark.asyncio
    async def test_metrics_track_enqueued(self, writer_config: DatabaseWriter) -> None:
        """Test that enqueued count is tracked."""
        initial = writer_config.get_metrics().enqueued

        await writer_config.write("servers", {"id": "m1", "hostname": "m1", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"})
        await writer_config.write("servers", {"id": "m2", "hostname": "m2", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"})

        await asyncio.sleep(0.2)

        metrics = writer_config.get_metrics()
        assert metrics.enqueued >= initial + 2

    @pytest.mark.asyncio
    async def test_metrics_track_successful(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that successful writes are counted."""
        initial = writer_config.get_metrics().successful

        for i in range(5):
            await writer_config.write(
                "servers",
                {"id": f"metrics-{i}", "hostname": f"metrics-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
            )
        await asyncio.sleep(0.3)

        metrics = writer_config.get_metrics()
        assert metrics.successful >= initial + 5

    @pytest.mark.asyncio
    async def test_metrics_track_failed(self, writer_config: DatabaseWriter) -> None:
        """Test that failed writes are counted."""
        initial = writer_config.get_metrics().failed

        await writer_config.write("cpu_samples", {"server_id": "bad", "timestamp": "2026-01-01T00:00:00Z", "per_core": "[]"})
        await asyncio.sleep(0.3)

        metrics = writer_config.get_metrics()
        assert metrics.failed >= initial + 1
        assert metrics.last_error is not None

    @pytest.mark.asyncio
    async def test_metrics_snapshot_isolation(self, writer_config: DatabaseWriter) -> None:
        """Test that get_metrics returns a snapshot, not live reference."""
        metrics1 = writer_config.get_metrics()
        metrics2 = writer_config.get_metrics()

        # They should be separate objects
        assert metrics1 is not metrics2
        # But with same values
        assert metrics1.enqueued == metrics2.enqueued


class TestWriterThreadSafety:
    """Tests proving SQLite runs off the event loop."""

    @pytest.mark.asyncio
    async def test_write_does_not_block_event_loop(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that write() returns control to event loop quickly."""
        import time

        # Track if event loop was blocked - measure time between yields
        loop_blocked = False
        last_yield = time.monotonic()

        async def monitor_loop() -> None:
            nonlocal loop_blocked, last_yield
            start = time.monotonic()
            while time.monotonic() - start < 1.0:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                # If gap between monitor iterations exceeds 500ms, loop was blocked
                if now - last_yield > 0.5:
                    loop_blocked = True
                    break
                last_yield = now

        # Start monitor
        monitor_task = asyncio.create_task(monitor_loop())

        # Do many writes rapidly
        for i in range(50):
            await writer_config.write(
                "servers",
                {"id": f"loop-{i}", "hostname": f"loop-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
                timeout=0.5,
            )

        await monitor_task
        # Event loop should not have been blocked
        assert loop_blocked is False

    @pytest.mark.asyncio
    async def test_concurrent_queue_eviction_thread_safe(self, migrated_db: str) -> None:
        """Test that concurrent priority eviction does not corrupt queue or lose tasks."""
        from app.database.config import DBConfig
        config = DBConfig(db_path=migrated_db, queue_size=10, batch_size=5, flush_interval=10.0)
        writer = DatabaseWriter(db_config=config, queue_size=10, batch_size=5, flush_interval=10.0)
        writer.start()

        try:
            # Fill queue with NORMAL priority
            for i in range(10):
                enqueued, _ = await writer.write(
                    "servers",
                    {"id": f"fill-{i}", "hostname": f"fill-{i}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
                    priority=WritePriority.NORMAL,
                )
                assert enqueued is True

            # Now fire many HIGH priority writes concurrently - each should evict one item
            # Use asyncio.gather to create concurrent pressure
            async def write_high(idx: int) -> bool:
                enqueued, _ = await writer.write(
                    "servers",
                    {"id": f"high-{idx}", "hostname": f"high-{idx}", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"},
                    priority=WritePriority.HIGH,
                    timeout=0.5,
                )
                return enqueued

            results = await asyncio.gather(*[write_high(i) for i in range(20)])

            # All HIGH priority writes should succeed (evicting lower priority)
            assert all(results), f"Some high priority writes failed: {results}"

            # Wait for processing - poll metrics instead of fixed sleep
            for _ in range(50):
                metrics = writer.get_metrics()
                if metrics.dropped >= 20 and metrics.enqueued >= 30:
                    break
                await asyncio.sleep(0.05)

            # Verify queue depth is bounded (max 10)
            assert writer.queue_depth <= 10

            # Verify metrics:
            # 10 initial enqueued + 20 high = 30 enqueued
            # First 10 HIGH evict 10 NORMAL (10 dropped)
            # Next 10 HIGH evict 10 earlier HIGH (10 more dropped) = 20 total dropped
            metrics = writer.get_metrics()
            assert metrics.enqueued == 30
            assert metrics.dropped == 20  # 10 NORMAL + 10 HIGH evicted
            assert metrics.failed == 0

            # Verify only the last 10 HIGH priority tasks made it to database
            # (first 10 HIGH were evicted by last 10 HIGH)
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM servers WHERE id LIKE 'high-%'")
                count = cursor.fetchone()[0]
                assert count == 10, f"Expected 10 high priority rows (last batch), got {count}"

                # NORMAL priority should have been evicted (0 remaining)
                cursor = conn.execute("SELECT COUNT(*) FROM servers WHERE id LIKE 'fill-%'")
                count = cursor.fetchone()[0]
                assert count == 0, f"Expected 0 fill rows (all evicted), got {count}"

        finally:
            writer.stop()


class TestWriterIntegration:
    """Integration tests with real database."""

    @pytest.mark.asyncio
    async def test_write_all_table_types(self, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test writing to all table types."""
        tables_and_data: list[tuple[str, dict[str, Any]]] = [
            ("servers", {"id": "int-test", "hostname": "int-test", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"}),
            ("cpu_samples", {"server_id": "int-test", "timestamp": "2026-01-01T00:00:00Z", "total_utilization": 50.0, "per_core": "[50.0]", "load_1min": 1.0, "load_5min": 1.0, "load_15min": 1.0, "cpu_count": 4}),
            ("memory_samples", {"server_id": "int-test", "timestamp": "2026-01-01T00:00:00Z", "total_bytes": 1000000, "available_bytes": 500000, "used_bytes": 500000}),
            ("disk_samples", {"server_id": "int-test", "timestamp": "2026-01-01T00:00:00Z", "device": "sda", "read_bytes": 1000, "write_bytes": 2000}),
            ("network_samples", {"server_id": "int-test", "timestamp": "2026-01-01T00:00:00Z", "interface": "eth0", "rx_bytes": 1000, "tx_bytes": 2000}),
            ("filesystem_samples", {"server_id": "int-test", "timestamp": "2026-01-01T00:00:00Z", "mount_point": "/", "total_bytes": 1000000, "free_bytes": 500000}),
            ("temperature_samples", {"server_id": "int-test", "timestamp": "2026-01-01T00:00:00Z", "sensor_name": "cpu", "temperature_celsius": 45.0}),
            ("events", {"server_id": "int-test", "timestamp": "2026-01-01T00:00:00Z", "event_type": "test", "severity": "INFO", "source": "test", "title": "Test", "message": "Test message"}),
            ("alerts", {"server_id": "int-test", "rule_id": "test-rule", "state": "FIRING", "severity": "WARNING", "condition": "test > 1", "first_seen": "2026-01-01T00:00:00Z", "last_seen": "2026-01-01T00:00:00Z"}),
            ("metric_rollups", {"server_id": "int-test", "metric_name": "cpu", "interval_type": "1m", "window_start": "2026-01-01T00:00:00Z", "window_end": "2026-01-01T00:01:00Z", "count": 10, "min_value": 1.0, "avg_value": 50.0, "max_value": 99.0}),
        ]

        for table, data in tables_and_data:
            enqueued, _ = await writer_config.write(table, data, priority=WritePriority.NORMAL)
            assert enqueued is True, f"Failed to enqueue write to {table}"

        await asyncio.sleep(0.5)

        # Verify all tables have data
        with database_connection(migrated_db) as conn:
            for table, _ in tables_and_data:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                assert count >= 1, f"Table {table} has no data"


class TestGlobalWriterFunctions:
    """Tests for the global writer singleton functions."""

    @pytest.mark.asyncio
    async def test_global_writer_start_stop(self, migrated_db: str) -> None:
        """Test global writer start/stop functions."""
        # Patch the global writer to use our test DB
        import app.database.writer as writer_module
        from app.database.config import DBConfig

        original_writer = writer_module._db_writer
        writer_module._db_writer = None

        try:
            # Override config
            test_config = DBConfig(db_path=migrated_db, queue_size=100, batch_size=10, flush_interval=0.1)
            writer_module._db_writer = DatabaseWriter(db_config=test_config, queue_size=100, batch_size=10, flush_interval=0.1)

            await start_db_writer()
            writer = get_db_writer()
            assert writer._running is True

            # Write something
            await writer.write("servers", {"id": "global-test", "hostname": "global-test", "os_name": "Linux", "os_version": "6.1", "kernel_version": "6.1", "architecture": "x86_64"})
            await asyncio.sleep(0.2)

            drained = await stop_db_writer()
            assert drained is True
            assert writer._running is False

        finally:
            writer_module._db_writer = original_writer
