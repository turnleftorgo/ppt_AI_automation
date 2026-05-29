"""
从 Desktop/test/ 下的 markdown 文件中提取 metadata + problem_description，
生成 batch_test_cases.json 供 batch_generate.py 使用。
"""
import json
import os
import re

MD_DIR = os.path.expanduser("~/Desktop/test")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch_test_cases.json")


def parse_md_file(filepath: str) -> dict:
    """从单个 md 文件中提取 metadata 和 problem_description。"""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    # ── 提取 report_id（文件名去掉 .md）────────────────────────────────
    report_id = os.path.splitext(os.path.basename(filepath))[0]

    # ── 提取 7 个 metadata 字段 ────────────────────────────────────────
    def extract_field(label: str) -> str:
        # 匹配 "N.標籤：值"，值在遇到下一個 "N." 或行尾時停止
        # 先嘗試帶 label 的精確匹配
        pattern = rf"\d+\.\s*{label}\s*[：:]\s*(.+?)(?=\s+\d+\.|\n|$)"
        m = re.search(pattern, text)
        if m:
            val = m.group(1).strip()
            val = re.sub(r"\*+", "", val).strip()
            return val
        return ""

    metadata = {
        "檔案名": extract_field("檔案名"),
        "iPad機型": extract_field("iPad機型"),
        "Build": extract_field("Build"),
        "iPad機種": extract_field("iPad機種"),
        "製程": extract_field("製程") or extract_field("制程"),
        "報告人": extract_field("報告人"),
        "關鍵字": extract_field("關鍵字"),
    }

    # ── 提取問題描述 ──────────────────────────────────────────────────
    # 匹配 "## **### 問題描述：**" 或类似变体后面的内容，直到下一个 ## 标题
    pd_pattern = r"問題描述[：:]\s*\*{0,4}\s*\n?\n?(.*?)(?=\n##|\n\*\*#|\Z)"
    m = re.search(pd_pattern, text, re.DOTALL)
    if m:
        problem_description = m.group(1).strip()
    else:
        # 尝试更宽松的匹配：問題描述后到問題分析之间
        pd_pattern2 = r"問題描述.*?\n(.*?)(?=問題分析|\n##\s*[一二三四五六七八九十]|\Z)"
        m2 = re.search(pd_pattern2, text, re.DOTALL)
        problem_description = m2.group(1).strip() if m2 else ""

    # 清理 markdown 格式
    problem_description = re.sub(r"\*+", "", problem_description).strip()
    # 合并多余空行
    problem_description = re.sub(r"\n{3,}", "\n\n", problem_description)

    return {
        "report_id": report_id,
        "metadata": metadata,
        "problem_description": problem_description,
    }


def main():
    md_files = sorted([
        f for f in os.listdir(MD_DIR) if f.endswith(".md")
    ])
    print(f"[INFO] Found {len(md_files)} markdown files in {MD_DIR}")

    cases = []
    for fname in md_files:
        filepath = os.path.join(MD_DIR, fname)
        case = parse_md_file(filepath)
        cases.append(case)
        print(f"  ✓ {fname}")
        print(f"    檔案名={case['metadata']['檔案名']}, 機種={case['metadata']['iPad機種']}, 製程={case['metadata']['製程']}")
        print(f"    問題描述: {case['problem_description'][:60]}...")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    print(f"\n[INFO] Saved {len(cases)} cases to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
