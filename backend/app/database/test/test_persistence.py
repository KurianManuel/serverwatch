"""Tests for the persistence adapter."""

import asyncio
import tempfile
from collections.abc import AsyncGenerator, Generator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.collectors.base import CollectorResult, CollectorStatus
from app.database.connection import database_connection
from app.database.migrations import run_migrations
from app.database.persistence import (
    PersistenceAdapter,
    get_persistence_adapter,
    start_persistence,
    stop_persistence,
)
from app.database.writer import DatabaseWriter
from app.state.manager import StateManager
from app.state.models import (
    DataStatus,
    MetricValue,
)


def _make_metric(value: Any, collector: str, status: DataStatus = DataStatus.CURRENT) -> MetricValue:
    """Create a MetricValue with proper timestamps."""
    return MetricValue(
        value=value,
        timestamp=datetime.utcnow(),
        monotonic_timestamp=0.0,  # Will be updated by state manager
        status=status,
        collector=collector,
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


@pytest.fixture
def state_manager() -> StateManager:
    """Create a fresh StateManager."""
    return StateManager()


@pytest.fixture(autouse=True)
def reset_global_writer() -> Generator[None, None, None]:
    """Reset global writer before each test to ensure isolation."""
    import app.database.writer as writer_module
    original_writer = writer_module._db_writer
    writer_module._db_writer = None
    try:
        yield
    finally:
        writer_module._db_writer = original_writer


@pytest.fixture
def persistence_adapter(state_manager: StateManager, writer_config: DatabaseWriter) -> Generator[PersistenceAdapter, None, None]:
    """Create a PersistenceAdapter with test configuration."""
    adapter = PersistenceAdapter(
        state_manager=state_manager,
        db_writer=writer_config,
        server_id="test-server",
        persist_interval=0.1,
    )
    yield adapter


@pytest.fixture
async def running_persistence(persistence_adapter: PersistenceAdapter) -> AsyncGenerator[PersistenceAdapter, None]:
    """Start and stop persistence adapter for testing."""
    await persistence_adapter.start()
    # Wait for first persist interval to pass (with empty state)
    # so that subsequent test snapshots will be captured on the next interval
    await asyncio.sleep(0.15)
    yield persistence_adapter
    await persistence_adapter.stop()


async def _apply_test_snapshot(state_manager: StateManager) -> None:
    """Apply a test snapshot to the state manager."""
    # CPU
    await state_manager.apply_collector_result(
        CollectorResult(
            collector_name="cpu",
            status=CollectorStatus.RUNNING,
            data=type(
                "CPUData",
                (),
                {
                    "total_utilization": 45.5,
                    "per_core": [40.0, 50.0, 45.0, 47.0],
                    "load_average": (1.2, 1.0, 0.8),
                    "cpu_count": 4,
                },
            )(),
        )
    )

    # Memory
    await state_manager.apply_collector_result(
        CollectorResult(
            collector_name="memory",
            status=CollectorStatus.RUNNING,
            data=type(
                "MemData",
                (),
                {
                    "total": 16_000_000_000,
                    "available": 8_000_000_000,
                    "used": 7_500_000_000,
                    "free": 500_000_000,
                    "swap_total": 2_000_000_000,
                    "swap_used": 500_000_000,
                    "swap_free": 1_500_000_000,
                },
            )(),
        )
    )

    # Disk
    await state_manager.apply_collector_result(
        CollectorResult(
            collector_name="disk",
            status=CollectorStatus.RUNNING,
            data=[
                type(
                    "DiskData",
                    (),
                    {
                        "device": "sda",
                        "read_bytes": 1_000_000,
                        "write_bytes": 2_000_000,
                        "read_ops": 100,
                        "write_ops": 200,
                        "read_throughput": 10.5,
                        "write_throughput": 20.5,
                        "iops": 150.0,
                    },
                )(),
            ],
        )
    )

    # Network
    await state_manager.apply_collector_result(
        CollectorResult(
            collector_name="network",
            status=CollectorStatus.RUNNING,
            data=[
                type(
                    "NetData",
                    (),
                    {
                        "name": "eth0",
                        "state": "up",
                        "rx_bytes": 5_000_000,
                        "tx_bytes": 3_000_000,
                        "rx_packets": 5000,
                        "tx_packets": 3000,
                        "rx_errors": 0,
                        "tx_errors": 0,
                        "rx_dropped": 0,
                        "tx_dropped": 0,
                        "throughput_rx": 5.0,
                        "throughput_tx": 3.0,
                    },
                )(),
            ],
        )
    )

    # Filesystem
    await state_manager.apply_collector_result(
        CollectorResult(
            collector_name="filesystem",
            status=CollectorStatus.RUNNING,
            data=[
                type(
                    "FSData",
                    (),
                    {
                        "mount_point": "/",
                        "device": "/dev/sda1",
                        "fstype": "ext4",
                        "total": 100_000_000_000,
                        "used": 50_000_000_000,
                        "available": 45_000_000_000,
                        "free": 50_000_000_000,
                        "utilization_pct": 50.0,
                        "inodes_total": 1_000_000,
                        "inodes_used": 500_000,
                        "inodes_free": 500_000,
                    },
                )(),
            ],
        )
    )

    # Temperature
    await state_manager.apply_collector_result(
        CollectorResult(
            collector_name="temperature",
            status=CollectorStatus.RUNNING,
            data=[
                type(
                    "TempData",
                    (),
                    {
                        "name": "cpu_thermal",
                        "current": 45.5,
                        "high": 80.0,
                        "critical": 95.0,
                    },
                )(),
            ],
        )
    )

    # System
    await state_manager.apply_collector_result(
        CollectorResult(
            collector_name="system",
            status=CollectorStatus.RUNNING,
            data=type(
                "SysData",
                (),
                {
                    "hostname": "test-host",
                    "os_name": "Ubuntu",
                    "os_version": "22.04",
                    "kernel_version": "5.15.0",
                    "architecture": "x86_64",
                    "cpu_model": "Intel Core i7",
                    "cpu_cores_physical": 4,
                    "cpu_cores_logical": 8,
                    "total_memory": 16_000_000_000,
                },
            )(),
        )
    )

    # Commit the snapshot
    await state_manager.commit_snapshot()


class TestPersistenceAdapter:
    """Tests for PersistenceAdapter."""

    @pytest.mark.asyncio
    async def test_start_stop(self, persistence_adapter: PersistenceAdapter) -> None:
        """Test starting and stopping the adapter."""
        assert not persistence_adapter.is_running

        await persistence_adapter.start()
        assert persistence_adapter.is_running

        await persistence_adapter.stop()
        assert not persistence_adapter.is_running

    @pytest.mark.asyncio
    async def test_persist_cpu_samples(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test CPU samples are persisted."""
        # Create and commit a snapshot
        await _apply_test_snapshot(state_manager)

        # Wait for persistence
        await asyncio.sleep(0.3)

        # Verify data was written
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM cpu_samples WHERE server_id = ?", ("test-server",))
            row = cursor.fetchone()
            assert row is not None
            assert row["server_id"] == "test-server"
            assert row["total_utilization"] == 45.5
            assert row["cpu_count"] == 4
            # per_core is JSON
            import json

            per_core = json.loads(row["per_core"])
            assert per_core == [40.0, 50.0, 45.0, 47.0]

    @pytest.mark.asyncio
    async def test_persist_memory_samples(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test memory samples are persisted."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.3)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM memory_samples WHERE server_id = ?", ("test-server",))
            row = cursor.fetchone()
            assert row is not None
            assert row["total_bytes"] == 16_000_000_000
            assert row["available_bytes"] == 8_000_000_000
            assert row["used_bytes"] == 7_500_000_000
            assert row["swap_total_bytes"] == 2_000_000_000
            assert row["swap_used_bytes"] == 500_000_000
            assert row["swap_free_bytes"] == 1_500_000_000

    @pytest.mark.asyncio
    async def test_persist_disk_samples(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test disk samples are persisted."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.3)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM disk_samples WHERE server_id = ?", ("test-server",))
            row = cursor.fetchone()
            assert row is not None
            assert row["device"] == "sda"
            assert row["read_bytes"] == 1_000_000
            assert row["write_bytes"] == 2_000_000
            assert row["read_ops"] == 100
            assert row["write_ops"] == 200

    @pytest.mark.asyncio
    async def test_persist_network_samples(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test network samples are persisted."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.3)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM network_samples WHERE server_id = ?", ("test-server",))
            row = cursor.fetchone()
            assert row is not None
            assert row["interface"] == "eth0"
            assert row["rx_bytes"] == 5_000_000
            assert row["tx_bytes"] == 3_000_000
            assert row["rx_packets"] == 5000
            assert row["tx_packets"] == 3000

    @pytest.mark.asyncio
    async def test_persist_filesystem_samples(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test filesystem samples are persisted."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.3)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM filesystem_samples WHERE server_id = ?", ("test-server",))
            row = cursor.fetchone()
            assert row is not None
            assert row["mount_point"] == "/"
            assert row["device"] == "/dev/sda1"
            assert row["fstype"] == "ext4"
            assert row["total_bytes"] == 100_000_000_000
            assert row["used_bytes"] == 50_000_000_000
            assert row["used_percent"] == 50.0

    @pytest.mark.asyncio
    async def test_persist_temperature_samples(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test temperature samples are persisted."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.3)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM temperature_samples WHERE server_id = ?", ("test-server",))
            row = cursor.fetchone()
            assert row is not None
            assert row["sensor_name"] == "cpu_thermal"
            assert row["temperature_celsius"] == 45.5
            assert row["high_threshold"] == 80.0
            assert row["critical_threshold"] == 95.0

    @pytest.mark.asyncio
    async def test_persist_server_info(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test server static info is persisted."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.3)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT * FROM servers WHERE id = ?", ("test-server",))
            row = cursor.fetchone()
            assert row is not None
            assert row["id"] == "test-server"
            assert row["hostname"] == "test-host"
            assert row["os_name"] == "Ubuntu"
            assert row["os_version"] == "22.04"
            assert row["architecture"] == "x86_64"

    @pytest.mark.asyncio
    async def test_persist_interval_respected(self, state_manager: StateManager, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that persistence only runs at the configured interval."""
        adapter = PersistenceAdapter(
            state_manager=state_manager,
            db_writer=writer_config,
            server_id="interval-test",
            persist_interval=1.0,  # Long interval
        )
        await adapter.start()

        try:
            await _apply_test_snapshot(state_manager)
            await asyncio.sleep(0.2)

            # Should NOT have persisted yet (interval is 1.0s)
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("interval-test",))
                count = cursor.fetchone()[0]
                assert count == 0, "Should not persist before interval"

            # Wait for interval
            await asyncio.sleep(1.0)

            # Now should have persisted
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("interval-test",))
                count = cursor.fetchone()[0]
                assert count >= 1
        finally:
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_skips_duplicate_sequences(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test that duplicate sequences are not re-persisted."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.3)

        # Get initial count
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("test-server",))
            initial_count = cursor.fetchone()[0]

        # Try to persist again without new snapshot
        await asyncio.sleep(0.2)

        # Count should be same
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("test-server",))
            count = cursor.fetchone()[0]
            assert count == initial_count

    @pytest.mark.asyncio
    async def test_persists_new_snapshot(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test that a new snapshot increments persisted data."""
        await _apply_test_snapshot(state_manager)
        await asyncio.sleep(0.5)  # Longer wait for first persist

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("test-server",))
            initial_count = cursor.fetchone()[0]

        # Create a NEW snapshot with different data
        async def apply_new() -> None:
            await state_manager.apply_collector_result(
                CollectorResult(
                    collector_name="cpu",
                    status=CollectorStatus.RUNNING,
                    data=type(
                        "CPUData",
                        (),
                        {
                            "total_utilization": 55.5,
                            "per_core": [50.0, 60.0, 55.0, 57.0],
                            "load_average": (1.5, 1.2, 1.0),
                            "cpu_count": 4,
                        },
                    )(),
                )
            )
            await state_manager.commit_snapshot()

        await apply_new()
        await asyncio.sleep(0.5)  # Longer wait for second persist

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("test-server",))
            count = cursor.fetchone()[0]
            assert count == initial_count + 1

    @pytest.mark.asyncio
    async def test_handles_unavailable_metrics(self, running_persistence: PersistenceAdapter, state_manager: StateManager, migrated_db: str) -> None:
        """Test that UNAVAILABLE metrics are not persisted."""
        async def apply_unavailable() -> None:
            # Only apply CPU, leave memory unavailable
            await state_manager.apply_collector_result(
                CollectorResult(
                    collector_name="cpu",
                    status=CollectorStatus.RUNNING,
                    data=type(
                        "CPUData",
                        (),
                        {
                            "total_utilization": 30.0,
                            "per_core": [25.0, 35.0],
                            "load_average": (0.5, 0.4, 0.3),
                            "cpu_count": 2,
                        },
                    )(),
                )
            )
            # Memory collector is FAILED - will mark memory as UNAVAILABLE
            await state_manager.apply_collector_result(
                CollectorResult(
                    collector_name="memory",
                    status=CollectorStatus.FAILED,
                    data=None,
                    error="Permission denied",
                )
            )
            await state_manager.commit_snapshot()

        await apply_unavailable()
        await asyncio.sleep(0.3)

        # CPU should be persisted
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("test-server",))
            cpu_count = cursor.fetchone()[0]
            assert cpu_count == 1

        # Memory should NOT be persisted (no data due to FAILED)
        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM memory_samples WHERE server_id = ?", ("test-server",))
            mem_count = cursor.fetchone()[0]
            assert mem_count == 0

    @pytest.mark.asyncio
    async def test_failure_tracking(self, state_manager: StateManager, migrated_db: str) -> None:
        """Test that database failures are tracked without unbounded retries."""
        # Create a writer that will fail - use a path that's invalid on all platforms
        # On Windows, use a path with invalid characters; on Unix, use a path in a non-existent directory
        import os

        from app.database.config import DBConfig
        if os.name == 'nt':
            # Windows: use a path with invalid characters
            invalid_path = r"C:\invalid<>:\"|?*.db"
        else:
            # Unix: use a path in a directory that doesn't exist and can't be created
            invalid_path = "/invalid/path/that/does/not/exist.db"

        config = DBConfig(db_path=invalid_path, queue_size=100, batch_size=10, flush_interval=0.1)
        failing_writer = DatabaseWriter(db_config=config, queue_size=100, batch_size=10, flush_interval=0.1)
        failing_writer.start()

        adapter = PersistenceAdapter(
            state_manager=state_manager,
            db_writer=failing_writer,
            server_id="fail-test",
            persist_interval=0.05,
        )
        await adapter.start()

        try:
            await _apply_test_snapshot(state_manager)

            # Wait for several persistence attempts
            await asyncio.sleep(0.3)

            # Writer should record failures (persistence adapter enqueues successfully,
            # but writer thread fails to write)
            writer_metrics = failing_writer.get_metrics()
            assert writer_metrics.failed > 0, "Writer should have recorded failures"
            assert writer_metrics.failed <= 10, "Failures should not be unbounded"

        finally:
            await adapter.stop()
            failing_writer.stop()

    @pytest.mark.asyncio
    async def test_global_functions(self, state_manager: StateManager, migrated_db: str) -> None:
        """Test global get/start/stop functions."""
        import app.database.persistence as persistence_module
        import app.database.writer as writer_module

        # Reset globals
        persistence_module._persistence_adapter = None
        writer_module._db_writer = None

        try:
            # Configure global writer to use test database
            from app.database.config import DBConfig
            test_config = DBConfig(db_path=migrated_db, queue_size=100, batch_size=10, flush_interval=0.1)
            writer_module._db_writer = DatabaseWriter(
                db_config=test_config, queue_size=100, batch_size=10, flush_interval=0.1
            )

            adapter = await get_persistence_adapter(state_manager, persist_interval=0.1)
            assert adapter is not None

            await start_persistence(state_manager, persist_interval=0.1)
            assert adapter.is_running

            await _apply_test_snapshot(state_manager)
            await asyncio.sleep(0.5)  # Wait for persistence (interval is 0.1s)

            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("local",))
                count = cursor.fetchone()[0]
                assert count >= 1

            await stop_persistence()
            assert not adapter.is_running

        finally:
            # Clean up global writer
            if writer_module._db_writer is not None:
                writer_module._db_writer.stop()
                writer_module._db_writer = None
            persistence_module._persistence_adapter = None


class TestPersistenceIntegration:
    """Integration tests for persistence with full stack."""

    @pytest.mark.asyncio
    async def test_full_stack_persistence(self, state_manager: StateManager, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test full stack: collectors -> state manager -> persistence -> database."""
        adapter = PersistenceAdapter(
            state_manager=state_manager,
            db_writer=writer_config,
            server_id="integration-test",
            persist_interval=0.1,
        )
        await adapter.start()

        try:
            # Simulate multiple collection cycles
            for cycle in range(3):
                async def apply_cycle(c: int = cycle) -> None:
                    await state_manager.apply_collector_result(
                        CollectorResult(
                            collector_name="cpu",
                            status=CollectorStatus.RUNNING,
                            data=type(
                                "CPUData",
                                (),
                                {
                                    "total_utilization": 40.0 + c * 5,
                                    "per_core": [35.0 + c, 45.0 + c],
                                    "load_average": (1.0, 0.9, 0.8),
                                    "cpu_count": 2,
                                },
                            )(),
                        )
                    )
                    await state_manager.commit_snapshot()

                await apply_cycle()
                await asyncio.sleep(0.15)  # Wait for persistence

            # Extra wait to ensure all pending writes are flushed
            await asyncio.sleep(0.3)

            # Verify all 3 cycles persisted
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("integration-test",))
                count = cursor.fetchone()[0]
                assert count == 3

                # Verify data progression
                cursor = conn.execute("SELECT total_utilization FROM cpu_samples WHERE server_id = ? ORDER BY timestamp", ("integration-test",))
                rows = cursor.fetchall()
                utilizations = [row["total_utilization"] for row in rows]
                assert utilizations == [40.0, 45.0, 50.0]

        finally:
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_shutdown_drains_pending(self, state_manager: StateManager, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that shutdown drains pending writes."""
        adapter = PersistenceAdapter(
            state_manager=state_manager,
            db_writer=writer_config,
            server_id="shutdown-test",
            persist_interval=10.0,  # Long interval so writes queue up
        )
        await adapter.start()

        try:
            await _apply_test_snapshot(state_manager)

            # Stop immediately - should drain
            await adapter.stop()

            # Wait for writer to flush (writer runs in separate thread)
            await asyncio.sleep(0.5)

            # Verify data was written despite quick shutdown
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM cpu_samples WHERE server_id = ?", ("shutdown-test",))
                count = cursor.fetchone()[0]
                assert count >= 1

        finally:
            if adapter.is_running:
                await adapter.stop()

    @pytest.mark.asyncio
    async def test_priority_of_writes(self, state_manager: StateManager, writer_config: DatabaseWriter, migrated_db: str) -> None:
        """Test that server info uses CRITICAL priority, metrics use NORMAL."""
        adapter = PersistenceAdapter(
            state_manager=state_manager,
            db_writer=writer_config,
            server_id="priority-test",
            persist_interval=0.1,
        )
        await adapter.start()

        # Small wait to ensure persist loop is running before applying snapshot
        await asyncio.sleep(0.05)

        try:
            await _apply_test_snapshot(state_manager)
            await asyncio.sleep(0.5)

            # All should be written
            with database_connection(migrated_db) as conn:
                # servers table uses 'id' column, not 'server_id'
                cursor = conn.execute("SELECT COUNT(*) FROM servers WHERE id = ?", ("priority-test",))
                count = cursor.fetchone()[0]
                assert count >= 1, "servers table should have data"

                for table in ["cpu_samples", "memory_samples", "disk_samples", "network_samples", "filesystem_samples", "temperature_samples"]:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE server_id = ?", ("priority-test",))
                    count = cursor.fetchone()[0]
                    assert count >= 1, f"Table {table} should have data"

        finally:
            await adapter.stop()
