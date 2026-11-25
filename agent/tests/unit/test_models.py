"""Contratos do domínio: slots do lead, request e response do /quote."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autoseguro_agent.domain.models import LeadProfile, QuoteRequest, QuoteResult

API_200 = {
    "plano_id": "completo",
    "plano_nome": "Completo",
    "premio_mensal": 209.9,
    "franquia": 3000,
    "coberturas": ["colisao", "roubo", "furto", "terceiros", "vidros"],
    "multiplicadores": {"faixa_etaria": 1.0, "idade_veiculo": 1.0, "regiao": 1.0},
    "carencia": {
        "coberturas": ["roubo", "furto"],
        "dias": 30,
        "observacao": "Coberturas de roubo e furto so passam a valer apos a carencia...",
    },
    "moeda": "BRL",
    "primeiro_pagamento_pro_rata": {
        "dias_no_mes": 31,
        "dias_cobrados": 17,
        "valor_primeiro_pagamento": 115.11,
    },
}


def test_missing_slots_in_fixed_order() -> None:
    assert LeadProfile().missing_slots() == ["veiculo_ano", "idade", "cep", "plano_id"]
    profile = LeadProfile(veiculo_ano=2022, idade=35)
    assert profile.missing_slots() == ["cep", "plano_id"]


def test_profile_never_holds_raw_cep() -> None:
    """O perfil guarda só o token do cofre; o CEP real nunca entra no estado do grafo."""
    LeadProfile(cep_token="<CEP_1>")
    with pytest.raises(ValidationError):
        LeadProfile(cep_token="01310-100")


def test_quote_request_payload() -> None:
    req = QuoteRequest(
        plano_id="completo",
        idade=35,
        veiculo_ano=2022,
        cep="01310-100",
        data_inicio=date(2026, 12, 1),
    )
    assert req.to_payload() == {
        "plano_id": "completo",
        "idade": 35,
        "veiculo_ano": 2022,
        "cep": "01310-100",
        "data_inicio": "2026-12-01",
    }


def test_quote_request_requires_normalized_cep() -> None:
    with pytest.raises(ValidationError):
        QuoteRequest(plano_id="completo", idade=35, veiculo_ano=2022, cep="1310100")


def test_quote_result_parses_api_200_with_exact_money() -> None:
    result = QuoteResult.model_validate(API_200)
    assert result.premio_mensal == Decimal("209.90")
    assert result.franquia == Decimal("3000")
    assert result.primeiro_pagamento_pro_rata is not None
    assert result.primeiro_pagamento_pro_rata.valor_primeiro_pagamento == Decimal("115.11")
    assert result.carencia.dias == 30


def test_quote_result_without_pro_rata() -> None:
    data = {k: v for k, v in API_200.items() if k != "primeiro_pagamento_pro_rata"}
    assert QuoteResult.model_validate(data).primeiro_pagamento_pro_rata is None


def test_quote_result_money_values_for_output_validator() -> None:
    """Todos os valores em R$ que podem aparecer numa mensagem (REQ-13)."""
    result = QuoteResult.model_validate(API_200)
    assert result.money_values() == {Decimal("209.90"), Decimal("3000"), Decimal("115.11")}
