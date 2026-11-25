"""Evento append-only: tudo que acontece numa conversa tem id e status (REQ-40, REQ-41)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
    "message.received",
    "message.sent",
    "message.duplicate",
    "conversation.status",
    "slot.updated",
    "slot.invalid",
    "policy.refused",
    "quote_request.started",
    "quote_attempt",
    "quote_request.finished",
    "handoff.opened",
    "output.blocked",
    "llm.error",
]


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime
    event_type: EventType
    conversation_id: str
    status: str
    message_id: str | None = None
    quote_request_id: str | None = None
    quote_attempt_id: str | None = None
    handoff_id: str | None = None
    latency_ms: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)  # sempre mascarado
