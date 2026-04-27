"""Agent package — registers agents and exports the runner singleton."""

from src.agents.llm import llm, get_langfuse_handler
from src.agents.registry import AgentSpec, REGISTRY, register, get
from src.agents.runner import AgentRunner, StreamEvent
from src.tools.rag_tool import rag_search_technical, rag_search_hr
from src.prompts.prompts import (
    TECHNICAL_AGENT_SYSTEM_PROMPT,
    HR_AGENT_SYSTEM_PROMPT,
    GENERAL_AGENT_SYSTEM_PROMPT,
)


register(AgentSpec(
    name="TECHNICAL_AGENT",
    system_prompt=TECHNICAL_AGENT_SYSTEM_PROMPT,
    tool=rag_search_technical,
    collection="kb_technical",
    label="Technical Agent",
))

register(AgentSpec(
    name="HR_AGENT",
    system_prompt=HR_AGENT_SYSTEM_PROMPT,
    tool=rag_search_hr,
    collection="kb_hr",
    label="HR Agent",
))

register(AgentSpec(
    name="GENERAL_AGENT",
    system_prompt=GENERAL_AGENT_SYSTEM_PROMPT,
    tool=None,
    collection=None,
    label="General Agent",
))


runner = AgentRunner(llm, callback_provider=get_langfuse_handler)


__all__ = [
    "AgentSpec",
    "AgentRunner",
    "StreamEvent",
    "REGISTRY",
    "register",
    "get",
    "runner",
    "llm",
    "get_langfuse_handler",
]
