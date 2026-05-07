"""
LLM engine — assembles a prompt from placeholder names + user description,
calls the OpenAI-compatible API, and returns a strict JSON dict.
"""
import json
import os
from typing import Dict, List

from openai import OpenAI


# ── Configuration (read from env or use defaults) ─────────────────────────────
API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def build_prompt(user_input: str, items: Dict[str, str]) -> str:
    """
    Build a prompt that instructs the LLM to fill *specific* placeholders,
    each with its own per-placeholder instruction.

    *items*: {placeholder_name: per-placeholder prompt}
    *user_input*: optional global context (topic / background)
    """
    item_lines = "\n".join(
        f"  - {name}：{prompt}" for name, prompt in items.items()
    )
    context_block = f"\n全局背景：{user_input}\n" if user_input else ""
    return f"""你是一个专业的 PPT 内容生成助手。{context_block}
以下占位符需要你生成内容，每个占位符后面有对应的提示词：
{item_lines}

要求：
1. 内容与全局背景及各占位符的提示词高度相关
2. 语言简洁有力，适合 PPT 演示
3. 每个值控制在合理长度（标题类 10-30 字，正文类 50-200 字）
4. 如果占位符名称暗示了用途（如 Title, Bullet_1, Subtitle），严格按其用途生成

你必须且只能返回一个严格的 JSON 对象，键为占位符名称，值为生成的文本。
不要输出任何其他内容、解释或 markdown 标记。

示例格式：
{{"占位符名称": "生成的文本内容"}}
"""


async def generate_content(user_input: str, items: Dict[str, str]) -> Dict[str, str]:
    """
    Generate content for specific placeholders (not necessarily all of them).

    *items*: {placeholder_name: per-placeholder prompt}
    Returns: {placeholder_name: generated_text}
    """
    if not items:
        return {}

    if not API_KEY:
        return _stub_generate(user_input, items)

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    user_msg = build_prompt(user_input, items)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "你是一个严格的 JSON 输出助手。只输出 JSON，不要任何额外文字。"},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    result = json.loads(raw)
    return {name: result.get(name, "") for name in items}


def _stub_generate(user_input: str, items: Dict[str, str]) -> Dict[str, str]:
    """Offline stub for testing without an API key."""
    return {
        name: f"[AI 生成] {name} — {prompt}"
        for name, prompt in items.items()
    }
