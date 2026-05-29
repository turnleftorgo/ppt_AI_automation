"""
批量 FACA 报告生成脚本。

读取 batch_test_cases.json 中的 20 个测试用例，
通过 Dify API 按顺序生成 4 个章节（問題分析→根本原因→圍堵措施→改善對策），
每个 case 输出为独立的 .md 文件到 batch_output/ 目录。

Usage:
    cd /Users/macsuper/dev/ppt_AI_automation
    python3 -m test.batch_generate
"""
import asyncio
import json
import os
import re
import sys
import time
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import requests

from core.yaml_loader import YAMLLoader
from core.prompt_builder import build_prompt

# ── Config ────────────────────────────────────────────────────────────────────
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "").rstrip("/")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
CASES_PATH = os.path.join(TEST_DIR, "batch_test_cases.json")
OUTPUT_DIR = os.path.join(TEST_DIR, "batch_output")

MAX_CONCURRENCY = 3  # 最大并发 case 数


# ══════════════════════════════════════════════════════════════════════════════
#  Module 1: Load YAML prompts
# ══════════════════════════════════════════════════════════════════════════════

def load_yaml_config() -> dict:
    """从 YAML 模板加载 llm_tasks 和 system_prompt。"""
    templates_dir = os.path.join(PROJECT_ROOT, "templates")
    loader = YAMLLoader(templates_dir)
    loader.load_all()
    cfg = loader.get("standard_report_v1")
    if not cfg:
        print("[ERROR] YAML template 'standard_report_v1' not found")
        sys.exit(1)
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
#  Module 2: Dify Chat API Call
# ══════════════════════════════════════════════════════════════════════════════

def _call_dify_chat(query: str, system_prompt: str) -> dict[str, Any]:
    """
    调用 Dify Chatflow API，返回 {ack, content}。
    与 llm_engine.py 使用同一个端点。
    """
    url = f"{DIFY_BASE_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }
    # 组装最终 query：system_prompt + 用户渲染后的 prompt
    full_query = f"{system_prompt}\n\n---\n\n{query}"

    body = {
        "inputs": {},
        "query": full_query,
        "response_mode": "blocking",
        "user": "batch-generate-user",
    }

    resp = requests.post(url, headers=headers, json=body, timeout=300)
    resp.raise_for_status()
    data = resp.json()

    raw_answer = data.get("answer", "")
    return _parse_json_answer(raw_answer)


def _parse_json_answer(raw: str) -> dict:
    """从 Dify 的 answer 中提取 {ack, content}。"""
    raw = raw.strip()

    # 去掉 <think> 标签
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试从 markdown code block 提取
        if "```" in raw:
            snippet = raw.split("```")[1]
            if snippet.startswith("json"):
                snippet = snippet[4:]
            try:
                result = json.loads(snippet.strip())
            except json.JSONDecodeError:
                return {"ack": "已生成内容", "content": raw}
        else:
            # 尝试找第一个 JSON 对象
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    return {"ack": "已生成内容", "content": raw}
            else:
                return {"ack": "已生成内容", "content": raw}

    return {
        "ack": result.get("ack", ""),
        "content": result.get("content", ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Module 3: Single Case Generation (Sequential 4 steps)
# ══════════════════════════════════════════════════════════════════════════════

async def generate_single_case(
    case: dict,
    tasks: list[dict],
    system_prompt: str,
) -> dict:
    """
    为单个 case 按顺序生成 4 个章节。
    每个章节的输出通过 context 传递给下游章节。
    """
    metadata = case["metadata"]
    problem_description = case["problem_description"]
    report_id = case["report_id"]

    # 构建 Jinja2 渲染的基础变量
    base_inputs = {
        "metadata": metadata,
        "issue_description": problem_description,
    }

    context = {}  # 存放上游输出
    sections = {}  # 最终结果
    total_time = 0.0

    for task in tasks:
        placeholder_key = task["target_placeholder"]

        # 合并 base_inputs + context（上游输出）
        render_inputs = {**base_inputs, **context}

        # 渲染 prompt（复用项目的 build_prompt）
        rendered_prompt = build_prompt(task["prompt"], render_inputs)

        # 首次生成时注入免责声明（与 main.py 逻辑一致）
        if placeholder_key in ("ISSUE_ANALYSIS", "ROOT_CAUSE") and not context:
            rendered_prompt = (
                "【提示】该内容为基于过往案例经验的推测，仅供参考，"
                "建议用户结合实际情况进行修正或补充更多细节以获得更精准的分析。\n\n"
                + rendered_prompt
            )

        # 调用 Dify API
        start = time.time()
        try:
            result = await asyncio.to_thread(
                _call_dify_chat, rendered_prompt, system_prompt
            )
            elapsed = round(time.time() - start, 2)
            total_time += elapsed

            content = result["content"]
            sections[placeholder_key] = content

            # 把输出注入 context，供下游使用
            context[f"context_{placeholder_key}"] = content

            print(f"    [{report_id}] {placeholder_key} OK ({elapsed}s)")

        except Exception as e:
            elapsed = round(time.time() - start, 2)
            total_time += elapsed
            error_msg = str(e)[:200]
            sections[placeholder_key] = f"[生成失败] {error_msg}"
            context[f"context_{placeholder_key}"] = ""
            print(f"    [{report_id}] {placeholder_key} FAIL ({elapsed}s): {error_msg}")

    return {
        "report_id": report_id,
        "metadata": metadata,
        "problem_description": problem_description,
        "sections": sections,
        "total_time": round(total_time, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Module 4: Batch Generation with Concurrency
# ══════════════════════════════════════════════════════════════════════════════

async def generate_all_cases(
    cases: list[dict],
    tasks: list[dict],
    system_prompt: str,
) -> list[dict]:
    """并发生成所有 case（semaphore 控制并发数）。"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    print(f"\n[INFO] Generating {len(cases)} cases (concurrency={MAX_CONCURRENCY})")
    print(f"[INFO] Each case has {len(tasks)} sections (sequential dependency chain)\n")

    async def _guarded(case: dict) -> dict:
        async with semaphore:
            return await generate_single_case(case, tasks, system_prompt)

    results = []
    completed = 0
    for coro in asyncio.as_completed([_guarded(c) for c in cases]):
        result = await coro
        completed += 1
        print(f"  [{completed}/{len(cases)}] Done: {result['report_id']} ({result['total_time']}s)")
        results.append(result)

    # 按原始顺序排序
    case_order = {c["report_id"]: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: case_order.get(r["report_id"], 999))

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  Module 5: Output as Individual Markdown Files
# ══════════════════════════════════════════════════════════════════════════════

# YAML 中 4 个 task 的顺序和对应的中文标题
SECTION_TITLES = {
    "ISSUE_ANALYSIS": "問題分析",
    "ROOT_CAUSE": "根本原因",
    "CONTAINMENT": "圍堵措施",
    "CORRECTIVE": "改善對策",
}

METADATA_LABELS = [
    ("檔案名", "檔案名"),
    ("iPad機型", "iPad機型"),
    ("Build", "Build"),
    ("iPad機種", "iPad機種"),
    ("製程", "製程"),
    ("報告人", "報告人"),
    ("關鍵字", "關鍵字"),
]


def save_individual_md(result: dict, output_dir: str) -> str:
    """将单个 case 的结果保存为 .md 文件。"""
    report_id = result["report_id"]
    metadata = result["metadata"]
    problem_desc = result["problem_description"]
    sections = result["sections"]

    lines = []
    lines.append(f"## **Case：** {report_id}\n")

    # Meta Data
    lines.append("## **Meta Data 元數據**\n")
    for i, (key, _) in enumerate(METADATA_LABELS, 1):
        val = metadata.get(key, "")
        lines.append(f"- {i}. {key}：{val}\n")

    # 問題描述
    lines.append("\n## **問題描述：**\n")
    lines.append(f"{problem_desc}\n")

    # 4 个 AI 生成章节
    for task_key, title in SECTION_TITLES.items():
        content = sections.get(task_key, "[未生成]")
        lines.append(f"\n## **{title}：**\n")
        lines.append(f"{content}\n")

    # 写入文件
    md_content = "\n".join(lines)
    filepath = os.path.join(output_dir, f"{report_id}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)

    return filepath


# ══════════════════════════════════════════════════════════════════════════════
#  Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  Batch FACA Report Generator")
    print("=" * 70)

    # 检查环境
    if not DIFY_API_KEY or not DIFY_BASE_URL:
        print("[ERROR] DIFY_API_KEY and DIFY_BASE_URL must be set in .env")
        sys.exit(1)

    if not os.path.exists(CASES_PATH):
        print(f"[ERROR] Test cases file not found: {CASES_PATH}")
        sys.exit(1)

    # Step 1: 加载 YAML 配置
    cfg = load_yaml_config()
    tasks = cfg["llm_tasks"]
    system_prompt = cfg["system_prompt"]
    print(f"[INFO] Loaded YAML template: {cfg['template_id']}")
    print(f"[INFO] LLM tasks: {[t['target_placeholder'] for t in tasks]}")

    # Step 2: 加载测试用例
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"[INFO] Loaded {len(cases)} test cases from {CASES_PATH}")

    # Step 3: 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Step 4: 批量生成
    results = await generate_all_cases(cases, tasks, system_prompt)

    # Step 5: 保存为独立 .md 文件
    print(f"\n[INFO] Saving {len(results)} markdown files to {OUTPUT_DIR}/")
    for result in results:
        filepath = save_individual_md(result, OUTPUT_DIR)
        print(f"  ✓ {os.path.basename(filepath)}")

    print(f"\n[DONE] Generated {len(results)} reports in {OUTPUT_DIR}/")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
