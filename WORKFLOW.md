# KnowledgeHub — Product Workflow

Dokumentasi cara kerja product dari ujung ke ujung. Format: pseudocode level fungsi, bukan kode asli. Cakupan:

1. Arsitektur tinggi (siapa bicara ke siapa)
2. Foundation: Ingestion pipeline
3. Main flow: **Chat** (Frontend → API → Multi-Agent Backend)
4. Admin flow: **RAG Monitoring** (Eval batch + Interactive Probe)
5. Ringkasan state per request
6. Cara menjalankan
7. **Spesifikasi RAG** — angka konkret (chunk size, k, rerank, vector dim, dll)
8. **Glosarium** — terminologi → definisi (Hit@K, HNSW, CoT, dll)

> Tidak dibahas di sini: landing page, role selection, logout — itu hanya simulasi UX di sisi browser, tidak menyentuh backend.

---

## 1. Arsitektur Tinggi

```
┌──────────────┐   HTTP/SSE   ┌──────────────┐   in-process   ┌──────────────────┐
│  Frontend    │ ───────────► │   FastAPI    │ ─────────────► │  LangGraph       │
│  (Next.js)   │ ◄─────────── │   (api/main) │ ◄───────────── │  Supervisor +    │
│              │   stream     │              │                │  Agent Runner    │
└──────────────┘              └──────┬───────┘                └────────┬─────────┘
                                     │                                  │
                                     │                                  │ tool call
                                     │                                  ▼
                                     │                          ┌──────────────┐
                                     │                          │  RAG Tool    │
                                     │                          │  (per KB)    │
                                     │                          └──────┬───────┘
                                     │                                  │
                                     ▼                                  ▼
                              ┌──────────────┐                  ┌──────────────┐
                              │  eval/*.json │                  │   Qdrant     │
                              │  (snapshot)  │                  │   Cloud      │
                              └──────────────┘                  └──────────────┘
                                                                       ▲
                                                                       │ ingest sekali
                                                                ┌──────┴───────┐
                                                                │  ingest.py   │
                                                                │  (PDF→vec)   │
                                                                └──────────────┘
```

**Komponen:**

| Layer | File | Tanggung jawab |
|---|---|---|
| Frontend chat | `frontend/src/app/chat/page.tsx` | Kirim pesan, render token streaming |
| Frontend admin | `frontend/src/app/admin/page.tsx` | Trigger eval, render metrik |
| Frontend probe | `frontend/src/app/admin/probe/page.tsx` | Interactive retrieval probe |
| API gateway | `api/main.py` | FastAPI: `/chat`, `/admin/eval/*`, `/admin/probe`, `/admin/dataset/label` |
| Graph topology | `src/agents/graph.py` | Supervisor node + routing edges |
| Per-agent execution | `src/agents/runner.py` | Bind tool, invoke LLM, handle tool call, stream |
| Agent registry | `src/agents/registry.py` + `src/agents/__init__.py` | Daftar agent: name, prompt, tool, collection |
| LLM factory | `src/agents/llm.py` | HuggingFace endpoint + Langfuse callback |
| RAG tool | `src/tools/rag_tool.py` | Qdrant similarity search + HF rerank |
| Prompts | `src/prompts/prompts.py` | System prompts (Supervisor, Technical, HR, General) |
| Ingestion | `ingest.py` | PDF → chunk → embed → Qdrant |
| Eval runner | `eval/run_eval.py` | Batch retrieval eval terhadap `dataset.json` |

**Tools / Library inti:**
- **LangGraph** — orchestrator multi-agent (StateGraph)
- **LangChain** — abstraksi LLM, ChatHuggingFace, Tool decorator
- **Qdrant Cloud** — vector database (cosine, 384-dim)
- **HuggingFace Inference API** — embeddings + LLM (Qwen2.5-72B default) + reranking via `sentence_similarity`
- **FastAPI** — backend + SSE streaming
- **Next.js (App Router)** — frontend
- **Langfuse** — observability (opsional, lewat callback)

**Agents (3):**

| Agent | Tool | Collection | Tugas |
|---|---|---|---|
| `TECHNICAL_AGENT` | `rag_search_technical` | `kb_technical` | Pertanyaan API/sistem |
| `HR_AGENT` | `rag_search_hr` | `kb_hr` | Pertanyaan kebijakan/SOP |
| `GENERAL_AGENT` | — (no tool) | — | Pertanyaan umum (LLM-only) |

Plus **Supervisor** — bukan AgentSpec, melainkan node LLM khusus di graph yang routing.

---

## 2. Foundation — Ingestion Pipeline

Dijalankan **sekali** (atau tiap kali dokumen berubah): `python ingest.py`. Tanpa ini, RAG tool akan return kosong.

```pseudocode
function ingest():
    # [1/3] Load + chunk
    for each PDF in docs/:
        target_collection = COLLECTION_MAP[file.stem]   # technical | hr
        raw_docs          = PyPDFLoader.load(file)
        annotate(raw_docs, source=file.name, domain=target_collection)
        chunks            = RecursiveCharacterTextSplitter(
                                size=800, overlap=150, add_start_index=True
                            ).split(raw_docs)
        annotate(chunks, chunk_id=index)
        bucket[target_collection].extend(chunks)

    # [2/3] (Re)create Qdrant collections
    for col in bucket.keys():
        if col exists: client.delete_collection(col)
        client.create_collection(col, size=384, distance=COSINE)

    # [3/3] Embed + insert
    for col, chunks in bucket:
        store = QdrantVectorStore(client, col, embedding=HF_endpoint_embeddings)
        store.add_documents(chunks)         # HF API embeds, Qdrant stores

    # Validation
    for col, sample_query: print top-2 similarity_search hits
```

**Metadata penting per chunk** (dipakai eval & UI):
`source`, `page`, `chunk_id`, `start_index`, `domain`.

---

## 3. Main Flow — Chat

End-to-end dari user mengetik pesan sampai jawaban ter-stream ke layar.

### 3.1 Diagram alur

```
User types        FE: POST /chat              API: _stream_response
─────────────►    ──────────────────►         ─────────────────────────
                  body = {                    1. build_lc_messages(history)
                    name, role,               2. inject role context (turn 1)
                    message,                  3. supervisor_node → routing
                    history                   4. runner.stream(routing, msgs)
                  }                                  │
                                                     ▼
                                              ┌──────────────┐
                                              │ Agent runner │
                                              └──────┬───────┘
                                                     │
                            ┌────────────────────────┴────────────────────┐
                            │                                              │
                  TECHNICAL/HR (has tool)                          GENERAL (no tool)
                  1. invoke llm_with_tool                          1. astream(llm)
                  2. if tool_calls:                                2. yield tokens
                       run rag_search_*(query)                     3. yield done
                       append ToolMessage
                       parse sources from tool result
                       yield tool_call {tool_name, sources}
                  3. astream(llm) untuk jawab final
                  4. yield tokens
                  5. yield done {agent, collection, sources}

                                   ▲
                                   │ SSE event types (semua "data: <json>\n\n"):
                                   │   {"token": "..."}
                                   │   {"tool_call": true, "tool_name":"...", "collection":"...", "sources":[...]}
                                   │   {"done": true, "agent":"...", "collection":"...", "sources":[...]}
                                   │
FE chat page reads stream:
  while reader.read():
    parse "data: " lines
    if event.token     → append ke bubble agent (streaming=true)
    if event.tool_call → tampilkan trace "🔍 Memanggil tool_name → N dokumen"
    if event.done      → set agent label + collection badge + render source chips,
                         streaming=false
```

### 3.2 Frontend — `frontend/src/app/chat/page.tsx`

```pseudocode
function ChatPage:
    state: messages[], input, isStreaming
    onMount: load name+role dari sessionStorage; redirect if missing

    function sendMessage():
        userMsg  = {role: "user", content: input}
        agentMsg = {role: "agent", content: "", streaming: true}
        push both to messages
        clear input; isStreaming = true

        response = await fetch(API_URL + "/chat", POST, {
            name, role, message: input,
            history: messages.filter(not streaming)
                             .map(m → {role, content})
        })

        reader = response.body.getReader()
        loop until done:
            chunk = decode(reader.read())
            for each line starting "data: ":
                event = JSON.parse(line.slice(6))
                if event.token:
                    update agentMsg.content += event.token   # token-by-token UI
                if event.done:
                    agentMsg.streaming = false
                    agentMsg.agent      = event.agent
                    agentMsg.collection = event.collection
        isStreaming = false
```

Yang penting: **history yang dikirim hanya pesan non-streaming yang sudah selesai**, format `{role: "user"|"assistant", content}`.

### 3.3 API — `api/main.py` :: `/chat`

```pseudocode
endpoint POST /chat (request: ChatRequest):
    return StreamingResponse(_stream_response(request),
                             media_type="text/event-stream")

async function _stream_response(req):
    callbacks = [Langfuse handler] if env keys present else None

    history_msgs = req.history.map(m → HumanMessage|AIMessage)
    user_text    = req.message
    if history_msgs is empty and req.role in ROLE_CONTEXT:
        # inject "Konteks: Pengguna adalah ..." HANYA di turn pertama
        user_text = f"[Konteks: {ROLE_CONTEXT[req.role]}]\n\n{req.message}"
    messages = history_msgs + [HumanMessage(user_text)]

    state = {messages, current_agent: "", routing_decision: ""}

    # Step 1 — Supervisor (sync, dijalankan di thread)
    routing = await to_thread(supervisor_node, state, callbacks)
                                  # → "TECHNICAL_AGENT" | "HR_AGENT" | "GENERAL_AGENT"

    # Step 2 — Agent stream
    async for ev in runner.stream(routing, messages, callbacks):
        if ev.kind == "token":
            yield  f'data: {{"token": "{ev.token}"}}\n\n'
        elif ev.kind == "tool_call":
            yield  f'data: {{"tool_call": true, "tool_name":"{ev.tool_name}",
                              "agent":"{ev.agent}", "collection":"{ev.collection}",
                              "sources":[...]}}\n\n'
        else:  # done
            yield  f'data: {{"done": true, "agent":"{ev.agent}",
                              "collection":"{ev.collection}",
                              "sources":[...]}}\n\n'
```

> Catatan: API tidak memakai `graph.invoke()` langsung. Ia memanggil `supervisor_node` lalu `runner.stream()` agar bisa SSE token-by-token. `main.py` (CLI) yang pakai `graph.invoke()` (non-streaming).

### 3.4 Supervisor — `src/agents/graph.py`

```pseudocode
class RoutingDecision:                             # pydantic enum literal
    decision: "TECHNICAL_AGENT" | "HR_AGENT" | "GENERAL_AGENT"

supervisor_llm = llm.with_structured_output(RoutingDecision)  # may raise NotImplementedError

function supervisor_node(state, callbacks):
    history = state.messages[-6:]                  # sliding window 6 turns
    try:
        result   = supervisor_llm.invoke([SystemMessage(SUPERVISOR_PROMPT), *history])
        decision = result.decision
    except:
        # Fallback: plain LLM + keyword sniff dari output text
        raw = llm.invoke([SystemMessage(SUPERVISOR_PROMPT), *history]).content.upper()
        if "TECHNICAL" in raw:  decision = "TECHNICAL_AGENT"
        elif "HR" in raw:       decision = "HR_AGENT"
        else:                   decision = "GENERAL_AGENT"
    return {...state, current_agent: decision, routing_decision: decision}
```

Supervisor prompt mendikte few-shot examples + tie-breakers (lihat `src/prompts/prompts.py`):
- Ambigu TECHNICAL vs HR → keyword dominan menang
- Ambigu doc-topic vs general knowledge → pilih doc agent

### 3.5 Agent Runner — `src/agents/runner.py`

Runner adalah satu-satunya tempat agent dieksekusi. Logikanya **sama** untuk sync (`run`) dan stream (`stream`), beda hanya di output.

```pseudocode
class AgentRunner(llm, window=6, callback_provider):
    _bound = {}                                    # cache llm.bind_tools per agent

    function _prepare(name, messages):
        spec     = REGISTRY[name]                  # AgentSpec(prompt, tool, collection,...)
        history  = messages[-6:]                   # sliding window
        prepared = [SystemMessage(spec.system_prompt)] + history
        llm_w_tool = llm.bind_tools([spec.tool]) if spec.tool else llm
        return prepared, llm_w_tool

    async function stream(agent_name, messages, callbacks):
        msgs, llm_w_tool = _prepare(agent_name, messages)
        spec             = REGISTRY[agent_name]
        captured_sources = []

        if spec.tool is not None:
            # ── ROUND 1: ask LLM, mungkin minta tool call ──
            first = await to_thread(llm_w_tool.invoke, msgs)
            if first.tool_calls:
                tool_call   = first.tool_calls[0]
                tool_result = await to_thread(spec.tool.invoke, tool_call.args)
                msgs.append(first)
                msgs.append(ToolMessage(tool_result, tool_call.id))

                # Parse [Source: file, halaman/chunk: N] dari tool_result (dedup)
                captured_sources = _parse_sources(tool_result)
                yield StreamEvent(tool_call,
                                  tool_name=spec.tool.name,
                                  collection=spec.collection,
                                  sources=captured_sources)
                # fall-through ke streaming round 2
            else:
                # LLM langsung jawab tanpa retrieval (rare path)
                yield StreamEvent(token=first.content)
                yield StreamEvent(done, agent=name, collection=spec.collection)
                return

        # ── ROUND 2 (atau satu-satunya round untuk GENERAL): stream final answer ──
        async for chunk in llm.astream(msgs):
            if chunk.content: yield StreamEvent(token=chunk.content)
        yield StreamEvent(done, agent=name, collection=spec.collection,
                          sources=captured_sources)
```

Poin halus:
- Window 6 turns dipakai **dua kali** (di supervisor dan di agent) — independen.
- Tool dipanggil **satu kali per request** (`tool_calls[0]`). Tidak ada loop multi-tool.
- Callback Langfuse di-flush di blok `finally` agar trace tidak hilang.

### 3.6 RAG Tool — `src/tools/rag_tool.py`

Dua tool, satu per koleksi. Logika identik kecuali env var collection.

```pseudocode
@tool
function rag_search_technical(query: str) → str:
    return _search("kb_technical", query)

@tool
function rag_search_hr(query: str) → str:
    return _search("kb_hr", query)

function _search(collection, query):
    store      = QdrantVectorStore(collection, embedding=HF_endpoint_embeddings)
    candidates = store.similarity_search(query, k=8)              # dense search
    top4       = _rerank(query, candidates)                       # HF cross-sim
    return _format(top4)                                          # text + [SUMBER]:...

function _rerank(query, docs):
    scores = HF_client.sentence_similarity(
                 sentence=query,
                 other_sentences=[d.page_content for d in docs],
                 model=EMBEDDING_MODEL)
    return sort(zip(scores, docs), desc by score)[:4]

function _format(results):
    parts = [f"[Source: {source}, halaman/chunk: {page}]\n{content}" for d in results]
    return  "\n\n---\n\n".join(parts) + "\n\n[SUMBER]: " + dedup(sources)
```

LLM melihat hasil format ini sebagai `ToolMessage`, lalu menulis jawaban final yang menyertakan `Sumber: ...` (instruksi dari prompt).

Versi `retrieve_with_scores(collection, query)` mengembalikan **(pre, post)** dengan skor mentah — dipakai oleh eval dan endpoint `/admin/probe`. Identik dengan production tapi tidak melakukan formatting.

### 3.7 LLM Factory — `src/agents/llm.py`

```pseudocode
llm = ChatHuggingFace(
        HuggingFaceEndpoint(
            repo_id   = env.HF_MODEL_ID || "Qwen/Qwen2.5-72B-Instruct",
            token     = env.HF_TOKEN,
            temperature = 0.01,
            max_new_tokens = 1024))

function get_langfuse_handler():
    if env.LANGFUSE_* set:
        return CallbackHandler(public, secret, host)
    else:
        return None
```

---

## 4. Admin Flow — RAG Monitoring

Admin memakai dua fitur: **batch evaluation** (skor agregat) dan **interactive probe** (debug satu pertanyaan + label dataset baru).

### 4.1 Batch Evaluation

```
Admin clicks "Run Eval"
        │
        ▼
FE POST /admin/eval/run  ──────────────►  API spawns thread → run_eval.run()
        │                                         │
        │ ◄─── SSE progress events ──────────────│  per-question:
        │      {progress, total, current}        │    progress_cb(i, total, q)
        │                                         │    evaluate_question(q)
        │ ◄─── SSE done event ───────────────────│  write eval/results.json
        │      {done, aggregate, by_group}        ▼
        ▼
FE re-fetches /admin/eval/results → render MetricCards + per-question drill-down
```

#### 4.1.1 API — `/admin/eval/run` (SSE)

```pseudocode
_eval_running = False                              # global guard, blokir concurrent run

endpoint POST /admin/eval/run:
    if _eval_running: raise 409 Conflict
    return StreamingResponse(generator(), text/event-stream)

async function generator():
    _eval_running = True
    queue = AsyncQueue()

    function progress_cb(i, total, q):             # dipanggil dari thread eval
        loop.call_soon_threadsafe(queue.put, {progress: i, total, current: q})

    task = create_task( to_thread(run_eval, progress_cb=progress_cb) )
    finally schedule sentinel ke queue

    while True:
        msg = await queue.get()
        if msg.is_sentinel: break
        yield f'data: {msg}\n\n'

    result = await task
    yield  f'data: {{"done": true, "aggregate":..., "by_group":...}}\n\n'
    _eval_running = False
```

#### 4.1.2 Eval runner — `eval/run_eval.py`

```pseudocode
function run(progress_cb=None):
    dataset = load("eval/dataset.json")            # [{id, question, kb, type, expected_chunks:[...]}]
    per_q   = []
    for i, q in enumerate(dataset.questions):
        progress_cb?(i, total, q.question)
        per_q.append( evaluate_question(q) )

    output = { run_timestamp, dataset_size,
               aggregate, by_group,                # mean Hit@4, Hit@8, MRR@4
               per_question: per_q }
    save("eval/results.json", output)
    return output

function evaluate_question(q):
    pre, post     = retrieve_with_scores(_collection_for(q.kb), q.question)
    expected_keys = { (c.source, c.page, c.start_index) for c in q.expected_chunks }
    pre_keys      = [ (d.source, d.page, d.start_index) for d in pre ]
    post_keys     = [ (d.source, d.page, d.start_index) for d in post ]

    hit_at_8     = any(k in expected_keys for k in pre_keys)
    hit_at_4     = any(k in expected_keys for k in post_keys)
    rank_in_post = first index+1 di post_keys yang masuk expected_keys, else None

    snippet_warnings = ...   # dataset staleness check: snippet di expected_chunks
                             # masih ada di chunk content yang sebenarnya?

    return { id, question, kb, type, expected, retrieved_at_8, retrieved_at_4,
             hit_at_4, hit_at_8, rank_in_post4, snippet_warnings }
```

**Metrik (semua: tinggi = bagus):**
| Metrik | Arti |
|---|---|
| Hit@8 (pre-rerank) | Apakah expected chunk muncul di top-8 dari Qdrant |
| Hit@4 (post-rerank) | Apakah expected chunk lolos rerank ke top-4 (yang dilihat LLM) |
| MRR@4 | Mean reciprocal rank chunk benar di top-4 (1.0 = selalu posisi #1) |

Diagnostik UI: bila `Hit@8 - Hit@4 > 0.15`, tampilkan warning **"Rerank drop terdeteksi"** — reranker membuang chunk benar.

#### 4.1.3 FE — `frontend/src/app/admin/page.tsx`

```pseudocode
function AdminPage:
    onMount: GET /admin/eval/results → render

    function runEval():
        running = true
        res     = await fetch(API + "/admin/eval/run", POST)
        loop SSE:
            event.progress → update progress bar
            event.done     → exit loop
        await loadResults()                        # refresh dashboard
        running = false

    render:
        Top: MetricCards (Hit@4, Hit@8, MRR@4, dataset N)
        Mid: warning banner if rerank drop
        Mid: breakdown table by (kb × type)
        Bottom: per-question expandable rows
                ├─ summary: id, kb, type, H@4 ✓/✗, H@8 ✓/✗, rank
                └─ details: expected chunks vs retrieved top-4 (highlight match green)
        Filter: All | Failures only
```

### 4.2 Interactive Probe (one-shot debugging + labeling)

Admin mengetik pertanyaan, pilih KB, lihat retrieval mentah, dan **boleh menambah ground truth ke dataset**.

```
Admin types question, picks KB (hr|technical)
        │
        ▼
FE POST /admin/probe {question, kb}
        │
        ▼
API: retrieve_with_scores(collection, question)
     return {
       retrieved_at_8: [{source, page, start_index, preview, similarity_score}, ...],
       retrieved_at_4: [{..., rerank_score}, ...]
     }
        │
        ▼
FE renders both lists; admin centang chunk yang benar
        │
        ▼
FE POST /admin/dataset/label {question, kb, approved_chunks:[{source,page,start_index,snippet}]}
        │
        ▼
API:
    dataset = load("eval/dataset.json")
    new_id  = next "{kb}-labeled-NNN" yang belum ada
    append { id, question, kb, type:"labeled",
             expected_agent: HR_AGENT|TECHNICAL_AGENT,
             expected_chunks }
    save dataset.json
    return {id, saved: true, total_entries}
```

Efeknya: dataset tumbuh dari yang awalnya hanya synthetic menjadi campuran synthetic + labeled. Eval batch berikutnya otomatis menggunakan semua entry baru.

---

## 5. Ringkasan State per Request

| Konteks | Yang dibawa | Yang di-derive saat itu |
|---|---|---|
| Request `/chat` | name, role, message, history | role context (turn 1 saja), routing |
| Request `/admin/eval/run` | (kosong) | per-question result, aggregate |
| Request `/admin/probe` | question, kb | pre/post-rerank dengan skor |
| Request `/admin/dataset/label` | question, kb, approved_chunks | new id `{kb}-labeled-NNN` |

Tidak ada session/DB user di backend. Semua "state percakapan" lahir-mati dalam satu request — frontend yang menyimpan `messages[]` dan mengirim ulang sebagai `history`.

---

## 6. Cara Menjalankan (urutan wajib)

```bash
# 1) Ingest dokumen → Qdrant (sekali, atau saat dokumen berubah)
python ingest.py

# 2a) CLI mode (Rich terminal UI, non-streaming)
python main.py

# 2b) Atau full-stack mode
uvicorn api.main:app --reload --port 8000          # backend
cd frontend && npm run dev                         # frontend di :3000
```

Endpoint yang dipakai FE:
- `POST /chat` — SSE chat stream (event: `token`, `tool_call`, `done`)
- `GET  /admin/eval/results` — snapshot terakhir
- `POST /admin/eval/run` — trigger batch eval (SSE)
- `POST /admin/probe` — probe satu pertanyaan
- `POST /admin/dataset/label` — append entry ke `eval/dataset.json`

---

## 7. Spesifikasi RAG (Angka Konkret)

Semua nilai diambil langsung dari kode (bukan estimasi). Source-of-truth: `ingest.py`, `src/tools/rag_tool.py`.

### 7.1 Ingestion (build-time)

| Parameter | Nilai | Lokasi | Alasan |
|---|---|---|---|
| Chunking strategy | `RecursiveCharacterTextSplitter` | `ingest.py:58` | Default LangChain — split berdasarkan paragraf → kalimat → kata, jaga konteks alami. |
| `chunk_size` | **800 karakter** | `ingest.py:27` | Cukup untuk 1–2 paragraf utuh, masih jauh di bawah context window LLM. |
| `chunk_overlap` | **150 karakter** | `ingest.py:28` | ~18% overlap → menjaga kontinuitas antar-chunk untuk kalimat yang terpotong. |
| `add_start_index` | `True` | `ingest.py:61` | Wajib untuk eval — `(source, page, start_index)` jadi composite key chunk. |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` | `.env` / `ingest.py:32` | Multilingual (Bahasa Indonesia), 384 dim, ringan, gratis di HF Inference API. |
| Vector dimension | **384** | `ingest.py:33` | Harus match dengan output embedding model. |
| Embedding provider | HuggingFace Inference API | `ingest.py:86` | No local download — semua inference di cloud HF. |
| Metadata per chunk | `source`, `page`, `chunk_id`, `start_index`, `domain` | `ingest.py:46-65` | Source attribution + eval keying + domain filter. |

### 7.2 Vector Database (Qdrant)

| Properti | Nilai | Catatan |
|---|---|---|
| Provider | **Qdrant Cloud** (managed) | Bukan self-hosted. |
| Index type | **HNSW** (Hierarchical Navigable Small World) | Default Qdrant — graph-based ANN, sub-linear search. |
| Distance metric | **Cosine** | `Distance.COSINE` di `ingest.py:76`. |
| Vector size | 384 | Cocok dengan MiniLM-L12-v2. |
| Collections | 2 — `kb_technical` + `kb_hr` | Multi-collection per domain → routing lebih presisi. |
| Recreate strategy | Drop + create on every `python ingest.py` | Idempoten: re-ingest selalu berangkat dari state bersih. |

### 7.3 Retrieval Pipeline (query-time)

Untuk **setiap** panggilan `rag_search_*(query)`:

```
query  ──► HF embedding (384-dim)
       ──► Qdrant.similarity_search(k=8)        ◄── DENSE RETRIEVAL (Stage 1)
       ──► HF sentence_similarity rerank        ◄── CROSS-ENCODER RERANK (Stage 2)
       ──► top-4 chunks
       ──► _format_results() → string + [SUMBER]: ...
       ──► dikembalikan ke LLM sebagai ToolMessage
```

| Parameter | Nilai | Lokasi | Catatan |
|---|---|---|---|
| Stage-1 retrieval method | **Dense** (single-vector cosine) | `rag_tool.py:130` | Tidak ada sparse/BM25 — pure semantic. |
| `RETRIEVAL_K` | **8 candidates** | `rag_tool.py:26` | Pool kasar yang akan di-rerank. |
| Stage-2 method | **Cross-encoder reranking** via `sentence_similarity` | `rag_tool.py:64-74` | Pakai model embedding yang sama, tapi compute pairwise similarity (query, doc) untuk re-scoring. |
| `RERANK_TOP_N` | **4 chunks final** | `rag_tool.py:27` | Yang sebenarnya masuk ke konteks LLM. |
| Filter metadata | Tidak ada | — | Routing per-domain sudah dipisah lewat collection terpisah, jadi tidak perlu metadata filter di runtime. |
| Source attribution format | `[Source: filename, halaman/chunk: N]` per chunk + `[SUMBER]: list` di akhir | `rag_tool.py:86-91` | Diparse oleh `runner._parse_sources()` jadi structured chips di UI. |

### 7.4 Agent Context Window

| Konteks | Window | Lokasi |
|---|---|---|
| Supervisor (routing decision) | last **6 messages** | `graph.py:46` |
| Agent (final answer) | last **6 messages** | `runner.py:36` |

PDF requirement: **minimum 3 turn** = 6 messages (1 user + 1 agent per turn). ✓ memenuhi.

### 7.5 Kompleksitas Tambahan vs Minimum

| Area | PDF minimum | Implementasi ini |
|---|---|---|
| RAG retrieval | Dense similarity saja | Dense + cross-encoder rerank (PDF §8 ✓) |
| Agent count | 2 sub-agent | 3 sub-agent (Technical, HR, General) |
| Routing | LLM bebas-form | LangChain **structured output** (Pydantic enum) + fallback keyword |
| Prompts | System prompt saja | + few-shot examples + chain-of-thought di supervisor |
| Source attribution | Disebut di teks jawaban | + structured SSE event + chip UI |
| Transparency | Log alur agent | + tool call event + retrieval count + collection badge |
| Eval | Tidak diwajibkan | Built-in Hit@4 / Hit@8 / MRR@4 + admin dashboard |
| Observability | Opsional Langfuse | Terintegrasi (auto-skip kalau env tidak diisi) |

---

## 8. Glosarium

Daftar istilah teknis yang muncul di codebase, README, dan dashboard. Format: **Terminologi → Definisi**.

### RAG & Retrieval

- **RAG (Retrieval-Augmented Generation)** → Pola arsitektur dimana LLM dilengkapi dengan retrieval step yang mengambil konteks dari sumber eksternal (dokumen) sebelum menjawab. Mengurangi halusinasi dan memungkinkan jawaban berbasis dokumen privat.
- **Chunk** → Potongan dokumen yang sudah di-split (di sini: 800 karakter dengan overlap 150). Unit terkecil yang di-embed dan disimpan di vector DB.
- **chunk_size / chunk_overlap** → Panjang chunk dan jumlah karakter yang di-overlap antar chunk berurutan. Overlap menjaga kontinuitas untuk kalimat yang terpotong di batas chunk.
- **Embedding** → Representasi numerik (vector 384-dim di sini) dari sebuah teks. Teks yang serupa menghasilkan vector berdekatan dalam ruang cosine.
- **Dense retrieval** → Pencarian berbasis vector embedding (semantik). Lawan: sparse retrieval (keyword-based, contoh BM25).
- **Hybrid search** → Kombinasi dense + sparse retrieval, biasanya digabung dengan reciprocal rank fusion. **Tidak diimplementasikan** di project ini (peluang kompleksitas tambahan).
- **k (top-k)** → Jumlah kandidat awal yang di-retrieve dari vector DB. Di sini `k=8`.
- **Reranking** → Tahap kedua setelah dense retrieval — re-skor `k` kandidat menggunakan model yang lebih akurat (cross-encoder), keep top-N. Tradeoff: presisi naik, latency naik.
- **Cross-encoder** → Model yang menerima sepasang teks `(query, doc)` sebagai input dan menghasilkan satu skor relevansi. Lebih akurat dari dense (bi-encoder) tapi lebih lambat → cocok untuk tahap rerank.
- **`sentence_similarity`** → Endpoint HF Inference API yang compute similarity antara satu kalimat anchor dan list kalimat lain. Dipakai sebagai cross-encoder rerank di project ini.
- **Source attribution** → Mencantumkan asal dokumen (filename + halaman/chunk) di jawaban agar dapat diverifikasi pengguna.

### Vector Database

- **Qdrant** → Vector database open-source (di project ini: edisi cloud-managed). Menyimpan vector + metadata, mendukung filtering metadata, similarity search.
- **HNSW (Hierarchical Navigable Small World)** → Algoritma index Approximate Nearest Neighbor (ANN) yang dipakai Qdrant default. Graph-based, memberi search sub-linear (~O(log n)) dengan trade-off recall sedikit di bawah exact search.
- **Cosine distance** → Metric similarity: `1 - cos(angle(a, b))`. Tidak sensitif terhadap magnitude vector. Default untuk text embeddings.
- **Collection** → Container di Qdrant — analog dengan "table" di SQL. Project ini punya 2: `kb_technical` dan `kb_hr`.

### Agentic / LangGraph

- **Agent** → Komponen yang menggabungkan LLM + sistem prompt (dan opsional: tool). Di sini: TECHNICAL_AGENT, HR_AGENT, GENERAL_AGENT.
- **Supervisor agent** → Agent khusus yang **tidak menjawab user**, melainkan memilih sub-agent mana yang akan handle pertanyaan. Implementasinya pakai structured output → enum literal.
- **Sub-agent** → Agent spesialis yang dipanggil oleh supervisor untuk task tertentu. PDF mensyaratkan minimum 2 sub-agent.
- **Tool** → Fungsi yang di-bind ke LLM via `bind_tools([...])`. LLM bisa memilih untuk memanggil tool, dengan argumen yang ia tentukan sendiri. Di sini: `rag_search_technical`, `rag_search_hr`.
- **Tool call** → Output LLM yang berbentuk "panggil fungsi X dengan args Y" (bukan teks jawaban langsung). Di-execute oleh runner, hasilnya dikirim balik sebagai `ToolMessage`.
- **LangGraph StateGraph** → Library untuk membangun multi-node workflow dengan state typed. Menggantikan loop manual.
- **Conditional edge** → Edge graph yang tujuannya ditentukan runtime oleh fungsi routing (di sini: `route_after_supervisor`).
- **Structured output** → Mode LLM dimana output dipaksa match Pydantic schema. Dipakai supervisor untuk routing yang reliable (bukan free-form text yang harus di-parse).
- **Chain-of-thought (CoT)** → Prompting style yang minta LLM berpikir step-by-step sebelum jawab. Diterapkan di supervisor prompt.
- **Few-shot examples** → Contoh `(input, output)` yang dimasukkan ke prompt untuk mengkalibrasi gaya & akurasi LLM. Supervisor punya 8 contoh routing.

### Streaming & API

- **SSE (Server-Sent Events)** → Protokol streaming HTTP satu arah (server → client). Format: `data: <json>\n\n`. Lebih sederhana dari WebSocket untuk one-way streaming.
- **`astream`** → Async generator method LangChain untuk stream token LLM satu per satu.
- **StreamEvent** → Internal dataclass runner — punya 3 kind: `token`, `tool_call`, `done`. Setiap kind di-mapping ke SSE message berbeda di `api/main.py`.

### Eval Metrics

- **Hit@K** → Boolean: apakah ada chunk yang benar (sesuai `expected_chunks` di dataset) muncul di top-K hasil retrieval. Range: 0 atau 1 per pertanyaan, di-mean across dataset.
- **Hit@8** → Hit pada **pre-rerank** (output langsung dari Qdrant top-8). Mengukur kualitas dense retrieval saja, sebelum rerank ikut campur.
- **Hit@4** → Hit pada **post-rerank** (top-4 yang akhirnya dilihat LLM). Mengukur kualitas keseluruhan pipeline.
- **MRR (Mean Reciprocal Rank)** → Mean dari `1/rank` posisi pertama chunk benar. Range 0..1; 1.0 = benar selalu di posisi #1, 0.5 = posisi #2, dst. Lebih informatif dari Hit karena memperhatikan urutan.
- **MRR@4** → MRR dihitung pada top-4 post-rerank. Jika tidak ada chunk benar di top-4, kontribusinya 0.
- **Rerank drop** → Diagnostik: bila `Hit@8 - Hit@4 > 0.15`, artinya reranker membuang chunk yang benar dari top-8 → top-4. Sinyal reranker over-aggressive atau model rerank kurang cocok.
- **Composite chunk key** → Tuple `(source, page, start_index)` — identifier unik untuk satu chunk. Dipakai membandingkan chunk retrieved vs expected.

### Observability

- **Langfuse** → Platform observability untuk LLM apps. Trace setiap call (LLM, tool, chain) dengan latency + token count + nested spans. Aktif kalau `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` di-set.
- **Callback handler** → LangChain mechanism untuk subscribe ke event eksekusi (start LLM, end tool, dll). Langfuse hook-nya mengirim trace ke server Langfuse.

### Backend / Frontend stack

- **HuggingFace Inference API** → Layanan HF untuk inference model di cloud (bukan self-host). Project ini pakai untuk: embeddings, LLM generation, dan rerank scoring.
- **ChatHuggingFace** → Wrapper LangChain di atas `HuggingFaceEndpoint` yang menambahkan dukungan `bind_tools` + chat format.
- **FastAPI** → Backend framework Python. Dipakai untuk `/chat` (SSE), `/admin/*` endpoints.
- **Next.js App Router** → Convention Next.js modern dengan file-based routing di `src/app/`. Project ini di Next.js 16.
- **`use client`** → Directive Next.js untuk menandai komponen yang harus dirender di browser (state, effects, fetch streaming).
