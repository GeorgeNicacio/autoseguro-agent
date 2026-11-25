"""Adaptador HTTP do quote-service (porta QuoteGateway).

Nenhuma exceção de HTTP sai daqui: toda resposta vira um `QuoteOutcome` com o
status do pedido e de cada tentativa, pronto para o grafo decidir e para o log.

Resiliência (o diferencial do desafio, números em docs/evidence):
1. Timeout por tentativa (3 s): a lentidão simulada é sleep(8) e DEPOIS sucesso.
2. Retry só em 5xx e timeout, até 3 tentativas, backoff exponencial com jitter
   (~0,5 s, ~1 s). Nunca em 400/422: repetir não muda a resposta.
3. Orçamento total por pedido (12 s): o lead não espera indefinidamente.
4. Circuit breaker compartilhado: com o legado fora, nem tenta e o grafo faz handoff.
5. Um `quote_request_id` por pedido e um `quote_attempt_id` por tentativa, enviados em
   headers: /quote é cálculo puro (retry seguro), mas a idempotência fica explícita.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from autoseguro_agent.adapters.circuit_breaker import CircuitBreaker
from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.domain.models import QuoteRequest, QuoteResult
from autoseguro_agent.domain.quote import QuoteAttempt, QuoteOutcome, TraceContext
from autoseguro_agent.domain.rules import PlanRules, load_snapshot
from autoseguro_agent.ports import Clock

RETRYABLE = {"timeout", "http_5xx"}
MIN_USEFUL_TIMEOUT_S = 0.05


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class _RetryableAttemptError(Exception):
    """Sinal interno para o tenacity: a tentativa falhou de forma transitória."""


class HttpQuoteGateway:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 3.0,
        client: httpx.AsyncClient | None = None,
        *,
        max_attempts: int = 3,
        budget_s: float = 12.0,
        backoff_initial_s: float = 0.5,
        backoff_max_s: float = 2.0,
        jitter_s: float = 0.25,
        breaker: CircuitBreaker | None = None,
        clock: Clock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client = client or httpx.AsyncClient(base_url=self._base_url)
        self._max_attempts = max_attempts
        self._budget_s = budget_s
        self._backoff_initial_s = backoff_initial_s
        self._backoff_max_s = backoff_max_s
        self._jitter_s = jitter_s
        self._breaker = breaker
        self._clock = clock or SystemClock()
        self._sleep = sleep
        self._rules = load_snapshot()
        self.rules_source: Literal["api", "snapshot"] = "snapshot"

    @property
    def breaker_state(self) -> str:
        return self._breaker.state if self._breaker else "disabled"

    def rules(self) -> PlanRules:
        return self._rules

    async def load_rules(self) -> None:
        """Na subida: regras de GET /planos; se falhar, mantém o snapshot versionado."""
        try:
            resp = await self._client.get("/planos", timeout=self._timeout_s)
            resp.raise_for_status()
            self._rules = PlanRules.from_planos(resp.json())
            self.rules_source = "api"
        except (httpx.HTTPError, KeyError, ValueError):
            self._rules = load_snapshot()
            self.rules_source = "snapshot"

    async def quote(self, req: QuoteRequest, ctx: TraceContext) -> QuoteOutcome:
        request_id = new_id("qr")
        started = self._clock.monotonic()
        attempts: list[QuoteAttempt] = []
        final: QuoteOutcome = _failed(request_id, "exhausted")

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(
                multiplier=self._backoff_initial_s, max=self._backoff_max_s, jitter=self._jitter_s
            ),
            retry=retry_if_exception_type(_RetryableAttemptError),
            sleep=self._sleep,
        )
        # Breaker por PEDIDO, não por tentativa: medido no teste de caos (v1), contar
        # tentativas abria o circuito com o legado só instável e mandava 84% para humano.
        if self._breaker is not None and not self._breaker.allow():
            skipped = _skipped(1, "circuit_open")
            return _failed(request_id, "circuit_open").model_copy(update={"attempts": (skipped,)})

        try:
            async for retry in retrying:
                with retry:
                    n = retry.retry_state.attempt_number
                    remaining = self._budget_s - (self._clock.monotonic() - started)
                    if remaining < MIN_USEFUL_TIMEOUT_S:
                        final = _failed(request_id, "budget_exceeded")
                        break
                    attempt, outcome = await self._attempt(
                        req, request_id, n, min(self._timeout_s, remaining)
                    )
                    attempts.append(attempt)
                    final = outcome
                    if attempt.status in RETRYABLE:
                        raise _RetryableAttemptError
        except RetryError:
            final = _failed(request_id, "exhausted")

        if self._breaker is not None:
            if final.status == "failed":
                self._breaker.record_failure()
            else:  # 200, recusa ou payload inválido: o legado respondeu
                self._breaker.record_success()
        return final.model_copy(update={"attempts": tuple(attempts)})

    async def _attempt(
        self, req: QuoteRequest, request_id: str, n: int, timeout_s: float
    ) -> tuple[QuoteAttempt, QuoteOutcome]:
        attempt_id = new_id("qa")
        t0 = time.perf_counter()

        def attempt(status: Any, http_status: int | None = None) -> QuoteAttempt:
            return QuoteAttempt(
                quote_attempt_id=attempt_id,
                attempt=n,
                status=status,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                http_status=http_status,
            )

        try:
            # asyncio.timeout garante o teto da tentativa inteira; o timeout do httpx
            # vale por operação de rede (conectar, ler) e sozinho não basta.
            async with asyncio.timeout(timeout_s):
                resp = await self._client.post(
                    "/quote",
                    json=req.to_payload(),
                    timeout=timeout_s,
                    headers={"x-request-id": request_id, "x-attempt-id": attempt_id},
                )
        except (TimeoutError, httpx.TimeoutException):
            return attempt("timeout"), _failed(request_id)
        except httpx.TransportError:
            return attempt("http_5xx"), _failed(request_id)

        code = resp.status_code
        if code == 200:
            try:
                result = QuoteResult.model_validate(resp.json())
            except (ValidationError, ValueError):
                return attempt("invalid", code), _invalid(request_id, "agent_bug")
            return attempt("ok", code), QuoteOutcome(
                quote_request_id=request_id, status="success", result=result
            )
        if code >= 500:
            return attempt("http_5xx", code), _failed(request_id)

        body = _json(resp)
        if code == 422 and body.get("error") == "cotacao_recusada":
            return attempt("refused", code), QuoteOutcome(
                quote_request_id=request_id,
                status="refused",
                refusal_motivo=str(body.get("motivo", "")),
            )
        if code == 400:
            return attempt("invalid", code), _invalid(request_id, "bad_input")
        # 422 do FastAPI (schema) ou qualquer 4xx inesperado: erro do agente.
        return attempt("invalid", code), _invalid(request_id, "agent_bug")


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _failed(
    request_id: str,
    reason: Literal["exhausted", "circuit_open", "budget_exceeded"] = "exhausted",
) -> QuoteOutcome:
    return QuoteOutcome(quote_request_id=request_id, status="failed", failure_reason=reason)


def _skipped(n: int, status: Literal["circuit_open"]) -> QuoteAttempt:
    return QuoteAttempt(quote_attempt_id=new_id("qa"), attempt=n, status=status, latency_ms=0)


def _invalid(request_id: str, reason: Literal["bad_input", "agent_bug"]) -> QuoteOutcome:
    return QuoteOutcome(quote_request_id=request_id, status="invalid", invalid_reason=reason)
