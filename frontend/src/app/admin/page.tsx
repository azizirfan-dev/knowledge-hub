"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AdminHeader } from "./_components/AdminHeader";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Aggregate = {
  n: number;
  hit_at_4: number;
  hit_at_8: number;
  mrr_at_4: number;
};

type GroupRow = Aggregate & { kb: string; type: string };

type ExpectedChunk = {
  source: string;
  page?: number;
  start_index: number;
  content_snippet?: string;
};

type RetrievedChunk = {
  source: string;
  page?: number;
  start_index: number;
  preview: string;
  similarity_score?: number;
  rerank_score?: number;
};

type PerQuestion = {
  id: string;
  question: string;
  kb: string;
  type: string;
  expected: ExpectedChunk[];
  retrieved_at_4: RetrievedChunk[];
  retrieved_at_8: RetrievedChunk[];
  hit_at_4: boolean;
  hit_at_8: boolean;
  rank_in_post4: number | null;
  snippet_warnings: string[];
};

type EvalResults = {
  run_timestamp?: string;
  dataset_size?: number;
  aggregate?: Aggregate;
  by_group?: GroupRow[];
  per_question?: PerQuestion[];
  status?: "empty";
};

function pct(x: number) {
  return `${(x * 100).toFixed(1)}%`;
}

function MetricCard({
  label,
  value,
  description,
  interpretation,
}: {
  label: string;
  value: string;
  description: string;
  interpretation: string;
}) {
  return (
    <div className="neo-box bg-white p-6 flex-1 min-w-[220px]">
      <div className="text-xs font-black uppercase tracking-widest text-gray-500">
        {label}
      </div>
      <div className="text-4xl font-black mt-2">{value}</div>
      <div className="text-xs font-bold text-gray-700 mt-2 leading-snug">
        {description}
      </div>
      <div className="text-[11px] font-medium text-gray-500 mt-1 italic leading-snug">
        {interpretation}
      </div>
    </div>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const [results, setResults] = useState<EvalResults | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ i: number; total: number; current: string } | null>(null);
  const [filter, setFilter] = useState<"all" | "failures">("all");
  const [error, setError] = useState("");

  useEffect(() => {
    const role = sessionStorage.getItem("kb_role");
    if (role !== "Admin") {
      router.push("/");
    }
  }, [router]);

  const loadResults = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/admin/eval/results`);
      const data: EvalResults = await r.json();
      setResults(data);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    loadResults();
  }, [loadResults]);

  async function runEval() {
    setRunning(true);
    setError("");
    setProgress({ i: 0, total: 0, current: "" });
    try {
      const res = await fetch(`${API_URL}/admin/eval/run`, { method: "POST" });
      if (!res.ok || !res.body) {
        throw new Error(`Run failed: ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const payload = JSON.parse(line.slice(5).trim());
          if (payload.done) {
            continue;
          }
          setProgress({ i: payload.progress ?? 0, total: payload.total ?? 0, current: payload.current ?? "" });
        }
      }
      await loadResults();
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
      setProgress(null);
    }
  }

  const hasResults = results && results.status !== "empty" && results.aggregate;
  const visibleQuestions = (results?.per_question ?? []).filter((q) =>
    filter === "failures" ? !q.hit_at_4 : true,
  );

  return (
    <main className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto">
        <AdminHeader
          title="Admin Dashboard"
          subtitle="RAG Retrieval Performance Monitor"
        />

        {/* Actions */}
        <div className="flex items-center gap-4 mb-6 flex-wrap">
          <button
            className="neo-btn font-black uppercase tracking-wider px-6 py-3"
            onClick={runEval}
            disabled={running}
          >
            {running ? "Running…" : "Run Evaluation"}
          </button>
          <button
            className="neo-btn bg-white font-black uppercase tracking-wider px-6 py-3"
            onClick={() => router.push("/admin/probe")}
            disabled={running}
          >
            Interactive Probe →
          </button>
          {results?.run_timestamp && (
            <span className="text-xs font-bold text-gray-600">
              Last run: {new Date(results.run_timestamp).toLocaleString()}
            </span>
          )}
        </div>

        {/* Progress */}
        {running && progress && (
          <div className="neo-box bg-white p-4 mb-6">
            <div className="flex justify-between text-xs font-black uppercase mb-2">
              <span>Evaluating</span>
              <span>
                {progress.i} / {progress.total || "?"}
              </span>
            </div>
            <div className="h-3 bg-gray-200 border-2 border-black">
              <div
                className="h-full bg-[#FFD700] transition-all"
                style={{
                  width: progress.total ? `${(progress.i / progress.total) * 100}%` : "0%",
                }}
              />
            </div>
            {progress.current && (
              <div className="text-xs font-medium text-gray-600 mt-2 truncate">
                → {progress.current}
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="neo-box bg-red-50 p-3 mb-6 text-sm font-bold text-red-700">
            {error}
          </div>
        )}

        {!hasResults && !running && (
          <div className="neo-box bg-white p-8 text-center">
            <p className="font-bold">No evaluation results yet.</p>
            <p className="text-sm text-gray-600 mt-2">
              Click <strong>Run Evaluation</strong> to evaluate the current dataset.
            </p>
          </div>
        )}

        {hasResults && results.aggregate && (
          <>
            {/* Metric legend */}
            <div className="neo-box-sm bg-white p-3 mb-4 text-xs font-medium leading-relaxed">
              <strong className="font-black uppercase tracking-widest">
                Cara Membaca ·
              </strong>{" "}
              Semua metrik: <strong>↑ semakin tinggi semakin bagus</strong>.
              Dari 50 pertanyaan evaluasi, masing-masing dicek apakah chunk yang
              <em> seharusnya</em> muncul (ground truth) benar-benar diambil oleh
              sistem.
            </div>

            {/* Aggregate cards */}
            <div className="flex gap-4 mb-6 flex-wrap">
              <MetricCard
                label="Hit@4 (post-rerank)"
                value={pct(results.aggregate.hit_at_4)}
                description="% pertanyaan yang chunk benar-nya lolos ke top-4 setelah reranking — inilah yang dilihat LLM."
                interpretation="Target: ≥ 80%. Rendah = LLM sering dapat konteks salah."
              />
              <MetricCard
                label="Hit@8 (pre-rerank)"
                value={pct(results.aggregate.hit_at_8)}
                description="% pertanyaan yang chunk benar-nya ada di top-8 dari Qdrant (sebelum reranking)."
                interpretation="Rendah = masalah retrieval dasar (embedding/chunk)."
              />
              <MetricCard
                label="MRR@4"
                value={results.aggregate.mrr_at_4.toFixed(3)}
                description="Mean Reciprocal Rank: rata-rata 1/posisi chunk benar di top-4."
                interpretation="1.000 = selalu posisi #1. 0.250 = rata-rata di posisi #4."
              />
              <MetricCard
                label="Dataset Size"
                value={String(results.aggregate.n)}
                description="Jumlah pertanyaan di dataset evaluasi."
                interpretation="Gabungan synthetic + labeled (via Interactive Probe)."
              />
            </div>

            {/* Diagnostic insight */}
            {(() => {
              const gap =
                results.aggregate!.hit_at_8 - results.aggregate!.hit_at_4;
              if (gap > 0.15) {
                return (
                  <div className="neo-box-sm bg-yellow-100 p-3 mb-6 text-xs font-medium">
                    ⚠ <strong>Rerank drop terdeteksi:</strong> Hit@8 ({pct(results.aggregate!.hit_at_8)})
                    jauh lebih tinggi dari Hit@4 ({pct(results.aggregate!.hit_at_4)}).
                    Reranker membuang chunk yang benar — periksa model rerank atau threshold-nya.
                  </div>
                );
              }
              return null;
            })()}

            {/* Breakdown */}
            <div className="neo-box bg-white p-4 mb-6">
              <h2 className="font-black uppercase text-sm tracking-widest mb-3">
                Breakdown by KB × Type
              </h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b-2 border-black text-left">
                    <th className="p-2 font-black uppercase text-xs">KB</th>
                    <th className="p-2 font-black uppercase text-xs">Type</th>
                    <th className="p-2 font-black uppercase text-xs">N</th>
                    <th className="p-2 font-black uppercase text-xs">Hit@4</th>
                    <th className="p-2 font-black uppercase text-xs">Hit@8</th>
                    <th className="p-2 font-black uppercase text-xs">MRR@4</th>
                  </tr>
                </thead>
                <tbody>
                  {results.by_group?.map((g, idx) => (
                    <tr key={idx} className="border-b border-gray-200">
                      <td className="p-2 font-bold">{g.kb}</td>
                      <td className="p-2">{g.type}</td>
                      <td className="p-2">{g.n}</td>
                      <td className="p-2">{pct(g.hit_at_4)}</td>
                      <td className="p-2">{pct(g.hit_at_8)}</td>
                      <td className="p-2">{g.mrr_at_4.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Drill-down */}
            <div className="neo-box bg-white p-4">
              <div className="flex justify-between items-center mb-3 flex-wrap gap-2">
                <h2 className="font-black uppercase text-sm tracking-widest">
                  Per-Question Results
                </h2>
                <div className="flex gap-2">
                  <button
                    className={`neo-box-sm px-3 py-1 text-xs font-black uppercase cursor-pointer ${
                      filter === "all" ? "bg-[#FFD700]" : "bg-white"
                    }`}
                    onClick={() => setFilter("all")}
                  >
                    All ({results.per_question?.length ?? 0})
                  </button>
                  <button
                    className={`neo-box-sm px-3 py-1 text-xs font-black uppercase cursor-pointer ${
                      filter === "failures" ? "bg-[#FFD700]" : "bg-white"
                    }`}
                    onClick={() => setFilter("failures")}
                  >
                    Failures only (
                    {(results.per_question ?? []).filter((q) => !q.hit_at_4).length})
                  </button>
                </div>
              </div>

              <div className="flex flex-col gap-3">
                {visibleQuestions.map((q) => (
                  <details
                    key={q.id}
                    className={`neo-box-sm p-3 ${
                      q.hit_at_4 ? "bg-white" : "bg-red-50"
                    }`}
                  >
                    <summary className="cursor-pointer flex justify-between items-center gap-3">
                      <div className="flex-1">
                        <div className="font-bold text-sm">{q.question}</div>
                        <div className="text-xs text-gray-600 font-mono mt-1">
                          {q.id} · {q.kb} · {q.type}
                        </div>
                      </div>
                      <div className="flex gap-2 items-center shrink-0">
                        <span
                          className={`text-xs font-black px-2 py-1 border-2 border-black ${
                            q.hit_at_4 ? "bg-green-200" : "bg-red-200"
                          }`}
                        >
                          H@4: {q.hit_at_4 ? "✓" : "✗"}
                        </span>
                        <span className="text-xs font-black px-2 py-1 border-2 border-black bg-white">
                          H@8: {q.hit_at_8 ? "✓" : "✗"}
                        </span>
                        <span className="text-xs font-black px-2 py-1 border-2 border-black bg-white">
                          rank: {q.rank_in_post4 ?? "—"}
                        </span>
                      </div>
                    </summary>
                    <div className="mt-3 text-xs grid md:grid-cols-2 gap-3">
                      <div>
                        <div className="font-black uppercase mb-1">Expected</div>
                        {q.expected.map((e, i) => (
                          <div key={i} className="font-mono text-xs bg-gray-100 p-2 mb-1">
                            {e.source} · page {e.page} · start {e.start_index}
                            {e.content_snippet && (
                              <div className="text-gray-600 mt-1">“{e.content_snippet}”</div>
                            )}
                          </div>
                        ))}
                      </div>
                      <div>
                        <div className="font-black uppercase mb-1">
                          Retrieved (top 4, post-rerank)
                        </div>
                        {q.retrieved_at_4.map((r, i) => {
                          const isHit = q.expected.some(
                            (e) =>
                              e.source === r.source &&
                              e.page === r.page &&
                              e.start_index === r.start_index,
                          );
                          return (
                            <div
                              key={i}
                              className={`font-mono text-xs p-2 mb-1 ${
                                isHit ? "bg-green-100" : "bg-gray-100"
                              }`}
                            >
                              #{i + 1} · {r.source} · page {r.page} · start {r.start_index}
                              {r.rerank_score !== undefined && (
                                <span className="ml-2 text-gray-600">
                                  score {r.rerank_score.toFixed(3)}
                                </span>
                              )}
                              <div className="text-gray-600 mt-1 font-sans">
                                {r.preview.slice(0, 120)}…
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    {q.snippet_warnings.length > 0 && (
                      <div className="mt-2 text-xs bg-yellow-100 border-2 border-black p-2">
                        ⚠ {q.snippet_warnings.join("; ")}
                      </div>
                    )}
                  </details>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
