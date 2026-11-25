"""EventStore em memória (testes e CLI). O SQLite append-only entra no Dia 2."""

from __future__ import annotations

from autoseguro_agent.domain.events import Event


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, event: Event) -> None:
        self._events.append(event)

    def timeline(self, conversation_id: str) -> list[Event]:
        return [e for e in self._events if e.conversation_id == conversation_id]

    def seen_wa_message(self, wa_message_id: str) -> bool:
        return any(
            e.event_type == "message.received" and e.payload.get("wa_message_id") == wa_message_id
            for e in self._events
        )

    @property
    def all(self) -> list[Event]:
        return list(self._events)
