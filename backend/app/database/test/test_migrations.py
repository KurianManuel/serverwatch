"""Tests for database migration framework."""

import importlib
import sqlite3
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from app.database.connection import database_connection
from app.database.migrations import (
    MIGRATION_0001_STATEMENTS,
    SUPPORTED_VERSION,
    MigrationError,
    _has_application_tables,
    _validate_schema_v1,
    _validate_schema_v2,
    run_migrations,
)


def _create_v1_database(db_path: str) -> None:
    """Create a valid version 1 database by running only v1 migration."""
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE TRANSACTION;")
        for stmt in MIGRATION_0001_STATEMENTS:
            conn.execute(stmt)
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


def _create_v1_db_with_schema_metadata_v1(db_path: str) -> None:
    """Create a database with schema_metadata version 1 and all v1 tables."""
    _create_v1_database(db_path)
    # Ensure version is set to 1
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("UPDATE schema_metadata SET version = 1")
    finally:
        conn.close()


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        yield db_path
    finally:
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def v1_database(temp_db: str) -> str:
    """Create a valid version 1 database."""
    _create_v1_database(temp_db)
    return temp_db


@pytest.fixture
def v1_database_with_version(temp_db: str) -> str:
    """Create a v1 database with explicit version 1 in schema_metadata."""
    _create_v1_database(temp_db)
    conn = sqlite3.connect(temp_db, isolation_level=None)
    try:
        conn.execute("UPDATE schema_metadata SET version = 1")
    finally:
        conn.close()
    return temp_db


@pytest.fixture
def v2_database(temp_db: str) -> str:
    """Create a valid version 2 database (full migration)."""
    from app.database.migrations import run_migrations
    run_migrations(temp_db)
    return temp_db


@pytest.fixture
def migrated_db(temp_db: str) -> str:
    """Create a database with migrations applied (latest version)."""
    from app.database.migrations import run_migrations
    run_migrations(temp_db)
    return temp_db


# ... existing test classes ...


class TestMigrationSuccess:
    """Tests for successful migration scenarios."""

    def test_fresh_database_migration_succeeds(self, temp_db: str) -> None:
        """Migration on fresh database succeeds to version 2."""
        version = run_migrations(temp_db)
        assert version == SUPPORTED_VERSION
        assert version == 2

    def test_version_recorded_after_schema_creation(self, temp_db: str) -> None:
        """Version 2 is recorded only after all schema statements succeed."""
        run_migrations(temp_db)
        with database_connection(temp_db) as conn:
            cursor = conn.execute("SELECT version FROM schema_metadata")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 2

    def test_idempotent_rerun(self, migrated_db: str) -> None:
        """Re-running migration on valid v2 database is a no-op."""
        version1 = run_migrations(migrated_db)
        version2 = run_migrations(migrated_db)
        assert version1 == version2 == SUPPORTED_VERSION

    def test_complete_v2_database_noop(self, migrated_db: str) -> None:
        """Complete version-2 database remains an idempotent no-op."""
        version = run_migrations(migrated_db)
        assert version == SUPPORTED_VERSION
        assert version == 2


class TestMigrationFailureHandling:
    """Tests for migration failure and rollback scenarios."""

    def test_unsupported_newer_version_rejected(self, temp_db: str) -> None:
        """Database with version > supported is rejected."""
        # Manually create a schema_metadata with version 3
        with database_connection(temp_db) as conn:
            conn.execute("CREATE TABLE schema_metadata (version INTEGER PRIMARY KEY, applied_at TIMESTAMP, description TEXT)")
            conn.execute("INSERT INTO schema_metadata (version, description) VALUES (3, 'Future version')")

        with pytest.raises(MigrationError, match="Database version 3 > supported 2"):
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
        # Create a valid v1 database
        _create_v1_database(temp_db)
        # Corrupt it by dropping a required table
        with database_connection(temp_db) as conn:
            conn.execute("DROP TABLE cpu_samples")

        with pytest.raises(MigrationError, match="schema validation failed"):
            run_migrations(temp_db)

    def test_version1_missing_index_rejected(self, temp_db: str) -> None:
        """Version-1 database missing required index is rejected."""
        # Create a valid v1 database
        _create_v1_database(temp_db)
        # Corrupt it by dropping a required index
        with database_connection(temp_db) as conn:
            conn.execute("DROP INDEX idx_cpu_samples_server_time")

        with pytest.raises(MigrationError, match="schema validation failed"):
            run_migrations(temp_db)

    def test_version2_missing_table_rejected(self, temp_db: str) -> None:
        """Version-2 database missing required table is rejected."""
        # Create a valid v1 database
        _create_v1_database(temp_db)
        # Set version to 2 but missing event_deduplication table
        with database_connection(temp_db) as conn:
            conn.execute("UPDATE schema_metadata SET version = 2")

        with pytest.raises(MigrationError, match="required tables/indexes are missing"):
            run_migrations(temp_db)

    def test_version2_missing_deduplication_table_rejected(self, temp_db: str) -> None:
        """Version-2 database missing event_deduplication table is rejected."""
        _create_v1_database(temp_db)
        with database_connection(temp_db) as conn:
            conn.execute("UPDATE schema_metadata SET version = 2")
            # Drop the event_deduplication table if it exists
            conn.execute("DROP TABLE IF EXISTS event_deduplication")

        with pytest.raises(MigrationError, match="required tables/indexes are missing"):
            run_migrations(temp_db)

    def test_version2_missing_fingerprint_column_rejected(self, temp_db: str) -> None:
        """Version-2 database missing fingerprint column in events is rejected."""
        _create_v1_database(temp_db)
        with database_connection(temp_db) as conn:
            conn.execute("UPDATE schema_metadata SET version = 2")
            # Remove fingerprint column from events
            conn.execute("""
                CREATE TABLE events_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL REFERENCES servers(id),
                    timestamp TIMESTAMP NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    source TEXT, title TEXT, message TEXT,
                    metadata TEXT
                )
            """)
            conn.execute("INSERT INTO events_new SELECT id, server_id, timestamp, event_type, severity, source, title, message, metadata FROM events")
            conn.execute("DROP TABLE events")
            conn.execute("ALTER TABLE events_new RENAME TO events")

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

        # Save original statements
        original_statements = MIGRATION_0001_STATEMENTS

        # Build a modified statement list: first N valid statements, then a syntax error
        # Use first 6 statements (schema_metadata table + servers table + hostname index +
        # cpu_samples table + cpu_samples index + memory_samples table) then inject invalid SQL
        valid_prefix = MIGRATION_0001_STATEMENTS[:6]
        # Syntax error: missing closing parenthesis
        invalid_stmt = "CREATE TABLE invalid_table (id INTEGER PRIMARY KEY, bad_column THIS_IS_NOT_A_VALID_TYPE;"
        modified_statements = valid_prefix + [invalid_stmt] + MIGRATION_0001_STATEMENTS[6:]

        # Monkeypatch the module's statement list
        monkeypatch.setattr('app.database.migrations.MIGRATION_0001_STATEMENTS', modified_statements)

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
        monkeypatch.setattr('app.database.migrations.MIGRATION_0001_STATEMENTS', original_statements)

        # Second attempt: normal migration should succeed completely
        version = run_migrations(temp_db)
        assert version == SUPPORTED_VERSION

        # Verify all 10 application tables + schema_metadata + event_deduplication = 12 tables
        # (sqlite_sequence makes 13 total in sqlite_master)
        with database_connection(temp_db) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            required_tables = {
                "servers", "cpu_samples", "memory_samples", "disk_samples",
                "network_samples", "filesystem_samples", "temperature_samples",
                "events", "alerts", "metric_rollups", "schema_metadata", "event_deduplication"
            }
            assert required_tables.issubset(tables), f"Missing tables: {required_tables - tables}"

            # Verify all 22 indexes exist (20 v1 + 2 v2)
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
                "idx_events_fingerprint", "idx_event_deduplication_created",
            }
            assert required_indexes.issubset(indexes), f"Missing indexes: {required_indexes - indexes}"

            # Verify schema version is 2
            cursor = conn.execute("SELECT version FROM schema_metadata")
            assert cursor.fetchone()[0] == 2

    def test_retry_after_rollback_succeeds(self, temp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """After a rollback, retrying migration succeeds (separate verification)."""
        # Use a different failure point to test retry scenario independently
        valid_prefix = MIGRATION_0001_STATEMENTS[:3]  # schema_metadata, servers, servers index

        monkeypatch.setattr(
            'app.database.migrations.MIGRATION_0001_STATEMENTS',
            valid_prefix + ["CREATE TABLE another_invalid (x BADTYPE;"] + MIGRATION_0001_STATEMENTS[3:]
        )

        # First attempt: should fail and rollback
        with pytest.raises(sqlite3.OperationalError):
            run_migrations(temp_db)

        # Verify rollback occurred
        with database_connection(temp_db) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            assert tables == set()

        # Restore and retry
        monkeypatch.setattr('app.database.migrations.MIGRATION_0001_STATEMENTS', MIGRATION_0001_STATEMENTS)
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
            assert cursor.fetchone()[0] == 2


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

    def test_validate_schema_v2_passes(self, migrated_db: str) -> None:
        """_validate_schema_v2 returns True for complete v2 schema."""
        with database_connection(migrated_db) as conn:
            assert _validate_schema_v2(conn) is True

    def test_validate_schema_v2_fails_missing_dedup_table(self, temp_db: str) -> None:
        """_validate_schema_v2 returns False when event_deduplication table is missing."""
        _create_v1_database(temp_db)
        with database_connection(temp_db) as conn:
            conn.execute("INSERT INTO schema_metadata (version, description) VALUES (2, 'test')")
            assert _validate_schema_v2(conn) is False

    def test_validate_schema_v2_fails_missing_fingerprint_column(self, temp_db: str) -> None:
        """_validate_schema_v2 returns False when fingerprint column is missing from events."""
        _create_v1_database(temp_db)
        with database_connection(temp_db) as conn:
            conn.execute("UPDATE schema_metadata SET version = 2")
            # Remove fingerprint column from events
            conn.execute("""
                CREATE TABLE events_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL REFERENCES servers(id),
                    timestamp TIMESTAMP NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    source TEXT, title TEXT, message TEXT,
                    metadata TEXT
                )
            """)
            conn.execute("INSERT INTO events_new SELECT id, server_id, timestamp, event_type, severity, source, title, message, metadata FROM events")
            conn.execute("DROP TABLE events")
            conn.execute("ALTER TABLE events_new RENAME TO events")

        with database_connection(temp_db) as conn:
            assert _validate_schema_v2(conn) is False

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
            # Count tables created (11 application tables + schema_metadata = 12,
            # plus sqlite_sequence internal table = 13)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            table_count = cursor.fetchone()[0]
            assert table_count == 13  # 12 application tables + sqlite_sequence

    def test_no_duplicate_schema_metadata_on_rerun(self, migrated_db: str) -> None:
        """Re-running doesn't create duplicate schema_metadata entries."""
        run_migrations(migrated_db)
        run_migrations(migrated_db)

        with database_connection(migrated_db) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM schema_metadata")
            assert cursor.fetchone()[0] == 1

    def test_version_remains_2_after_rerun(self, migrated_db: str) -> None:
        """Version stays at 2 after multiple runs."""
        for _ in range(5):
            version = run_migrations(migrated_db)
            assert version == 2


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
            assert cursor.fetchone()[0] == 2

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
