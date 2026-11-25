"""Gera o log de uma execução completa (entregável 4) em docs/demo-conversation.md.

Roda uma conversa roteirizada contra a instância `quote-api-demo` (instabilidade
padrão, QUOTE_SEED=4): o 1º pedido de cotação fica lento, o 2º falha com 5xx e o
3º responde, então o retry e a mensagem de espera aparecem no log. Reinicie o
container antes (make demo faz isso) para a sequência da seed começar do zero.

    py -m uv run python -m autoseguro_agent.evaluation.demo --out ../docs/demo-conversation.md
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.adapters.events_memory import InMemoryEventStore
from autoseguro_agent.agent import Agent
from autoseguro_agent.bootstrap import OutboxChannel, make_gateway, make_llm
from autoseguro_agent.domain.events import Event
from autoseguro_agent.graph.nodes import Deps
from autoseguro_agent.observability import LoggingEventStore, configure_logging
from autoseguro_agent.pii import InMemoryVault
from autoseguro_agent.settings import Settings

SCRIPT = (
    "Oi, quero fazer o seguro do meu carro",
    "é um Onix 2022",
    "35 anos",
    "meu cpf é 529.982.247-25 e o cep é 01310-100",
    "quero o completo",
    "e o premium?",
    "fechado, quero contratar",
)
CONVERSATION_ID = "demo_001"


class RecordingOutbox(OutboxChannel):
    pass


def _detail(e: Event) -> str:
    p = e.payload
    if e.event_type == "quote_attempt":
        return f"tentativa {p.get('attempt')} · http {p.get('http_status') or '—'}"
    if e.event_type == "quote_request.finished":
        extra = p.get("premio_mensal") or p.get("failure_reason") or ""
        return f"{p.get('attempts')} tentativa(s) {extra}".strip()
    if e.event_type == "handoff.opened":
        return f"regra {p.get('rule_id')} · prioridade {p.get('priority')}"
    if e.event_type == "slot.updated":
        return f"{p.get('slot')} = {p.get('value')}"
    if e.event_type == "message.received" and "pii_kinds" in p:
        kinds = ", ".join(p["pii_kinds"]) or "nenhum"
        return f"PII mascarada: {kinds}"
    if e.event_type == "message.sent" and p.get("kind") == "waiting":
        return "mensagem de espera"
    if e.event_type == "quote_request.started":
        return f"{p.get('plano_id')} · início {p.get('data_inicio')}"
    return ""


async def wait_until_up(url: str, seconds: float = 30) -> None:
    """O container da demo acabou de reiniciar (seed do zero): espera o /health."""
    import httpx

    async with httpx.AsyncClient() as client:
        for _ in range(int(seconds * 2)):
            try:
                if (await client.get(f"{url}/health", timeout=1)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise SystemExit(f"quote-service da demo não respondeu em {url}")


async def run(url: str, llm_provider: str) -> str:
    await wait_until_up(url)
    settings = Settings().model_copy(update={"quote_base_url": url, "llm_provider": llm_provider})
    gateway = make_gateway(settings)
    await gateway.load_rules()
    store = InMemoryEventStore()
    outbox = OutboxChannel()
    clock = SystemClock()
    agent = Agent(
        Deps(
            llm=make_llm(settings),
            gateway=gateway,
            events=LoggingEventStore(store),
            outbound=outbox,
            clock=clock,
            vault=InMemoryVault(),
        )
    )

    lines = [
        "# Log de uma execução completa (entregável 4)\n",
        f"Gerado por `python -m autoseguro_agent.evaluation.demo` em "
        f"{datetime.now().astimezone():%d/%m/%Y %H:%M} · LLM: "
        f"{settings.llm_model if llm_provider == 'anthropic' else 'FakeLLM (sem chave)'} · "
        f"quote-service real com instabilidade padrão e `QUOTE_SEED=4` · "
        f"regras de `/planos` vindas da {gateway.rules_source}.\n",
        f"`conversation_id = {CONVERSATION_ID}`. As falas do lead aparecem como o agente as "
        "guarda e manda ao LLM: já mascaradas (o lead digitou um CPF e um CEP fictícios).\n",
        "## Conversa\n",
    ]
    for text in SCRIPT:
        before = len(outbox.sent)
        await agent.handle(CONVERSATION_ID, text)
        received = [
            e
            for e in store.timeline(CONVERSATION_ID)
            if e.event_type == "message.received" and "text" in e.payload
        ]
        lines.append(f"**Lead:** {received[-1].payload['text']}\n")
        for _, reply in outbox.sent[before:]:
            lines.append("**Agente:** " + reply.replace("\n", "  \n") + "\n")

    state = agent.state(CONVERSATION_ID)
    lines += [
        "## Estado final\n",
        f"- Status da conversa: `{state.get('status')}`",
        f"- Handoff: `{(state.get('handoff') or {}).get('rule_id')}` "
        f"(`{(state.get('handoff') or {}).get('handoff_id')}`)",
        f"- Perfil guardado (mascarado): `{state.get('profile')}`",
        "",
        "## Linha do tempo de eventos\n",
        "Mesma linha do tempo que `GET /conversations/{id}` devolve e que vai para o log JSON.\n",
        "| # | Evento | Status | Latência | message_id | quote_request_id | quote_attempt_id "
        "| Detalhe |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, e in enumerate(store.timeline(CONVERSATION_ID), 1):
        lat = f"{e.latency_ms} ms" if e.latency_ms is not None else ""
        lines.append(
            f"| {i} | `{e.event_type}` | {e.status} | {lat} | {e.message_id or ''} | "
            f"{e.quote_request_id or ''} | {e.quote_attempt_id or ''} | {_detail(e)} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8003")
    ap.add_argument("--llm", choices=["fake", "anthropic"], default=None)
    ap.add_argument("--out")
    args = ap.parse_args()
    provider = args.llm or ("anthropic" if Settings().anthropic_api_key else "fake")
    configure_logging()
    doc = asyncio.run(run(args.url, provider))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(doc)
    print(doc)


if __name__ == "__main__":
    main()
