"""Composition root: o único lugar que conhece todos os adaptadores (SOLID · D)."""

from __future__ import annotations

from dataclasses import dataclass

from autoseguro_agent.adapters.clock import SystemClock
from autoseguro_agent.adapters.events_memory import InMemoryEventStore
from autoseguro_agent.adapters.llm_anthropic import AnthropicLLM
from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.adapters.quote_http import HttpQuoteGateway
from autoseguro_agent.agent import Agent
from autoseguro_agent.graph.nodes import Deps
from autoseguro_agent.pii import InMemoryVault
from autoseguro_agent.ports import EventStore, LLMClient, OutboundChannel
from autoseguro_agent.settings import Settings


class NullOutbound:
    """No CLI quem imprime é o próprio CLI; no webhook, o outbox vai na resposta."""

    def send(self, conversation_id: str, text: str) -> None:
        return None


@dataclass
class App:
    agent: Agent
    gateway: HttpQuoteGateway
    events: EventStore
    settings: Settings


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


async def build_app(
    settings: Settings | None = None,
    events: EventStore | None = None,
    outbound: OutboundChannel | None = None,
) -> App:
    settings = settings or Settings()
    gateway = HttpQuoteGateway(settings.quote_base_url, timeout_s=settings.quote_timeout_s)
    await gateway.load_rules()
    store = events or InMemoryEventStore()
    deps = Deps(
        llm=make_llm(settings),
        gateway=gateway,
        events=store,
        outbound=outbound or NullOutbound(),
        clock=SystemClock(),
        vault=InMemoryVault(),
    )
    return App(agent=Agent(deps), gateway=gateway, events=store, settings=settings)
