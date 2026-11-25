"""API HTTP: webhook do WhatsApp, dashboard e APIs de observabilidade.

- `POST /webhook/whatsapp` (formato Cloud API): idempotente por `wa_message_id` e, com
  Redis, só ENFILEIRA e responde na hora; o worker processa (REQ-90).
- `GET /dashboard`: conversas, métricas, custos, latência, cache, fila e trace (REQ-95).
- `POST /api/chat`, `POST /api/golden`, `GET /api/jobs/{id}`: chat manual e golden set
  pela mesma fila e pelo mesmo agente (REQ-96, 97).

O telefone do lead nunca é guardado: o `conversation_id` é um hash do número.

    uv run uvicorn autoseguro_agent.api:app --port 8080
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from autoseguro_agent.adapters.cache import CacheError, CacheStore, NullCache
from autoseguro_agent.agent import Agent, MessageType
from autoseguro_agent.dispatch import Dispatcher, InlineDispatcher
from autoseguro_agent.metrics import compute, conversation_summaries, trace
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


class ChatIn(BaseModel):
    conversation_id: str | None = None
    text: str = ""
    message_type: Literal["text", "image", "audio", "document"] = "text"


class GoldenIn(BaseModel):
    llm: Literal["fake", "anthropic"] = "fake"


def conversation_id_for(phone: str) -> str:
    """Hash do número: rastreável por conversa sem guardar o telefone (minimização)."""
    return "wa_" + hashlib.sha256(phone.encode()).hexdigest()[:16]


def _dashboard_html() -> str:
    return files("autoseguro_agent.static").joinpath("dashboard.html").read_text("utf-8")


def create_api(
    agent: Agent,
    events: EventStore,
    lifespan: Any = None,
    dispatcher: Dispatcher | None = None,
    cache: CacheStore | None = None,
    llm_mode: str = "fake",
) -> FastAPI:
    api = FastAPI(title="AutoSeguro Agent", version="0.2.0", lifespan=lifespan)
    dispatch: Dispatcher = dispatcher or InlineDispatcher(agent)
    store: CacheStore = cache or NullCache()

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/dashboard")

    @api.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return _dashboard_html()

    # --- canal --------------------------------------------------------------
    @api.post("/webhook/whatsapp")
    async def webhook(payload: WaWebhook) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for entry in payload.entry:
            for change in entry.changes:
                for msg in change.value.messages:
                    conv = conversation_id_for(msg.from_)
                    if store.enabled and not _first_delivery(store, msg.id):
                        results.append(
                            {
                                "conversation_id": conv,
                                "wa_message_id": msg.id,
                                "duplicate": True,
                                "messages": [],
                            }
                        )
                        continue
                    if msg.type == "text" and msg.text is not None:
                        text, mtype = msg.text.body, "text"
                    else:
                        text, mtype = f"[{msg.type}]", MEDIA_TYPES.get(msg.type, "document")
                    sub = await dispatch.submit_message(conv, text, mtype, msg.id)  # type: ignore[arg-type]
                    duplicate = (
                        sub["status"] == "finished"
                        and not sub["messages"]
                        and events.seen_wa_message(msg.id)
                    )
                    results.append(
                        {
                            "conversation_id": conv,
                            "wa_message_id": msg.id,
                            "duplicate": duplicate,
                            **sub,
                        }
                    )
        return {"processed": len(results), "results": results}

    # --- chat manual e golden set -------------------------------------------
    @api.post("/api/chat")
    async def chat(body: ChatIn) -> dict[str, Any]:
        conv = body.conversation_id or f"chat_{uuid.uuid4().hex[:8]}"
        text = body.text if body.message_type == "text" else f"[{body.message_type}]"
        sub = await dispatch.submit_message(conv, text, body.message_type)
        return {"conversation_id": conv, **sub}

    @api.post("/api/golden")
    async def golden(body: GoldenIn) -> dict[str, Any]:
        return await dispatch.submit_golden(body.llm)

    @api.get("/api/golden/last")
    def golden_last() -> dict[str, Any]:
        try:
            raw = store.get("golden:last")
        except CacheError:
            raw = None
        return json.loads(raw) if raw else {}

    @api.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        try:
            return dispatch.job(job_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="job não encontrado") from exc

    # --- observabilidade ----------------------------------------------------
    @api.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        hot: dict[str, list[tuple[str, int]]] = {}
        stats: dict[str, Any] = {}
        try:
            hot = {"llm": store.top_hot("llm", 10), "quote": store.top_hot("quote", 10)}
            stats = store.stats()
        except CacheError:
            stats = {"error": "redis indisponível"}
        data = compute(events.all_events(), queue=dispatch.info(), hot=hot, cache_stats=stats)
        data["config"] = {
            "llm_mode": llm_mode,
            "cache": "redis" if store.enabled else "off",
            "queue": dispatch.mode,
        }
        return data

    @api.get("/api/conversations")
    def conversations() -> list[dict[str, Any]]:
        return conversation_summaries(events.all_events())

    @api.get("/api/conversations/{conversation_id}")
    async def conversation_detail(conversation_id: str) -> dict[str, Any]:
        timeline = events.timeline(conversation_id)
        if not timeline:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        state = await agent.astate(conversation_id)
        summary = next(iter(conversation_summaries(timeline)), {})
        return {
            "summary": summary,
            "status": state.get("status"),
            "profile": state.get("profile"),
            "handoff": state.get("handoff"),
            "quotes": state.get("quotes", []),
            "turns": trace(timeline),
        }

    @api.get("/conversations/{conversation_id}")
    async def conversation(conversation_id: str) -> dict[str, Any]:
        """Linha do tempo crua (formato da entrega base)."""
        timeline = events.timeline(conversation_id)
        if not timeline:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        state = await agent.astate(conversation_id)
        return {
            "conversation_id": conversation_id,
            "status": state.get("status"),
            "handoff": state.get("handoff"),
            "quotes": state.get("quotes", []),
            "events": [e.model_dump(mode="json") for e in timeline],
        }

    return api


def _first_delivery(store: CacheStore, wa_message_id: str) -> bool:
    """SET NX no Redis: só a 1ª entrega de um wa_message_id é enfileirada."""
    try:
        return store.set_once(f"wa:{wa_message_id}", 86_400)
    except CacheError:
        return True


def _production_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        from autoseguro_agent.bootstrap import build_app

        built = await build_app(persistent=True, log_json=True)
        inner = create_api(
            built.agent,
            built.events,
            dispatcher=built.dispatcher,
            cache=built.cache,
            llm_mode=built.settings.llm_provider,
        )
        api.router.routes.extend(inner.router.routes)
        yield
        await built.aclose()

    return FastAPI(title="AutoSeguro Agent", version="0.2.0", lifespan=lifespan)


app = _production_app()
