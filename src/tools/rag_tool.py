"""
Component 2 — RAG Tools (collection-aware, with HF Inference API reranking)
Two LangChain Tools: one per domain collection.
  rag_search_technical → kb_technical
  rag_search_hr        → kb_hr

Retrieval pipeline:
  1. Dense similarity search (HF Inference API embeddings, k=8 candidates)
  2. Reranking via HF Inference API sentence_similarity (keeps top 4)
  3. Context formatting with source attribution

All inference runs on HuggingFace cloud — no local model downloads required.
"""

import os
from dotenv import load_dotenv
from langchain.tools import tool
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from huggingface_hub import InferenceClient

load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
RETRIEVAL_K = 8   # candidates fetched before reranking
RERANK_TOP_N = 4  # final chunks passed to LLM

_qdrant_client: QdrantClient | None = None
_stores: dict[str, QdrantVectorStore] = {}
_hf_client: InferenceClient | None = None


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY"),
        )
    return _qdrant_client


def _get_hf_client() -> InferenceClient:
    global _hf_client
    if _hf_client is None:
        _hf_client = InferenceClient(token=os.getenv("HF_TOKEN"))
    return _hf_client


def _get_store(collection_name: str) -> QdrantVectorStore:
    if collection_name not in _stores:
        _stores[collection_name] = QdrantVectorStore(
            client=_get_qdrant(),
            collection_name=collection_name,
            embedding=HuggingFaceEndpointEmbeddings(
                model=EMBEDDING_MODEL,
                huggingfacehub_api_token=os.getenv("HF_TOKEN"),
            ),
        )
    return _stores[collection_name]


def _rerank(query: str, docs: list) -> list:
    """Rerank docs via HF Inference API sentence_similarity, return top RERANK_TOP_N."""
    if not docs:
        return docs
    scores = _get_hf_client().sentence_similarity(
        sentence=query,
        other_sentences=[doc.page_content for doc in docs],
        model=EMBEDDING_MODEL,
    )
    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ranked[:RERANK_TOP_N]]


def _format_results(results) -> str:
    if not results:
        return "Tidak ada dokumen relevan yang ditemukan."

    parts = []
    sources = []
    for doc in results:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", doc.metadata.get("chunk_id", "?"))
        parts.append(f"[Source: {source}, halaman/chunk: {page}]\n{doc.page_content}")
        sources.append(f"{source} (hal/chunk {page})")

    context = "\n\n---\n\n".join(parts)
    source_list = ", ".join(dict.fromkeys(sources))
    return f"{context}\n\n[SUMBER]: {source_list}"


def extract_sources(results) -> list[dict]:
    """Structured sources for UI rendering. Dedup on (source, page)."""
    seen = set()
    out = []
    for doc in results:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", doc.metadata.get("chunk_id"))
        key = (source, page)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "source": source,
            "page": page,
            "preview": doc.page_content[:160],
        })
    return out


def retrieve_with_scores(collection: str, query: str):
    """
    Run the same retrieval pipeline as production tools, but return raw
    (pre_rerank, post_rerank) with scores attached. Used by eval runner and
    the admin Interactive Probe.

    Returns: (pre, post) where each is list[(score, Document)].
      pre  — Qdrant similarity scores (higher = more similar, cosine)
      post — HF rerank scores for the top RERANK_TOP_N after reranking
    """
    store = _get_store(collection)
    pre_with_scores = store.similarity_search_with_score(query, k=RETRIEVAL_K)
    if not pre_with_scores:
        return [], []

    docs = [d for d, _ in pre_with_scores]
    rerank_scores = _get_hf_client().sentence_similarity(
        sentence=query,
        other_sentences=[d.page_content for d in docs],
        model=EMBEDDING_MODEL,
    )
    ranked = sorted(zip(rerank_scores, docs), key=lambda x: x[0], reverse=True)[:RERANK_TOP_N]

    pre = [(float(s), d) for d, s in pre_with_scores]
    post = [(float(s), d) for s, d in ranked]
    return pre, post


@tool
def rag_search_technical(query: str) -> str:
    """
    Search internal technical documentation (API Gateway, system architecture,
    integration guides, endpoint references). Use this for questions about
    technical systems, APIs, endpoints, authentication, or error codes.
    """
    collection = os.getenv("QDRANT_COLLECTION_TECHNICAL", "kb_technical")
    candidates = _get_store(collection).similarity_search(query, k=RETRIEVAL_K)
    results = _rerank(query, candidates)
    return _format_results(results)


@tool
def rag_search_hr(query: str) -> str:
    """
    Search internal HR documents (leave policy, onboarding procedures,
    employee benefits, company regulations). Use this for questions about
    employee policies, onboarding steps, leave entitlements, or HR processes.
    """
    collection = os.getenv("QDRANT_COLLECTION_HR", "kb_hr")
    candidates = _get_store(collection).similarity_search(query, k=RETRIEVAL_K)
    results = _rerank(query, candidates)
    return _format_results(results)
