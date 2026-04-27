"""
FastAPI backend — wraps the LangGraph multi-agent system with a streaming /chat endpoint.
"""

import os
import sys
import json
import asyncio
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage, AIMessage
from src.agents.graph import supervisor_node, AgentState
from src.agents import runner, get_langfuse_handler, REGISTRY
from eval.run_eval import (
    run as run_eval,
    RESULTS_PATH as EVAL_RESULTS_PATH,
    DATASET_PATH as EVAL_DATASET_PATH,
    _collection_for as eval_collection_for,
)
from src.tools.rag_tool import retrieve_with_scores

app = FastAPI(title="KnowledgeHub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROLE_CONTEXT = {
    "Developer": "Pengguna adalah seorang Developer/Engineer yang kemungkinan memiliki pertanyaan teknis.",
    "HR Staff": "Pengguna adalah staf HR yang kemungkinan memiliki pertanyaan tentang kebijakan SDM.",
    "Employee": "Pengguna adalah karyawan umum yang mungkin memiliki berbagai pertanyaan.",
    "Admin": "Pengguna adalah admin yang memantau performa sistem.",
}

# Guard against concurrent eval runs (Pola A grilling decision).
_eval_running = False

class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    name: str
    role: str
    message: str
    history: list[Message] = []


class ProbeRequest(BaseModel):
    question: str
    kb: str  # "hr" | "technical"


class LabelChunk(BaseModel):
    source: str
    page: int | None = None
    start_index: int
    content_snippet: str | None = None


class LabelRequest(BaseModel):
    question: str
    kb: str
    approved_chunks: list[LabelChunk]


def _build_lc_messages(history: list[Message]) -> list:
    msgs = []
    for m in history:
        if m.role == "user":
            msgs.append(HumanMessage(content=m.content))
        else:
            msgs.append(AIMessage(content=m.content))
    return msgs


def _run_supervisor(state: AgentState, callbacks=None) -> str:
    result = supervisor_node(state, callbacks=callbacks)
    return result.get("routing_decision", "GENERAL_AGENT")


async def _stream_response(request: ChatRequest) -> AsyncIterator[str]:
    lf_handler = get_langfuse_handler()
    callbacks = [lf_handler] if lf_handler else None

    history_msgs = _build_lc_messages(request.history)
    role_ctx = ROLE_CONTEXT.get(request.role, "")

    user_content = request.message
    if not history_msgs and role_ctx:
        user_content = f"[Konteks: {role_ctx}]\n\n{request.message}"

    messages = history_msgs + [HumanMessage(content=user_content)]

    state: AgentState = {
        "messages": messages,
        "current_agent": "",
        "routing_decision": "",
    }

    routing = await asyncio.to_thread(_run_supervisor, state, callbacks)

    async for ev in runner.stream(routing, messages, callbacks=callbacks):
        if ev.kind == "token":
            yield f"data: {json.dumps({'token': ev.token})}\n\n"
        elif ev.kind == "tool_call":
            yield f"data: {json.dumps({'tool_call': True, 'tool_name': ev.tool_name, 'agent': ev.agent, 'collection': ev.collection, 'sources': ev.sources})}\n\n"
        else:
            yield f"data: {json.dumps({'done': True, 'agent': ev.agent, 'collection': ev.collection, 'sources': ev.sources})}\n\n"


@app.post("/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        _stream_response(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/eval/results")
async def admin_eval_results():
    """Return the latest eval snapshot, or null-ish stub if none yet."""
    if not EVAL_RESULTS_PATH.exists():
        return {"status": "empty"}
    with open(EVAL_RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


@app.post("/admin/eval/run")
async def admin_eval_run():
    """Run batch eval and stream progress events via SSE."""
    from fastapi import HTTPException

    global _eval_running
    if _eval_running:
        raise HTTPException(status_code=409, detail="Eval already running.")

    async def generator():
        global _eval_running
        _eval_running = True
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def progress_cb(i: int, total: int, question: str):
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"progress": i, "total": total, "current": question},
            )

        async def runner():
            try:
                return await asyncio.to_thread(run_eval, progress_cb=progress_cb)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, {"_sentinel": True})

        task = asyncio.create_task(runner())
        try:
            while True:
                msg = await queue.get()
                if msg.get("_sentinel"):
                    break
                yield f"data: {json.dumps(msg)}\n\n"
            result = await task
            yield f"data: {json.dumps({'done': True, 'aggregate': result['aggregate'], 'by_group': result['by_group']})}\n\n"
        finally:
            _eval_running = False

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _doc_to_payload(score: float, doc, score_field: str) -> dict:
    m = doc.metadata
    return {
        "source": m.get("source"),
        "page": m.get("page"),
        "start_index": m.get("start_index"),
        "preview": doc.page_content[:400],
        score_field: score,
    }


@app.post("/admin/probe")
async def admin_probe(req: ProbeRequest):
    """Ad-hoc retrieval probe. Returns raw pre/post rerank chunks with scores."""
    from fastapi import HTTPException

    if req.kb not in ("hr", "technical"):
        raise HTTPException(status_code=400, detail="kb must be 'hr' or 'technical'")
    collection = eval_collection_for(req.kb)
    pre, post = await asyncio.to_thread(retrieve_with_scores, collection, req.question)
    return {
        "question": req.question,
        "kb": req.kb,
        "retrieved_at_8": [_doc_to_payload(s, d, "similarity_score") for s, d in pre],
        "retrieved_at_4": [_doc_to_payload(s, d, "rerank_score") for s, d in post],
    }


@app.post("/admin/dataset/label")
async def admin_dataset_label(req: LabelRequest):
    """Append a labeled entry to eval/dataset.json."""
    from fastapi import HTTPException

    if req.kb not in ("hr", "technical"):
        raise HTTPException(status_code=400, detail="kb must be 'hr' or 'technical'")
    if not req.approved_chunks:
        raise HTTPException(status_code=400, detail="approved_chunks cannot be empty")

    with open(EVAL_DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    existing_ids = {q["id"] for q in dataset["questions"]}
    prefix = f"{req.kb}-labeled-"
    n = 1
    while f"{prefix}{n:03d}" in existing_ids:
        n += 1
    new_id = f"{prefix}{n:03d}"

    entry = {
        "id": new_id,
        "question": req.question,
        "kb": req.kb,
        "type": "labeled",
        "expected_agent": "HR_AGENT" if req.kb == "hr" else "TECHNICAL_AGENT",
        "expected_chunks": [c.model_dump(exclude_none=True) for c in req.approved_chunks],
    }
    dataset["questions"].append(entry)

    with open(EVAL_DATASET_PATH, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    return {"id": new_id, "saved": True, "total_entries": len(dataset["questions"])}
