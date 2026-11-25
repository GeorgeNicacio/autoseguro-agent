"""Adaptador HTTP do quote-service (porta QuoteGateway).

Nenhuma exceção de HTTP sai daqui: toda resposta vira um `QuoteOutcome` com o
status do pedido e de cada tentativa, pronto para o grafo decidir e para o log.

Dia 1: uma tentativa com timeout. O Dia 2 acrescenta retry com backoff e jitter,
orçamento total e circuit breaker em volta de `_attempt`.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from autoseguro_agent.domain.models import QuoteRequest, QuoteResult
from autoseguro_agent.domain.quote import QuoteAttempt, QuoteOutcome, TraceContext
from autoseguro_agent.domain.rules import PlanRules, load_snapshot


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class HttpQuoteGateway:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 3.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client = client or httpx.AsyncClient(base_url=self._base_url)
        self._rules = load_snapshot()
        self.rules_source: Literal["api", "snapshot"] = "snapshot"

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
        attempt, outcome = await self._attempt(req, request_id, 1)
        return outcome.model_copy(update={"attempts": (attempt,)})

    async def _attempt(
        self, req: QuoteRequest, request_id: str, n: int
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
            resp = await self._client.post(
                "/quote",
                json=req.to_payload(),
                timeout=self._timeout_s,
                headers={"x-request-id": request_id, "x-attempt-id": attempt_id},
            )
        except httpx.TimeoutException:
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


def _failed(request_id: str) -> QuoteOutcome:
    return QuoteOutcome(quote_request_id=request_id, status="failed", failure_reason="exhausted")


def _invalid(request_id: str, reason: Literal["bad_input", "agent_bug"]) -> QuoteOutcome:
    return QuoteOutcome(quote_request_id=request_id, status="invalid", invalid_reason=reason)
