"""Eventos append-only em SQLite + log JSON sem PII (REQ-41, REQ-52, SMART M-09)."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autoseguro_agent.adapters.sqlite_events import SqliteEventStore
from autoseguro_agent.domain.events import Event
from autoseguro_agent.observability import LoggingEventStore, redact_processor

TS = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def ev(conv: str = "c1", **kw: object) -> Event:
    base: dict[str, object] = {
        "ts": TS,
        "event_type": "message.received",
        "conversation_id": conv,
        "status": "received",
    }
    base.update(kw)
    return Event.model_validate(base)


@pytest.fixture
def store(tmp_path: Path) -> SqliteEventStore:
    return SqliteEventStore(str(tmp_path / "events.db"))


def test_timeline_in_order_per_conversation(store: SqliteEventStore) -> None:
    store.append(ev(status="received"))
    store.append(ev(conv="outra"))
    store.append(
        ev(
            event_type="quote_attempt",
            status="timeout",
            latency_ms=3001,
            quote_request_id="qr_1",
            quote_attempt_id="qa_1",
        )
    )
    timeline = store.timeline("c1")
    assert [e.status for e in timeline] == ["received", "timeout"]
    assert timeline[1].latency_ms == 3001
    assert timeline[1].quote_attempt_id == "qa_1"


def test_update_and_delete_are_blocked_by_trigger(store: SqliteEventStore, tmp_path: Path) -> None:
    store.append(ev())
    con = sqlite3.connect(tmp_path / "events.db")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("UPDATE events SET status = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("DELETE FROM events")


def test_dedup_by_whatsapp_message_id(store: SqliteEventStore) -> None:
    assert not store.seen_wa_message("wamid.1")
    store.append(ev(payload={"wa_message_id": "wamid.1"}))
    assert store.seen_wa_message("wamid.1")


def test_persists_across_instances(tmp_path: Path) -> None:
    path = str(tmp_path / "e.db")
    SqliteEventStore(path).append(ev())
    assert len(SqliteEventStore(path).timeline("c1")) == 1


def test_redact_processor_removes_raw_pii() -> None:
    out = redact_processor(None, "info", {"event": "x", "payload": {"t": "cpf 529.982.247-25"}})
    assert "529.982" not in json.dumps(out)
    assert "<CPF_1>" in json.dumps(out)


def test_logging_store_writes_json_with_ids(capsys: pytest.CaptureFixture[str]) -> None:
    from autoseguro_agent.adapters.events_memory import InMemoryEventStore
    from autoseguro_agent.observability import configure_logging

    configure_logging()
    store = LoggingEventStore(InMemoryEventStore())
    store.append(ev(event_type="quote_attempt", status="http_5xx", quote_request_id="qr_9"))
    line = capsys.readouterr().err.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["event"] == "quote_attempt"
    assert data["conversation_id"] == "c1"
    assert data["quote_request_id"] == "qr_9"
    assert data["status"] == "http_5xx"
