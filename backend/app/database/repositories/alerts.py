"""Alerts repository."""

import sqlite3
from typing import Any

from app.database.connection import database_connection


class AlertsRepository:
    def get_alerts(
        self, server_id: str, limit: int = 100, offset: int = 0, state: str | None = None
    ) -> list[sqlite3.Row]:
        with database_connection() as conn:  # type: sqlite3.Connection
            query = "SELECT * FROM alerts WHERE server_id = ?"
            params: list[Any] = [server_id]
            if state:
                query += " AND state = ?"
                params.append(state)
            query += " ORDER BY first_seen DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cursor = conn.execute(query, params)
            return cursor.fetchall()


alerts_repository = AlertsRepository()
