# KnowledgeHub Assistant

Multi-Agent RAG Chatbot untuk sistem tanya-jawab cerdas berbasis dokumen internal perusahaan.

**Stack:** LangChain · LangGraph · HuggingFace Inference API · Qdrant Cloud · FastAPI · Next.js · Langfuse

---

## Arsitektur

```
┌──────────────┐  HTTP/SSE  ┌──────────────┐  in-process  ┌──────────────────┐
│  Frontend    │ ─────────► │   FastAPI    │ ───────────► │  LangGraph       │
│  (Next.js)   │ ◄───────── │   (api/main) │ ◄─────────── │  Supervisor +    │
└──────────────┘            └──────┬───────┘              │  Agent Runner    │
                                   │                      └────────┬─────────┘
                                   ▼                               │ tool call
                            eval/results.json                      ▼
                                                            ┌──────────────┐
                                                            │  RAG Tool    │
                                                            │  + reranker  │
                                                            └──────┬───────┘
                                                                   ▼
                                                            ┌──────────────┐
                                                            │   Qdrant     │
                                                            │   Cloud      │
                                                            └──────────────┘
```

**Routing 3-arah:**

| Agent | Tool | Collection | Domain |
|---|---|---|---|
| `TECHNICAL_AGENT` | `rag_search_technical` | `kb_technical` | API Gateway, sistem teknis |
| `HR_AGENT` | `rag_search_hr` | `kb_hr` | Cuti, onboarding, kebijakan |
| `GENERAL_AGENT` | — | — | Pertanyaan umum (LLM-only) |

Detail lengkap alur per komponen: lihat **[WORKFLOW.md](WORKFLOW.md)** (termasuk glosarium istilah teknis).

---

## Prerequisites

- Python 3.10+
- Node.js 18+ (untuk frontend)
- HuggingFace account + access token (LLM + embeddings via Inference API)
- Qdrant Cloud account (URL + API key)
- Langfuse account (opsional — observability)

---

## Setup

### 1. Clone & install backend

```bash
git clone <your-repo-url>
cd knowledge-hub
pip install -r requirements.txt
```

### 2. Configure backend environment

```bash
cp .env.example .env
```

Isi `.env` dengan kredensial Anda. Field penting:
- `HF_TOKEN` — HuggingFace token (wajib)
- `QDRANT_URL` & `QDRANT_API_KEY` — kredensial Qdrant Cloud
- `LANGFUSE_*` — opsional

### 3. Install frontend

```bash
cd frontend
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL kalau backend bukan localhost:8000
npm install
cd ..
```

### 4. Siapkan dokumen

Letakkan PDF di `docs/`:
```
docs/
├── Dokumentasi_Teknis_API_Gateway.pdf       → kb_technical
├── Kebijakan_Cuti_dan_Izin_Karyawan.pdf     → kb_hr
└── SOP_Onboarding_Karyawan_Baru.pdf         → kb_hr
```

Mapping file → collection diatur di `ingest.py` (`COLLECTION_MAP`).

---

## Menjalankan Aplikasi

### Step 1 — Ingest dokumen ke Qdrant (sekali)

```bash
python ingest.py
```

Membuat dua collection (`kb_technical`, `kb_hr`), embed semua chunk via HF Inference API, dan menjalankan similarity search test untuk validasi. Re-run kapanpun dokumen berubah.

### Step 2 — Start backend

```bash
uvicorn api.main:app --reload --port 8000
```

Endpoint utama: `POST /chat` (SSE), `POST /admin/eval/run`, `POST /admin/probe`.

### Step 3 — Start frontend

```bash
cd frontend
npm run dev
```

Buka **http://localhost:3000**. Halaman:
- `/` — input nama + role
- `/chat` — chat interface dengan streaming token + source citation
- `/admin` — dashboard eval (Hit@4, Hit@8, MRR@4)
- `/admin/probe` — interactive retrieval probe + dataset labeling

### (Opsional) CLI mode

```bash
python main.py
```

Terminal interface dengan Rich (banner, agent badge, history, help). Tidak streaming.

---

## Project Structure

```
knowledge-hub/
├── docs/                      # Source PDFs
├── src/
│   ├── agents/
│   │   ├── graph.py           # LangGraph topology + supervisor node
│   │   ├── runner.py          # Per-agent execution (sync + stream)
│   │   ├── registry.py        # AgentSpec dataclass + registry
│   │   ├── llm.py             # ChatHuggingFace factory + Langfuse handler
│   │   └── __init__.py        # Register all 3 agents
│   ├── tools/
│   │   └── rag_tool.py        # RAG tools per collection + HF reranker
│   └── prompts/
│       └── prompts.py         # Versioned system prompts (with few-shot)
├── api/
│   └── main.py                # FastAPI: /chat (SSE), /admin/*
├── frontend/                  # Next.js App Router (chat + admin)
├── eval/
│   ├── dataset.json           # Ground-truth questions + expected chunks
│   ├── run_eval.py            # Hit@4 / Hit@8 / MRR@4 batch evaluator
│   └── results.json           # Latest snapshot
├── ingest.py                  # Document → chunk → embed → Qdrant
├── main.py                    # CLI entry (Rich terminal UI)
├── WORKFLOW.md                # Detailed workflow + glossary
└── requirements.txt
```

---

## Beyond Minimum Requirements

Implementasi melebihi requirement minimum di beberapa titik (relevant untuk presentasi):

| Komponen | Tambahan |
|---|---|
| Vector DB | Multi-collection (per-domain) — bukan single collection |
| RAG Tool | **Cross-encoder reranking** via HF `sentence_similarity` (k=8 → top-4) |
| Multi-Agent | 3 sub-agent (PDF minta minimum 2) + **structured output** untuk routing |
| Prompt | Few-shot examples + chain-of-thought di supervisor |
| UI | Streaming token-by-token + **structured source chips** + agent badges |
| Observability | **Langfuse** integration (LLM tracing) |
| Eval | Built-in eval framework (Hit@4, Hit@8, MRR@4) + admin dashboard |
| Tooling | **Interactive probe** untuk debug retrieval + dataset labeling UI |

Untuk istilah teknis (Hit@4, MRR, HNSW, dll), lihat **[Glosarium di WORKFLOW.md](WORKFLOW.md#glosarium)**.

---

## Catatan Keamanan

- `.env` di-`.gitignore` — credential tidak masuk repo.
- Sebelum demo / deploy ulang: rotate HF token, Qdrant API key, dan Langfuse keys.
- File `.env.example` aman untuk di-commit (placeholder saja).
