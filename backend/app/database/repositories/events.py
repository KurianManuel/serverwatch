"""Events repository."""

from typing import Optional, List, Any
import sqlite3
from app.database.connection import database_connection


class EventsRepository:
    def get_events(self, server_id: str, limit: int = 100, offset: int = 0, severity: Optional[str] = None) -> List[sqlite3.Row]:
        with database_connection() as conn:  # type: sqlite3.Connection
            query = "SELECT * FROM events WHERE server_id = ?"
            params: List[Any] = [server_id]
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cursor = conn.execute(query, params)
            return cursor.fetchall()


events_repository = EventsRepository()