"""AgentRunner — single execution surface for all agents."""

import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.registry import REGISTRY


def _last_user_query(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        if role in {"human", "user"}:
            content = getattr(msg, "content", "")
            return content if isinstance(content, str) else str(content)
    return ""


# Parses each chunk header in formatted RAG tool output:
#   [Source: filename.pdf, halaman/chunk: 3]
_SOURCE_HEADER_RE = re.compile(
    r"\[Source:\s*([^,\]]+),\s*halaman/chunk:\s*([^\]]+)\]"
)


def _parse_sources(tool_result: str) -> list[dict]:
    """Pull (source, page) tuples from formatted tool output, deduplicated."""
    found = _SOURCE_HEADER_RE.findall(tool_result or "")
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for source, page in found:
        s, p = source.strip(), page.strip()
        if (s, p) in seen:
            continue
        seen.add((s, p))
        out.append({"source": s, "page": p})
    return out


@dataclass
class StreamEvent:
    kind: Literal["token", "tool_call", "done"]
    token: str = ""
    agent: str = ""
    collection: Optional[str] = None
    tool_name: str = ""
    sources: list[dict] = field(default_factory=list)


class AgentRunner:
    def __init__(self, llm, *, window: int = 6, callback_provider=None):
        self._llm = llm
        self._window = window
        self._cb_provider = callback_provider

    def _prepare(self, name: str, messages: list, tool_context: str | None = None) -> list:
        spec = REGISTRY[name]
        system_content = spec.system_prompt
        if tool_context:
            system_content = (
                f"{spec.system_prompt}\n\n"
                f"=== Retrieved context ===\n{tool_context}\n=== End context ==="
            )
        history = list(messages)[-self._window:]
        return [SystemMessage(content=system_content)] + history

    def _resolve_callbacks(self, callbacks):
        if callbacks is not None:
            return callbacks
        if self._cb_provider is None:
            return None
        handler = self._cb_provider()
        return [handler] if handler else None

    @staticmethod
    def _flush(callbacks):
        if not callbacks:
            return
        for cb in callbacks:
            lf = getattr(cb, "langfuse", None)
            if lf is not None:
                try:
                    lf.flush()
                except Exception:
                    pass

    def run(self, agent_name: str, messages: list, *, callbacks=None) -> AIMessage:
        spec = REGISTRY[agent_name]
        cbs = self._resolve_callbacks(callbacks)
        cfg = {"callbacks": cbs} if cbs else {}

        try:
            tool_context = None
            if spec.tool is not None:
                query = _last_user_query(messages)
                tool_context = spec.tool.invoke({"query": query})

            msgs = self._prepare(agent_name, messages, tool_context=tool_context)
            response = self._llm.invoke(msgs, config=cfg)
            return AIMessage(content=response.content)
        finally:
            self._flush(cbs)

    async def stream(
        self, agent_name: str, messages: list, *, callbacks=None
    ) -> AsyncIterator[StreamEvent]:
        import asyncio

        spec = REGISTRY[agent_name]
        cbs = self._resolve_callbacks(callbacks)
        cfg = {"callbacks": cbs} if cbs else {}

        captured_sources: list[dict] = []
        tool_context: str | None = None
        try:
            if spec.tool is not None:
                query = _last_user_query(messages)
                tool_context = await asyncio.to_thread(
                    spec.tool.invoke, {"query": query}
                )
                captured_sources = _parse_sources(tool_context)
                yield StreamEvent(
                    kind="tool_call",
                    agent=agent_name,
                    tool_name=getattr(spec.tool, "name", ""),
                    collection=spec.collection,
                    sources=captured_sources,
                )

            msgs = self._prepare(agent_name, messages, tool_context=tool_context)
            async for chunk in self._llm.astream(msgs, config=cfg):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    yield StreamEvent(kind="token", token=token)

            yield StreamEvent(
                kind="done",
                agent=agent_name,
                collection=spec.collection,
                sources=captured_sources,
            )
        finally:
            self._flush(cbs)
