"""Estado da conversa no checkpoint do LangGraph.

Só tipos JSON (dicts, listas, strings, números): serializa igual em memória e em
SQLite, e o checkpoint nunca carrega classes arbitrárias. Todo texto é MASCARADO.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

ConvStatus = Literal["active", "quoted", "handed_off", "closed"]


class TurnInput(TypedDict):
    message_id: str
    text: str  # já mascarado
    message_type: Literal["text", "image", "audio", "document"]
    pii_kinds: list[str]


class ConversationState(TypedDict, total=False):
    # --- persistente entre turnos ---
    conversation_id: str
    llm_provider: str | None  # escolhido no dashboard; None = padrão
    status: ConvStatus
    profile: dict[str, Any]  # LeadProfile.model_dump(mode="json")
    pending_slot: str | None
    slot_failures: dict[str, int]
    low_confidence_streak: int
    media_strikes: int
    greeted: bool
    pii_notice_sent: bool
    start_date_default: bool
    last_success: dict[str, Any] | None  # QuoteResult da última cotação success
    quoted_key: str | None  # "plano|data" da última cotação success
    quotes: list[dict[str, Any]]  # resumo de cada pedido: ids, status, plano
    handoff: dict[str, Any] | None
    quote_recovered: bool  # retry pós-handoff conseguiu a cotação
    # --- só do turno atual (zerado no ingest) ---
    turn: TurnInput
    extraction: dict[str, Any] | None
    turn_errors: list[str]  # slots com erro de formato neste turno
    turn_policy: dict[str, str] | None  # PolicyRefusal
    turn_quote: dict[str, Any] | None  # QuoteOutcome do turno
    turn_handoff: dict[str, str] | None  # HandoffDecision
    turn_recommended: str | None
    turn_llm_failed: bool
    early_sent: list[str]  # mensagens já enviadas no meio do turno (espera)
    outbox: list[str]
