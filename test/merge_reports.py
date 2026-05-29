"""
将真实报告与 AI 生成报告按章节合并为对比文档。
真实在左（引用块），AI 在右（正常文本）。

Usage:
    python3 /Users/macsuper/dev/ppt_AI_automation/test/merge_reports.py
"""
import os
import re

REAL_DIR = os.path.expanduser("~/Desktop/Origin output")
AI_DIR = os.path.expanduser("~/Desktop/batch_output")
OUTPUT_DIR = os.path.expanduser("~/Desktop/Test_output_compare")

SECTIONS = ["問題分析", "根本原因", "圍堵措施", "改善對策"]


def extract_sections(text: str) -> dict[str, str]:
    """从 markdown 中提取各章节内容。"""
    sections = {}

    # 問題描述
    pd_match = re.search(r"問題描述[：:]\s*\*{0,4}\s*\n?\n?(.*?)(?=\n##|\n\*\*#|\Z)", text, re.DOTALL)
    if pd_match:
        sections["問題描述"] = pd_match.group(1).strip()

    # 4 个主要章节
    for section_name in SECTIONS:
        pattern = rf"{section_name}[：:]\s*\*{{0,4}}\s*\n(.*?)(?=\n##|\Z)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            content = m.group(1).strip()
            content = re.sub(r"^\*{0,4}\s*", "", content, flags=re.MULTILINE)
            content = re.sub(r"^- ###\s*", "", content, flags=re.MULTILINE)
            sections[section_name] = content.strip()

    return sections


def extract_metadata(text: str) -> str:
    """提取 Meta Data 区域。"""
    m = re.search(r"(Meta Data.*?問題描述)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(0).strip()
    return ""


def merge_case(case_id: str, real_text: str, ai_text: str) -> str:
    """合并为对比文档：真实（引用块）vs AI（正常文本）。"""
    real_sections = extract_sections(real_text)
    ai_sections = extract_sections(ai_text)

    lines = []
    lines.append(f"# {case_id} — 真实 vs AI 对比\n")
    lines.append("---\n")

    # Meta Data
    meta = extract_metadata(real_text)
    if meta:
        lines.append(f"## Meta Data\n")
        lines.append(f"{meta}\n")

    # 問題描述
    problem_desc = real_sections.get("問題描述", ai_sections.get("問題描述", ""))
    if problem_desc:
        lines.append(f"\n## 問題描述\n")
        lines.append(f"{problem_desc}\n")

    lines.append("\n---\n")

    # 逐章节对比
    for section_name in SECTIONS:
        real_content = real_sections.get(section_name, "")
        ai_content = ai_sections.get(section_name, "")

        lines.append(f"\n## {section_name} 对比\n")

        # 真实报告（引用块）
        lines.append(f"### 真实报告\n")
        if real_content:
            for line in real_content.split("\n"):
                lines.append(f"> {line}")
            lines.append("")
        else:
            lines.append("> （无）\n")

        # AI 生成
        lines.append(f"### AI 生成\n")
        if ai_content:
            lines.append(f"{ai_content}\n")
        else:
            lines.append("（无）\n")

        lines.append("---\n")

    return "\n".join(lines)


def main():
    # 两个文件夹的文件名完全相同，直接配对
    real_files = sorted([f for f in os.listdir(REAL_DIR) if f.endswith(".md")])
    ai_files = set(f for f in os.listdir(AI_DIR) if f.endswith(".md"))

    pairs = []
    for fname in real_files:
        if fname in ai_files:
            pairs.append(fname)
        else:
            print(f"  [WARN] No AI pair for: {fname}")

    print(f"[INFO] Found {len(pairs)} matched pairs\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for fname in pairs:
        with open(os.path.join(REAL_DIR, fname), "r", encoding="utf-8") as f:
            real_text = f.read()
        with open(os.path.join(AI_DIR, fname), "r", encoding="utf-8") as f:
            ai_text = f.read()

        case_id = fname.replace(".md", "")
        merged = merge_case(case_id, real_text, ai_text)

        out_path = os.path.join(OUTPUT_DIR, f"对比 {fname}")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(merged)

        print(f"  ✓ 对比 {fname}")

    print(f"\n[DONE] {len(pairs)} comparison reports in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
