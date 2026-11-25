"""decide_handoff: uma regra por linha, um teste por regra (REQ-30, SMART M-06)."""

import pytest

from autoseguro_agent.domain.eligibility import PolicyRefusal
from autoseguro_agent.domain.handoff import HANDOFF_RULES, HandoffContext, decide_handoff

BASE = HandoffContext()


@pytest.mark.parametrize(
    ("ctx", "rule_id"),
    [
        (HandoffContext(intents=frozenset({"wants_human"})), "explicit_request"),
        (HandoffContext(quote_status="failed", failure_reason="exhausted"), "infra_unavailable"),
        (
            HandoffContext(quote_status="failed", failure_reason="circuit_open"),
            "infra_unavailable",
        ),
        (HandoffContext(intents=frozenset({"complaint"})), "risk_or_conflict"),
        (HandoffContext(intents=frozenset({"legal_threat"})), "risk_or_conflict"),
        (HandoffContext(intents=frozenset({"strong_anger"})), "risk_or_conflict"),
        (
            HandoffContext(policy_refusal=PolicyRefusal("condutor_acima_limite", "Idade.")),
            "out_of_policy",
        ),
        (HandoffContext(quote_status="refused", api_refusal_motivo="Veiculo."), "out_of_policy"),
        (HandoffContext(intents=frozenset({"claim"})), "out_of_scope"),
        (HandoffContext(intents=frozenset({"cancel"})), "out_of_scope"),
        (HandoffContext(intents=frozenset({"endorsement"})), "out_of_scope"),
        (HandoffContext(intents=frozenset({"second_copy"})), "out_of_scope"),
        (HandoffContext(intents=frozenset({"fleet"})), "out_of_scope"),
        (HandoffContext(intents=frozenset({"commercial_use"})), "out_of_scope"),
        (HandoffContext(quote_status="invalid", invalid_reason="agent_bug"), "agent_bug"),
        (HandoffContext(intents=frozenset({"discount"})), "price_negotiation"),
        (HandoffContext(intents=frozenset({"competitor_match"})), "price_negotiation"),
        (HandoffContext(intents=frozenset({"special_installments"})), "price_negotiation"),
        (HandoffContext(max_slot_failures=2), "stuck"),
        (HandoffContext(low_confidence_streak=2), "stuck"),
        (HandoffContext(quote_status="invalid", invalid_reason="bad_input"), "stuck"),
        (HandoffContext(media_strikes=2), "media_unsupported"),
        (HandoffContext(quoted=True, intents=frozenset({"wants_to_buy"})), "ready_to_close"),
        (HandoffContext(quoted=True, intents=frozenset({"accepts_quote"})), "ready_to_close"),
    ],
)
def test_each_rule_fires(ctx: HandoffContext, rule_id: str) -> None:
    decision = decide_handoff(ctx)
    assert decision is not None
    assert decision.rule_id == rule_id
    assert decision.motivo


@pytest.mark.parametrize(
    "ctx",
    [
        BASE,
        HandoffContext(intents=frozenset({"greeting", "plan_question", "will_think"})),
        HandoffContext(max_slot_failures=1),  # 1ª falha: pede correção, não passa
        HandoffContext(low_confidence_streak=1),
        HandoffContext(media_strikes=1),  # 1ª mídia: só aviso (achado D2 do dataset)
        HandoffContext(intents=frozenset({"wants_to_buy"})),  # sem cotação ainda: segue
        HandoffContext(quote_status="success"),
    ],
)
def test_no_handoff(ctx: HandoffContext) -> None:
    assert decide_handoff(ctx) is None


def test_priority_order_when_many_fire() -> None:
    """Pedido explícito vence tudo; infra vence negociação; o resto segue a tabela."""
    ctx = HandoffContext(
        intents=frozenset({"wants_human", "discount"}),
        quote_status="failed",
        failure_reason="exhausted",
    )
    assert decide_handoff(ctx).rule_id == "explicit_request"  # type: ignore[union-attr]
    ctx2 = HandoffContext(
        intents=frozenset({"discount"}), quote_status="failed", failure_reason="exhausted"
    )
    assert decide_handoff(ctx2).rule_id == "infra_unavailable"  # type: ignore[union-attr]


def test_every_rule_in_the_table_is_tested() -> None:
    """Se alguém criar uma regra nova sem teste, este teste quebra (SMART M-06)."""
    tested = {
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
    }
    assert {r.rule_id for r in HANDOFF_RULES} == tested


def test_policy_refusal_carries_reason() -> None:
    d = decide_handoff(HandoffContext(policy_refusal=PolicyRefusal("x", "Veiculo velho.")))
    assert d is not None
    assert d.motivo == "Veiculo velho."
    assert d.priority == "alta"


def test_ready_to_close_waits_for_requote() -> None:
    """Aceite junto com troca de plano/data: recota primeiro, o lead precisa ver o preço novo."""
    ctx = HandoffContext(quoted=True, intents=frozenset({"accepts_quote"}), requote_pending=True)
    assert decide_handoff(ctx) is None
