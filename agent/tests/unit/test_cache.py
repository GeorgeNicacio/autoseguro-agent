"""Cache em Redis: cotação, regras, extração do LLM e consultas quentes (REQ-70..77)."""

from datetime import date
from decimal import Decimal

import fakeredis
import pytest
import redis

from autoseguro_agent.adapters.cache import NullCache, RedisCache
from autoseguro_agent.adapters.cached_llm import CachedLLM
from autoseguro_agent.adapters.cached_quote import CachedQuoteGateway, quote_cache_key
from autoseguro_agent.adapters.clock import FixedClock
from autoseguro_agent.adapters.llm_fake import FakeLLM
from autoseguro_agent.domain.extraction import ExtractionRequest
from autoseguro_agent.domain.models import QuoteRequest
from autoseguro_agent.domain.quote import TraceContext
from autoseguro_agent.domain.rules import load_snapshot
from tests.fakes import FakeGateway

CTX = TraceContext(conversation_id="c1")


def req(**kw: object) -> QuoteRequest:
    base: dict[str, object] = {
        "plano_id": "completo",
        "idade": 35,
        "veiculo_ano": 2022,
        "cep": "01310-100",
        "data_inicio": date(2026, 12, 1),
    }
    base.update(kw)
    return QuoteRequest.model_validate(base)


@pytest.fixture
def cache() -> RedisCache:
    return RedisCache(fakeredis.FakeStrictRedis(decode_responses=True))


# --- cotação -------------------------------------------------------------------


async def test_same_quote_hits_cache(cache: RedisCache) -> None:
    inner = FakeGateway()
    gw = CachedQuoteGateway(inner, cache, FixedClock())
    first = await gw.quote(req(), CTX)
    second = await gw.quote(req(cep="01999-000"), CTX)  # mesma região (prefixo 01)
    assert len(inner.requests) == 1
    assert first.cache == "miss"
    assert second.cache == "hit"
    assert second.status == "success"
    assert second.result is not None
    assert second.result.premio_mensal == Decimal("209.90")
    assert second.attempts == ()


@pytest.mark.parametrize(
    "change",
    [
        {"plano_id": "premium"},
        {"idade": 22},
        {"veiculo_ano": 2015},
        {"cep": "21000-000"},
        {"data_inicio": date(2026, 12, 15)},
    ],
)
async def test_any_pricing_input_changes_the_key(
    cache: RedisCache, change: dict[str, object]
) -> None:
    inner = FakeGateway()
    gw = CachedQuoteGateway(inner, cache, FixedClock())
    await gw.quote(req(), CTX)
    await gw.quote(req(**change), CTX)
    assert len(inner.requests) == 2


def test_key_depends_on_day_and_rules_version() -> None:
    rules = load_snapshot()
    k1 = quote_cache_key(req(), rules.version, date(2026, 11, 25))
    assert k1 != quote_cache_key(req(), rules.version, date(2026, 11, 26))
    assert k1 != quote_cache_key(req(), "outra-versao", date(2026, 11, 25))
    assert "01310" not in k1  # nem o CEP completo nem dado pessoal na chave


@pytest.mark.parametrize("status", ["failed", "refused", "invalid"])
async def test_only_success_is_cached(cache: RedisCache, status: str) -> None:
    inner = FakeGateway(script=[status, "success"])
    gw = CachedQuoteGateway(inner, cache, FixedClock())
    await gw.quote(req(), CTX)
    await gw.quote(req(), CTX)
    assert len(inner.requests) == 2


async def test_redis_down_does_not_break_quotes() -> None:
    broken = RedisCache(redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.05))
    inner = FakeGateway()
    gw = CachedQuoteGateway(inner, broken, FixedClock())
    out = await gw.quote(req(), CTX)
    assert out.status == "success"
    assert out.cache == "error"


async def test_null_cache_is_disabled() -> None:
    gw = CachedQuoteGateway(FakeGateway(), NullCache(), FixedClock())
    assert (await gw.quote(req(), CTX)).cache == "disabled"


# --- extração do LLM -----------------------------------------------------------


def ex(text: str, pending: str | None = "idade") -> ExtractionRequest:
    return ExtractionRequest(masked_text=text, pending_slot=pending, today_iso="2026-11-25")  # type: ignore[arg-type]


def test_same_masked_answer_reuses_extraction(cache: RedisCache) -> None:
    inner = FakeLLM()
    llm = CachedLLM(inner, cache, model="claude-opus-5-5", prompt_version="extract_v2")
    a = llm.extract(ex("35"))
    b = llm.extract(ex("  35 "))  # normalizado
    assert a == b
    assert len(inner.requests) == 1
    assert llm.last_stats is not None
    assert llm.last_stats.cache == "hit"


def test_pending_slot_is_part_of_the_key(cache: RedisCache) -> None:
    inner = FakeLLM()
    llm = CachedLLM(inner, cache, model="m", prompt_version="v")
    llm.extract(ex("2019", pending="idade"))
    llm.extract(ex("2019", pending="veiculo_ano"))
    assert len(inner.requests) == 2


def test_hot_queries_are_ranked_and_get_longer_ttl(cache: RedisCache) -> None:
    llm = CachedLLM(
        FakeLLM(), cache, model="m", prompt_version="v", hot_threshold=3, ttl_s=60, hot_ttl_s=10_000
    )
    for _ in range(4):
        llm.extract(ex("quero falar com um atendente", pending=None))
    llm.extract(ex("35"))
    top = cache.top_hot("llm", 5)
    assert top[0][0] == "quero falar com um atendente"
    assert top[0][1] == 4
    key = llm.key_for(ex("quero falar com um atendente", pending=None))
    assert cache.ttl(key) > 60  # promovida a chave quente


# --- regras --------------------------------------------------------------------


async def test_rules_are_cached_with_version(cache: RedisCache) -> None:
    inner = FakeGateway()
    gw = CachedQuoteGateway(inner, cache, FixedClock())
    await gw.load_rules()
    assert gw.rules_source in {"api", "snapshot", "cache"}
    assert gw.rules().version == load_snapshot().version
