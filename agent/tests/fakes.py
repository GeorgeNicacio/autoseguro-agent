"""Fakes compartilhados pelos testes de fluxo (sem rede, determinísticos)."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from autoseguro_agent.adapters.clock import FixedClock
from autoseguro_agent.adapters.events_memory import InMemoryEventStore
from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.agent import Agent
from autoseguro_agent.domain.models import QuoteRequest, QuoteResult
from autoseguro_agent.domain.quote import QuoteAttempt, QuoteOutcome, TraceContext
from autoseguro_agent.domain.rules import PlanRules, load_snapshot
from autoseguro_agent.graph.nodes import Deps
from autoseguro_agent.pii import InMemoryVault
from tests.unit.test_models import API_200

PLAN_NAMES = {"essencial": "Essencial", "completo": "Completo", "premium": "Premium"}


def success_for(req: QuoteRequest) -> QuoteResult:
    data: dict[str, Any] = {
        **API_200,
        "plano_id": req.plano_id,
        "plano_nome": PLAN_NAMES[req.plano_id],
    }
    data.pop("primeiro_pagamento_pro_rata")
    return QuoteResult.model_validate(data)


class FakeGateway:
    """Responde sucesso por padrão; aceita uma fila de status para simular falhas."""

    def __init__(self, script: Iterable[str] = ()) -> None:
        self.script: deque[str] = deque(script)
        self.requests: list[QuoteRequest] = []
        self._rules = load_snapshot()

    def rules(self) -> PlanRules:
        return self._rules

    async def quote(self, req: QuoteRequest, ctx: TraceContext) -> QuoteOutcome:
        self.requests.append(req)
        n = len(self.requests)
        status = self.script.popleft() if self.script else "success"
        attempt = QuoteAttempt(
            quote_attempt_id=f"qa_{n}",
            attempt=1,
            latency_ms=5,
            status={"success": "ok", "failed": "http_5xx", "refused": "refused"}.get(
                status, "invalid"
            ),  # type: ignore[arg-type]
        )
        rid = f"qr_{n}"
        if status == "success":
            return QuoteOutcome(
                quote_request_id=rid,
                status="success",
                result=success_for(req),
                attempts=(attempt,),
            )
        if status == "failed":
            return QuoteOutcome(
                quote_request_id=rid,
                status="failed",
                failure_reason="exhausted",
                attempts=(attempt,),
            )
        if status == "refused":
            return QuoteOutcome(
                quote_request_id=rid,
                status="refused",
                refusal_motivo="Recusado.",
                attempts=(attempt,),
            )
        return QuoteOutcome(
            quote_request_id=rid,
            status="invalid",
            invalid_reason="agent_bug",
            attempts=(attempt,),
        )


class Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, conversation_id: str, text: str) -> None:
        self.sent.append((conversation_id, text))


def make_agent(
    gateway: FakeGateway | None = None, llm: FakeLLM | None = None
) -> tuple[Agent, FakeGateway, FakeLLM, InMemoryEventStore]:
    gw = gateway or FakeGateway()
    fake_llm = llm or FakeLLM()
    events = InMemoryEventStore()
    deps = Deps(
        llm=fake_llm,
        gateway=gw,
        events=events,
        outbound=Outbox(),
        clock=FixedClock(),
        vault=InMemoryVault(),
    )
    return Agent(deps), gw, fake_llm, events
