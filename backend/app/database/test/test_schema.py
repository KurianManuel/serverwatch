"""Tests for database schema creation and validation."""

import sqlite3
from collections.abc import Callable

import pytest

from app.database.connection import database_connection
from app.database.migrations import _has_application_tables, _validate_schema_v1, run_migrations

REQUIRED_TABLES = {
    "servers", "cpu_samples", "memory_samples", "disk_samples",
    "network_samples", "filesystem_samples", "temperature_samples",
    "events", "alerts", "metric_rollups", "schema_metadata"
}

REQUIRED_INDEXES = {
    "idx_servers_hostname",
    "idx_cpu_samples_server_time",
    "idx_memory_samples_server_time",
    "idx_disk_samples_server_time", "idx_disk_samples_device",
    "idx_network_samples_server_time", "idx_network_samples_interface",
    "idx_filesystem_samples_server_time", "idx_filesystem_samples_mount",
    "idx_temperature_samples_server_time", "idx_temperature_samples_sensor",
    "idx_events_server_time", "idx_events_type", "idx_events_severity",
    "idx_alerts_server_time", "idx_alerts_state", "idx_alerts_rule",
    "idx_rollups_server_metric_time", "idx_rollups_interval", "idx_rollups_unique",
}


class TestSchemaCreation:
    """Tests for schema creation and completeness."""

    def test_all_tables_exist(self, db_connection: sqlite3.Connection) -> None:
        """Verify all 10 application tables plus schema_metadata are created."""
        cursor = db_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert REQUIRED_TABLES.issubset(tables), f"Missing tables: {REQUIRED_TABLES - tables}"

    def test_all_indexes_exist(self, db_connection: sqlite3.Connection) -> None:
        """Verify all required indexes are created."""
        cursor = db_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert REQUIRED_INDEXES.issubset(indexes), f"Missing indexes: {REQUIRED_INDEXES - indexes}"

    def test_foreign_keys_enforced(self, db_connection: sqlite3.Connection) -> None:
        """Verify foreign key constraints are enforced."""
        # Try to insert a sample with non-existent server_id
        with pytest.raises(sqlite3.IntegrityError):
            db_connection.execute(
                "INSERT INTO cpu_samples (server_id, timestamp, per_core) VALUES (?, ?, ?)",
                ("non-existent-uuid", "2026-01-01T00:00:00Z", "[]")
            )

    def test_column_types_correct(
        self, db_connection: sqlite3.Connection, get_table_columns: Callable[[sqlite3.Connection, str], list[str]]
) -> None:
        """Verify key columns have correct types."""
        # Check servers table
        server_cols = get_table_columns(db_connection, "servers")
        assert "id" in server_cols
        assert "hostname" in server_cols
        assert "created_at" in server_cols

        # Check cpu_samples has required columns
        cpu_cols = get_table_columns(db_connection, "cpu_samples")
        assert "id" in cpu_cols
        assert "server_id" in cpu_cols
        assert "timestamp" in cpu_cols
        assert "total_utilization" in cpu_cols
        assert "per_core" in cpu_cols
        assert "cpu_count" in cpu_cols

        # Check memory_samples has required columns
        mem_cols = get_table_columns(db_connection, "memory_samples")
        assert "total_bytes" in mem_cols
        assert "available_bytes" in mem_cols
        assert "used_bytes" in mem_cols

        # Check metric_rollups has required columns
        rollup_cols = get_table_columns(db_connection, "metric_rollups")
        assert "metric_name" in rollup_cols
        assert "interval_type" in rollup_cols
        assert "window_start" in rollup_cols
        assert "window_end" in rollup_cols
        assert "count" in rollup_cols
        assert "min_value" in rollup_cols
        assert "avg_value" in rollup_cols
        assert "max_value" in rollup_cols

    def test_migration_idempotent(self, migrated_db: str) -> None:
        """Verify running migration twice is a no-op."""
        # First run already done by fixture
        version1 = run_migrations(migrated_db)
        # Second run
        version2 = run_migrations(migrated_db)
        assert version1 == version2 == 1


class TestSchemaValidation:
    """Tests for schema validation logic."""

    def test_validate_schema_v1_passes(self, db_connection: sqlite3.Connection) -> None:
        """_validate_schema_v1 returns True for complete schema."""
        assert _validate_schema_v1(db_connection) is True

    def test_has_application_tables_detects_tables(self, db_connection: sqlite3.Connection) -> None:
        """_has_application_tables returns True when app tables exist."""
        assert _has_application_tables(db_connection) is True

    def test_has_application_tables_false_on_empty_db(self, temp_db: str) -> None:
        """_has_application_tables returns False on empty database."""
        with database_connection(temp_db) as conn:
            assert _has_application_tables(conn) is False
