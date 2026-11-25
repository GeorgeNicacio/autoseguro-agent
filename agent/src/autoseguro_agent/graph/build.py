"""Monta o grafo LangGraph (composition root do fluxo)."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from autoseguro_agent.graph.nodes import Deps, Nodes
from autoseguro_agent.graph.state import ConversationState


def build_graph(
    deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None, nodes: Nodes | None = None
) -> Any:
    n = nodes or Nodes(deps)
    # Any: os overloads de add_node do LangGraph não aceitam TypedDict total=False no mypy.
    g: Any = StateGraph(ConversationState)
    g.add_node("ingest", n.traced("ingest", n.ingest))
    g.add_node("extract", n.traced("extract", n.extract))
    g.add_node("apply", n.traced("apply", n.apply))
    g.add_node("route", n.traced("route", n.route))
    g.add_node("quote", n.traced("quote", n.quote))
    g.add_node("route_quote", n.traced("route_quote", n.route_quote))
    g.add_node("present", n.traced("present", n.present))
    g.add_node("respond", n.traced("respond", n.respond))
    g.add_node("handoff", n.traced("handoff", n.handoff))
    g.add_node("deliver", n.traced("deliver", n.deliver))

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "extract")
    g.add_edge("extract", "apply")
    g.add_edge("apply", "route")
    g.add_conditional_edges(
        "route", n.next_after_route, {"handoff": "handoff", "quote": "quote", "respond": "respond"}
    )
    g.add_edge("quote", "route_quote")
    g.add_conditional_edges(
        "route_quote", n.next_after_quote, {"handoff": "handoff", "present": "present"}
    )
    g.add_edge("present", "deliver")
    g.add_edge("respond", "deliver")
    g.add_edge("handoff", "deliver")
    g.add_edge("deliver", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
