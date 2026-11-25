"""Mensagens com números saem só de templates preenchidos pela API (REQ-13, REQ-25)."""

from decimal import Decimal

import pytest

from autoseguro_agent import templates
from autoseguro_agent.domain.models import QuoteResult
from autoseguro_agent.domain.output_validator import validate_output
from autoseguro_agent.domain.rules import PlanRules
from tests.unit.test_models import API_200


@pytest.fixture
def quote() -> QuoteResult:
    return QuoteResult.model_validate(API_200)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("209.90"), "R$ 209,90"),
        (Decimal("3000"), "R$ 3.000,00"),
        (Decimal("1234567.8"), "R$ 1.234.567,80"),
        (Decimal("115.11"), "R$ 115,11"),
    ],
)
def test_format_brl(value: Decimal, text: str) -> None:
    assert templates.format_brl(value) == text


def test_quote_message_has_everything_from_the_api(quote: QuoteResult, rules: PlanRules) -> None:
    msg = templates.quote_message(quote, rules)
    assert "Completo" in msg
    assert "R$ 209,90" in msg
    assert "R$ 3.000,00" in msg
    assert "R$ 115,11" in msg
    assert "17 dias" in msg
    assert "colisão" in msg
    assert "vidros" in msg
    assert "30 dias" in msg
    assert "roubo e furto" in msg
    assert validate_output(msg, quote, rules).ok


def test_quote_message_offers_other_plans_without_price(
    quote: QuoteResult, rules: PlanRules
) -> None:
    msg = templates.quote_message(quote, rules, offer_others=True)
    assert "Essencial" in msg
    assert "Premium" in msg
    assert validate_output(msg, quote, rules).ok
    assert "R$ 119,90" not in msg
    assert "R$ 339,90" not in msg


def test_quote_message_without_pro_rata(rules: PlanRules) -> None:
    data = {k: v for k, v in API_200.items() if k != "primeiro_pagamento_pro_rata"}
    msg = templates.quote_message(QuoteResult.model_validate(data), rules)
    assert "primeiro pagamento" not in msg.lower()


@pytest.mark.parametrize("slot", ["veiculo_ano", "idade", "cep", "plano_id"])
def test_ask_slot_has_no_money(slot: str, rules: PlanRules) -> None:
    msg = templates.ask_slot(slot)  # type: ignore[arg-type]
    assert msg.endswith("?")
    assert validate_output(msg, None, rules).ok
    retry = templates.ask_slot(slot, retry=True)  # type: ignore[arg-type]
    assert retry != msg


def test_failure_message_is_honest_and_has_no_price(rules: PlanRules) -> None:
    msg = templates.quote_unavailable()
    assert "consultor" in msg.lower()
    assert validate_output(msg, None, rules).ok


def test_plan_info_uses_planos_only(rules: PlanRules) -> None:
    msg = templates.plan_info(rules, "franquia")
    assert "R$ 4.500,00" in msg
    assert "R$ 1.500,00" in msg
    assert validate_output(msg, None, rules).ok


@pytest.mark.parametrize(
    "fn",
    [
        templates.waiting,
        templates.media_ack,
        templates.unsolicited_pii_notice,
        templates.llm_unavailable,
        templates.safe_fallback,
    ],
)
def test_simple_templates_have_no_money(fn: object, rules: PlanRules) -> None:
    msg = fn()  # type: ignore[operator]
    assert msg
    assert validate_output(msg, None, rules).ok


def test_confirm_start_date() -> None:
    from datetime import date

    assert "01/12/2026" in templates.confirm_start_date(date(2026, 12, 1))
