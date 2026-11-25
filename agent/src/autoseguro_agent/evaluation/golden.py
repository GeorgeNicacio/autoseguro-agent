"""Golden set: conversas roteirizadas inspiradas no dataset (T3.1 · SMART M-05).

Cada cenário roda o agente inteiro contra o quote-service real numa instância
ESTÁVEL (sem falha simulada), para que o resultado seja determinístico. Os casos de
falha usam injeção controlada: API inacessível (G10) e latência injetada (G11).

    py -m uv run python -m autoseguro_agent.evaluation.golden --url http://localhost:8002 \\
        --out ../docs/evidence/golden_report.md
    # com o Claude real no lugar do FakeLLM:
    py -m uv run python -m autoseguro_agent.evaluation.golden --llm anthropic
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from autoseguro_agent.adapters.circuit_breaker import CircuitBreaker
from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.adapters.events_memory import InMemoryEventStore
from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.adapters.quote_http import HttpQuoteGateway
from autoseguro_agent.agent import Agent, MessageType
from autoseguro_agent.bootstrap import OutboxChannel, make_llm
from autoseguro_agent.graph.nodes import Deps
from autoseguro_agent.pii import InMemoryVault, contains_pii
from autoseguro_agent.ports import EventStore, LLMClient
from autoseguro_agent.settings import Settings

MEDIA: dict[str, MessageType] = {"[imagem]": "image", "[audio]": "audio", "[documento]": "document"}
FULL = "tenho 35 anos, um Onix 2022, cep 01310-100, quero o completo"


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    messages: tuple[str, ...]
    status: str
    handoff_rule: str | None = None
    quotes: int | None = None
    premio: str | None = None
    contains: tuple[str, ...] = ()
    not_contains: tuple[str, ...] = ()
    gateway: str = "stable"  # stable | down | slow


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "G01",
        "Caminho feliz, um dado por vez",
        ("Oi, quero cotar o seguro do meu carro", "um Onix 2022", "35", "01310-100", "completo"),
        "quoted",
        quotes=1,
        premio="209.90",
        contains=("R$ 209,90", "01/12/2026"),
    ),
    Scenario(
        "G02",
        "Condutor de 22 anos (×1,60)",
        ("Oi! tenho 22 anos, um HB20 2022, cep 01310-100, quero o completo",),
        "quoted",
        quotes=1,
        premio="335.84",
    ),
    Scenario(
        "G03",
        "Carro 2003: recusa local, sem chamar a API",
        ("quero cotar meu Corolla 2003",),
        "handed_off",
        "out_of_policy",
        quotes=0,
        contains=("20 anos",),
        not_contains=("R$",),
    ),
    Scenario(
        "G04",
        "Condutor de 80 anos: recusa local",
        ("tenho um Gol 2020", "tenho 80 anos"),
        "handed_off",
        "out_of_policy",
        quotes=0,
        not_contains=("R$",),
    ),
    Scenario(
        "G05",
        "CEP de alto risco (×1,30)",
        ("35 anos, Onix 2022, cep 21040-020, completo",),
        "quoted",
        quotes=1,
        premio="272.87",
    ),
    Scenario(
        "G06",
        "Pede atendente no meio",
        ("Oi, tenho um Onix 2022", "quero falar com um atendente"),
        "handed_off",
        "explicit_request",
        quotes=0,
    ),
    Scenario(
        "G07",
        "Manda foto e depois responde por texto",
        ("Oi, tenho um Onix 2022", "[imagem]", "35 anos, cep 01310-100, completo"),
        "quoted",
        quotes=1,
        contains=("Não preciso desse arquivo",),
    ),
    Scenario(
        "G07b",
        "Responde com áudio duas vezes",
        ("Oi, tenho um Onix 2022", "[audio]", "[audio]"),
        "handed_off",
        "media_unsupported",
        quotes=0,
    ),
    Scenario(
        "G08",
        "Pede desconto depois da cotação",
        (FULL, "tem desconto à vista?"),
        "handed_off",
        "price_negotiation",
        quotes=1,
    ),
    Scenario(
        "G09",
        "Manda CPF sem ser pedido",
        ("Oi, meu cpf é 529.982.247-25, tenho 35 anos e um Onix 2022", "cep 01310-100, completo"),
        "quoted",
        quotes=1,
        contains=("não preciso de CPF",),
        not_contains=("529.982",),
    ),
    Scenario(
        "G10",
        "API fora do ar",
        (FULL,),
        "handed_off",
        "infra_unavailable",
        quotes=1,
        contains=("instável",),
        not_contains=("R$",),
        gateway="down",
    ),
    Scenario(
        "G11",
        "API lenta duas vezes e depois responde",
        (FULL,),
        "quoted",
        quotes=1,
        premio="209.90",
        contains=("Estou calculando",),
        gateway="slow",
    ),
    Scenario(
        "G12",
        "CEP incompleto e depois sem resposta",
        ("tenho 35 anos e um Onix 2022", "1310-100", "sei la"),
        "handed_off",
        "stuck",
        quotes=0,
    ),
    Scenario(
        "G13",
        "Sinistro",
        ("bati o carro ontem, como aciono o seguro?",),
        "handed_off",
        "out_of_scope",
        quotes=0,
    ),
    Scenario(
        "G14",
        "Uso comercial (Uber)",
        ("quero cotar, é pra rodar de uber",),
        "handed_off",
        "out_of_scope",
        quotes=0,
    ),
    Scenario(
        "G15",
        "Cotou e quer fechar",
        (FULL, "fechado, quero contratar"),
        "handed_off",
        "ready_to_close",
        quotes=1,
    ),
    Scenario(
        "G16",
        "Não sabe o plano (carro 2012)",
        ("tenho 40 anos, um Gol 2012, cep 01310-100", "não sei, me indica"),
        "quoted",
        quotes=1,
        contains=("recomendo", "Essencial", "Completo"),
    ),
    Scenario(
        "G17",
        "Acha a franquia alta",
        (FULL, "a franquia tá alta"),
        "quoted",
        quotes=1,
        contains=("Franquia por plano",),
    ),
    Scenario(
        "G18", "Vou pensar", (FULL, "vou pensar"), "quoted", quotes=1, contains=("à disposição",)
    ),
    Scenario(
        "G19",
        "Condutor de 65 anos (×1,40)",
        ("tenho 65 anos, Onix 2022, cep 01310-100, completo",),
        "quoted",
        quotes=1,
        premio="293.86",
    ),
)


class LatencyInjectingTransport(httpx.AsyncBaseTransport):
    """Atrasa as primeiras chamadas ao /quote e depois repassa para a API real."""

    def __init__(self, delays_s: list[float]) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self._delays: deque[float] = deque(delays_s)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/quote" and self._delays:
            await asyncio.sleep(self._delays.popleft())
        return await self._inner.handle_async_request(request)


@dataclass
class Result:
    scenario: Scenario
    ok: bool
    got: dict[str, Any]
    problems: list[str] = field(default_factory=list)
    conversation_id: str = ""


def _gateway(kind: str, url: str, clock: SystemClock) -> HttpQuoteGateway:
    if kind == "down":
        return HttpQuoteGateway("http://127.0.0.1:9", timeout_s=0.5, clock=clock)
    client = None
    if kind == "slow":
        client = httpx.AsyncClient(base_url=url, transport=LatencyInjectingTransport([10, 10]))
    return HttpQuoteGateway(url, client=client, breaker=CircuitBreaker(clock, 5, 30), clock=clock)


async def run_scenario(
    sc: Scenario,
    url: str,
    llm: LLMClient,
    events: EventStore | None = None,
    run_id: str | None = None,
) -> Result:
    """Sem cache de propósito: o golden set avalia o fluxo e o modelo de verdade."""
    clock = SystemClock()
    gw = _gateway(sc.gateway, url, clock)
    await gw.load_rules()
    events = events if events is not None else InMemoryEventStore()
    agent = Agent(
        Deps(
            llm=llm,
            gateway=gw,
            events=events,
            outbound=OutboxChannel(),
            clock=clock,
            vault=InMemoryVault(),
        )
    )
    conv = f"golden_{run_id}_{sc.id}" if run_id else f"golden_{sc.id}"
    replies: list[str] = []
    for text in sc.messages:
        mtype = MEDIA.get(text, "text")
        replies += await agent.handle(conv, text, message_type=mtype)

    state = agent.state(conv)
    joined = "\n".join(replies)
    handoff = (state.get("handoff") or {}).get("rule_id")
    quotes = len(state.get("quotes", []))
    last = state.get("last_success") or {}
    premio = str(Decimal(str(last["premio_mensal"])).quantize(Decimal("0.01"))) if last else None
    got = {"status": state.get("status"), "handoff": handoff, "quotes": quotes, "premio": premio}

    problems: list[str] = []
    if got["status"] != sc.status:
        problems.append(f"status {got['status']} != {sc.status}")
    if handoff != sc.handoff_rule:
        problems.append(f"handoff {handoff} != {sc.handoff_rule}")
    if sc.quotes is not None and quotes != sc.quotes:
        problems.append(f"cotações {quotes} != {sc.quotes}")
    if sc.premio and premio != sc.premio:
        problems.append(f"prêmio {premio} != {sc.premio}")
    problems += [f"faltou '{c}'" for c in sc.contains if c not in joined]
    problems += [f"não devia ter '{c}'" for c in sc.not_contains if c in joined]
    if not last and re.search(r"R\$", joined) and sc.id not in {"G03"}:
        problems.append("R$ sem cotação válida")
    if any(contains_pii(str(e.payload)) for e in events.timeline(conv)):
        problems.append("PII crua nos eventos")
    return Result(sc, not problems, got, problems, conv)


async def run_golden(
    url: str, llm_factory: Any, events: EventStore | None = None, run_id: str | None = None
) -> list[Result]:
    return [await run_scenario(sc, url, llm_factory(), events, run_id) for sc in SCENARIOS]


def to_markdown(results: list[Result], llm_name: str) -> str:
    passed = sum(r.ok for r in results)
    lines = [
        "# Golden set (T3.1 · SMART M-05)\n",
        f"Gerado por `python -m autoseguro_agent.evaluation.golden` · LLM: {llm_name} · "
        f"quote-service real sem falha simulada (G10 e G11 com falha injetada).\n",
        f"**{passed} de {len(results)} cenários passaram.**\n",
        "| # | Cenário | Esperado | Obtido | Resultado |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        sc = r.scenario
        exp = sc.status + (f" · {sc.handoff_rule}" if sc.handoff_rule else "")
        if sc.premio:
            exp += f" · R$ {sc.premio.replace('.', ',')}"
        got = str(r.got["status"]) + (f" · {r.got['handoff']}" if r.got["handoff"] else "")
        if r.got["premio"]:
            got += f" · R$ {r.got['premio'].replace('.', ',')}"
        verdict = "passou" if r.ok else "falhou: " + "; ".join(r.problems)
        lines.append(f"| {sc.id} | {sc.title} | {exp} | {got} | {verdict} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8002")
    ap.add_argument("--llm", choices=["fake", "anthropic"], default="fake")
    ap.add_argument("--out")
    args = ap.parse_args()
    settings = Settings().model_copy(update={"llm_provider": args.llm})

    def factory() -> LLMClient:
        return FakeLLM() if args.llm == "fake" else make_llm(settings)

    results = asyncio.run(run_golden(args.url, factory))
    report = to_markdown(results, "FakeLLM" if args.llm == "fake" else settings.llm_model)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(report)
    sys.exit(0 if all(r.ok for r in results) else 1)


if __name__ == "__main__":
    main()
