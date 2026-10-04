"""Events repository."""

import sqlite3
from typing import Any

from app.database.connection import database_connection


class EventsRepository:
    def get_events(self, server_id: str, limit: int = 100, offset: int = 0, severity: str | None = None) -> list[sqlite3.Row]:
        with database_connection() as conn:  # type: sqlite3.Connection
            query = "SELECT * FROM events WHERE server_id = ?"
            params: list[Any] = [server_id]
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cursor = conn.execute(query, params)
            return cursor.fetchall()


events_repository = EventsRepository()
