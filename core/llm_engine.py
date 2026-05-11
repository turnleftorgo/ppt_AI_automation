"""
LLM engine — Dify-powered multi-turn conversation for placeholder content generation.
"""
import json
import os
import re

import requests


# ── Configuration (Dify API) ─────────────────────────────────────────────────
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "").rstrip("/")

DEFAULT_SYSTEM_PROMPT = """你是一个专业的 PPT 品質改善報告内容生成助手。

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

# ── Conversation ID cache (per placeholder, for multi-turn) ──────────────────
_conversation_ids: dict[str, str] = {}


def _call_dify(query: str, conversation_key: str) -> dict:
    """Call Dify chat API and return the parsed JSON response."""
    url = f"{DIFY_BASE_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "user": "ppt-ai-user",
    }

    # Attach conversation_id if we have one for this placeholder
    conv_id = _conversation_ids.get(conversation_key)
    if conv_id:
        body["conversation_id"] = conv_id

    resp = requests.post(url, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    # Cache conversation_id for multi-turn continuity
    new_conv_id = data.get("conversation_id")
    if new_conv_id:
        _conversation_ids[conversation_key] = new_conv_id

    answer = data.get("answer", "")
    return _parse_json_answer(answer)


def _parse_json_answer(raw: str) -> dict:
    """Extract {ack, content} from Dify's answer text."""
    raw = raw.strip()

    # Strip <think>...</think> tags (some models output these)
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown code block
        if "```" in raw:
            snippet = raw.split("```")[1]
            if snippet.startswith("json"):
                snippet = snippet[4:]
            result = json.loads(snippet.strip())
        else:
            # Last resort: find first { ... } in the text
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                # Return raw text as content if no JSON found
                return {"ack": "已生成内容", "content": raw}

    return {
        "ack": result.get("ack", ""),
        "content": result.get("content", ""),
    }


async def generate_content(
    placeholder_key: str,
    message: str,
    history: list[dict],
    system_prompt: str = None,
) -> dict:
    """
    Multi-turn conversation generation for a single placeholder.

    Args:
        placeholder_key: The placeholder being filled
        message: Current user message
        history: Previous conversation [{ role: 'user'|'assistant', content: '...' }]
        system_prompt: Optional override for the default system prompt

    Returns:
        { ack: str, content: str }
    """
    if not message.strip():
        return {"ack": "", "content": ""}

    if not DIFY_API_KEY or not DIFY_BASE_URL:
        return _stub_generate(placeholder_key, message)

    # Build query: system prompt context + user message
    effective_system = system_prompt or DEFAULT_SYSTEM_PROMPT
    query = f"{effective_system}\n\n---\n\n[当前占位符：{placeholder_key}]\n\n{message}"

    try:
        return _call_dify(query, conversation_key=placeholder_key)
    except requests.exceptions.HTTPError as e:
        error_body = e.response.text if e.response else str(e)
        return {
            "ack": f"[API错误] {e.response.status_code if e.response else 'unknown'}",
            "content": f"调用Dify API失败: {error_body[:200]}",
        }
    except Exception as e:
        return {
            "ack": "[生成失败]",
            "content": f"生成内容时出错: {str(e)[:200]}",
        }


def _stub_generate(placeholder_key: str, message: str) -> dict:
    """Offline stub for testing without an API key."""
    return {
        "ack": f"[测试] 已收到关于 {placeholder_key} 的指令",
        "content": f"[AI 生成] {placeholder_key} — {message}",
    }
