"""SQLite database connection management."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings


def get_connection() -> sqlite3.Connection:
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")

    return conn


@contextmanager
def database_connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_database() -> None:
    with database_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_metadata (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS servers (
                id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                display_name TEXT,
                os_name TEXT,
                os_version TEXT,
                kernel_version TEXT,
                architecture TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cpu_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                timestamp TIMESTAMP NOT NULL,
                total_utilization REAL,
                per_core TEXT,
                load_1min REAL,
                load_5min REAL,
                load_15min REAL,
                cpu_count INTEGER,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS memory_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                timestamp TIMESTAMP NOT NULL,
                total_bytes INTEGER,
                available_bytes INTEGER,
                used_bytes INTEGER,
                free_bytes INTEGER,
                buffers_bytes INTEGER,
                cached_bytes INTEGER,
                swap_total_bytes INTEGER,
                swap_used_bytes INTEGER,
                swap_free_bytes INTEGER,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS disk_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                timestamp TIMESTAMP NOT NULL,
                device TEXT NOT NULL,
                read_bytes INTEGER,
                write_bytes INTEGER,
                read_ops INTEGER,
                write_ops INTEGER,
                read_throughput REAL,
                write_throughput REAL,
                iops REAL,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS network_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                timestamp TIMESTAMP NOT NULL,
                interface TEXT NOT NULL,
                state TEXT,
                rx_bytes INTEGER,
                tx_bytes INTEGER,
                rx_packets INTEGER,
                tx_packets INTEGER,
                rx_errors INTEGER,
                tx_errors INTEGER,
                rx_dropped INTEGER,
                tx_dropped INTEGER,
                throughput_rx REAL,
                throughput_tx REAL,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS filesystem_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                timestamp TIMESTAMP NOT NULL,
                mount_point TEXT NOT NULL,
                device TEXT,
                fstype TEXT,
                total_bytes INTEGER,
                used_bytes INTEGER,
                available_bytes INTEGER,
                utilization_pct REAL,
                inodes_total INTEGER,
                inodes_used INTEGER,
                inodes_free INTEGER,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS temperature_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                timestamp TIMESTAMP NOT NULL,
                sensor_name TEXT NOT NULL,
                sensor_label TEXT,
                temperature_celsius REAL,
                high_threshold REAL,
                critical_threshold REAL,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                timestamp TIMESTAMP NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                source TEXT,
                title TEXT,
                message TEXT,
                metadata TEXT,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                rule_id TEXT NOT NULL,
                state TEXT NOT NULL,
                severity TEXT NOT NULL,
                condition TEXT,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                fired_at TIMESTAMP,
                recovered_at TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS metric_rollups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL REFERENCES servers(id),
                metric_name TEXT NOT NULL,
                interval_type TEXT NOT NULL,
                window_start TIMESTAMP NOT NULL,
                window_end TIMESTAMP NOT NULL,
                count INTEGER,
                min_value REAL,
                avg_value REAL,
                max_value REAL,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_cpu_samples_server_time
                ON cpu_samples(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_samples_server_time
                ON memory_samples(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_disk_samples_server_time
                ON disk_samples(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_network_samples_server_time
                ON network_samples(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_filesystem_samples_server_time
                ON filesystem_samples(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_temperature_samples_server_time
                ON temperature_samples(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_events_server_time
                ON events(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_alerts_server_time
                ON alerts(server_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_rollups_server_metric_time
                ON metric_rollups(server_id, metric_name, window_start DESC);
        """)
        conn.commit()
