"""
LLM engine — Dify-powered multi-turn conversation for placeholder content generation.
"""
import asyncio
import json
import os
import re

import httpx


# ── Configuration (Dify API) ─────────────────────────────────────────────────
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "").rstrip("/")

# ── Shared async HTTP client (connection pooling) ─────────────────────────────
_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    """Get or create a shared async HTTP client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=120.0)
    return _http_client


# ── Conversation ID cache (per placeholder, for multi-turn) ──────────────────
_conversation_ids: dict[str, str] = {}
_conversation_lock = asyncio.Lock()


async def _call_dify(query: str, conversation_key: str, user: str = "") -> dict:
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
        "user": user or "ppt-ai-user",
    }

    # Attach conversation_id if we have one for this placeholder
    async with _conversation_lock:
        conv_id = _conversation_ids.get(conversation_key)
    if conv_id:
        body["conversation_id"] = conv_id

    client = await _get_http_client()
    resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()

    # Cache conversation_id for multi-turn continuity
    new_conv_id = data.get("conversation_id")
    if new_conv_id:
        async with _conversation_lock:
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
    user: str = "",
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

    # Build query: system prompt (if any) + user message
    effective_system = (system_prompt or "").strip()
    query = f"{effective_system}\n\n---\n\n{message}" if effective_system else message

    try:
        return await _call_dify(query, conversation_key=f"{user}:{placeholder_key}", user=user)
    except httpx.HTTPStatusError as e:
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
