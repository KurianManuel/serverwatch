"""Metrics repositories."""

from typing import Optional, List, Any
import sqlite3
from app.database.connection import database_connection


class MetricsRepository:
    """Repository for metric samples."""

    def get_latest_cpu(self, server_id: str, limit: int = 1) -> List[sqlite3.Row]:
        with database_connection() as conn:  # type: sqlite3.Connection
            cursor = conn.execute(
                "SELECT * FROM cpu_samples WHERE server_id = ? ORDER BY timestamp DESC LIMIT ?",
                (server_id, limit),
            )
            return cursor.fetchall()

    def get_latest_memory(self, server_id: str, limit: int = 1) -> List[sqlite3.Row]:
        with database_connection() as conn:  # type: sqlite3.Connection
            cursor = conn.execute(
                "SELECT * FROM memory_samples WHERE server_id = ? ORDER BY timestamp DESC LIMIT ?",
                (server_id, limit),
            )
            return cursor.fetchall()

    def get_history(
        self, server_id: str, metric: str, start: str, end: str, limit: int = 2000
    ) -> List[sqlite3.Row]:
        table_map = {
            "cpu": "cpu_samples",
            "memory": "memory_samples",
            "disk": "disk_samples",
            "network": "network_samples",
            "filesystem": "filesystem_samples",
            "temperature": "temperature_samples",
        }
        table = table_map.get(metric)
        if not table:
            return []

        with database_connection() as conn:  # type: sqlite3.Connection
            cursor = conn.execute(
                f"SELECT * FROM {table} WHERE server_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT ?",
                (server_id, start, end, limit),
            )
            return cursor.fetchall()


metrics_repository = MetricsRepository()