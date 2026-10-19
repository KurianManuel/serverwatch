"""Database migration framework for ServerWatch."""

import sqlite3

from app.database.connection import database_connection

# Current supported schema version
SUPPORTED_VERSION = 2


class MigrationError(Exception):
    """Raised when a migration fails or version is unsupported."""
    pass


# Source of truth: IMPLEMENTATION_SPEC.md "Database Schema" section
# This list MUST match that specification exactly.
# Version 1 is recorded LAST - only if all schema creation succeeds.
MIGRATION_0001_STATEMENTS = [
    # 1. Create all tables FIRST (including schema_metadata table, but NO version insert)
    """CREATE TABLE schema_metadata (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT (datetime('now')),
        description TEXT
    )""",
    # servers
    """CREATE TABLE servers (
        id TEXT PRIMARY KEY,
        hostname TEXT NOT NULL,
        display_name TEXT,
        os_name TEXT,
        os_version TEXT,
        kernel_version TEXT,
        architecture TEXT,
        created_at TIMESTAMP DEFAULT (datetime('now')),
        updated_at TIMESTAMP DEFAULT (datetime('now'))
    )""",
    """CREATE INDEX idx_servers_hostname ON servers(hostname)""",
    # cpu_samples
    """CREATE TABLE cpu_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        timestamp TIMESTAMP NOT NULL,
        total_utilization REAL,
        per_core TEXT NOT NULL,
        load_1min REAL, load_5min REAL, load_15min REAL,
        cpu_count INTEGER
    )""",
    """CREATE INDEX idx_cpu_samples_server_time ON cpu_samples(server_id, timestamp DESC)""",
    # memory_samples
    """CREATE TABLE memory_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        timestamp TIMESTAMP NOT NULL,
        total_bytes INTEGER NOT NULL,
        available_bytes INTEGER NOT NULL,
        used_bytes INTEGER NOT NULL,
        free_bytes INTEGER, buffers_bytes INTEGER, cached_bytes INTEGER,
        swap_total_bytes INTEGER, swap_used_bytes INTEGER, swap_free_bytes INTEGER
    )""",
    """CREATE INDEX idx_memory_samples_server_time ON memory_samples(server_id, timestamp DESC)""",
    # disk_samples
    """CREATE TABLE disk_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        timestamp TIMESTAMP NOT NULL,
        device TEXT NOT NULL,
        read_bytes INTEGER, write_bytes INTEGER,
        read_ops INTEGER, write_ops INTEGER,
        read_throughput REAL, write_throughput REAL, iops REAL
    )""",
    """CREATE INDEX idx_disk_samples_server_time ON disk_samples(server_id, timestamp DESC)""",
    """CREATE INDEX idx_disk_samples_device ON disk_samples(server_id, device, timestamp DESC)""",
    # network_samples
    """CREATE TABLE network_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        timestamp TIMESTAMP NOT NULL,
        interface TEXT NOT NULL,
        rx_bytes INTEGER, tx_bytes INTEGER,
        rx_packets INTEGER, tx_packets INTEGER,
        rx_errors INTEGER, tx_errors INTEGER,
        rx_drops INTEGER, tx_drops INTEGER
    )""",
    """CREATE INDEX idx_network_samples_server_time ON network_samples(server_id, timestamp DESC)""",
    """CREATE INDEX idx_network_samples_interface ON network_samples(server_id, interface, timestamp DESC)""",
    # filesystem_samples
    """CREATE TABLE filesystem_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        timestamp TIMESTAMP NOT NULL,
        mount_point TEXT NOT NULL,
        device TEXT,
        fstype TEXT,
        total_bytes INTEGER, free_bytes INTEGER, available_bytes INTEGER,
        used_bytes INTEGER, used_percent REAL,
        inodes_total INTEGER, inodes_free INTEGER
    )""",
    """CREATE INDEX idx_filesystem_samples_server_time ON filesystem_samples(server_id, timestamp DESC)""",
    """CREATE INDEX idx_filesystem_samples_mount ON filesystem_samples(server_id, mount_point, timestamp DESC)""",
    # temperature_samples
    """CREATE TABLE temperature_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        timestamp TIMESTAMP NOT NULL,
        sensor_name TEXT NOT NULL,
        sensor_label TEXT,
        temperature_celsius REAL,
        high_threshold REAL, critical_threshold REAL
    )""",
    """CREATE INDEX idx_temperature_samples_server_time ON temperature_samples(server_id, timestamp DESC)""",
    """CREATE INDEX idx_temperature_samples_sensor ON temperature_samples(server_id, sensor_name, timestamp DESC)""",
    # events
    """CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        timestamp TIMESTAMP NOT NULL,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        source TEXT, title TEXT, message TEXT,
        metadata TEXT
    )""",
    """CREATE INDEX idx_events_server_time ON events(server_id, timestamp DESC)""",
    """CREATE INDEX idx_events_type ON events(server_id, event_type, timestamp DESC)""",
    """CREATE INDEX idx_events_severity ON events(server_id, severity, timestamp DESC)""",
    # alerts
    """CREATE TABLE alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        rule_id TEXT NOT NULL,
        state TEXT NOT NULL,
        severity TEXT NOT NULL,
        condition TEXT,
        first_seen TIMESTAMP NOT NULL,
        last_seen TIMESTAMP NOT NULL,
        fired_at TIMESTAMP, recovered_at TIMESTAMP,
        metadata TEXT
    )""",
    """CREATE INDEX idx_alerts_server_time ON alerts(server_id, first_seen DESC)""",
    """CREATE INDEX idx_alerts_state ON alerts(server_id, state, first_seen DESC)""",
    """CREATE INDEX idx_alerts_rule ON alerts(server_id, rule_id, first_seen DESC)""",
    # metric_rollups
    """CREATE TABLE metric_rollups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT NOT NULL REFERENCES servers(id),
        metric_name TEXT NOT NULL,
        interval_type TEXT NOT NULL,
        window_start TIMESTAMP NOT NULL,
        window_end TIMESTAMP NOT NULL,
        count INTEGER NOT NULL,
        min_value REAL NOT NULL,
        avg_value REAL NOT NULL,
        max_value REAL NOT NULL
    )""",
    """CREATE INDEX idx_rollups_server_metric_time ON metric_rollups(server_id, metric_name, window_start DESC)""",
    """CREATE INDEX idx_rollups_interval ON metric_rollups(interval_type, window_start DESC)""",
    """CREATE UNIQUE INDEX idx_rollups_unique ON metric_rollups(server_id, metric_name, interval_type, window_start)""",
    # 2. Insert version record LAST - only if all schema creation succeeds.
    """INSERT INTO schema_metadata (version, description) VALUES (1, 'Initial schema')""",
]


# Version 2: Add fingerprint column to events and event_deduplication table for 24-hour deduplication
# Note: DDL statements (ALTER TABLE, CREATE INDEX, CREATE TABLE) implicitly commit in SQLite,
# so we split the migration into two parts: DDL first, then version update in a separate transaction.
MIGRATION_0002_STATEMENTS_DDL = [
    # Add fingerprint column to events table
    """ALTER TABLE events ADD COLUMN fingerprint TEXT""",
    # Create index for fingerprint lookups
    """CREATE INDEX idx_events_fingerprint ON events(fingerprint)""",
    # Create deduplication table for 24-hour windowed deduplication
    """CREATE TABLE event_deduplication (
        fingerprint TEXT NOT NULL,
        server_id TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (fingerprint, server_id)
    )""",
    # Index for efficient cleanup of old deduplication records
    """CREATE INDEX idx_event_deduplication_created ON event_deduplication(created_at)""",
]

MIGRATION_0002_STATEMENTS_VERSION = [
    # 2. Update version record LAST - only if all above succeeded
    # Use DELETE + INSERT instead of INSERT OR REPLACE because version changes from 1 to 2
    """DELETE FROM schema_metadata WHERE version = 1""",
    """INSERT INTO schema_metadata (version, description) VALUES (2, 'Add fingerprint column and event_deduplication table for 24-hour deduplication')""",
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def _has_application_tables(conn: sqlite3.Connection) -> bool:
    """Check for any ServerWatch application tables excluding schema_metadata."""
    app_tables = {
        "servers", "cpu_samples", "memory_samples", "disk_samples",
        "network_samples", "filesystem_samples", "temperature_samples",
        "events", "alerts", "metric_rollups"
    }
    placeholders = ','.join('?' for _ in app_tables)
    cursor = conn.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
        tuple(app_tables)
    )
    return cursor.fetchone() is not None


def _get_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version from schema_metadata."""
    cursor = conn.execute("SELECT version FROM schema_metadata ORDER BY version DESC LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else 0


def _validate_schema_v1(conn: sqlite3.Connection) -> bool:
    """Verify all Phase 4A required tables and indexes exist."""
    required_tables = {
        "servers", "cpu_samples", "memory_samples", "disk_samples",
        "network_samples", "filesystem_samples", "temperature_samples",
        "events", "alerts", "metric_rollups", "schema_metadata"
    }
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

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}

    return required_tables.issubset(tables) and required_indexes.issubset(indexes)


def _validate_schema_v2(conn: sqlite3.Connection) -> bool:
    """Verify all Phase 5.1 required tables and indexes exist."""
    required_tables = {"event_deduplication"}
    required_indexes = {"idx_events_fingerprint", "idx_event_deduplication_created"}

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}

    return required_tables.issubset(tables) and required_indexes.issubset(indexes)


def _apply_initial_migration_transactional(conn: sqlite3.Connection) -> int:
    """Apply 0001 migration in a single explicit transaction."""
    conn.execute("BEGIN IMMEDIATE TRANSACTION;")
    try:
        for stmt in MIGRATION_0001_STATEMENTS:
            conn.execute(stmt)
        conn.execute("COMMIT;")
    except Exception:
        try:
            conn.execute("ROLLBACK;")
        except sqlite3.OperationalError:
            pass  # No transaction to roll back
        raise
    return SUPPORTED_VERSION


def _apply_migration_transactional(conn: sqlite3.Connection, version: int) -> None:
    """Apply a specific migration version in an explicit transaction."""
    if version == 1:
        _apply_initial_migration_transactional(conn)
    elif version == 2:
        # DDL statements (ALTER TABLE, CREATE INDEX, CREATE TABLE) implicitly commit in SQLite
        # Execute DDL statements first
        for stmt in MIGRATION_0002_STATEMENTS_DDL:
            conn.execute(stmt)
        # Then update version in a separate transaction
        conn.execute("BEGIN IMMEDIATE TRANSACTION;")
        try:
            for stmt in MIGRATION_0002_STATEMENTS_VERSION:
                conn.execute(stmt)
            conn.execute("COMMIT;")
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except sqlite3.OperationalError:
                pass  # No transaction to roll back
            raise
    else:
        raise MigrationError(f"Unknown migration version: {version}")


def run_migrations(db_path: str | None = None) -> int:
    """
    Apply pending migrations and return the current schema version.

    Args:
        db_path: Optional database path. Uses config default if not provided.

    Returns:
        The schema version after migrations (1 for Phase 4A).

    Raises:
        MigrationError: If database version is newer than supported,
                        or required objects are missing from a version-1 database.
    """
    with database_connection(db_path) as conn:
        has_metadata = _table_exists(conn, "schema_metadata")
        has_app_tables = _has_application_tables(conn)

        if not has_metadata and has_app_tables:
            raise MigrationError(
                "Database contains application tables but no schema_metadata. "
                "Manual intervention required - cannot determine schema version."
            )

        if not has_metadata:
            # Fresh database - apply all migrations from version 1 to SUPPORTED_VERSION
            _apply_initial_migration_transactional(conn)
            # Continue to apply any remaining migrations
            current = 1
        else:
            current = _get_version(conn)

        if current > SUPPORTED_VERSION:
            raise MigrationError(f"Database version {current} > supported {SUPPORTED_VERSION}")

        if current == SUPPORTED_VERSION:
            # Validate based on the supported version
            if SUPPORTED_VERSION == 1:
                if not _validate_schema_v1(conn):
                    raise MigrationError(
                        "Database reports version 1 but required tables/indexes are missing. "
                        "Manual intervention required."
                    )
            elif SUPPORTED_VERSION >= 2:
                # For v2+, validate both v1 and v2 schemas
                if not _validate_schema_v1(conn) or not _validate_schema_v2(conn):
                    raise MigrationError(
                        "Database reports version 2 but required tables/indexes are missing. "
                        "Manual intervention required."
                    )
            return current

        # SINGLE LOOP: apply each pending migration exactly once
        for version in range(current + 1, SUPPORTED_VERSION + 1):
            _apply_migration_transactional(conn, version)

        # Validate final state
        if SUPPORTED_VERSION == 1:
            if not _validate_schema_v1(conn):
                raise MigrationError("Migration completed but schema validation failed.")
        elif SUPPORTED_VERSION >= 2:
            # For v2+, validate both v1 and v2 schemas
            if not _validate_schema_v1(conn) or not _validate_schema_v2(conn):
                raise MigrationError("Migration completed but schema validation failed.")

        return SUPPORTED_VERSION
