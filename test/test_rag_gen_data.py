"""
Dify API 数据生成脚本 — 生成 RAGAS 评估数据集。

调用 /chat-messages 端点（与 llm_engine.py 同一个 Dify 应用），
生成 answer + contexts，保存为 ragas_dataset.json 供 test_ragas_minimal.py 使用。

Usage:
  cd /mnt/e/workspace/ppt_ai_automation
  python -m test.test_ragas_eval
"""
import asyncio
import json
import os
import sys
import time
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import requests

# ── Config ────────────────────────────────────────────────────────────────────
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "").rstrip("/")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
GROUND_TRUTH_PATH = os.path.join(TEST_DIR, "ground_truth_reports.json")
OUTPUT_PATH = os.path.join(TEST_DIR, "ragas_dataset.json")

# Maximum concurrent Dify API calls
MAX_CONCURRENCY = 3

# Section type → prompt template mapping（key 与 ground_truth_reports.json 的 sections 一致）
SECTION_PROMPT_TEMPLATES: dict[str, str] = {
    "問題分析": (
        "针对以下异常问题，请进行製程排查分析。\n\n"
        "【基本信息】\n"
        "档案名：{檔案名}\n"
        "iPad机型：{iPad機型}\n"
        "Build阶段：{Build}\n"
        "iPad机种：{iPad機種}\n"
        "製程：{製程}\n"
        "报告人：{報告人}\n"
        "关键字：{關鍵字}\n\n"
        "【问题描述】\n{problem_description}\n\n"
        "【输出要求】\n"
        "1. 列出製程排查步骤和结果\n"
        "2. 包含具体数据（机台号、批次、数量等）\n"
        "3. 不超过200字"
    ),
    "根本原因": (
        "针对以下异常问题，请分析根本原因。\n\n"
        "【基本信息】\n"
        "档案名：{檔案名}\n"
        "iPad机型：{iPad機型}\n"
        "Build阶段：{Build}\n"
        "iPad机种：{iPad機種}\n"
        "製程：{製程}\n"
        "报告人：{報告人}\n"
        "关键字：{關鍵字}\n\n"
        "【问题描述】\n{problem_description}\n\n"
        "【输出要求】\n"
        "1. 使用5Why分析法\n"
        "2. 区分直接原因和根本原因\n"
        "3. 包含具体的设备、刀具、参数信息\n"
        "4. 不超过200字"
    ),
    "圍堵措施": (
        "针对以下异常问题，请制定围堵措施。\n\n"
        "【基本信息】\n"
        "档案名：{檔案名}\n"
        "iPad机型：{iPad機型}\n"
        "Build阶段：{Build}\n"
        "iPad机种：{iPad機種}\n"
        "製程：{製程}\n"
        "报告人：{報告人}\n"
        "关键字：{關鍵字}\n\n"
        "【问题描述】\n{problem_description}\n\n"
        "【输出要求】\n"
        "1. 客户端和厂内两端围堵\n"
        "2. 明确数量、方式、结果\n"
        "3. 不超过200字"
    ),
    "改善對策": (
        "针对以下异常问题，请制定改善对策。\n\n"
        "【基本信息】\n"
        "档案名：{檔案名}\n"
        "iPad机型：{iPad機型}\n"
        "Build阶段：{Build}\n"
        "iPad机种：{iPad機種}\n"
        "製程：{製程}\n"
        "报告人：{報告人}\n"
        "关键字：{關鍵字}\n\n"
        "【问题描述】\n{problem_description}\n\n"
        "【输出要求】\n"
        "1. 製程改善措施（具体设备/治具变更）\n"
        "2. 检验改善措施（新增/强化检测工站）\n"
        "3. 不超过200字"
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
#  Module 1: Data Loading
# ══════════════════════════════════════════════════════════════════════════════

def load_ground_truth(path: str) -> list[dict]:
    """Load ground truth reports from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"[INFO] Loaded {len(data)} ground truth reports from {path}")
    return data


# ══════════════════════════════════════════════════════════════════════════════
#  Module 2: Dify Chat API Call
# ══════════════════════════════════════════════════════════════════════════════

RAGAS_SPLITTER = "===RAGAS_SPLITTER==="


def _call_dify_chat(prompt: str) -> dict[str, Any]:
    """
    调用 Dify Chatflow API（/chat-messages），与 llm_engine.py 使用同一个端点。

    Returns:
        {
            "answer": str,          # LLM 生成内容（分隔符前半段）
            "contexts": list[str],  # 检索命中的知识片段（分隔符后半段）
            "raw": dict
        }
    """
    url = f"{DIFY_BASE_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "inputs": {},
        "query": prompt,
        "response_mode": "blocking",
        "user": "ragas-eval-user",
    }

    resp = requests.post(url, headers=headers, json=body, timeout=300)
    resp.raise_for_status()
    data = resp.json()

    raw_text = data.get("answer", "")

    if RAGAS_SPLITTER in raw_text:
        parts = raw_text.split(RAGAS_SPLITTER, 1)
        answer = parts[0].strip()
        raw_contexts = parts[1].strip()
    else:
        answer = raw_text.strip()
        raw_contexts = ""

    contexts: list[str] = []
    if raw_contexts:
        chunks = [c.strip() for c in raw_contexts.split("\n\n") if c.strip()]
        if len(chunks) <= 1:
            chunks = [c.strip() for c in raw_contexts.split("\n") if c.strip()]
        if len(chunks) <= 1:
            chunks = [raw_contexts]
        contexts = chunks

    if not contexts:
        contexts = [answer]

    return {"answer": answer, "contexts": contexts, "raw": data}


async def generate_section(
    metadata: dict,
    problem_description: str,
    section_type: str,
) -> dict[str, Any]:
    """Build prompt, call Dify API, return result."""
    template = SECTION_PROMPT_TEMPLATES.get(section_type)
    if not template:
        return {
            "section_type": section_type,
            "prompt": "",
            "answer": "",
            "contexts": [],
            "error": f"No prompt template for section type: {section_type}",
            "elapsed_sec": 0,
        }

    prompt = template.format(problem_description=problem_description, **metadata)

    start = time.time()
    try:
        result = await asyncio.to_thread(_call_dify_chat, prompt)
        return {
            "section_type": section_type,
            "prompt": prompt,
            "answer": result["answer"],
            "contexts": result["contexts"],
            "error": None,
            "elapsed_sec": round(time.time() - start, 2),
        }
    except requests.exceptions.HTTPError as e:
        error_body = e.response.text[:300] if e.response else str(e)
        return {
            "section_type": section_type,
            "prompt": prompt,
            "answer": "",
            "contexts": [],
            "error": f"HTTP {e.response.status_code if e.response else '?'}: {error_body}",
            "elapsed_sec": round(time.time() - start, 2),
        }
    except Exception as e:
        return {
            "section_type": section_type,
            "prompt": prompt,
            "answer": "",
            "contexts": [],
            "error": str(e)[:300],
            "elapsed_sec": round(time.time() - start, 2),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Module 3: Concurrent Dify Calls
# ══════════════════════════════════════════════════════════════════════════════

async def generate_all_sections(
    reports: list[dict],
) -> dict[tuple[str, str], dict]:
    """Call Dify API for all report × section combinations."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    total_tasks = sum(len(r["sections"]) for r in reports)
    print(f"\n[INFO] Generating {total_tasks} sections across {len(reports)} reports (concurrency={MAX_CONCURRENCY})")

    async def _guarded_call(report_id: str, section_type: str, report: dict) -> tuple[str, str, dict]:
        async with semaphore:
            result = await generate_section(
                metadata=report["metadata"],
                problem_description=report["problem_description"],
                section_type=section_type,
            )
            return (report_id, section_type, result)

    tasks = []
    for report in reports:
        for section_type in report["sections"]:
            tasks.append(_guarded_call(report["report_id"], section_type, report))

    results: dict[tuple[str, str], dict] = {}
    completed = 0
    for coro in asyncio.as_completed(tasks):
        report_id, section_type, result = await coro
        completed += 1
        status = "OK" if not result["error"] else "FAIL"
        print(f"  [{completed}/{total_tasks}] [{status}] {report_id}/{section_type} ({result['elapsed_sec']}s)")
        results[(report_id, section_type)] = result

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  Module 4: Build & Save RAGAS Dataset
# ══════════════════════════════════════════════════════════════════════════════

def build_and_save_dataset(
    reports: list[dict],
    generated_results: dict[tuple[str, str], dict],
    output_path: str,
) -> list[dict]:
    """
    Build RAGAS dataset rows and save to JSON.

    Each row: { question, contexts, answer, ground_truth, report_id, section_type }
    """
    rows = []

    for report in reports:
        for section_type, ground_truth_text in report["sections"].items():
            gen = generated_results[(report["report_id"], section_type)]

            if gen["error"] or not gen["answer"]:
                print(f"  [SKIP] {report['report_id']}/{section_type}: {gen['error'] or 'empty answer'}")
                continue

            rows.append({
                "question": gen["prompt"],
                "contexts": gen["contexts"],
                "answer": gen["answer"],
                "ground_truth": ground_truth_text,
                "report_id": report["report_id"],
                "section_type": section_type,
            })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"\n[INFO] Saved {len(rows)} valid samples to: {output_path}")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════

async def run_generation():
    """Generate RAGAS dataset from Dify API."""
    print("=" * 80)
    print("RAGAS Dataset Generator (Dify Chatflow API)")
    print("=" * 80)

    if not DIFY_API_KEY or not DIFY_BASE_URL:
        print("[ERROR] DIFY_API_KEY and DIFY_BASE_URL must be set in .env")
        sys.exit(1)

    if not os.path.exists(GROUND_TRUTH_PATH):
        print(f"[ERROR] Ground truth file not found: {GROUND_TRUTH_PATH}")
        sys.exit(1)

    # Step 1: Load ground truth
    reports = load_ground_truth(GROUND_TRUTH_PATH)

    # Step 2: Call Dify API
    generated_results = await generate_all_sections(reports)

    # Step 3: Build and save dataset
    rows = build_and_save_dataset(reports, generated_results, OUTPUT_PATH)

    if len(rows) == 0:
        print("[ERROR] No valid samples generated. Check API responses.")
        sys.exit(1)

    print("\n[DONE] Dataset generation complete.")
    print(f"[NEXT] Run: python -m test.test_ragas_minimal")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_generation())
    finally:
        loop.close()
