"""Tests for database connection and PRAGMA settings."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.database.connection import _apply_pragmas, database_connection
from app.database.migrations import run_migrations


class TestConnectionPRAGMAs:
    """Tests for PRAGMA configuration."""

    def test_wal_mode_enabled(self, temp_db: str) -> None:
        """Verify WAL journal mode is enabled."""
        with database_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode == "wal", f"Expected WAL mode, got {mode}"

    def test_foreign_keys_on(self, temp_db: str) -> None:
        """Verify foreign keys are enabled."""
        with database_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA foreign_keys")
            fk = cursor.fetchone()[0]
            assert fk == 1, f"Expected foreign_keys=ON, got {fk}"

    def test_synchronous_normal(self, temp_db: str) -> None:
        """Verify synchronous=NORMAL."""
        with database_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA synchronous")
            sync = cursor.fetchone()[0]
            # 1 = NORMAL, 2 = FULL, 0 = OFF
            assert sync == 1, f"Expected synchronous=NORMAL (1), got {sync}"

    def test_busy_timeout_set(self, temp_db: str) -> None:
        """Verify busy_timeout is set to 5000ms."""
        with database_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA busy_timeout")
            timeout = cursor.fetchone()[0]
            assert timeout == 5000, f"Expected busy_timeout=5000, got {timeout}"

    def test_wal_autocheckpoint_set(self, temp_db: str) -> None:
        """Verify wal_autocheckpoint is set."""
        with database_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA wal_autocheckpoint")
            checkpoint = cursor.fetchone()[0]
            assert checkpoint == 1000, f"Expected wal_autocheckpoint=1000, got {checkpoint}"

    def test_mmap_size_set(self, temp_db: str) -> None:
        """Verify mmap_size is set to 256MB."""
        with database_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA mmap_size")
            mmap = cursor.fetchone()[0]
            assert mmap == 268435456, f"Expected mmap_size=268435456, got {mmap}"

    def test_row_factory_is_row(self, temp_db: str) -> None:
        """Verify row_factory is sqlite3.Row for dict-like access."""
        with database_connection(temp_db) as conn:
            assert conn.row_factory == sqlite3.Row

    def test_apply_pragmas_directly(self, temp_db: str) -> None:
        """Test _apply_pragmas function directly."""
        conn = sqlite3.connect(temp_db)
        _apply_pragmas(conn)
        cursor = conn.execute("PRAGMA journal_mode")
        assert cursor.fetchone()[0] == "wal"
        cursor = conn.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1
        conn.close()


class TestThreadIsolation:
    """Tests for thread isolation of connections."""

    def test_concurrent_connections(self, migrated_db: str) -> None:
        """Verify multiple threads can open connections concurrently."""
        def query_db() -> int:
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                row = cursor.fetchone()
                return row[0] if row else 0

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(query_db) for _ in range(20)]
            results = [f.result() for f in futures]

        # All should succeed and return table count >= 11 (10 app + schema_metadata; sqlite_sequence makes 12)
        assert all(r >= 11 for r in results), f"Some queries failed: {results}"

    def test_concurrent_read_write(self, migrated_db: str) -> None:
        """Verify readers don't block each other in WAL mode."""
        # In WAL mode, multiple readers can coexist with a single writer
        # This is a basic sanity check
        def read_tables() -> list[str]:
            with database_connection(migrated_db) as conn:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                return [row[0] for row in cursor.fetchall()]

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(read_tables) for _ in range(10)]
            results = [f.result() for f in futures]

        for tables in results:
            assert "servers" in tables
            assert "cpu_samples" in tables


class TestConnectionBehavior:
    """Tests for connection behavior."""

    def test_connection_closes_properly(self, temp_db: str) -> None:
        """Verify connections are properly closed after context exit."""
        conn_ref = []

        with database_connection(temp_db) as conn:
            conn_ref.append(conn)

        # Connection should be closed - verify by attempting operation
        with pytest.raises(sqlite3.ProgrammingError):
            conn_ref[0].execute("SELECT 1")

    def test_migrations_apply_pragmas(self, temp_db: str) -> None:
        """Verify migrations run with PRAGMAs applied."""
        version = run_migrations(temp_db)
        assert version == 2

        # Verify PRAGMAs still work after migration
        with database_connection(temp_db) as conn:
            cursor = conn.execute("PRAGMA journal_mode")
            assert cursor.fetchone()[0] == "wal"
            cursor = conn.execute("PRAGMA foreign_keys")
            assert cursor.fetchone()[0] == 1
