"""Fachada do agente: o que o CLI, o webhook e os testes chamam.

`handle()` mascara a mensagem ANTES de tudo (o texto cru nunca entra no estado,
no log nem no LLM), registra o recebimento e roda um turno do grafo.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from autoseguro_agent.domain.events import Event
from autoseguro_agent.graph.build import build_graph
from autoseguro_agent.graph.nodes import Deps
from autoseguro_agent.graph.state import TurnInput
from autoseguro_agent.pii import PiiMasker

MessageType = Literal["text", "image", "audio", "document"]


class Agent:
    def __init__(self, deps: Deps, checkpointer: Any = None) -> None:
        self.deps = deps
        self.masker = PiiMasker(deps.vault)
        self.graph = build_graph(deps, checkpointer)

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
        state = await self.graph.ainvoke(
            {"conversation_id": conversation_id, "turn": turn},
            config={"configurable": {"thread_id": conversation_id}},
        )
        self._event(conversation_id, message_id, "message.received", "processed", wa_message_id)
        return list(state.get("outbox", []))

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
            )
        )
