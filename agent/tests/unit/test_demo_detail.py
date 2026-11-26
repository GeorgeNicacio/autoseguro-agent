"""Coluna "Detalhe" do log da demo (entregável 4): spans e chamadas ao LLM legíveis."""

from __future__ import annotations

from datetime import UTC, datetime

from autoseguro_agent.domain.events import Event
from autoseguro_agent.evaluation.demo import _detail


def _event(event_type: str, status: str, payload: dict[str, object]) -> Event:
    return Event(
        ts=datetime(2026, 11, 26, tzinfo=UTC),
        event_type=event_type,  # type: ignore[arg-type]
        status=status,
        conversation_id="c1",
        payload=payload,
    )


def test_llm_call_shows_model_tokens_cost_and_cache() -> None:
    e = _event(
        "llm.call",
        "miss",
        {
            "model": "claude-haiku-5-5",
            "prompt_version": "extract_v3",
            "input_tokens": 120,
            "output_tokens": 45,
            "cache_read_tokens": 3300,
            "cost_usd": 0.000089,
        },
    )
    assert _detail(e) == (
        "claude-haiku-5-5 · extract_v3 · 120 in / 45 out / 3300 cache · US$ 0.000089"
    )


def test_trace_span_shows_node_name() -> None:
    assert _detail(_event("trace.span", "ok", {"node": "extract"})) == "nó extract"
