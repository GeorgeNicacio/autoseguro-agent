"""Composition root: o único lugar que conhece todos os adaptadores (SOLID · D)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autoseguro_agent.adapters.circuit_breaker import CircuitBreaker
from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.adapters.events_memory import InMemoryEventStore
from autoseguro_agent.adapters.llm_anthropic import AnthropicLLM
from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.adapters.quote_http import HttpQuoteGateway
from autoseguro_agent.adapters.sqlite_events import SqliteEventStore
from autoseguro_agent.agent import Agent
from autoseguro_agent.graph.nodes import Deps
from autoseguro_agent.observability import LoggingEventStore, configure_logging
from autoseguro_agent.pii import InMemoryVault
from autoseguro_agent.ports import EventStore, LLMClient, OutboundChannel
from autoseguro_agent.settings import Settings


class OutboxChannel:
    """Simula o envio pelo WhatsApp: guarda o que saiu (o webhook devolve na resposta)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, conversation_id: str, text: str) -> None:
        self.sent.append((conversation_id, text))


@dataclass
class App:
    agent: Agent
    gateway: HttpQuoteGateway
    events: EventStore
    settings: Settings
    closers: list[Any] = field(default_factory=list)

    async def aclose(self) -> None:
        for closer in self.closers:
            await closer()


def make_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLM()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return AnthropicLLM(
        model=settings.llm_model,
        effort=settings.llm_effort,
        timeout_s=settings.llm_timeout_s,
        api_key=key,
    )


def make_gateway(settings: Settings) -> HttpQuoteGateway:
    clock = SystemClock()
    return HttpQuoteGateway(
        settings.quote_base_url,
        timeout_s=settings.quote_timeout_s,
        max_attempts=settings.quote_max_attempts,
        budget_s=settings.quote_budget_s,
        breaker=CircuitBreaker(clock, settings.breaker_failures, settings.breaker_open_s),
        clock=clock,
    )


async def build_app(
    settings: Settings | None = None,
    *,
    outbound: OutboundChannel | None = None,
    persistent: bool = False,
    log_json: bool = False,
) -> App:
    """`persistent=True`: eventos e checkpoint em SQLite (API). Senão, memória (CLI, testes)."""
    settings = settings or Settings()
    gateway = make_gateway(settings)
    await gateway.load_rules()

    store: EventStore
    checkpointer: Any = None
    closers: list[Any] = []
    if persistent:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        store = SqliteEventStore(settings.db_path)
        conn = await aiosqlite.connect(settings.checkpoint_db_path)
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        closers.append(conn.close)
    else:
        store = InMemoryEventStore()
    if log_json:
        configure_logging()
        store = LoggingEventStore(store)

    deps = Deps(
        llm=make_llm(settings),
        gateway=gateway,
        events=store,
        outbound=outbound or OutboxChannel(),
        clock=SystemClock(),
        vault=InMemoryVault(),
        wait_message_after_s=settings.wait_message_after_s,
    )
    return App(
        agent=Agent(deps, checkpointer),
        gateway=gateway,
        events=store,
        settings=settings,
        closers=closers,
    )
