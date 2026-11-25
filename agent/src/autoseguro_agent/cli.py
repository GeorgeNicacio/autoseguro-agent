"""Chat no terminal para demo.

    uv run python -m autoseguro_agent.cli                 # Claude (precisa ANTHROPIC_API_KEY)
    uv run python -m autoseguro_agent.cli --fake-llm      # sem chave, extrator heurístico
    uv run python -m autoseguro_agent.cli --events        # mostra a linha do tempo de eventos
    uv run python -m autoseguro_agent.cli --script conversa.txt   # uma mensagem por linha

Mensagens começando com [audio], [imagem] ou [documento] simulam mídia.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from autoseguro_agent.agent import MessageType
from autoseguro_agent.bootstrap import build_app
from autoseguro_agent.domain.events import Event
from autoseguro_agent.settings import Settings

MEDIA_PREFIX: dict[str, MessageType] = {
    "[audio]": "audio",
    "[imagem]": "image",
    "[documento]": "document",
}


def format_event(e: Event) -> str:
    ids = " ".join(
        f"{k}={v}"
        for k, v in (
            ("msg", e.message_id),
            ("qr", e.quote_request_id),
            ("qa", e.quote_attempt_id),
            ("ho", e.handoff_id),
        )
        if v
    )
    lat = f" {e.latency_ms}ms" if e.latency_ms is not None else ""
    extra = ""
    if e.event_type == "handoff.opened":
        extra = f" rule={e.payload.get('rule_id')} prio={e.payload.get('priority')}"
    if e.event_type == "quote_attempt":
        extra = f" tentativa={e.payload.get('attempt')} http={e.payload.get('http_status')}"
    return f"    · {e.event_type} [{e.status}]{lat} {ids}{extra}"


async def run(args: argparse.Namespace) -> int:
    settings = Settings()
    if args.fake_llm:
        settings = settings.model_copy(update={"llm_provider": "fake"})
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key is None:
        print("ANTHROPIC_API_KEY não configurada. Use --fake-llm ou crie agent/.env.")
        return 2

    app = await build_app(settings)
    conv = args.conversation or f"conv_{uuid.uuid4().hex[:8]}"
    print(
        f"conversation_id={conv} · LLM={settings.llm_provider} · regras={app.gateway.rules_source}"
    )
    print("Digite sua mensagem (/sair para encerrar).\n")

    lines = Path(args.script).read_text(encoding="utf-8").splitlines() if args.script else None
    seen = 0
    while True:
        if lines is not None:
            if not lines:
                break
            text = lines.pop(0).strip()
            if not text:
                continue
            print(f"Lead: {text}")
        else:
            try:
                text = (await asyncio.to_thread(input, "Lead: ")).strip()
            except EOFError:
                break
        if text in {"/sair", "/exit"}:
            break
        mtype: MessageType = next(
            (t for p, t in MEDIA_PREFIX.items() if text.lower().startswith(p)), "text"
        )
        replies = await app.agent.handle(conv, text, message_type=mtype)
        for r in replies:
            print("Agente: " + r.replace("\n", "\n        "))
        if args.events:
            timeline = app.events.timeline(conv)
            for e in timeline[seen:]:
                print(format_event(e))
            seen = len(timeline)
        print()
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser(description="Chat com o agente AutoSeguro")
    ap.add_argument("--fake-llm", action="store_true")
    ap.add_argument("--events", action="store_true")
    ap.add_argument("--conversation")
    ap.add_argument("--script")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
