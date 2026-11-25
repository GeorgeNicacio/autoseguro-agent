"""HttpQuoteGateway: cada linha da tabela de respostas da API vira um QuoteOutcome (REQ-26, 27).

Dia 1: uma tentativa, com timeout. Retry, backoff e circuit breaker entram no Dia 2.
"""

from datetime import date

import httpx
import pytest
import respx

from autoseguro_agent.adapters.quote_http import HttpQuoteGateway
from autoseguro_agent.domain.models import QuoteRequest
from autoseguro_agent.domain.quote import TraceContext
from tests.unit.test_models import API_200

BASE = "http://quote.test"
REQ = QuoteRequest(
    plano_id="completo", idade=35, veiculo_ano=2022, cep="01310-100", data_inicio=date(2026, 12, 1)
)
CTX = TraceContext(conversation_id="c1", message_id="m1")


@pytest.fixture
def gateway() -> HttpQuoteGateway:
    """Uma tentativa: aqui o foco é o mapeamento de cada resposta (retry: test_quote_resilience)."""
    return HttpQuoteGateway(base_url=BASE, timeout_s=0.2, max_attempts=1)


@respx.mock
async def test_200_is_success(gateway: HttpQuoteGateway) -> None:
    route = respx.post(f"{BASE}/quote").respond(200, json=API_200)
    out = await gateway.quote(REQ, CTX)
    assert out.status == "success"
    assert out.result is not None
    assert len(out.attempts) == 1
    assert out.attempts[0].status == "ok"
    assert route.calls[0].request.headers["x-request-id"] == out.quote_request_id
    assert out.attempts[0].quote_attempt_id != out.quote_request_id


@respx.mock
async def test_422_business_refusal(gateway: HttpQuoteGateway) -> None:
    respx.post(f"{BASE}/quote").respond(
        422,
        json={"error": "cotacao_recusada", "motivo": "Veiculo com mais de 20 anos nao e aceito."},
    )
    out = await gateway.quote(REQ, CTX)
    assert out.status == "refused"
    assert out.refusal_motivo == "Veiculo com mais de 20 anos nao e aceito."
    assert out.attempts[0].status == "refused"


@respx.mock
async def test_422_schema_is_agent_bug(gateway: HttpQuoteGateway) -> None:
    respx.post(f"{BASE}/quote").respond(422, json={"detail": [{"loc": ["body", "idade"]}]})
    out = await gateway.quote(REQ, CTX)
    assert out.status == "invalid"
    assert out.invalid_reason == "agent_bug"


@respx.mock
async def test_400_bad_input(gateway: HttpQuoteGateway) -> None:
    respx.post(f"{BASE}/quote").respond(400, json={"error": "payload_invalido", "detalhe": "x"})
    out = await gateway.quote(REQ, CTX)
    assert out.status == "invalid"
    assert out.invalid_reason == "bad_input"


@pytest.mark.parametrize("code", [500, 502, 503])
@respx.mock
async def test_5xx_is_failure(gateway: HttpQuoteGateway, code: int) -> None:
    respx.post(f"{BASE}/quote").respond(code, json={"error": "upstream_unavailable"})
    out = await gateway.quote(REQ, CTX)
    assert out.status == "failed"
    assert out.failure_reason == "exhausted"
    assert out.attempts[0].status == "http_5xx"
    assert out.attempts[0].http_status == code


@respx.mock
async def test_timeout_is_failure(gateway: HttpQuoteGateway) -> None:
    respx.post(f"{BASE}/quote").mock(side_effect=httpx.ReadTimeout("slow"))
    out = await gateway.quote(REQ, CTX)
    assert out.status == "failed"
    assert out.attempts[0].status == "timeout"


@respx.mock
async def test_unparseable_200_is_agent_bug_not_crash(gateway: HttpQuoteGateway) -> None:
    respx.post(f"{BASE}/quote").respond(200, json={"inesperado": True})
    out = await gateway.quote(REQ, CTX)
    assert out.status == "invalid"
    assert out.invalid_reason == "agent_bug"


@respx.mock
async def test_rules_from_api_with_snapshot_fallback() -> None:
    respx.get(f"{BASE}/planos").respond(503)
    gw = HttpQuoteGateway(base_url=BASE)
    await gw.load_rules()
    assert gw.rules_source == "snapshot"
    assert gw.rules().plan("completo") is not None
