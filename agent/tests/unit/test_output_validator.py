"""Garantia contra preço inventado (REQ-13): todo R$ da mensagem existe na fonte certa."""

from decimal import Decimal

import pytest

from autoseguro_agent.domain.models import QuoteResult
from autoseguro_agent.domain.output_validator import extract_money, validate_output
from autoseguro_agent.domain.rules import PlanRules
from tests.unit.test_models import API_200


@pytest.fixture
def quote() -> QuoteResult:
    return QuoteResult.model_validate(API_200)


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("fica R$ 209,90 por mês", [Decimal("209.90")]),
        ("franquia de R$ 3.000,00", [Decimal("3000.00")]),
        ("R$3000", [Decimal("3000")]),
        ("só 199,90 no total", [Decimal("199.90")]),
        ("R$ 1.234.567,80", [Decimal("1234567.80")]),
        ("tenho 35 anos, carro 2022, carência de 30 dias", []),
    ],
)
def test_extract_money(text: str, values: list[Decimal]) -> None:
    assert extract_money(text) == values


def test_no_quote_means_no_price(rules: PlanRules) -> None:
    check = validate_output("Seu seguro fica R$ 189,90 por mês", None, rules)
    assert not check.ok
    assert check.offending == ("R$ 189,90",)


def test_text_without_money_is_always_ok(rules: PlanRules) -> None:
    assert validate_output("Qual o ano do seu carro?", None, rules).ok


def test_values_from_success_quote_are_ok(quote: QuoteResult, rules: PlanRules) -> None:
    text = "Plano Completo: R$ 209,90/mês, franquia R$ 3.000,00, 1º pagamento R$ 115,11."
    assert validate_output(text, quote, rules).ok


def test_value_not_in_quote_is_blocked(quote: QuoteResult, rules: PlanRules) -> None:
    check = validate_output("Consigo por R$ 199,90", quote, rules)
    assert not check.ok


def test_bare_amount_without_symbol_is_checked_too(quote: QuoteResult, rules: PlanRules) -> None:
    assert not validate_output("fica 199,90", quote, rules).ok
    assert validate_output("fica 209,90", quote, rules).ok


def test_franchise_from_planos_is_allowed_without_quote(rules: PlanRules) -> None:
    """Franquia é dado fixo do /planos (fonte oficial), não preço calculado."""
    assert validate_output("A franquia do Premium é R$ 1.500,00.", None, rules).ok


def test_percentages_are_blocked(rules: PlanRules) -> None:
    """Multiplicador/desconto em % nunca sai para o lead (SPARK R1)."""
    check = validate_output("Você tem 10% de desconto", None, rules)
    assert not check.ok
    assert check.offending == ("10%",)
