"""Teste de caos contra o quote-service REAL (T2.6 · SMART M-02, M-03, M-04, M-07, M-08).

Roda N conversas completas em paralelo contra uma instância instável e mede:
- travas: turno que passou do limite sem responder;
- preço sem cotação válida: qualquer R$ numa conversa sem cotação `success`;
- falha esgotada sem handoff;
- latência por pedido de cotação, tentativas, sucesso e breaker.

O LLM é o FakeLLM: o que se testa aqui é a resiliência, não a extração.

    py -m uv run python -m autoseguro_agent.evaluation.chaos --url http://localhost:8001 \\
        --out ../docs/evidence/chaos_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from autoseguro_agent.adapters.circuit_breaker import CircuitBreaker
from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.adapters.events_memory import InMemoryEventStore
from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.adapters.quote_http import HttpQuoteGateway
from autoseguro_agent.agent import Agent
from autoseguro_agent.bootstrap import OutboxChannel
from autoseguro_agent.graph.nodes import Deps
from autoseguro_agent.pii import InMemoryVault

HANG_LIMIT_S = 15.0
MONEY = re.compile(r"R\$")
CEPS = ["01310-100", "04538-132", "21040-020", "30130-010", "80010-000", "59010-000"]
PLANS = ["essencial", "completo", "premium"]


@dataclass
class ChaosReport:
    conversations: int
    concurrency: int
    url: str
    hangs: int = 0
    money_without_success: int = 0
    failed_without_handoff: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    request_status: Counter[str] = field(default_factory=Counter)
    failure_reasons: Counter[str] = field(default_factory=Counter)
    attempt_status: Counter[str] = field(default_factory=Counter)
    attempts_per_request: Counter[int] = field(default_factory=Counter)
    waiting_messages: int = 0
    request_latency_ms: list[int] = field(default_factory=list)
    turn_seconds: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        lat = sorted(self.request_latency_ms)
        turns = sorted(self.turn_seconds)

        def pct(xs: list[Any], p: float) -> Any:
            return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))] if xs else None

        done = self.request_status["success"] + self.request_status["failed"]
        return {
            "conversations": self.conversations,
            "concurrency": self.concurrency,
            "url": self.url,
            "hangs": self.hangs,
            "money_without_success": self.money_without_success,
            "failed_without_handoff": self.failed_without_handoff,
            "conversation_status": dict(self.statuses),
            "quote_request_status": dict(self.request_status),
            "failure_reasons": dict(self.failure_reasons),
            "attempt_status": dict(self.attempt_status),
            "attempts_per_request": {
                str(k): v for k, v in sorted(self.attempts_per_request.items())
            },
            "success_rate": round(self.request_status["success"] / done, 4) if done else None,
            "waiting_messages": self.waiting_messages,
            "request_latency_ms": {
                "p50": pct(lat, 50),
                "p95": pct(lat, 95),
                "max": lat[-1] if lat else None,
            },
            "turn_seconds": {
                "p50": round(pct(turns, 50), 2) if turns else None,
                "max": round(turns[-1], 2) if turns else None,
            },
        }


async def run_chaos(url: str, n: int = 50, concurrency: int = 10, seed: int = 7) -> ChaosReport:
    rng = random.Random(seed)
    clock = SystemClock()
    gateway = HttpQuoteGateway(url, breaker=CircuitBreaker(clock, 5, 30), clock=clock)
    await gateway.load_rules()
    events = InMemoryEventStore()
    agent = Agent(
        Deps(
            llm=FakeLLM(),
            gateway=gateway,
            events=events,
            outbound=OutboxChannel(),
            clock=clock,
            vault=InMemoryVault(),
        )
    )
    report = ChaosReport(conversations=n, concurrency=concurrency, url=url)
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int) -> None:
        conv = f"chaos_{i:03d}"
        idade = rng.randint(18, 75)
        ano = rng.randint(2007, 2026)
        text = f"tenho {idade} anos, Onix {ano}, cep {rng.choice(CEPS)}, {rng.choice(PLANS)}"
        async with sem:
            t0 = time.perf_counter()
            try:
                replies = await asyncio.wait_for(agent.handle(conv, text), timeout=HANG_LIMIT_S)
            except TimeoutError:
                report.hangs += 1
                return
            report.turn_seconds.append(time.perf_counter() - t0)

        state = agent.state(conv)
        report.statuses[state.get("status", "?")] += 1
        has_success = bool(state.get("last_success"))
        if not has_success and any(MONEY.search(r) for r in replies):
            report.money_without_success += 1
        timeline = events.timeline(conv)
        finished = [e for e in timeline if e.event_type == "quote_request.finished"]
        for e in finished:
            report.request_status[e.status] += 1
            report.request_latency_ms.append(e.latency_ms or 0)
            report.attempts_per_request[int(e.payload.get("attempts", 0))] += 1
            if e.status == "failed":
                report.failure_reasons[str(e.payload.get("failure_reason"))] += 1
        for e in timeline:
            if e.event_type == "quote_attempt":
                report.attempt_status[e.status] += 1
            if e.payload.get("kind") == "waiting":
                report.waiting_messages += 1
        failed = any(e.status == "failed" for e in finished)
        handed = any(e.event_type == "handoff.opened" for e in timeline)
        if failed and not handed:
            report.failed_without_handoff += 1

    await asyncio.gather(*(one(i) for i in range(n)))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8001")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--out")
    args = ap.parse_args()
    report = asyncio.run(run_chaos(args.url, args.n, args.concurrency))
    data = report.summary()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")


if __name__ == "__main__":
    main()
