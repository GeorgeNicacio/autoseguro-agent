"""Log estruturado (structlog, JSON) com os ids de rastreio em toda linha (REQ-40).

Defesa em profundidade: os eventos já chegam mascarados, mas o processor
`redact_processor` remascara qualquer string antes de escrever (REQ-52).
LangSmith fica opcional por variável de ambiente (LANGSMITH_TRACING=true).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from autoseguro_agent.domain.events import Event
from autoseguro_agent.pii import InMemoryVault, PiiMasker, contains_pii
from autoseguro_agent.ports import EventStore


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return PiiMasker(InMemoryVault()).mask(value, "log").text if contains_pii(value) else value
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(v) for v in value]
    return value


# Ids de rastreio e metadados nunca são texto do lead: não passam pelo mascarador
# (um hash hexadecimal pode ter 8 dígitos seguidos e parecer um CEP).
TRUSTED_FIELDS = frozenset(
    {
        "conversation_id",
        "message_id",
        "quote_request_id",
        "quote_attempt_id",
        "handoff_id",
        "event",
        "status",
        "level",
        "timestamp",
        "latency_ms",
        "wa_message_id",
    }
)


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    return {k: v if k in TRUSTED_FIELDS else _redact(v) for k, v in event_dict.items()}


def configure_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


class LoggingEventStore:
    """Decorator: grava no store e escreve a mesma linha no log JSON."""

    def __init__(self, inner: EventStore) -> None:
        self._inner = inner
        self._log = structlog.get_logger("autoseguro")

    def append(self, event: Event) -> None:
        self._inner.append(event)
        fields = event.model_dump(mode="json", exclude_none=True, exclude={"event_type", "ts"})
        self._log.info(event.event_type, **fields)

    def timeline(self, conversation_id: str) -> list[Event]:
        return self._inner.timeline(conversation_id)

    def seen_wa_message(self, wa_message_id: str) -> bool:
        return self._inner.seen_wa_message(wa_message_id)
