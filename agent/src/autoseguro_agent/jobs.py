"""Jobs executados pelo worker RQ (`rq worker ... -w rq.worker.SimpleWorker agent`).

O worker é o único processo que roda o agente. Ele mantém UM event loop e UMA
instância do app (cliente HTTP, conexão do checkpoint, cofre de PII) entre jobs:
por isso o SimpleWorker, que não faz fork por job.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
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
    result = loop.run_until_complete(run_golden_for_app(app, llm))
    with contextlib.suppress(Exception):
        app.cache.set("golden:last", json.dumps(result), 30 * 86_400)
    return result


async def run_golden_for_app(app: App, llm: str) -> dict[str, Any]:
    """Roda o golden set gravando os eventos no mesmo store do dashboard."""
    from autoseguro_agent.adapters.llm_fake import FakeLLM
    from autoseguro_agent.bootstrap import make_llm
    from autoseguro_agent.evaluation.golden import run_golden

    settings = app.settings.model_copy(update={"llm_provider": llm})
    run_id = uuid.uuid4().hex[:6]

    def factory() -> Any:
        return FakeLLM() if llm == "fake" else make_llm(settings)

    results = await run_golden(
        app.settings.golden_quote_url, factory, events=app.events, run_id=run_id
    )
    return {
        "run_id": run_id,
        "llm": "FakeLLM" if llm == "fake" else settings.llm_model,
        "passed": sum(r.ok for r in results),
        "total": len(results),
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
