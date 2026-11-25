"""Métricas, custos e trace a partir dos eventos (REQ-80..82)."""

from autoseguro_agent.metrics import compute, conversation_summaries, trace
from tests.fakes import FakeGateway, make_agent


async def test_metrics_after_conversations() -> None:
    agent, _, _, events = make_agent(gateway=FakeGateway(script=["success", "failed"]))
    await agent.handle("c1", "35 anos, Onix 2022, cep 01310-100, completo")
    await agent.handle("c2", "35 anos, Onix 2022, cep 01310-100, premium")
    m = compute(events.all_events())
    assert m["conversations"]["total"] == 2
    assert m["conversations"]["by_status"] == {"quoted": 1, "handed_off": 1}
    assert m["handoffs_by_rule"] == {"infra_unavailable": 1}
    assert m["quote"]["requests"] == {"success": 1, "failed": 1}
    assert m["llm"]["calls"] == 2
    assert m["turn_latency_ms"]["n"] == 2
    assert set(m["node_latency_ms"]) >= {"ingest", "extract", "apply", "route", "deliver"}


async def test_trace_groups_spans_and_transcript_by_turn() -> None:
    agent, _, _, events = make_agent()
    await agent.handle("c3", "Oi, tenho um Onix 2022")
    await agent.handle("c3", "35")
    turns = trace(events.timeline("c3"))
    assert len(turns) == 2
    assert turns[0]["lead"] == "Oi, tenho um Onix 2022"
    assert any("idade" in t.lower() for t in turns[0]["agent"])
    assert [s["node"] for s in turns[0]["spans"]][:3] == ["ingest", "extract", "apply"]
    assert turns[0]["duration_ms"] is not None


async def test_summaries_split_golden_from_live() -> None:
    agent, _, _, events = make_agent()
    await agent.handle("golden_x_G01", "oi")
    await agent.handle("live1", "oi")
    sources = {
        r["conversation_id"]: r["source"] for r in conversation_summaries(events.all_events())
    }
    assert sources == {"golden_x_G01": "golden", "live1": "live"}
