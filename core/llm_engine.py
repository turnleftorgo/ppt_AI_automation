"""
LLM engine — DeepSeek-powered multi-turn conversation for placeholder content generation.
"""
import json
import os

from openai import OpenAI


# ── Configuration (DeepSeek, OpenAI-compatible API) ───────────────────────────
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

SYSTEM_PROMPT = """你是一个专业的 PPT 品質改善報告内容生成助手。

用户正在填写一个 PPT 模板中的占位符。你需要：
1. 根据用户的描述生成或修改该占位符的内容
2. 语言简洁有力，适合 PPT 演示文稿
3. 内容专业、结构清晰

每次回复你必须且只能返回一个严格的 JSON 对象，包含两个字段：
- "ack": 简短回应（不超过 50 字），确认你理解了用户的意思
- "content": 更新后的占位符最终文本内容

示例：
{"ack": "好的，已更新根本原因分析，加入了材料批次问题。", "content": "经分析，根本原因为10月批次原材料硬度不达标导致外壳变形。"}

不要输出任何其他内容、解释或 markdown 标记。"""


def _get_client():
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


async def generate_content(placeholder_key: str, message: str, history: list[dict]) -> dict:
    """
    Multi-turn conversation generation for a single placeholder.

    Args:
        placeholder_key: The placeholder being filled
        message: Current user message
        history: Previous conversation [{ role: 'user'|'assistant', content: '...' }]

    Returns:
        { ack: str, content: str }
    """
    if not message.strip():
        return {"ack": "", "content": ""}

    if not API_KEY:
        return _stub_generate(placeholder_key, message)

    client = _get_client()

    # Build message list: system + history + current
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})

    context_prefix = f"[当前占位符：{placeholder_key}]\n\n"
    messages.append({"role": "user", "content": context_prefix + message})

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try to extract JSON from markdown code block
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            result = json.loads(raw.strip())
        else:
            raise

    return {
        "ack": result.get("ack", ""),
        "content": result.get("content", ""),
    }


def _stub_generate(placeholder_key: str, message: str) -> dict:
    """Offline stub for testing without an API key."""
    return {
        "ack": f"[测试] 已收到关于 {placeholder_key} 的指令",
        "content": f"[AI 生成] {placeholder_key} — {message}",
    }
