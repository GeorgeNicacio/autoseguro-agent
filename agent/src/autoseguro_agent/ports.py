"""Portas do hexágono (SOLID · I e D): interfaces pequenas que o núcleo usa.

Os adaptadores (adapters/) implementam estes Protocols; os testes usam fakes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from autoseguro_agent.domain.events import Event
from autoseguro_agent.domain.extraction import ExtractionRequest, ExtractionResult
from autoseguro_agent.domain.models import QuoteRequest
from autoseguro_agent.domain.quote import QuoteOutcome, TraceContext
from autoseguro_agent.domain.rules import PlanRules
from autoseguro_agent.pii import Vault

__all__ = [
    "Clock",
    "EventStore",
    "LLMClient",
    "LLMUnavailableError",
    "OutboundChannel",
    "QuoteGateway",
    "TaskQueue",
    "Vault",
]


class LLMUnavailableError(Exception):
    """Provedor fora, recusa do modelo ou saída inválida: o grafo responde por template."""


class LLMClient(Protocol):
    def extract(self, req: ExtractionRequest) -> ExtractionResult: ...


class QuoteGateway(Protocol):
    async def quote(self, req: QuoteRequest, ctx: TraceContext) -> QuoteOutcome: ...
    def rules(self) -> PlanRules: ...


class EventStore(Protocol):
    def append(self, event: Event) -> None: ...
    def timeline(self, conversation_id: str) -> list[Event]: ...
    def seen_wa_message(self, wa_message_id: str) -> bool: ...
    def all_events(self) -> list[Event]: ...


class TaskQueue(Protocol):
    """Fila de tarefas em segundo plano (RQ neste teste)."""

    def schedule_quote_retry(self, conversation_id: str, attempt: int, delay_s: int) -> None: ...


class OutboundChannel(Protocol):
    def send(self, conversation_id: str, text: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
    def today(self) -> date: ...
    def monotonic(self) -> float: ...
