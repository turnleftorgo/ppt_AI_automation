"""
从 RAG 检索结果中按章节名正则提取内容，无需 LLM。

RAG 文本结构固定：每个【检索片段 N】内含 問題描述/問題分析/根本原因/圍堵措施/改善對策 等章节。
本模块直接按章节标题切分提取，省去一次 Dify 调用。
"""
import re

# 已知的章节标题（繁体+简体），用于切分段落边界
_SECTION_HEADERS = [
    "問題描述", "問題分析", "根本原因", "圍堵措施", "圍措施", "改善對策",
    "问题描述", "问题分析", "围堵措施", "改善对策",
    "Meta Data",
]


def extract_sections_from_rag(rag_context: str, section_name: str) -> str:
    """
    从 RAG 文本中，按【检索片段 N】切分，提取每个片段中指定章节的内容。

    Args:
        rag_context: 完整 RAG 文本（含 【检索片段 1】... 【检索片段 N】）
        section_name: 要提取的章节名（如 "問題分析"、"圍堵措施"）

    Returns:
        "#資料分析\n1. xxx\n2. xxx\n3. xxx" 格式；无内容时返回 "#資料分析\n無相關資料"
    """
    if not rag_context or not rag_context.strip():
        return "#資料分析\n無相關資料"

    # 按【检索片段 N】切分
    fragments = re.split(r'(?=【检索片段\s*\d+】)', rag_context)
    fragments = [f.strip() for f in fragments if f.strip()]

    # 构建"下一个章节标题"的边界正则
    boundary = "|".join(re.escape(h) for h in _SECTION_HEADERS)

    # 目标章节匹配：匹配 "問題分析：\n..." 直到下一个章节标题或片段结尾
    target_pattern = re.compile(
        rf'{re.escape(section_name)}[：:]\s*\n?(.*?)(?=\n[#\s]*(?:{boundary})[：:]|\Z)',
        re.DOTALL
    )

    results = []
    for frag in fragments:
        m = target_pattern.search(frag)
        if m:
            text = m.group(1).strip()
            if text:
                results.append(text)

    if not results:
        return "#資料分析\n無相關資料"

    numbered = "\n".join(f"資料{i+1}\n{r}" for i, r in enumerate(results))
    return f"#資料分析\n{numbered}"
