"""
批量 FACA 报告生成脚本 v2.0 — Pipeline 并发版。

核心优化：把并发单元从"case"改为"单个 API 调用"。
20 个 ISSUE_ANALYSIS 同时发出，哪个先完成就立刻接 ROOT_CAUSE，
再接 CONTAINMENT，再接 CORRECTIVE。semaphore 控制总并发数。

Usage:
    cd /Users/macsuper/dev/ppt_AI_automation
    python3 test/2.0batch_generate.py
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

# 同时在飞的最大 API 请求数（不是 case 数）
MAX_CONCURRENCY = 1

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
    """调用 Dify Chatflow API，返回 {ack, content}。"""
    url = f"{DIFY_BASE_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }
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
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        if "```" in raw:
            snippet = raw.split("```")[1]
            if snippet.startswith("json"):
                snippet = snippet[4:]
            try:
                result = json.loads(snippet.strip())
            except json.JSONDecodeError:
                return {"ack": "已生成内容", "content": raw}
        else:
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
#  Module 3: Progress Tracker
# ══════════════════════════════════════════════════════════════════════════════

SECTION_KEYS = ["ISSUE_ANALYSIS", "ROOT_CAUSE", "CONTAINMENT", "CORRECTIVE"]
SECTION_SHORT = {
    "ISSUE_ANALYSIS": "分析",
    "ROOT_CAUSE": "原因",
    "CONTAINMENT": "围堵",
    "CORRECTIVE": "对策",
}
STATUS_ICON = {"pending": " . ", "running": " >>> ", "done": " OK ", "fail": "FAIL"}


class ProgressTracker:
    """实时进度面板，用 ANSI 转义码原地刷新。"""

    def __init__(self, cases: list[dict]):
        self.start_time = time.time()
        self.lock = asyncio.Lock()
        # {report_id: {section_key: "pending"|"running"|"done"|"fail"}}
        self.state: dict[str, dict[str, str]] = {}
        self.elapsed_map: dict[str, dict[str, float]] = {}  # 每步耗时
        self._lines_printed = 0  # 追踪上次输出行数，用于清屏覆盖

        for case in cases:
            rid = case["report_id"]
            self.state[rid] = {k: "pending" for k in SECTION_KEYS}
            self.elapsed_map[rid] = {k: 0.0 for k in SECTION_KEYS}

    async def update(self, report_id: str, section_key: str, status: str, elapsed: float = 0):
        """更新某个 case 的某个 section 状态，然后刷新面板。"""
        async with self.lock:
            self.state[report_id][section_key] = status
            if elapsed > 0:
                self.elapsed_map[report_id][section_key] = elapsed
            self._render()

    def _render(self):
        """清掉上次输出，重新打印整个进度表。"""
        # 清除上次输出的行
        if self._lines_printed > 0:
            sys.stdout.write(f"\033[{self._lines_printed}A\033[J")

        lines = []

        # 统计
        total = len(self.state) * len(SECTION_KEYS)
        done = sum(1 for cs in self.state.values() for s in cs.values() if s in ("done", "fail"))
        running = sum(1 for cs in self.state.values() for s in cs.values() if s == "running")
        elapsed = round(time.time() - self.start_time, 0)

        lines.append(f"  Progress: {done}/{total} done | {running} running | {int(elapsed)}s elapsed")
        lines.append("")

        # 表头
        lines.append(f"  {'Case':<45} {'分析':>5} {'原因':>5} {'围堵':>5} {'对策':>5}")
        lines.append(f"  {'─' * 45} {'─' * 5} {'─' * 5} {'─' * 5} {'─' * 5}")

        # 每行一个 case
        for rid, sections in self.state.items():
            # 缩短 report_id 显示（去掉 "QMS FACA " 前缀）
            short_id = rid.replace("QMS FACA ", "")
            if len(short_id) > 43:
                short_id = short_id[:40] + "..."

            cols = []
            for key in SECTION_KEYS:
                st = sections[key]
                t = self.elapsed_map[rid][key]
                if st == "done":
                    cols.append(f"{int(t):>4}s")
                elif st == "fail":
                    cols.append(f" FAIL")
                elif st == "running":
                    cols.append(f"  >>>")
                else:
                    cols.append(f"   .")

            lines.append(f"  {short_id:<45} {cols[0]:>5} {cols[1]:>5} {cols[2]:>5} {cols[3]:>5}")

        output = "\n".join(lines)
        sys.stdout.write(output + "\n")
        sys.stdout.flush()
        self._lines_printed = len(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Module 4: Single Section Generation
# ══════════════════════════════════════════════════════════════════════════════

async def generate_single_section(
    case: dict,
    task: dict,
    context: dict,
    system_prompt: str,
    tracker: ProgressTracker,
) -> dict:
    """
    生成单个 section（一步）。
    从 case 中取 metadata + problem_description，合并上游 context，
    渲染 prompt，调用 Dify API，返回 {content, elapsed}。
    """
    report_id = case["report_id"]
    placeholder_key = task["target_placeholder"]

    await tracker.update(report_id, placeholder_key, "running")

    render_inputs = {
        "metadata": case["metadata"],
        "issue_description": case["problem_description"],
        **context,
    }

    rendered_prompt = build_prompt(task["prompt"], render_inputs)

    # 首次生成时注入免责声明（与 main.py 逻辑一致）
    if placeholder_key in ("ISSUE_ANALYSIS", "ROOT_CAUSE") and not context:
        rendered_prompt = (
            "【提示】该内容为基于过往案例经验的推测，仅供参考，"
            "建议用户结合实际情况进行修正或补充更多细节以获得更精准的分析。\n\n"
            + rendered_prompt
        )

    start = time.time()
    try:
        result = await asyncio.to_thread(
            _call_dify_chat, rendered_prompt, system_prompt
        )
        elapsed = round(time.time() - start, 2)
        await tracker.update(report_id, placeholder_key, "done", elapsed)
        return {"content": result["content"], "elapsed": elapsed, "error": None}
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        error_msg = str(e)[:200]
        await tracker.update(report_id, placeholder_key, "fail", elapsed)
        return {"content": f"[生成失败] {error_msg}", "elapsed": elapsed, "error": error_msg}


# ══════════════════════════════════════════════════════════════════════════════
#  Module 4: Pipeline Concurrency
# ══════════════════════════════════════════════════════════════════════════════

async def run_case_pipeline(
    case: dict,
    tasks: list[dict],
    system_prompt: str,
    sem: asyncio.Semaphore,
    tracker: ProgressTracker,
    output_dir: str,
) -> dict:
    """
    单个 case 的 4 步 pipeline。
    整个 case 占住一个 semaphore 槽位，4 步全部跑完才释放。
    完成后立即写入 .md 文件。
    """
    report_id = case["report_id"]
    context = {}
    sections = {}
    total_time = 0.0

    async with sem:  # 整个 case 占一个槽位，4 步全部完成才释放
        for task in tasks:
            placeholder_key = task["target_placeholder"]
            result = await generate_single_section(case, task, context, system_prompt, tracker)

            sections[placeholder_key] = result["content"]
            context[f"context_{placeholder_key}"] = result["content"]
            total_time += result["elapsed"]

            if result["error"]:
                for remaining_task in tasks[tasks.index(task) + 1:]:
                    sections[remaining_task["target_placeholder"]] = "[上游生成失败，跳过]"
                break

    # 4 步全部完成（或失败中断），立刻保存 .md
    result_dict = {
        "report_id": report_id,
        "metadata": case["metadata"],
        "problem_description": case["problem_description"],
        "sections": sections,
        "total_time": round(total_time, 2),
    }
    filepath = save_individual_md(result_dict, output_dir)
    print(f"  [SAVED] {os.path.basename(filepath)}")

    return result_dict


async def generate_all_cases(
    cases: list[dict],
    tasks: list[dict],
    system_prompt: str,
    output_dir: str,
) -> list[dict]:
    """
    并发生成所有 case。

    6 个 case 同时跑，每个 case 占一个槽位跑完全部 4 步才释放。
    释放后立刻从队列取下一个 case。最多同时 6 个 API 请求在飞。
    """
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    tracker = ProgressTracker(cases)

    total_sections = len(cases) * len(tasks)
    print(f"\n[INFO] Pipeline mode: {len(cases)} cases × {len(tasks)} sections = {total_sections} API calls")
    print(f"[INFO] Max concurrent API requests: {MAX_CONCURRENCY}")
    print(f"[INFO] All ISSUE_ANALYSIS fire simultaneously, downstream triggers on completion\n")

    # 初始化面板（打印一次空表格）
    tracker._render()

    start_time = time.time()

    # 所有 case 的 pipeline 同时启动
    results = await asyncio.gather(*[
        run_case_pipeline(case, tasks, system_prompt, sem, tracker, output_dir)
        for case in cases
    ])

    total_elapsed = round(time.time() - start_time, 2)
    print(f"\n[INFO] All {len(cases)} cases completed in {total_elapsed}s")

    return list(results)


# ══════════════════════════════════════════════════════════════════════════════
#  Module 5: Output as Individual Markdown Files
# ══════════════════════════════════════════════════════════════════════════════

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

    lines.append("## **Meta Data 元數據**\n")
    for i, (key, _) in enumerate(METADATA_LABELS, 1):
        val = metadata.get(key, "")
        lines.append(f"- {i}. {key}：{val}\n")

    lines.append("\n## **問題描述：**\n")
    lines.append(f"{problem_desc}\n")

    for task_key, title in SECTION_TITLES.items():
        content = sections.get(task_key, "[未生成]")
        lines.append(f"\n## **{title}：**\n")
        lines.append(f"{content}\n")

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
    print("  Batch FACA Report Generator v2.0 (Pipeline)")
    print("=" * 70)

    if not DIFY_API_KEY or not DIFY_BASE_URL:
        print("[ERROR] DIFY_API_KEY and DIFY_BASE_URL must be set in .env")
        sys.exit(1)

    if not os.path.exists(CASES_PATH):
        print(f"[ERROR] Test cases file not found: {CASES_PATH}")
        sys.exit(1)

    cfg = load_yaml_config()
    tasks = cfg["llm_tasks"]
    system_prompt = cfg["system_prompt"]
    print(f"[INFO] Loaded YAML template: {cfg['template_id']}")
    print(f"[INFO] LLM tasks: {[t['target_placeholder'] for t in tasks]}")

    with open(CASES_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"[INFO] Loaded {len(cases)} test cases from {CASES_PATH}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    results = await generate_all_cases(cases, tasks, system_prompt, OUTPUT_DIR)

    print(f"\n[DONE] Generated {len(results)} reports in {OUTPUT_DIR}/")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
