"""Jobs executados pelo worker RQ (`rq worker ... -w rq.worker.SimpleWorker agent`).

O worker é o único processo que roda o agente. Ele mantém UM event loop e UMA
instância do app (cliente HTTP, conexão do checkpoint, cofre de PII) entre jobs:
por isso o SimpleWorker, que não faz fork por job.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from autoseguro_agent.agent import MessageType
from autoseguro_agent.bootstrap import App, build_app

_loop: asyncio.AbstractEventLoop | None = None
_app: App | None = None


def _runtime() -> tuple[asyncio.AbstractEventLoop, App]:
    global _loop, _app
    if _loop is None or _app is None:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _app = _loop.run_until_complete(build_app(persistent=True, log_json=True, worker=True))
    return _loop, _app


def process_message_job(
    conversation_id: str,
    text: str,
    message_type: MessageType,
    wa_message_id: str | None,
    llm: str | None = None,
) -> dict[str, Any]:
    loop, app = _runtime()
    messages = loop.run_until_complete(
        app.agent.handle(
            conversation_id,
            text,
            message_type=message_type,
            wa_message_id=wa_message_id,
            llm=llm,
        )
    )
    return {"conversation_id": conversation_id, "messages": messages}


def retry_quote_job(conversation_id: str, attempt: int) -> dict[str, Any]:
    loop, app = _runtime()
    return loop.run_until_complete(app.agent.retry_quote(conversation_id, attempt))


def run_golden_job(llm: str) -> dict[str, Any]:
    loop, app = _runtime()
    return loop.run_until_complete(run_golden_for_app(app, llm))


async def run_golden_for_app(app: App, llm: str) -> dict[str, Any]:
    """Roda o golden set gravando os eventos no mesmo store do dashboard e guarda um
    resumo (acerto, custo, tokens, latência) para comparar modelos."""
    from autoseguro_agent.bootstrap import make_named_llm, resolve_llm_choice
    from autoseguro_agent.evaluation.golden import run_golden

    name = resolve_llm_choice(app.settings, llm) or "fake"
    run_id = uuid.uuid4().hex[:6]
    started = time.perf_counter()
    results = await run_golden(
        app.settings.golden_quote_url,
        lambda: make_named_llm(app.settings, name),
        events=app.events,
        run_id=run_id,
    )
    usage = _usage(app, f"golden_{run_id}_", len(results))
    summary = {
        "run_id": run_id,
        "llm": "FakeLLM" if name == "fake" else name,
        "model": name,
        "passed": sum(r.ok for r in results),
        "total": len(results),
        "duration_s": round(time.perf_counter() - started, 1),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **usage,
    }
    result = {
        **summary,
        "results": [
            {
                "id": r.scenario.id,
                "title": r.scenario.title,
                "ok": r.ok,
                "expected": {
                    "status": r.scenario.status,
                    "handoff": r.scenario.handoff_rule,
                    "premio": r.scenario.premio,
                },
                "got": r.got,
                "problems": r.problems,
                "conversation_id": r.conversation_id,
            }
            for r in results
        ],
    }
    _remember(app, result, summary)
    return result


def _usage(app: App, prefix: str, conversations: int) -> dict[str, Any]:
    calls = [
        e
        for e in app.events.all_events()
        if e.event_type == "llm.call" and e.conversation_id.startswith(prefix)
    ]
    lat = sorted(e.latency_ms or 0 for e in calls)
    cost = sum(float(e.payload.get("cost_usd", 0.0)) for e in calls)
    return {
        "llm_calls": len(calls),
        "cost_usd": round(cost, 6),
        "cost_per_conversation_usd": round(cost / max(conversations, 1), 6),
        "input_tokens": sum(int(e.payload.get("input_tokens", 0)) for e in calls),
        "output_tokens": sum(int(e.payload.get("output_tokens", 0)) for e in calls),
        "cache_read_tokens": sum(int(e.payload.get("cache_read_tokens", 0)) for e in calls),
        "llm_latency_p50_ms": lat[len(lat) // 2] if lat else None,
        "llm_latency_p95_ms": lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))] if lat else None,
    }


def _remember(app: App, result: dict[str, Any], summary: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):
        app.cache.set("golden:last", json.dumps(result), 30 * 86_400)
        raw = app.cache.get("golden:history")
        history = json.loads(raw) if raw else []
        app.cache.set("golden:history", json.dumps([summary, *history][:20]), 90 * 86_400)
