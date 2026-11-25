"""Resultado de um pedido de cotação, com cada tentativa rastreável (REQ-40)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from autoseguro_agent.domain.models import QuoteResult

RequestStatus = Literal["success", "refused", "invalid", "failed"]
AttemptStatus = Literal["ok", "timeout", "http_5xx", "refused", "invalid", "circuit_open"]
FailureReason = Literal["exhausted", "circuit_open", "budget_exceeded"]
InvalidReason = Literal["bad_input", "agent_bug"]
CacheStatus = Literal["hit", "miss", "error", "disabled"]


class TraceContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: str
    message_id: str | None = None


class QuoteAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    quote_attempt_id: str
    attempt: int
    status: AttemptStatus
    latency_ms: int
    http_status: int | None = None


class QuoteOutcome(BaseModel):
    """Saída do QuoteGateway. Nunca levanta exceção de HTTP para fora do adaptador."""

    model_config = ConfigDict(frozen=True)

    quote_request_id: str
    status: RequestStatus
    attempts: tuple[QuoteAttempt, ...] = ()
    result: QuoteResult | None = None
    refusal_motivo: str | None = None
    failure_reason: FailureReason | None = None
    invalid_reason: InvalidReason | None = None
    cache: CacheStatus | None = None  # preenchido pelo CachedQuoteGateway
    saved_ms: int | None = None  # latência da resposta original, economizada num hit
