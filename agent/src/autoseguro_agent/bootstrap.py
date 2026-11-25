"""Composition root: o único lugar que conhece todos os adaptadores (SOLID · D).

Com `AGENT_REDIS_URL`: cache de cotação, de regras e de extração em Redis, e fila RQ.
Sem Redis: cache no-op e trabalho executado na hora (testes, CLI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autoseguro_agent.adapters.cache import CacheStore, NullCache, RedisCache
from autoseguro_agent.adapters.cached_llm import CachedLLM
from autoseguro_agent.adapters.cached_quote import CachedQuoteGateway
from autoseguro_agent.adapters.circuit_breaker import CircuitBreaker
from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.adapters.events_memory import InMemoryEventStore
from autoseguro_agent.adapters.llm_anthropic import PROMPT_VERSION, AnthropicLLM
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
    gateway: CachedQuoteGateway
    events: EventStore
    settings: Settings
    cache: CacheStore = field(default_factory=NullCache)
    dispatcher: Any = None
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


def make_cache(settings: Settings) -> CacheStore:
    return RedisCache.from_url(settings.redis_url) if settings.redis_url else NullCache()


async def build_app(
    settings: Settings | None = None,
    *,
    outbound: OutboundChannel | None = None,
    persistent: bool = False,
    log_json: bool = False,
    worker: bool = False,
) -> App:
    """`persistent=True`: eventos e checkpoint em SQLite (API e worker). Senão, memória."""
    settings = settings or Settings()
    clock = SystemClock()
    cache = make_cache(settings)
    gateway = CachedQuoteGateway(
        make_gateway(settings),
        cache,
        clock,
        ttl_s=settings.quote_cache_ttl_s,
        rules_ttl_s=settings.rules_cache_ttl_s,
        hot_threshold=settings.hot_threshold,
        hot_ttl_s=settings.hot_ttl_s,
    )
    await gateway.load_rules()
    fake = settings.llm_provider == "fake"
    llm = CachedLLM(
        make_llm(settings),
        cache,
        model="fake" if fake else settings.llm_model,
        prompt_version="heuristic" if fake else PROMPT_VERSION,
        ttl_s=settings.llm_cache_ttl_s,
        hot_threshold=settings.hot_threshold,
        hot_ttl_s=settings.hot_ttl_s,
    )

    store: EventStore
    checkpointer: Any = None
    closers: list[Any] = []
    if persistent:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        store = SqliteEventStore(settings.db_path)
        conn = await aiosqlite.connect(settings.checkpoint_db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        closers.append(conn.close)
    else:
        store = InMemoryEventStore()
    if log_json:
        configure_logging()
        store = LoggingEventStore(store)

    queue = None
    tasks = None
    if settings.redis_url:
        import redis
        from rq import Queue

        from autoseguro_agent.dispatch import QUEUE_NAME, RQTaskQueue

        queue = Queue(QUEUE_NAME, connection=redis.Redis.from_url(settings.redis_url))
        tasks = RQTaskQueue(queue) if worker else None

    deps = Deps(
        llm=llm,
        gateway=gateway,
        events=store,
        outbound=outbound or OutboxChannel(),
        clock=clock,
        vault=InMemoryVault(),
        wait_message_after_s=settings.wait_message_after_s,
        tasks=tasks,
        quote_retry_delays_s=tuple(settings.retry_delays),
    )
    app = App(
        agent=Agent(deps, checkpointer),
        gateway=gateway,
        events=store,
        settings=settings,
        cache=cache,
        closers=closers,
    )

    from autoseguro_agent.dispatch import InlineDispatcher, RQDispatcher

    if queue is not None:
        app.dispatcher = RQDispatcher(queue)
    else:
        from autoseguro_agent.jobs import run_golden_for_app

        async def golden(llm_name: str) -> dict[str, Any]:
            return await run_golden_for_app(app, llm_name)

        app.dispatcher = InlineDispatcher(app.agent, golden)
    return app
