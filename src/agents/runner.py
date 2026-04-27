"""AgentRunner — single execution surface for all agents."""

import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Optional

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.agents.registry import REGISTRY


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
        self._bound: dict[str, object] = {}

    def _llm_for(self, name: str):
        spec = REGISTRY[name]
        if spec.tool is None:
            return self._llm
        if name not in self._bound:
            self._bound[name] = self._llm.bind_tools([spec.tool])
        return self._bound[name]

    def _prepare(self, name: str, messages: list) -> tuple[list, object]:
        spec = REGISTRY[name]
        history = list(messages)[-self._window:]
        prepared = [SystemMessage(content=spec.system_prompt)] + history
        return prepared, self._llm_for(name)

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
        msgs, llm_w_tool = self._prepare(agent_name, messages)
        cbs = self._resolve_callbacks(callbacks)
        cfg = {"callbacks": cbs} if cbs else {}

        try:
            response = llm_w_tool.invoke(msgs, config=cfg)

            if spec.tool is not None and getattr(response, "tool_calls", None):
                tool_call = response.tool_calls[0]
                tool_result = spec.tool.invoke(tool_call["args"])
                msgs.append(response)
                msgs.append(ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_call["id"],
                ))
                final = self._llm.invoke(msgs, config=cfg)
                return AIMessage(content=final.content)

            return AIMessage(content=response.content)
        finally:
            self._flush(cbs)

    async def stream(
        self, agent_name: str, messages: list, *, callbacks=None
    ) -> AsyncIterator[StreamEvent]:
        import asyncio

        spec = REGISTRY[agent_name]
        msgs, llm_w_tool = self._prepare(agent_name, messages)
        cbs = self._resolve_callbacks(callbacks)
        cfg = {"callbacks": cbs} if cbs else {}

        captured_sources: list[dict] = []
        try:
            stream_target = self._llm
            if spec.tool is not None:
                first = await asyncio.to_thread(llm_w_tool.invoke, msgs, cfg)
                if getattr(first, "tool_calls", None):
                    tool_call = first.tool_calls[0]
                    tool_result = await asyncio.to_thread(
                        spec.tool.invoke, tool_call["args"]
                    )
                    msgs.append(first)
                    msgs.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=tool_call["id"],
                    ))
                    captured_sources = _parse_sources(tool_result)
                    yield StreamEvent(
                        kind="tool_call",
                        agent=agent_name,
                        tool_name=getattr(spec.tool, "name", ""),
                        collection=spec.collection,
                        sources=captured_sources,
                    )
                else:
                    content = first.content or ""
                    if content:
                        yield StreamEvent(kind="token", token=content)
                    yield StreamEvent(
                        kind="done", agent=agent_name, collection=spec.collection
                    )
                    return

            async for chunk in stream_target.astream(msgs, config=cfg):
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
