"""Teste de contrato contra o quote-service REAL (T1.6 · REQ-13).

Prova que nossos modelos entendem a resposta da API e que as regras lidas de
/planos batem com o que a API aplica. Pula se o serviço não estiver no ar.

Este teste ainda não usa o gateway resiliente (Dia 2): repete a chamada só para
atravessar as falhas simuladas, e sempre com timeout curto.
"""

from __future__ import annotations

import os
import time
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from autoseguro_agent.domain.models import QuoteRequest, QuoteResult
from autoseguro_agent.domain.rules import PlanRules

pytestmark = pytest.mark.contract

BASE_URL = os.getenv("QUOTE_BASE_URL", "http://localhost:8000")
RETRYABLE = {500, 502, 503}


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    client = httpx.Client(base_url=BASE_URL, timeout=3.0)
    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"quote-service fora do ar em {BASE_URL}")
    return client


def post_quote(api: httpx.Client, payload: dict[str, Any], attempts: int = 15) -> httpx.Response:
    for _ in range(attempts):
        try:
            resp = api.post("/quote", json=payload)
        except httpx.TimeoutException:
            continue
        if resp.status_code not in RETRYABLE:
            return resp
        time.sleep(0.05)
    pytest.fail("quote-service não respondeu sem falha em 15 tentativas")


def test_readme_example_premium_and_pro_rata(api: httpx.Client) -> None:
    """Exemplo do README: completo, 35 anos, carro de 4 anos, CEP 01310-100, início 15/07.

    O README usa veiculo_ano 2022; como a API calcula a idade do veículo com
    date.today(), usamos "ano atual - 4" para o contrato não envelhecer.
    A data de início no passado é aceita pela API (o agente é que recusa).
    """
    req = QuoteRequest(
        plano_id="completo",
        idade=35,
        veiculo_ano=date.today().year - 4,
        cep="01310-100",
        data_inicio=date(2026, 7, 15),
    )
    resp = post_quote(api, req.to_payload())
    assert resp.status_code == 200
    result = QuoteResult.model_validate(resp.json())

    assert result.premio_mensal == Decimal("209.90")
    assert result.franquia == Decimal("3000")
    assert result.multiplicadores == {"faixa_etaria": 1.0, "idade_veiculo": 1.0, "regiao": 1.0}
    assert result.carencia.dias == 30
    assert result.carencia.coberturas == ("roubo", "furto")
    assert result.primeiro_pagamento_pro_rata is not None
    assert result.primeiro_pagamento_pro_rata.dias_cobrados == 17
    assert result.primeiro_pagamento_pro_rata.valor_primeiro_pagamento == Decimal("115.11")


def test_first_of_month_has_no_pro_rata(api: httpx.Client) -> None:
    """Nossa data padrão (1º do mês seguinte) não gera pro-rata."""
    req = QuoteRequest(
        plano_id="essencial",
        idade=40,
        veiculo_ano=date.today().year - 2,
        cep="01310-100",
        data_inicio=date(2026, 12, 1),
    )
    result = QuoteResult.model_validate(post_quote(api, req.to_payload()).json())
    assert result.primeiro_pagamento_pro_rata is None


@pytest.mark.parametrize(
    ("idade", "anos_veiculo", "cep", "esperado"),
    [
        (22, 2, "01310-100", {"faixa_etaria": 1.6, "idade_veiculo": 1.0, "regiao": 1.0}),
        (65, 8, "21000-000", {"faixa_etaria": 1.4, "idade_veiculo": 1.15, "regiao": 1.3}),
        (27, 14, "59000-000", {"faixa_etaria": 1.25, "idade_veiculo": 1.45, "regiao": 1.3}),
    ],
)
def test_api_applies_the_bands_we_read_from_planos(
    api: httpx.Client,
    rules: PlanRules,
    idade: int,
    anos_veiculo: int,
    cep: str,
    esperado: dict[str, float],
) -> None:
    """As faixas que usamos para validar são as mesmas que a API aplica."""
    req = QuoteRequest(
        plano_id="completo",
        idade=idade,
        veiculo_ano=date.today().year - anos_veiculo,
        cep=cep,
    )
    result = QuoteResult.model_validate(post_quote(api, req.to_payload()).json())
    assert result.multiplicadores == esperado
    assert rules.is_high_risk_cep(cep) == (esperado["regiao"] > 1)


@pytest.mark.parametrize(
    ("idade", "anos_veiculo"),
    [(76, 2), (35, 21)],
)
def test_policy_refusals_match_local_rules(
    api: httpx.Client, idade: int, anos_veiculo: int
) -> None:
    """O que validamos localmente como recusa, a API também recusa (422 cotacao_recusada)."""
    payload = {
        "plano_id": "completo",
        "idade": idade,
        "veiculo_ano": date.today().year - anos_veiculo,
        "cep": "01310-100",
    }
    resp = post_quote(api, payload)
    assert resp.status_code == 422
    assert resp.json()["error"] == "cotacao_recusada"


def test_unknown_plan_is_422_refusal_not_400(api: httpx.Client) -> None:
    """Fato lido no código: plano inexistente é recusa (422), por isso validamos antes."""
    payload = {"plano_id": "ouro", "idade": 35, "veiculo_ano": 2022, "cep": "01310-100"}
    resp = post_quote(api, payload)
    assert resp.status_code == 422
    assert resp.json()["error"] == "cotacao_recusada"


def test_bad_date_is_400_and_schema_violation_is_fastapi_422(api: httpx.Client) -> None:
    bad_date = {"plano_id": "completo", "idade": 35, "veiculo_ano": 2022, "data_inicio": "15/07"}
    resp = post_quote(api, bad_date)
    assert resp.status_code == 400
    assert resp.json()["error"] == "payload_invalido"

    out_of_schema = {"plano_id": "completo", "idade": 35, "veiculo_ano": 1900}
    resp = api.post("/quote", json=out_of_schema)  # validação do FastAPI roda antes da falha
    assert resp.status_code == 422
    assert "detail" in resp.json()
