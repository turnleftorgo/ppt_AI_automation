"""
RAGAS 评估脚本 — 加载 ragas_dataset.json，运行 context_recall + answer_correctness 评估。

前置步骤: 先运行 test_ragas_eval.py 生成 ragas_dataset.json

Usage:
  cd /mnt/e/workspace/ppt_ai_automation
  python -m test.test_ragas_minimal
"""
import asyncio
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from datasets import Dataset
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import evaluate
from ragas.metrics import context_recall, answer_correctness

# ── patch nest_asyncio（必须在 ragas import 之后）────────────────────────────
import nest_asyncio
def _safe_run(coro, **kwargs):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
asyncio.run = _safe_run

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
MODEL = os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.2")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(TEST_DIR, "ragas_dataset.json")
OUTPUT_PATH = os.path.join(TEST_DIR, "ragas_results.json")


def load_dataset(path: str) -> Dataset:
    """Load RAGAS dataset from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    print(f"[INFO] Loaded {len(rows)} samples from {path}")

    return Dataset.from_dict({
        "question": [r["question"] for r in rows],
        "contexts": [r["contexts"] for r in rows],
        "answer": [r["answer"] for r in rows],
        "ground_truth": [r["ground_truth"] for r in rows],
    }), rows


def run_evaluation(dataset: Dataset) -> dict:
    """Run RAGAS evaluation and return scores."""
    print(f"\n[INFO] Running RAGAS evaluation...")
    print(f"  Metrics: context_recall, answer_correctness")
    print(f"  LLM: {MODEL} @ {BASE_URL}")
    print(f"  Embeddings: BAAI/bge-m3 @ {BASE_URL}")

    llm = ChatOpenAI(
        model=MODEL,
        openai_api_key=API_KEY,
        openai_api_base=BASE_URL,
        temperature=0.0,
    )

    embeddings = OpenAIEmbeddings(
        model="BAAI/bge-m3",
        openai_api_key=API_KEY,
        openai_api_base=BASE_URL,
    )

    result = evaluate(
        dataset=dataset,
        metrics=[context_recall, answer_correctness],
        llm=llm,
        embeddings=embeddings,
    )

    # Extract per-sample scores
    per_sample = []
    for i in range(len(dataset)):
        per_sample.append({
            "context_recall": result["context_recall"][i] if result["context_recall"] else None,
            "answer_correctness": result["answer_correctness"][i] if result["answer_correctness"] else None,
        })

    # Calculate averages
    cr_scores = [s["context_recall"] for s in per_sample if s["context_recall"] is not None]
    ac_scores = [s["answer_correctness"] for s in per_sample if s["answer_correctness"] is not None]

    summary = {
        "context_recall": round(sum(cr_scores) / len(cr_scores), 4) if cr_scores else 0,
        "answer_correctness": round(sum(ac_scores) / len(ac_scores), 4) if ac_scores else 0,
    }

    return {"summary": summary, "per_sample": per_sample}


def save_report(rows: list[dict], scores: dict, output_path: str):
    """Save evaluation report to JSON."""
    # Merge scores into rows
    for i, row in enumerate(rows):
        if i < len(scores["per_sample"]):
            row["scores"] = scores["per_sample"][i]

    output = {
        "total_samples": len(rows),
        "summary": scores["summary"],
        "results": rows,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] Report saved to: {output_path}")

    # Print summary table
    print("\n" + "=" * 90)
    print("EVALUATION SUMMARY")
    print("=" * 90)
    print(f"\n{'Report ID':<30} {'Section':<25} {'Context Recall':>15} {'Answer Correctness':>20}")
    print("-" * 90)

    for row in rows:
        scores_data = row.get("scores", {})
        cr = scores_data.get("context_recall")
        ac = scores_data.get("answer_correctness")
        cr_str = f"{cr:.4f}" if cr is not None else "N/A"
        ac_str = f"{ac:.4f}" if ac is not None else "N/A"
        print(f"{row.get('report_id', '?'):<30} {row.get('section_type', '?'):<25} {cr_str:>15} {ac_str:>20}")

    print("-" * 90)
    print(f"{'OVERALL':<56} {scores['summary']['context_recall']:>15.4f} {scores['summary']['answer_correctness']:>20.4f}")
    print("=" * 90)


if __name__ == "__main__":
    print("=" * 80)
    print("RAGAS Evaluation — context_recall + answer_correctness")
    print("=" * 80)

    if not API_KEY:
        print("[ERROR] SILICONFLOW_API_KEY must be set in .env")
        sys.exit(1)

    if not os.path.exists(DATASET_PATH):
        print(f"[ERROR] Dataset not found: {DATASET_PATH}")
        print("[HINT] Run first: python -m test.test_ragas_eval")
        sys.exit(1)

    # Load dataset
    dataset, rows = load_dataset(DATASET_PATH)

    # Run evaluation
    scores = run_evaluation(dataset)

    # Save report
    save_report(rows, scores, OUTPUT_PATH)

    print("\n[DONE]")
