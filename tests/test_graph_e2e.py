from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

import src.agents.graph as gm
from src.agents import runner, REGISTRY


def _routing(decision: str) -> MagicMock:
    m = MagicMock()
    m.decision = decision
    return m


def _response(content: str, tool_calls=None) -> MagicMock:
    m = MagicMock()
    m.content = content
    m.tool_calls = tool_calls or []
    return m


def _patch_runner_llm(invoke_side_effect=None, invoke_return=None):
    """Replace runner._llm with a mock; clear bound-tool cache so the next
    bind_tools call sees the fresh mock."""
    runner._bound.clear()
    fake_llm = MagicMock()
    fake_with_tool = MagicMock()
    fake_llm.bind_tools.return_value = fake_with_tool

    if invoke_side_effect is not None:
        fake_llm.invoke.side_effect = invoke_side_effect
    elif invoke_return is not None:
        fake_llm.invoke.return_value = invoke_return

    return patch.object(runner, "_llm", fake_llm), fake_llm, fake_with_tool


# ---------------------------------------------------------------------------
# Technical question routed to TECHNICAL_AGENT
# ---------------------------------------------------------------------------

def test_technical_agent_routing_and_response():
    cm, fake_llm, fake_with_tool = _patch_runner_llm()
    fake_with_tool.invoke.return_value = _response("API Gateway uses OAuth2.")

    with patch.object(gm, "_supervisor_llm") as sup, cm:
        sup.invoke.return_value = _routing("TECHNICAL_AGENT")

        state = {
            "messages": [HumanMessage(content="How does API Gateway work?")],
            "current_agent": "",
            "routing_decision": "",
        }
        result = gm.graph.invoke(state)

    assert result["current_agent"] == "TECHNICAL_AGENT"
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == "API Gateway uses OAuth2."


# ---------------------------------------------------------------------------
# HR question routed to HR_AGENT
# ---------------------------------------------------------------------------

def test_hr_agent_routing_and_response():
    cm, fake_llm, fake_with_tool = _patch_runner_llm()
    fake_with_tool.invoke.return_value = _response("Annual leave is 12 days.")

    with patch.object(gm, "_supervisor_llm") as sup, cm:
        sup.invoke.return_value = _routing("HR_AGENT")

        state = {
            "messages": [HumanMessage(content="How many days of leave do I get?")],
            "current_agent": "",
            "routing_decision": "",
        }
        result = gm.graph.invoke(state)

    assert result["current_agent"] == "HR_AGENT"
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == "Annual leave is 12 days."


# ---------------------------------------------------------------------------
# General question routed to GENERAL_AGENT (no RAG tool involved)
# ---------------------------------------------------------------------------

def test_general_agent_routing_and_response():
    cm, fake_llm, _ = _patch_runner_llm(
        invoke_return=_response("The capital of France is Paris.")
    )

    with patch.object(gm, "_supervisor_llm") as sup, cm:
        sup.invoke.return_value = _routing("GENERAL_AGENT")

        state = {
            "messages": [HumanMessage(content="What is the capital of France?")],
            "current_agent": "",
            "routing_decision": "",
        }
        result = gm.graph.invoke(state)

    assert result["current_agent"] == "GENERAL_AGENT"
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == "The capital of France is Paris."


# ---------------------------------------------------------------------------
# Supervisor fallback: structured output raises, string matching saves routing
# ---------------------------------------------------------------------------

def test_supervisor_fallback_routes_via_string_matching():
    cm, fake_llm, fake_with_tool = _patch_runner_llm()
    fake_llm.invoke.return_value = _response("TECHNICAL_AGENT")
    fake_with_tool.invoke.return_value = _response("Fallback technical answer.")

    with patch.object(gm, "_supervisor_llm") as sup, \
         patch.object(gm, "llm", fake_llm), \
         cm:
        sup.invoke.side_effect = Exception("structured output failed")

        state = {
            "messages": [HumanMessage(content="Tell me about the API endpoints.")],
            "current_agent": "",
            "routing_decision": "",
        }
        result = gm.graph.invoke(state)

    assert result["current_agent"] == "TECHNICAL_AGENT"
    assert isinstance(result["messages"][-1], AIMessage)


# ---------------------------------------------------------------------------
# RAG tool is invoked when the agent emits a tool_call (two-pass flow)
# ---------------------------------------------------------------------------

def test_technical_agent_invokes_rag_tool():
    tool_call = {
        "name": "rag_search_technical",
        "args": {"query": "API endpoints"},
        "id": "tc-001",
    }
    first_response = MagicMock()
    first_response.tool_calls = [tool_call]
    first_response.content = ""

    cm, fake_llm, fake_with_tool = _patch_runner_llm()
    fake_with_tool.invoke.return_value = first_response
    fake_llm.invoke.return_value = _response("The endpoints are /auth, /data, /health.")

    spec = REGISTRY["TECHNICAL_AGENT"]
    mock_tool = MagicMock()
    mock_tool.invoke.return_value = "Found: /auth, /data, /health"

    # Replace the registered tool reference for the duration of the test.
    original_tool = spec.tool
    object.__setattr__(spec, "tool", mock_tool)
    try:
        with patch.object(gm, "_supervisor_llm") as sup, cm:
            sup.invoke.return_value = _routing("TECHNICAL_AGENT")

            state = {
                "messages": [HumanMessage(content="List all API endpoints.")],
                "current_agent": "",
                "routing_decision": "",
            }
            result = gm.graph.invoke(state)
    finally:
        object.__setattr__(spec, "tool", original_tool)

    mock_tool.invoke.assert_called_once_with({"query": "API endpoints"})
    assert result["current_agent"] == "TECHNICAL_AGENT"
    assert "endpoints" in result["messages"][-1].content
