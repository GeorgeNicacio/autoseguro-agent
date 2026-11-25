"""API HTTP: webhook no formato do WhatsApp Cloud API + linha do tempo (REQ-42, 43, 60).

Simula o canal real sem depender de Meta ou Twilio. O telefone do lead nunca é
guardado: o `conversation_id` é um hash do número de origem.

    uv run uvicorn autoseguro_agent.api:app --port 8080
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from autoseguro_agent.agent import Agent, MessageType
from autoseguro_agent.ports import EventStore

MEDIA_TYPES: dict[str, MessageType] = {
    "image": "image",
    "audio": "audio",
    "voice": "audio",
    "document": "document",
    "video": "image",
    "sticker": "image",
}


# --- subconjunto do payload do WhatsApp Cloud API -------------------------------
class WaText(BaseModel):
    body: str


class WaMessage(BaseModel):
    from_: str = Field(alias="from")
    id: str
    type: str
    text: WaText | None = None


class WaValue(BaseModel):
    messages: list[WaMessage] = Field(default_factory=list)


class WaChange(BaseModel):
    value: WaValue


class WaEntry(BaseModel):
    changes: list[WaChange] = Field(default_factory=list)


class WaWebhook(BaseModel):
    object: str = "whatsapp_business_account"
    entry: list[WaEntry] = Field(default_factory=list)


def conversation_id_for(phone: str) -> str:
    """Hash do número: rastreável por conversa sem guardar o telefone (minimização)."""
    return "wa_" + hashlib.sha256(phone.encode()).hexdigest()[:16]


def create_api(agent: Agent, events: EventStore, lifespan: Any = None) -> FastAPI:
    api = FastAPI(title="AutoSeguro Agent", version="0.1.0", lifespan=lifespan)

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/webhook/whatsapp")
    async def webhook(payload: WaWebhook) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for entry in payload.entry:
            for change in entry.changes:
                for msg in change.value.messages:
                    conv = conversation_id_for(msg.from_)
                    if msg.type == "text" and msg.text is not None:
                        replies = await agent.handle(conv, msg.text.body, wa_message_id=msg.id)
                    else:
                        mtype = MEDIA_TYPES.get(msg.type, "document")
                        replies = await agent.handle(
                            conv, f"[{msg.type}]", message_type=mtype, wa_message_id=msg.id
                        )
                    results.append(
                        {
                            "conversation_id": conv,
                            "wa_message_id": msg.id,
                            "duplicate": not replies and events.seen_wa_message(msg.id),
                            "messages": replies,
                        }
                    )
        return {"processed": len(results), "results": results}

    @api.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict[str, Any]:
        timeline = events.timeline(conversation_id)
        if not timeline:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        state = agent.state(conversation_id)
        return {
            "conversation_id": conversation_id,
            "status": state.get("status"),
            "handoff": state.get("handoff"),
            "quotes": state.get("quotes", []),
            "events": [e.model_dump(mode="json") for e in timeline],
        }

    return api


def _production_app() -> FastAPI:
    holder: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        from autoseguro_agent.bootstrap import build_app

        built = await build_app(persistent=True, log_json=True)
        holder["app"] = built
        inner = create_api(built.agent, built.events)
        api.router.routes.extend(inner.router.routes)
        yield
        await built.aclose()

    return FastAPI(title="AutoSeguro Agent", version="0.1.0", lifespan=lifespan)


app = _production_app()
