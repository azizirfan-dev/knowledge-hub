"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AdminHeader } from "../_components/AdminHeader";
import { ScoreBar } from "../_components/ScoreBar";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Kb = "hr" | "technical";

type RetrievedChunk = {
  source: string;
  page?: number;
  start_index: number;
  preview: string;
  similarity_score?: number;
  rerank_score?: number;
};

type ProbeResponse = {
  question: string;
  kb: Kb;
  retrieved_at_8: RetrievedChunk[];
  retrieved_at_4: RetrievedChunk[];
};

function chunkKey(c: RetrievedChunk) {
  return `${c.source}::${c.page ?? "_"}::${c.start_index}`;
}

export default function ProbePage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [kb, setKb] = useState<Kb>("hr");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ProbeResponse | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [savedMsg, setSavedMsg] = useState("");

  useEffect(() => {
    const role = sessionStorage.getItem("kb_role");
    if (role !== "Admin") router.push("/");
  }, [router]);

  async function runProbe() {
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setSavedMsg("");
    setApproved(new Set());
    setResult(null);
    try {
      const res = await fetch(`${API_URL}/admin/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim(), kb }),
      });
      if (!res.ok) throw new Error(`Probe failed: ${res.status}`);
      const data: ProbeResponse = await res.json();
      setResult(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function toggleApprove(c: RetrievedChunk) {
    const k = chunkKey(c);
    setApproved((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  async function saveLabel() {
    if (!result || approved.size === 0) return;
    setError("");
    setSavedMsg("");
    const allChunks = [...result.retrieved_at_8, ...result.retrieved_at_4];
    const seen = new Set<string>();
    const chunks = allChunks
      .filter((c) => {
        const k = chunkKey(c);
        if (!approved.has(k) || seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .map((c) => ({
        source: c.source,
        page: c.page,
        start_index: c.start_index,
        content_snippet: c.preview.slice(0, 80).trim(),
      }));
    try {
      const res = await fetch(`${API_URL}/admin/dataset/label`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: result.question,
          kb: result.kb,
          approved_chunks: chunks,
        }),
      });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      const data = await res.json();
      setSavedMsg(`Saved as ${data.id} (dataset now has ${data.total_entries} entries).`);
      setApproved(new Set());
    } catch (e) {
      setError(String(e));
    }
  }

  function renderChunk(c: RetrievedChunk, rank: number, scoreField: "similarity_score" | "rerank_score") {
    const k = chunkKey(c);
    const isApproved = approved.has(k);
    const score = c[scoreField];
    const scoreLabel = scoreField === "rerank_score" ? "rerank" : "similarity";
    return (
      <div
        key={k + "-" + rank}
        className={`neo-box-sm p-3 mb-2 ${isApproved ? "bg-green-100" : "bg-white"}`}
      >
        <div className="flex justify-between items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="font-black text-xs uppercase">
              #{rank} · {c.source}
            </div>
            <div className="text-xs font-mono text-gray-600 mt-1">
              page {c.page} · start {c.start_index}
            </div>
            {score !== undefined && (
              <div className="mt-2">
                <ScoreBar value={score} label={scoreLabel} />
              </div>
            )}
            <div className="text-sm mt-2 whitespace-pre-wrap">{c.preview}</div>
          </div>
          <button
            onClick={() => toggleApprove(c)}
            className={`shrink-0 neo-box-sm px-3 py-2 text-xs font-black uppercase cursor-pointer ${
              isApproved ? "bg-green-300" : "bg-white"
            }`}
            title="Tandai chunk ini sebagai jawaban yang benar"
          >
            {isApproved ? "✓ Approved" : "👍 Approve"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-5xl mx-auto">
        <AdminHeader
          title="Interactive Probe"
          subtitle="Ad-hoc retrieval + label chunks to grow the eval dataset"
        />

        <div className="mb-4">
          <button
            className="neo-btn bg-white text-xs font-black uppercase px-3 py-2"
            onClick={() => router.push("/admin")}
          >
            ← Back to Dashboard
          </button>
        </div>

        {/* Score legend */}
        <div className="neo-box-sm bg-white p-3 mb-6 text-xs font-medium leading-relaxed">
          <strong className="font-black uppercase tracking-widest">
            Cara Membaca Skor ·
          </strong>{" "}
          Cosine similarity, range 0–1, <strong>↑ semakin tinggi semakin relevan</strong>.
          <span className="inline-flex items-center gap-3 ml-2 flex-wrap">
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-red-400 border border-black" />
              &lt; 0.3 lemah
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-yellow-300 border border-black" />
              0.3–0.5 sedang
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-green-400 border border-black" />
              ≥ 0.5 kuat
            </span>
          </span>
          <div className="mt-1 text-gray-600">
            <strong>similarity</strong> = Qdrant cosine (pre-rerank) ·{" "}
            <strong>rerank</strong> = HF sentence-similarity (post-rerank).
            Approve chunk yang benar-benar menjawab pertanyaan — skor hanya petunjuk, bukan patokan otomatis.
          </div>
        </div>

        {/* Query form */}
        <div className="neo-box bg-white p-4 mb-6">
          <label className="block text-xs font-black uppercase tracking-widest mb-2">
            Question
          </label>
          <textarea
            className="neo-input w-full mb-3"
            rows={2}
            placeholder="e.g. Berapa hari cuti tahunan karyawan tetap?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs font-black uppercase">KB:</label>
            {(["hr", "technical"] as Kb[]).map((k) => (
              <button
                key={k}
                className={`neo-box-sm px-3 py-2 text-xs font-black uppercase cursor-pointer ${
                  kb === k ? "bg-[#FFD700]" : "bg-white"
                }`}
                onClick={() => setKb(k)}
              >
                {k}
              </button>
            ))}
            <button
              className="neo-btn font-black uppercase px-6 py-2 ml-auto"
              disabled={loading || !question.trim()}
              onClick={runProbe}
            >
              {loading ? "Retrieving…" : "Retrieve →"}
            </button>
          </div>
        </div>

        {error && (
          <div className="neo-box bg-red-50 p-3 mb-4 text-sm font-bold text-red-700">
            {error}
          </div>
        )}
        {savedMsg && (
          <div className="neo-box bg-green-50 p-3 mb-4 text-sm font-bold text-green-800">
            {savedMsg}
          </div>
        )}

        {result && (
          <>
            {/* Save action bar */}
            <div className="neo-box bg-white p-3 mb-4 flex justify-between items-center flex-wrap gap-2">
              <div className="text-xs font-bold">
                {approved.size} chunk(s) approved — approve chunks that correctly
                answer the question, then save as a labeled dataset entry.
              </div>
              <button
                className="neo-btn font-black uppercase px-4 py-2"
                disabled={approved.size === 0}
                onClick={saveLabel}
              >
                Save to Dataset
              </button>
            </div>

            {/* Top 4 post-rerank */}
            <div className="neo-box bg-white p-4 mb-4">
              <h2 className="font-black uppercase text-sm tracking-widest mb-3">
                Top 4 · Post-Rerank (sampai ke LLM)
              </h2>
              {result.retrieved_at_4.map((c, i) => renderChunk(c, i + 1, "rerank_score"))}
            </div>

            {/* Pre-rerank */}
            <details className="neo-box bg-white p-4">
              <summary className="font-black uppercase text-sm tracking-widest cursor-pointer">
                Pre-Rerank Top 8 (raw Qdrant)
              </summary>
              <div className="mt-3">
                {result.retrieved_at_8.map((c, i) =>
                  renderChunk(c, i + 1, "similarity_score"),
                )}
              </div>
            </details>
          </>
        )}
      </div>
    </main>
  );
}
