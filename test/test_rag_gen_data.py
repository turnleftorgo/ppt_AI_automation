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
        # ── 全局设定与格式 ──────────────────────────────────────────────────
        "你是FACA报告智能推测专家，根据用户提供的机型和不良现象，推测可能的根因和对策。\n\n"
        "## 推测逻辑\n\n"
        "### 输入信息\n"
        "用户会提供：\n"
        "1. 机型（如J70x、J48x等）\n"
        "2. 不良现象（如磁铁偏位、漏铣等）\n"
        "3. 制程（如组装Assy、金加CNC等）\n\n"
        "### 推测输出\n"
        "根据【机型+不良现象】匹配历史案例，输出常见的排查维度：\n"
        "- 物料排查：供应商、批次\n"
        "- SN追溯：生产日期、线体、机台\n"
        "- 制程排查：机台状态、治具、刀具\n"
        "- 首件记录：检验结果\n\n"
        "## 输出格式要求\n\n"
        "每个部分必须按【推理输出】的结构进行最终输出，不要有多余的内容：\n"
        "以下是推理示例和参考分析，请先学习推理方式和输出风格，再处理最后的待处理信息。\n\n"
        "---\n\n"
        # ── 推理示例库 (Few-Shot) ─────────────────────────────────────────────
        "## 推理示例\n\n"
        "【示例 1】\n"
        "【输入信息】\n"
        "机型：J70x\n"
        "不良现象：C4 鱼塘磁铁夹异物\n"
        "制程：组装(Assy)\n\n"
        "【推理逻辑 (CoT)】\n"
        "拆解现象：发现磁铁夹异物，拆机确认为磁铁残缺块，初步判定为来料不良或料盘周转损伤。\n"
        "追溯物料与设备：查系统确认BV装配时间，锁定点胶机（1#）、载具（3#）、压合治具（2#），并锁定小件供应商（英斯特）及批次。\n"
        "排查制程：调取点胶前后图片，确认料盘同批磁铁存在残缺，排除次組立人员操作人为损伤。\n"
        "分析漏失：查AOI检测结果一次pass，比对图片发现可见异物，确认AOI存在漏检。\n"
        "综合结论：供应商来料不良导致残缺，AOI漏检导致流出，需从源头和AOI拦截双向排查。\n\n"
        "【推测输出】\n"
        "物料排查：确认供应商（如：英斯特）来料是否存在边缘破损或残缺批次。\n"
        "SN追溯：追溯生产时间、点胶机台号（如1#）、关联的载具和压合治具编号。\n"
        "制程排查：调取次組立和点胶站CCD影像，排查作业员操作流程是否规范，排除人为碰撞。\n"
        "首件记录：排查AOI检测图片及过站记录，确认是否存在特征比对漏失导致的误判Pass。\n\n"
        "【示例 2】\n"
        "【输入信息】\n"
        "机型：J70x\n"
        "不良现象：0.66 Lip height fail (尺寸NG)\n"
        "制程：金加(CNC)\n\n"
        "【推理逻辑 (CoT)】\n"
        "拆解现象：Lip面尺寸测大导致NG。分析扫描数据确定玻璃面局部凸起，造成探点异常。\n"
        "追溯物料与设备：查过站记录及首件检测均无异常，锁定加工机台号（71#）及风险批次生产时间。\n"
        "制程与环境排查：探针探测Lip时（P22点位）探到异物导致补差值偏差，从而加工凸起。\n"
        "分析漏失：Trace AIM检测结果显示OK，推测由于Lip面粘附残胶异物，AIM点激光刚好踩在异物上导致测大流出。\n"
        "综合结论：异物干扰导致探针补偿错误及AIM测量漏失。\n\n"
        "【推测输出】\n"
        "物料排查：排查上游流转物料表面是否存在残胶或异物污染。\n"
        "SN追溯：追溯加工机台号（如71#）及具体生产时间段。\n"
        "制程排查：排查机台探针探测点位（如P22点）是否存在异物干扰，确认机台相近探测值的偏差防呆是否生效。\n"
        "首件记录：排查Trace AIM检测记录及影像，确认视觉量测点是否误扫异物导致检测结果假OK。\n\n"
        "【示例 3】\n"
        "【输入信息】\n"
        "机型：J70x\n"
        "不良现象：RC 内腔结构过铣\n"
        "制程：金加(CNC)\n\n"
        "【推理逻辑 (CoT)】\n"
        "拆解现象：内腔出现过铣（多切削）以及未加工（漏切削）现象。\n"
        "追溯物料与设备：查询首件与过站记录无异常。锁定加工机台号（97#）及生产前后一天的风险批次。\n"
        "排查制程：分析过铣原因，系CNC机台（T3）开粗刀把夹屑，使得刀具偏摆过大，进而导致过铣与未加工。\n"
        "分析漏失：需在刀把位置加装吹气喷管防夹屑，并在CNC夹全检工站进行重点拦截。\n"
        "综合结论：刀具排屑不良引起偏摆，导致物理切削异常。\n\n"
        "【推测输出】\n"
        "物料排查：追溯受影响批次毛坯件是否存在余量异常。\n"
        "SN追溯：追溯加工机台号（如97#）、排查风险批次生产时间。\n"
        "制程排查：重点排查CNC机台刀把状态，检查开粗刀具（如T3刀具）是否夹屑、刀具偏摆幅度及吹气防屑功能是否正常。\n"
        "首件记录：确认首件检测无异常，并排查后续制程全检工站的拦截能力。\n\n"
        "---\n\n"
        # ── 真实输入任务 ─────────────────────────────────────────────────────
        "## <待处理信息>\n\n"
        "【基本信息】\n"
        "档案名：{檔案名}\n"
        "iPad机型：{iPad機型}\n"
        "Build阶段：{Build}\n"
        "iPad机种：{iPad機種}\n"
        "製程：{製程}\n"
        "报告人：{報告人}\n"
        "关键字：{關鍵字}\n\n"
        "【问题描述】\n{problem_description}\n\n"
        "请根据以上信息，按照推测逻辑和输出格式要求，生成该不良问题的製程排查分析。"
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
