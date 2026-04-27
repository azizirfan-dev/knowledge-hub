"""
Component 3 — Multi-Agent LangGraph Workflow

Graph flow:
  supervisor → <agent from REGISTRY> → END

Per-agent execution lives in `src.agents.runner.AgentRunner`. This module
owns only the supervisor + LangGraph topology.
"""

from typing import Annotated, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from src.agents import REGISTRY, runner, llm, get_langfuse_handler  # noqa: F401
from src.prompts.prompts import SUPERVISOR_SYSTEM_PROMPT


# --- State ---

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    current_agent: str
    routing_decision: str


# --- Supervisor structured output ---

class RoutingDecision(BaseModel):
    decision: Literal["TECHNICAL_AGENT", "HR_AGENT", "GENERAL_AGENT"]


try:
    _supervisor_llm = llm.with_structured_output(RoutingDecision)
except NotImplementedError:
    _supervisor_llm = None


# --- Nodes ---

def supervisor_node(state: AgentState, callbacks=None) -> AgentState:
    history = state["messages"][-6:]
    cfg = {"callbacks": callbacks} if callbacks else {}
    try:
        if _supervisor_llm is None:
            raise NotImplementedError
        result: RoutingDecision = _supervisor_llm.invoke(
            [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT), *history],
            config=cfg,
        )
        decision = result.decision
    except Exception:
        response = llm.invoke(
            [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT), *history],
            config=cfg,
        )
        raw = response.content.strip().upper()
        if "TECHNICAL" in raw:
            decision = "TECHNICAL_AGENT"
        elif "HR" in raw:
            decision = "HR_AGENT"
        else:
            decision = "GENERAL_AGENT"

    return {**state, "current_agent": decision, "routing_decision": decision}


def _agent_node(name: str):
    def node(state: AgentState) -> AgentState:
        ai = runner.run(name, state["messages"])
        return {
            **state,
            "current_agent": name,
            "messages": state["messages"] + [ai],
        }
    return node


# --- Routing ---

def _node_key(name: str) -> str:
    return name.lower()


def route_after_supervisor(state: AgentState) -> str:
    decision = state.get("routing_decision", "GENERAL_AGENT")
    if decision not in REGISTRY:
        decision = "GENERAL_AGENT"
    return _node_key(decision)


# --- Graph ---

def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("supervisor", supervisor_node)

    routes: dict[str, str] = {}
    for spec in REGISTRY.values():
        key = _node_key(spec.name)
        builder.add_node(key, _agent_node(spec.name))
        builder.add_edge(key, END)
        routes[key] = key

    builder.set_entry_point("supervisor")
    builder.add_conditional_edges("supervisor", route_after_supervisor, routes)
    return builder.compile()


graph = build_graph()
