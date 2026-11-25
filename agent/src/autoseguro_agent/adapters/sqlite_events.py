"""EventStore em SQLite, append-only garantido por trigger (REQ-41).

Zero setup para o avaliador e inspecionável com um comando:
    sqlite3 autoseguro.db "select seq, event_type, status, latency_ms from events"
Em produção: Postgres com a mesma tabela e as mesmas regras.
"""

from __future__ import annotations

import json
import sqlite3
import threading

from autoseguro_agent.domain.events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    status TEXT NOT NULL,
    message_id TEXT,
    quote_request_id TEXT,
    quote_attempt_id TEXT,
    handoff_id TEXT,
    latency_ms INTEGER,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_conversation ON events(conversation_id, seq);
CREATE INDEX IF NOT EXISTS ix_events_wa ON events(json_extract(payload_json, '$.wa_message_id'));
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
"""

COLUMNS = (
    "ts, event_type, conversation_id, status, message_id, quote_request_id, "
    "quote_attempt_id, handoff_id, latency_ms, payload_json"
)


class SqliteEventStore:
    def __init__(self, path: str) -> None:
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._con.executescript(SCHEMA)

    def append(self, event: Event) -> None:
        row = (
            event.ts.isoformat(),
            event.event_type,
            event.conversation_id,
            event.status,
            event.message_id,
            event.quote_request_id,
            event.quote_attempt_id,
            event.handoff_id,
            event.latency_ms,
            json.dumps(event.payload, ensure_ascii=False, default=str),
        )
        with self._lock:
            self._con.execute(f"INSERT INTO events ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            self._con.commit()

    def timeline(self, conversation_id: str) -> list[Event]:
        with self._lock:
            rows = self._con.execute(
                f"SELECT {COLUMNS} FROM events WHERE conversation_id = ? ORDER BY seq",
                (conversation_id,),
            ).fetchall()
        return [
            Event(
                ts=r[0],
                event_type=r[1],
                conversation_id=r[2],
                status=r[3],
                message_id=r[4],
                quote_request_id=r[5],
                quote_attempt_id=r[6],
                handoff_id=r[7],
                latency_ms=r[8],
                payload=json.loads(r[9]),
            )
            for r in rows
        ]

    def seen_wa_message(self, wa_message_id: str) -> bool:
        with self._lock:
            row = self._con.execute(
                "SELECT 1 FROM events WHERE event_type = 'message.received' "
                "AND json_extract(payload_json, '$.wa_message_id') = ? LIMIT 1",
                (wa_message_id,),
            ).fetchone()
        return row is not None
