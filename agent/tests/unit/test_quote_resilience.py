"""Resiliência do /quote, o diferencial do desafio (REQ-20..25).

Timeout por tentativa, retry só no que é transitório, backoff com jitter,
orçamento total e circuit breaker. Respostas simuladas com respx.
"""

import asyncio
from datetime import date

import httpx
import pytest
import respx

from autoseguro_agent.adapters.circuit_breaker import CircuitBreaker
from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.adapters.quote_http import HttpQuoteGateway
from autoseguro_agent.domain.models import QuoteRequest
from autoseguro_agent.domain.quote import TraceContext
from tests.unit.test_models import API_200

BASE = "http://quote.test"
REQ = QuoteRequest(
    plano_id="completo", idade=35, veiculo_ano=2022, cep="01310-100", data_inicio=date(2026, 12, 1)
)
CTX = TraceContext(conversation_id="c1")
FAIL_503 = httpx.Response(503, json={"error": "upstream_unavailable"})
OK = httpx.Response(200, json=API_200)


async def no_sleep(_: float) -> None:
    return None


def gateway(**kw: object) -> HttpQuoteGateway:
    params: dict[str, object] = {
        "base_url": BASE,
        "timeout_s": 0.2,
        "max_attempts": 3,
        "backoff_initial_s": 0.0,
        "jitter_s": 0.0,
        "sleep": no_sleep,
    }
    params.update(kw)
    return HttpQuoteGateway(**params)  # type: ignore[arg-type]


@respx.mock
async def test_retries_5xx_then_succeeds() -> None:
    route = respx.post(f"{BASE}/quote").mock(side_effect=[FAIL_503, FAIL_503, OK])
    out = await gateway().quote(REQ, CTX)
    assert out.status == "success"
    assert [a.status for a in out.attempts] == ["http_5xx", "http_5xx", "ok"]
    assert [a.attempt for a in out.attempts] == [1, 2, 3]
    assert len({a.quote_attempt_id for a in out.attempts}) == 3  # id por tentativa
    ids = {c.request.headers["x-request-id"] for c in route.calls}
    assert ids == {out.quote_request_id}  # mesmo pedido (idempotência)


@respx.mock
async def test_timeout_then_success() -> None:
    respx.post(f"{BASE}/quote").mock(side_effect=[httpx.ReadTimeout("lento"), OK])
    out = await gateway().quote(REQ, CTX)
    assert out.status == "success"
    assert [a.status for a in out.attempts] == ["timeout", "ok"]


@respx.mock
async def test_real_slowness_is_cut_by_client_timeout() -> None:
    """A lentidão simulada é sleep(8) e depois 200: sem timeout, o lead esperaria 8 s."""

    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return OK

    respx.post(f"{BASE}/quote").mock(side_effect=[slow, OK])
    out = await gateway(timeout_s=0.1).quote(REQ, CTX)
    assert out.status == "success"
    assert out.attempts[0].status == "timeout"
    assert out.attempts[0].latency_ms < 1000


@respx.mock
async def test_gives_up_after_max_attempts() -> None:
    route = respx.post(f"{BASE}/quote").mock(return_value=FAIL_503)
    out = await gateway().quote(REQ, CTX)
    assert out.status == "failed"
    assert out.failure_reason == "exhausted"
    assert len(out.attempts) == 3
    assert route.call_count == 3


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(422, json={"error": "cotacao_recusada", "motivo": "x"}),
        httpx.Response(422, json={"detail": []}),
        httpx.Response(400, json={"error": "payload_invalido"}),
    ],
)
@respx.mock
async def test_never_retries_4xx(response: httpx.Response) -> None:
    route = respx.post(f"{BASE}/quote").mock(return_value=response)
    out = await gateway().quote(REQ, CTX)
    assert route.call_count == 1
    assert len(out.attempts) == 1


@respx.mock
async def test_backoff_waits_grow_between_attempts() -> None:
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    respx.post(f"{BASE}/quote").mock(return_value=FAIL_503)
    gw = gateway(backoff_initial_s=0.5, jitter_s=0.0, sleep=record, budget_s=12.0)
    await gw.quote(REQ, CTX)
    assert waits == [0.5, 1.0]


@respx.mock
async def test_total_budget_stops_retrying() -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return OK

    respx.post(f"{BASE}/quote").mock(side_effect=slow)
    gw = gateway(timeout_s=0.3, budget_s=0.5, max_attempts=5)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    out = await gw.quote(REQ, CTX)
    assert loop.time() - t0 < 1.0
    assert out.status == "failed"
    assert out.failure_reason == "budget_exceeded"
    assert len(out.attempts) == 2  # 0,3 s + 0,2 s restantes


@respx.mock
async def test_breaker_counts_failed_requests_not_attempts() -> None:
    """Uma falha transitória que o retry resolve não conta para o breaker."""
    respx.post(f"{BASE}/quote").mock(side_effect=[FAIL_503, FAIL_503, OK] * 3)
    breaker = CircuitBreaker(SystemClock(), failure_threshold=2, open_seconds=30)
    gw = gateway(breaker=breaker)
    for _ in range(3):
        assert (await gw.quote(REQ, CTX)).status == "success"
    assert breaker.state == "closed"


@respx.mock
async def test_breaker_opens_after_failed_requests_and_skips_http() -> None:
    route = respx.post(f"{BASE}/quote").mock(return_value=FAIL_503)
    breaker = CircuitBreaker(SystemClock(), failure_threshold=2, open_seconds=30)
    gw = gateway(breaker=breaker)
    await gw.quote(REQ, CTX)
    await gw.quote(REQ, CTX)
    assert breaker.state == "open"
    calls = route.call_count
    third = await gw.quote(REQ, CTX)
    assert route.call_count == calls  # nem tentou: resposta imediata e handoff
    assert third.status == "failed"
    assert third.failure_reason == "circuit_open"
    assert [a.status for a in third.attempts] == ["circuit_open"]


@respx.mock
async def test_business_refusal_counts_as_healthy_for_breaker() -> None:
    respx.post(f"{BASE}/quote").mock(
        return_value=httpx.Response(422, json={"error": "cotacao_recusada", "motivo": "x"})
    )
    breaker = CircuitBreaker(SystemClock(), failure_threshold=2)
    gw = gateway(breaker=breaker)
    for _ in range(3):
        await gw.quote(REQ, CTX)
    assert breaker.state == "closed"
