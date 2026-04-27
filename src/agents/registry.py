"""Agent registry — pure data describing each agent."""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class AgentSpec:
    name: str
    system_prompt: str
    tool: Optional[Callable] = None
    collection: Optional[str] = None
    label: str = ""


REGISTRY: dict[str, AgentSpec] = {}


def register(spec: AgentSpec) -> None:
    REGISTRY[spec.name] = spec


def get(name: str) -> AgentSpec:
    return REGISTRY[name]
