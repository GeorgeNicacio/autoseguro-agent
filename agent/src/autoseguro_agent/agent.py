"""Fachada do agente: o que o CLI, o webhook e os testes chamam.

`handle()` mascara a mensagem ANTES de tudo (o texto cru nunca entra no estado,
no log nem no LLM), registra o recebimento e roda um turno do grafo.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from autoseguro_agent import templates
from autoseguro_agent.domain.events import Event
from autoseguro_agent.domain.models import QuoteResult
from autoseguro_agent.domain.quote import TraceContext
from autoseguro_agent.graph.build import build_graph
from autoseguro_agent.graph.nodes import Deps, Nodes
from autoseguro_agent.graph.state import TurnInput
from autoseguro_agent.pii import PiiMasker

MessageType = Literal["text", "image", "audio", "document"]


class Agent:
    def __init__(self, deps: Deps, checkpointer: Any = None) -> None:
        self.deps = deps
        self.masker = PiiMasker(deps.vault)
        self.nodes = Nodes(deps)
        self.graph = build_graph(deps, checkpointer, self.nodes)

    async def handle(
        self,
        conversation_id: str,
        text: str,
        *,
        message_type: MessageType = "text",
        wa_message_id: str | None = None,
    ) -> list[str]:
        if wa_message_id and self.deps.events.seen_wa_message(wa_message_id):
            self._event(conversation_id, None, "message.duplicate", "ignored", wa_message_id)
            return []

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        masked = self.masker.mask(text, conversation_id) if message_type == "text" else None
        turn: TurnInput = {
            "message_id": message_id,
            "text": masked.text if masked else f"[{message_type}]",
            "message_type": message_type,
            "pii_kinds": list(masked.kinds) if masked else [],
        }
        self._event(
            conversation_id,
            message_id,
            "message.received",
            "received",
            wa_message_id,
            {"message_type": message_type, "pii_kinds": turn["pii_kinds"], "text": turn["text"]},
        )
        t0 = self.deps.clock.monotonic()
        state = await self.graph.ainvoke(
            {"conversation_id": conversation_id, "turn": turn},
            config={"configurable": {"thread_id": conversation_id}},
        )
        self._event(conversation_id, message_id, "message.received", "processed", wa_message_id)
        self._event(
            conversation_id,
            message_id,
            "turn.finished",
            str(state.get("status")),
            None,
            {"replies": len(state.get("outbox", [])) + len(state.get("early_sent", []))},
            latency_ms=int((self.deps.clock.monotonic() - t0) * 1000),
        )
        return [*state.get("early_sent", []), *state.get("outbox", [])]

    async def astate(self, conversation_id: str) -> dict[str, Any]:
        snap = await self.graph.aget_state({"configurable": {"thread_id": conversation_id}})
        return dict(snap.values)

    async def retry_quote(self, conversation_id: str, attempt: int) -> dict[str, Any]:
        """REQ-91: nova tentativa de cotação depois de um handoff por infraestrutura.

        Se der certo, o lead recebe a cotação e o consultor é avisado (`handoff.updated`).
        Se falhar e ainda houver tentativas, agenda a próxima na fila.
        """
        config = {"configurable": {"thread_id": conversation_id}}
        s: Any = await self.astate(conversation_id)
        handoff = s.get("handoff") or {}
        if (
            s.get("status") != "handed_off"
            or handoff.get("rule_id") != "infra_unavailable"
            or s.get("quote_recovered")
        ):
            return {"status": "skipped"}

        n = self.nodes
        req, default_date = n.quote_request_for(s)
        ctx = TraceContext(conversation_id=conversation_id)
        t0 = self.deps.clock.monotonic()
        outcome = await self.deps.gateway.quote(req, ctx)
        total_ms = int((self.deps.clock.monotonic() - t0) * 1000)
        summary = n.record_quote(s, req, outcome, total_ms, retry_attempt=attempt)
        n.emit(
            s,
            "quote_retry.finished",
            outcome.status,
            quote_request_id=outcome.quote_request_id,
            handoff_id=handoff.get("handoff_id"),
            payload={"attempt": attempt},
        )

        update: dict[str, Any] = {"quotes": [*s.get("quotes", []), summary]}
        if outcome.status == "success" and outcome.result is not None:
            result: QuoteResult = outcome.result
            texts = [
                templates.quote_recovered(),
                templates.quote_message(result, self.deps.gateway.rules()),
            ]
            for text in texts:
                self.deps.outbound.send(conversation_id, text)
                n.emit(
                    s,
                    "message.sent",
                    "sent",
                    payload={"chars": len(text), "text": text, "kind": "quote_recovered"},
                )
            n.emit(
                s,
                "handoff.updated",
                "quote_recovered",
                handoff_id=handoff.get("handoff_id"),
                quote_request_id=outcome.quote_request_id,
                payload={"premio_mensal": str(result.premio_mensal), "attempt": attempt},
            )
            update |= {
                "last_success": result.model_dump(mode="json"),
                "quote_recovered": True,
                "start_date_default": default_date,
            }
            await self.graph.aupdate_state(config, update, as_node="deliver")
            return {"status": "success", "messages": texts}

        await self.graph.aupdate_state(config, update, as_node="deliver")
        delays = self.deps.quote_retry_delays_s
        if attempt < len(delays) and self.deps.tasks is not None:
            self.deps.tasks.schedule_quote_retry(conversation_id, attempt + 1, delays[attempt])
            n.emit(
                s,
                "quote_retry.scheduled",
                "scheduled",
                handoff_id=handoff.get("handoff_id"),
                payload={"attempt": attempt + 1, "delay_s": delays[attempt]},
            )
            return {"status": "rescheduled", "next_attempt": attempt + 1}
        return {"status": "gave_up"}

    def state(self, conversation_id: str) -> dict[str, Any]:
        snap = self.graph.get_state({"configurable": {"thread_id": conversation_id}})
        return dict(snap.values)

    def _event(
        self,
        conversation_id: str,
        message_id: str | None,
        event_type: Any,
        status: str,
        wa_message_id: str | None,
        payload: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        data = dict(payload or {})
        if wa_message_id:
            data["wa_message_id"] = wa_message_id
        self.deps.events.append(
            Event(
                ts=self.deps.clock.now(),
                event_type=event_type,
                conversation_id=conversation_id,
                message_id=message_id,
                status=status,
                payload=data,
                latency_ms=latency_ms,
            )
        )
