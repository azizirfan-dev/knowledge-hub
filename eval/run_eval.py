"""
Batch retrieval evaluation runner.

Compares retrieval output (pre & post rerank) against ground truth chunks
in eval/dataset.json and writes aggregate + per-question results to
eval/results.json.

Metrics:
  - Hit@8 (pre-rerank): did any expected chunk appear in top-8 from Qdrant?
  - Hit@4 (post-rerank): did any expected chunk survive rerank to top-4?
  - MRR@4: mean reciprocal rank of the first correct chunk in post-rerank top-4

Composite chunk key: (source, page, start_index)

Usage:
  CLI:      python -m eval.run_eval
  Library:  from eval.run_eval import run; run(progress_cb=...)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv

load_dotenv()

from src.tools.rag_tool import retrieve_with_scores

EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "dataset.json"
RESULTS_PATH = EVAL_DIR / "results.json"

KB_COLLECTION_ENV = {
    "hr": ("QDRANT_COLLECTION_HR", "kb_hr"),
    "technical": ("QDRANT_COLLECTION_TECHNICAL", "kb_technical"),
}


def _collection_for(kb: str) -> str:
    env_var, default = KB_COLLECTION_ENV[kb]
    return os.getenv(env_var, default)


def _chunk_key(meta: dict) -> tuple:
    return (meta.get("source"), meta.get("page"), meta.get("start_index"))


def _doc_summary(score: float, doc, score_field: str) -> dict:
    m = doc.metadata
    return {
        "source": m.get("source"),
        "page": m.get("page"),
        "start_index": m.get("start_index"),
        "preview": doc.page_content[:200],
        score_field: score,
    }


def evaluate_question(q: dict) -> dict:
    collection = _collection_for(q["kb"])
    pre, post = retrieve_with_scores(collection, q["question"])

    expected_keys = {
        (c["source"], c.get("page"), c["start_index"]) for c in q["expected_chunks"]
    }

    pre_keys = [_chunk_key(d.metadata) for _, d in pre]
    post_keys = [_chunk_key(d.metadata) for _, d in post]

    hit_at_8 = any(k in expected_keys for k in pre_keys)
    hit_at_4 = any(k in expected_keys for k in post_keys)
    rank_in_post = next(
        (i + 1 for i, k in enumerate(post_keys) if k in expected_keys), None
    )

    # Snippet sanity check (dataset staleness warning)
    snippet_warnings = []
    for c in q["expected_chunks"]:
        snippet = c.get("content_snippet")
        if not snippet:
            continue
        key = (c["source"], c.get("page"), c["start_index"])
        matching = next(
            (d for _, d in pre if _chunk_key(d.metadata) == key), None
        )
        if matching and snippet not in matching.page_content:
            snippet_warnings.append(
                f"snippet not found in chunk {key}: {snippet!r}"
            )

    return {
        "id": q["id"],
        "question": q["question"],
        "kb": q["kb"],
        "type": q["type"],
        "expected": q["expected_chunks"],
        "retrieved_at_8": [_doc_summary(s, d, "similarity_score") for s, d in pre],
        "retrieved_at_4": [_doc_summary(s, d, "rerank_score") for s, d in post],
        "hit_at_8": hit_at_8,
        "hit_at_4": hit_at_4,
        "rank_in_post4": rank_in_post,
        "snippet_warnings": snippet_warnings,
    }


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _metrics(rows):
    hit4 = [1.0 if r["hit_at_4"] else 0.0 for r in rows]
    hit8 = [1.0 if r["hit_at_8"] else 0.0 for r in rows]
    mrr = [1.0 / r["rank_in_post4"] if r["rank_in_post4"] else 0.0 for r in rows]
    return {
        "hit_at_4": _mean(hit4),
        "hit_at_8": _mean(hit8),
        "mrr_at_4": _mean(mrr),
    }


def aggregate(per_question: list) -> dict:
    overall = _metrics(per_question)
    overall["n"] = len(per_question)

    groups: dict = {}
    for r in per_question:
        groups.setdefault((r["kb"], r["type"]), []).append(r)

    by_group = []
    for (kb, t), items in sorted(groups.items()):
        m = _metrics(items)
        m.update({"kb": kb, "type": t, "n": len(items)})
        by_group.append(m)

    return {"aggregate": overall, "by_group": by_group}


def run(
    dataset_path: Path = DATASET_PATH,
    results_path: Path = RESULTS_PATH,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    questions = dataset["questions"]
    per_q = []
    for i, q in enumerate(questions):
        if progress_cb:
            progress_cb(i, len(questions), q["question"])
        per_q.append(evaluate_question(q))

    agg = aggregate(per_q)
    output = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_size": len(questions),
        **agg,
        "per_question": per_q,
    }

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output


if __name__ == "__main__":
    def _cli_progress(i, total, question):
        print(f"  [{i+1}/{total}] {question[:60]}...")

    result = run(progress_cb=_cli_progress)
    a = result["aggregate"]
    print("\n=== Summary ===")
    print(f"N      : {a['n']}")
    print(f"Hit@4  : {a['hit_at_4']:.1%}")
    print(f"Hit@8  : {a['hit_at_8']:.1%}")
    print(f"MRR@4  : {a['mrr_at_4']:.3f}")
    print("\n=== By group ===")
    for g in result["by_group"]:
        print(
            f"  [{g['kb']}/{g['type']}] n={g['n']} "
            f"H@4={g['hit_at_4']:.1%} H@8={g['hit_at_8']:.1%} MRR={g['mrr_at_4']:.3f}"
        )
