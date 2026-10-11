"""Tests for database migration framework."""

import importlib
import sqlite3
from pathlib import Path

import pytest

from app.database.connection import database_connection
from app.database.migrations import (
    MIGRATION_0001_STATEMENTS,
    SUPPORTED_VERSION,
    MigrationError,
    _has_application_tables,
    _validate_schema_v1,
    run_migrations,
)


class TestMigrationSuccess:
    """Tests for successful migration scenarios."""

    def test_fresh_database_migration_succeeds(self, temp_db: str) -> None:
        """Migration on fresh database succeeds."""
        version = run_migrations(temp_db)
        assert version == SUPPORTED_VERSION

    def test_version_recorded_after_schema_creation(self, temp_db: str) -> None:
        """Version 1 is recorded only after all schema statements succeed."""
        run_migrations(temp_db)
        with database_connection(temp_db) as conn:
            cursor = conn.execute("SELECT version FROM schema_metadata")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 1

    def test_idempotent_rerun(self, migrated_db: str) -> None:
        """Re-running migration on valid v1 database is a no-op."""
        version1 = run_migrations(migrated_db)
        version2 = run_migrations(migrated_db)
        assert version1 == version2 == SUPPORTED_VERSION

    def test_complete_v1_database_noop(self, migrated_db: str) -> None:
        """Complete version-1 database remains an idempotent no-op."""
        # Already validated by migrated_db fixture
        version = run_migrations(migrated_db)
        assert version == 1


class TestMigrationFailureHandling:
    """Tests for migration failure and rollback scenarios."""

    def test_unsupported_newer_version_rejected(self, temp_db: str) -> None:
        """Database with version > supported is rejected."""
        # Manually create a schema_metadata with version 2
        with database_connection(temp_db) as conn:
            conn.execute("CREATE TABLE schema_metadata (version INTEGER PRIMARY KEY, applied_at TIMESTAMP, description TEXT)")
            conn.execute("INSERT INTO schema_metadata (version, description) VALUES (2, 'Future version')")

        with pytest.raises(MigrationError, match="Database version 2 > supported 1"):
            run_migrations(temp_db)

    def test_pre_existing_tables_without_metadata_rejected(self, temp_db: str) -> None:
        """Database with app tables but no schema_metadata is rejected."""
        with database_connection(temp_db) as conn:
            # Create one app table but not schema_metadata
            conn.execute("CREATE TABLE servers (id TEXT PRIMARY KEY)")

        with pytest.raises(MigrationError, match="application tables but no schema_metadata"):
            run_migrations(temp_db)

    def test_version1_missing_table_rejected(self, temp_db: str) -> None:
        """Version-1 database missing required table is rejected."""
        # Create schema_metadata with version 1 but incomplete tables
        with database_connection(temp_db) as conn:
            conn.execute("CREATE TABLE schema_metadata (version INTEGER PRIMARY KEY, applied_at TIMESTAMP, description TEXT)")
            conn.execute("INSERT INTO schema_metadata (version, description) VALUES (1, 'Initial schema')")
            # Only create some tables
            conn.execute("CREATE TABLE servers (id TEXT PRIMARY KEY)")

        with pytest.raises(MigrationError, match="required tables/indexes are missing"):
            run_migrations(temp_db)

    def test_version1_missing_index_rejected(self, temp_db: str) -> None:
        """Version-1 database missing required index is rejected."""
        # Create all tables but skip one index
        with database_connection(temp_db) as conn:
            # Run almost all migration statements but skip one index
            for stmt in MIGRATION_0001_STATEMENTS:
                if "idx_cpu_samples_server_time" not in stmt:
                    conn.execute(stmt)

        with pytest.raises(MigrationError, match="required tables/indexes are missing"):
            run_migrations(temp_db)


class TestTransactionRollback:
    """Tests for transactional rollback on failure."""

    def test_injected_failure_rolls_back_completely(self, temp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Inject a deterministic SQL failure by temporarily replacing
        MIGRATION_0001_STATEMENTS with a sequence containing an invalid
        statement after several valid DDL statements. Exercise the real
        migration runner and verify complete rollback.
        """
        from app.database import migrations as migration_module

        # Save original statements
        original_statements = migration_module.MIGRATION_0001_STATEMENTS

        # Build a modified statement list: first N valid statements, then a syntax error
        # Use first 6 statements (schema_metadata table + servers table + hostname index +
        # cpu_samples table + cpu_samples index + memory_samples table) then inject invalid SQL
        valid_prefix = original_statements[:6]
        # Syntax error: missing closing parenthesis
        invalid_stmt = "CREATE TABLE invalid_table (id INTEGER PRIMARY KEY, bad_column THIS_IS_NOT_A_VALID_TYPE;"
        modified_statements = valid_prefix + [invalid_stmt] + original_statements[6:]

        # Monkeypatch the module's statement list
        monkeypatch.setattr(migration_module, 'MIGRATION_0001_STATEMENTS', modified_statements)

        # Run migration through the REAL runner - should fail with SQLite error
        with pytest.raises(sqlite3.OperationalError):
            run_migrations(temp_db)

        # Verify rollback: no tables, no indexes, no schema_metadata table at all
        with database_connection(temp_db) as conn:
            # Check tables
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            assert tables == set(), f"Expected no tables after rollback, got {tables}"

            # Check indexes
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}
            assert indexes == set(), f"Expected no indexes after rollback, got {indexes}"

            # Check schema_metadata table does not exist (via sqlite_master)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_metadata'")
            assert cursor.fetchone() is None, "schema_metadata table should not exist after rollback"

        # Restore original statements
        monkeypatch.setattr(migration_module, 'MIGRATION_0001_STATEMENTS', original_statements)

        # Second attempt: normal migration should succeed completely
        version = run_migrations(temp_db)
        assert version == SUPPORTED_VERSION

        # Verify 10 application tables + schema_metadata = 11 tables exist
        # (sqlite_sequence makes 12 total in sqlite_master)
        with database_connection(temp_db) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            required_tables = {
                "servers", "cpu_samples", "memory_samples", "disk_samples",
                "network_samples", "filesystem_samples", "temperature_samples",
                "events", "alerts", "metric_rollups", "schema_metadata"
            }
            assert required_tables.issubset(tables), f"Missing tables: {required_tables - tables}"

            # Verify all 20 indexes exist
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
            indexes = {row[0] for row in cursor.fetchall()}
            required_indexes = {
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
            assert required_indexes.issubset(indexes), f"Missing indexes: {required_indexes - indexes}"

            # Verify schema version is 1
            cursor = conn.execute("SELECT version FROM schema_metadata")
            assert cursor.fetchone()[0] == 1

    def test_retry_after_rollback_succeeds(self, temp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """After a rollback, retrying migration succeeds (separate verification)."""
        from app.database import migrations as migration_module

        # Use a different failure point to test retry scenario independently
        original_statements = migration_module.MIGRATION_0001_STATEMENTS
        valid_prefix = original_statements[:3]  # schema_metadata, servers, servers index
        # Syntax error: missing closing parenthesis
        invalid_stmt = "CREATE TABLE another_invalid (x BADTYPE;"
        modified_statements = valid_prefix + [invalid_stmt] + original_statements[3:]

        monkeypatch.setattr(migration_module, 'MIGRATION_0001_STATEMENTS', modified_statements)

        # First attempt: should fail and rollback
        with pytest.raises(sqlite3.OperationalError):
            run_migrations(temp_db)

        # Verify rollback occurred
        with database_connection(temp_db) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            assert tables == set()

        # Restore and retry
        monkeypatch.setattr(migration_module, 'MIGRATION_0001_STATEMENTS', original_statements)
        version = run_migrations(temp_db)
        assert version == SUPPORTED_VERSION

        # Verify all tables and version exist
        with database_connection(temp_db) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            assert "servers" in tables
            assert "cpu_samples" in tables
            assert "schema_metadata" in tables
            cursor = conn.execute("SELECT version FROM schema_metadata")
            assert cursor.fetchone()[0] == 1


class TestMigrationValidation:
    """Tests for schema validation after migration."""

    def test_validate_schema_v1_passes(self, migrated_db: str) -> None:
        """_validate_schema_v1 returns True for complete schema."""
        with database_connection(migrated_db) as conn:
            assert _validate_schema_v1(conn) is True

    def test_validate_schema_v1_fails_missing_table(self, temp_db: str) -> None:
        """_validate_schema_v1 returns False when table is missing."""
        with database_connection(temp_db) as conn:
            conn.execute("CREATE TABLE schema_metadata (version INTEGER PRIMARY KEY, applied_at TIMESTAMP, description TEXT)")
            conn.execute("INSERT INTO schema_metadata (version, description) VALUES (1, 'test')")
            # Missing all other tables
            assert _validate_schema_v1(conn) is False

    def test_validate_schema_v1_fails_missing_index(self, temp_db: str) -> None:
        """_validate_schema_v1 returns False when index is missing."""
        with database_connection(temp_db) as conn:
            # Create schema_metadata and one table but no indexes
            conn.execute("CREATE TABLE schema_metadata (version INTEGER PRIMARY KEY, applied_at TIMESTAMP, description TEXT)")
            conn.execute("INSERT INTO schema_metadata (version, description) VALUES (1, 'test')")
            conn.execute("CREATE TABLE servers (id TEXT PRIMARY KEY, hostname TEXT)")
            assert _validate_schema_v1(conn) is False

    def test_has_application_tables(self, temp_db: str) -> None:
        """_has_application_tables detects ServerWatch tables."""
        with database_connection(temp_db) as conn:
            # Empty DB
            assert _has_application_tables(conn) is False

            # Add one app table
            conn.execute("CREATE TABLE cpu_samples (id INTEGER PRIMARY KEY)")
            assert _has_application_tables(conn) is True

    def test_schema_metadata_not_counted_as_app_table(self, temp_db: str) -> None:
        """schema_metadata alone doesn't trigger _has_application_tables."""
        with database_connection(temp_db) as conn:
            conn.execute("CREATE TABLE schema_metadata (version INTEGER PRIMARY KEY)")
            assert _has_application_tables(conn) is False


class TestMigrationIdempotence:
    """Additional idempotence tests."""

    def test_migration_statements_execute_in_order(self, temp_db: str) -> None:
        """All MIGRATION_0001_STATEMENTS execute without error."""
        run_migrations(temp_db)

        with database_connection(temp_db) as conn:
            # Count tables created (10 application tables + schema_metadata = 11,
            # plus sqlite_sequence internal table = 12)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            table_count = cursor.fetchone()[0]
            assert table_count == 12

    def test_no_duplicate_schema_metadata_on_rerun(self, migrated_db: str) -> None:
        """Re-running doesn't create duplicate schema_metadata entries."""
        run_migrations(migrated_db)
        run_migrations(migrated_db)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM schema_metadata")
            assert cursor.fetchone()[0] == 1

    def test_version_remains_1_after_rerun(self, migrated_db: str) -> None:
        """Version stays at 1 after multiple runs."""
        for _ in range(5):
            version = run_migrations(migrated_db)
            assert version == 1


class TestMigrationEdgeCases:
    """Edge case tests."""

    def test_empty_database_path_uses_config_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """run_migrations() without path uses config default database path."""
        # Create an isolated temporary database path
        isolated_db = tmp_path / "isolated" / "serverwatch.db"
        db_path = str(isolated_db)

        # Override the config default via environment variable
        monkeypatch.setenv("DATABASE_PATH", db_path)

        # Need to reload settings to pick up the new env var
        from app import config as app_config
        importlib.reload(app_config)

        from app.database.migrations import run_migrations as run_migrations_fresh

        # Run migration without explicit path - should use config default
        version = run_migrations_fresh()
        assert version == SUPPORTED_VERSION

        # Verify database was created at the config default path
        assert isolated_db.exists(), f"Database not created at {db_path}"

        # Verify schema is correct
        from app.database.connection import database_connection
        with database_connection(db_path) as conn:
            cursor = conn.execute("SELECT version FROM schema_metadata")
            assert cursor.fetchone()[0] == 1

    def test_database_creation_creates_parent_directories(self, tmp_path: Path) -> None:
        """database_connection creates parent directories if they don't exist."""
        # Path with non-existent parent directories
        db_path = tmp_path / "deep" / "nested" / "parent" / "test.db"
        assert not db_path.parent.exists()

        # Open connection - should create parent directories
        from app.database.connection import database_connection
        with database_connection(str(db_path)) as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")

        # Verify database file and parent directories were created
        assert db_path.exists(), f"Database not created at {db_path}"
        assert db_path.parent.exists(), "Parent directory not created"

        # Verify we can read back the data
        with database_connection(str(db_path)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test")
            assert cursor.fetchone()[0] == 0

    def test_migration_error_inherits_exception(self) -> None:
        """MigrationError is an Exception."""
        assert issubclass(MigrationError, Exception)

    def test_supported_version_is_1(self) -> None:
        """SUPPORTED_VERSION constant is 1."""
        assert SUPPORTED_VERSION == 1
