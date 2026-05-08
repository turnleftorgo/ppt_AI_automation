"""
LLM engine — generates text for a single placeholder based on user prompt.
"""
import os

from openai import OpenAI


# ── Configuration (read from env or use defaults) ─────────────────────────────
API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


async def generate_content(placeholder_key: str, prompt: str) -> str:
    """
    Generate text for a single placeholder.

    Returns the generated plain text string.
    """
    if not prompt.strip():
        return ""

    if not API_KEY:
        return _stub_generate(placeholder_key, prompt)

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    system_msg = (
        "你是一个专业的 PPT 内容生成助手。用户会告诉你一个占位符的用途和需求，"
        "你需要生成一段适合直接填入 PPT 该位置的文本。"
        "语言简洁有力，适合演示文稿。只输出生成的文本内容，不要输出任何解释或标记。"
    )
    user_msg = f"占位符名称：{placeholder_key}\n\n需求：{prompt}"

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()


def _stub_generate(placeholder_key: str, prompt: str) -> str:
    """Offline stub for testing without an API key."""
    return f"[AI 生成] {placeholder_key} — {prompt}"
