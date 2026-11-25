"""Métricas e custos calculados a partir dos eventos (fonte única · REQ-82).

Em produção isso seriam séries temporais (Prometheus) e traces (OpenTelemetry); aqui,
com o volume de um teste, agregar a tabela `events` na hora é simples e auditável.
Conversas do golden set (prefixo `golden_`) aparecem separadas das conversas "ao vivo".
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from autoseguro_agent.domain.events import Event

GOLDEN_PREFIX = "golden_"


def _pct(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def _lat(values: list[int]) -> dict[str, int | None]:
    return {
        "p50": _pct(values, 50),
        "p95": _pct(values, 95),
        "max": max(values, default=None),
        "n": len(values),
    }


def source_of(conversation_id: str) -> str:
    return "golden" if conversation_id.startswith(GOLDEN_PREFIX) else "live"


def conversation_summaries(events: list[Event]) -> list[dict[str, Any]]:
    by_conv: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_conv[e.conversation_id].append(e)
    rows = []
    for conv, evs in by_conv.items():
        status = "active"
        rule = None
        cost = 0.0
        tokens = 0
        quotes = 0
        turns = 0
        for e in evs:
            if e.event_type == "conversation.status":
                status = e.status
            elif e.event_type == "handoff.opened":
                rule = e.payload.get("rule_id")
            elif e.event_type == "llm.call":
                cost += float(e.payload.get("cost_usd", 0.0))
                tokens += int(e.payload.get("input_tokens", 0)) + int(
                    e.payload.get("output_tokens", 0)
                )
            elif e.event_type == "quote_request.finished":
                quotes += 1
            elif e.event_type == "turn.finished":
                turns += 1
        rows.append(
            {
                "conversation_id": conv,
                "source": source_of(conv),
                "status": status,
                "handoff_rule": rule,
                "turns": turns,
                "quotes": quotes,
                "tokens": tokens,
                "cost_usd": round(cost, 6),
                "started_at": evs[0].ts.isoformat(),
                "updated_at": evs[-1].ts.isoformat(),
            }
        )
    return sorted(rows, key=lambda r: r["updated_at"], reverse=True)


def compute(
    events: list[Event],
    *,
    queue: dict[str, Any] | None = None,
    hot: dict[str, list[tuple[str, int]]] | None = None,
    cache_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    convs = conversation_summaries(events)
    statuses = Counter(c["status"] for c in convs)
    sources = Counter(c["source"] for c in convs)
    handoffs = Counter(c["handoff_rule"] for c in convs if c["handoff_rule"])

    quote_status: Counter[str] = Counter()
    quote_cache: Counter[str] = Counter()
    attempts: Counter[str] = Counter()
    quote_lat: list[int] = []
    quote_saved_ms = 0
    for e in events:
        if e.event_type == "quote_request.finished":
            quote_status[e.status] += 1
            quote_cache[str(e.payload.get("cache") or "none")] += 1
            if e.payload.get("cache") == "hit":
                quote_saved_ms += int(e.payload.get("saved_ms") or 0)
            elif e.latency_ms is not None:
                quote_lat.append(e.latency_ms)
        elif e.event_type == "quote_attempt":
            attempts[e.status] += 1

    llm = [e for e in events if e.event_type == "llm.call"]
    llm_cache = Counter(e.status for e in llm)
    llm_lat = [e.latency_ms or 0 for e in llm if e.status != "hit"]
    total_cost = sum(float(e.payload.get("cost_usd", 0.0)) for e in llm)
    saved_cost = sum(float(e.payload.get("saved_cost_usd", 0.0)) for e in llm)
    tokens = {
        k: sum(int(e.payload.get(k, 0)) for e in llm)
        for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    }
    models = Counter(str(e.payload.get("model")) for e in llm if e.status != "hit")
    by_model: dict[str, list[int]] = defaultdict(list)
    for e in llm:
        if e.status != "hit":
            by_model[str(e.payload.get("model"))].append(e.latency_ms or 0)
    turn_lat = [e.latency_ms or 0 for e in events if e.event_type == "turn.finished"]
    spans: dict[str, list[int]] = defaultdict(list)
    for e in events:
        if e.event_type == "trace.span":
            spans[str(e.payload.get("node"))].append(e.latency_ms or 0)

    done = quote_status["success"] + quote_status["failed"]
    llm_lookups = llm_cache["hit"] + llm_cache["miss"]
    quote_lookups = quote_cache["hit"] + quote_cache["miss"]
    with_cost = [c for c in convs if c["cost_usd"] > 0]
    return {
        "conversations": {
            "total": len(convs),
            "by_source": dict(sources),
            "by_status": dict(statuses),
        },
        "handoffs_by_rule": dict(handoffs.most_common()),
        "quote": {
            "requests": dict(quote_status),
            "success_rate": round(quote_status["success"] / done, 4) if done else None,
            "attempts": dict(attempts),
            "latency_ms": _lat(quote_lat),
            "cache": dict(quote_cache),
            "cache_hit_rate": round(quote_cache["hit"] / quote_lookups, 4)
            if quote_lookups
            else None,
            "latency_saved_ms": quote_saved_ms,
        },
        "llm": {
            "calls": len(llm),
            "models": dict(models),
            "cache": dict(llm_cache),
            "cache_hit_rate": round(llm_cache["hit"] / llm_lookups, 4) if llm_lookups else None,
            "tokens": tokens,
            "cost_usd": round(total_cost, 6),
            "cost_saved_usd": round(saved_cost, 6),
            "avg_cost_per_conversation_usd": round(total_cost / len(with_cost), 6)
            if with_cost
            else 0.0,
            "latency_ms": _lat(llm_lat),
            "latency_by_model_ms": {k: _lat(v) for k, v in sorted(by_model.items())},
        },
        "turn_latency_ms": _lat(turn_lat),
        "node_latency_ms": {k: _lat(v) for k, v in sorted(spans.items())},
        "queue": queue or {},
        "hot_queries": {k: [{"query": q, "hits": h} for q, h in v] for k, v in (hot or {}).items()},
        "cache_server": cache_stats or {},
    }


def trace(events: list[Event]) -> list[dict[str, Any]]:
    """Linha do tempo de uma conversa agrupada por turno (message_id), com os spans."""
    turns: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for e in events:
        mid = e.message_id or "-"
        if mid not in turns:
            turns[mid] = {
                "message_id": mid,
                "started_at": e.ts.isoformat(),
                "spans": [],
                "events": [],
                "lead": None,
                "agent": [],
                "duration_ms": None,
            }
            order.append(mid)
        t = turns[mid]
        if e.event_type == "trace.span":
            t["spans"].append({"node": e.payload.get("node"), "ms": e.latency_ms})
        elif e.event_type == "message.received" and "text" in e.payload:
            t["lead"] = e.payload["text"]
        elif e.event_type == "message.sent" and "text" in e.payload:
            t["agent"].append(e.payload["text"])
        elif e.event_type == "turn.finished":
            t["duration_ms"] = e.latency_ms
        t["events"].append(e.model_dump(mode="json"))
    return [turns[m] for m in order]
