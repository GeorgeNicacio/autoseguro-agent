"""Critério de handoff: tabela de regras em código, uma linha = uma regra = um teste (REQ-30).

O LLM só SINALIZA intenções; quem decide passar para humano é esta função pura.
A tabela é avaliada em ordem de prioridade e a primeira regra que dispara vence.
Para criar uma regra: adicione uma linha em HANDOFF_RULES e um caso no teste.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from autoseguro_agent.domain.eligibility import PolicyRefusal
from autoseguro_agent.domain.extraction import Intent
from autoseguro_agent.domain.quote import FailureReason, InvalidReason, RequestStatus

Priority = Literal["imediata", "alta", "media", "fim_feliz"]
RuleId = Literal[
    "explicit_request",
    "infra_unavailable",
    "risk_or_conflict",
    "out_of_policy",
    "out_of_scope",
    "agent_bug",
    "price_negotiation",
    "stuck",
    "media_unsupported",
    "ready_to_close",
]

STUCK_AFTER = 2
MEDIA_STRIKES_LIMIT = 2


@dataclass(frozen=True)
class HandoffContext:
    """Tudo que as regras olham. Montado pelo grafo a partir do estado do turno."""

    intents: frozenset[Intent] = frozenset()
    quote_status: RequestStatus | None = None
    failure_reason: FailureReason | None = None
    invalid_reason: InvalidReason | None = None
    api_refusal_motivo: str | None = None
    policy_refusal: PolicyRefusal | None = None
    max_slot_failures: int = 0
    low_confidence_streak: int = 0
    media_strikes: int = 0
    quoted: bool = False
    # A mensagem muda plano ou data: recota antes de fechar (o lead precisa ver o preço novo).
    requote_pending: bool = False


@dataclass(frozen=True)
class HandoffDecision:
    rule_id: RuleId
    priority: Priority
    motivo: str


@dataclass(frozen=True)
class HandoffRule:
    rule_id: RuleId
    priority: Priority
    reason: str  # motivo defensável (vai para o README e para o resumo do handoff)
    fires: Callable[[HandoffContext], bool]
    motivo: Callable[[HandoffContext], str] | None = None


_OUT_OF_SCOPE: frozenset[Intent] = frozenset(
    {"claim", "cancel", "endorsement", "second_copy", "fleet", "commercial_use"}
)
_RISK: frozenset[Intent] = frozenset({"complaint", "legal_threat", "strong_anger"})
_NEGOTIATION: frozenset[Intent] = frozenset(
    {"discount", "competitor_match", "special_installments"}
)


def _policy_motivo(c: HandoffContext) -> str:
    if c.policy_refusal is not None:
        return c.policy_refusal.motivo
    return c.api_refusal_motivo or "Fora da política de aceitação."


HANDOFF_RULES: tuple[HandoffRule, ...] = (
    HandoffRule(
        "explicit_request",
        "imediata",
        "Respeitar o cliente: insistir custa a venda.",
        lambda c: "wants_human" in c.intents,
    ),
    HandoffRule(
        "infra_unavailable",
        "imediata",
        "Cotação indisponível: não inventar preço nem deixar o lead sem resposta.",
        lambda c: c.quote_status == "failed",
    ),
    HandoffRule(
        "risk_or_conflict",
        "alta",
        "Reclamação, ameaça ou irritação forte pedem uma pessoa.",
        lambda c: bool(c.intents & _RISK),
    ),
    HandoffRule(
        "out_of_policy",
        "alta",
        "Exceção comercial (idade, idade do veículo) é decisão humana.",
        lambda c: c.policy_refusal is not None or c.quote_status == "refused",
        _policy_motivo,
    ),
    HandoffRule(
        "out_of_scope",
        "alta",
        "O agente só vende seguro individual novo.",
        lambda c: bool(c.intents & _OUT_OF_SCOPE),
    ),
    HandoffRule(
        "agent_bug",
        "alta",
        "Payload fora do schema é erro do agente: humano assume e o log vira bug.",
        lambda c: c.quote_status == "invalid" and c.invalid_reason == "agent_bug",
    ),
    HandoffRule(
        "price_negotiation",
        "media",
        "O agente não tem alçada de desconto.",
        lambda c: bool(c.intents & _NEGOTIATION),
    ),
    HandoffRule(
        "stuck",
        "media",
        "Duas tentativas sem conseguir um dado: evita loop e frustração.",
        lambda c: (
            c.max_slot_failures >= STUCK_AFTER
            or c.low_confidence_streak >= STUCK_AFTER
            or (c.quote_status == "invalid" and c.invalid_reason == "bad_input")
        ),
    ),
    HandoffRule(
        "media_unsupported",
        "media",
        "O agente não lê mídia; após duas mídias no mesmo dado, uma pessoa assume.",
        lambda c: c.media_strikes >= MEDIA_STRIKES_LIMIT,
    ),
    HandoffRule(
        "ready_to_close",
        "fim_feliz",
        "Contratação pede CPF, documentos e pagamento: humano com contexto completo.",
        lambda c: (
            c.quoted
            and not c.requote_pending
            and bool(c.intents & {"wants_to_buy", "accepts_quote"})
        ),
    ),
)


def decide_handoff(ctx: HandoffContext) -> HandoffDecision | None:
    for rule in HANDOFF_RULES:
        if rule.fires(ctx):
            motivo = rule.motivo(ctx) if rule.motivo else rule.reason
            return HandoffDecision(rule.rule_id, rule.priority, motivo)
    return None
