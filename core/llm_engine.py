"""
LLM engine — Dify-powered multi-turn conversation for placeholder content generation.
"""
import asyncio
import json
import os
import re
from typing import Any

import httpx
from cachetools import TTLCache


# ── Configuration (Dify API) ─────────────────────────────────────────────────
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_API_KEY_FLASH = os.getenv("DIFY_API_KEY_flash", "")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "").rstrip("/")

# ── Shared async HTTP client (connection pooling) ─────────────────────────────
_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    """Get or create a shared async HTTP client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
        timeout=120.0,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    return _http_client


# ── Conversation ID cache (per user+session+placeholder, for multi-turn) ────
# TTL=1d aligns with Dify's typical conversation retention; maxsize=500 bounds
# memory. session_id in the key isolates concurrent reports by the same user.
_conversation_ids: TTLCache = TTLCache(maxsize=500, ttl=86400)
_conversation_lock = asyncio.Lock()


async def _call_dify(query: str, conversation_key: str, user: str = "", fresh: bool = False, api_key: str = "") -> dict:
    """Call Dify chat API and return the parsed JSON response.

    Args:
        fresh: If True, skip conversation_id reuse/cache (for pipeline steps).
        api_key: Optional override for the API key (e.g. flash model key).
    """
    effective_key = api_key or DIFY_API_KEY
    url = f"{DIFY_BASE_URL}/chat-messages"
    headers = {
        "Authorization": f"Bearer {effective_key}",
        "Content-Type": "application/json",
    }

    body = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "user": user or "ppt-ai-user",
    }

    # Attach conversation_id if we have one for this placeholder
    if not fresh:
        async with _conversation_lock:
            conv_id = _conversation_ids.get(conversation_key)
        if conv_id:
            body["conversation_id"] = conv_id
            print(f"[Dify] key={conversation_key} REUSING conversation_id={conv_id[:12]}...")
        else:
            print(f"[Dify] key={conversation_key} NEW conversation (no cached id)")
    else:
        print(f"[Dify] key={conversation_key} FRESH (pipeline step)")

    client = await _get_http_client()
    resp = await client.post(url, headers=headers, json=body)
    if resp.status_code != 200:
        print(f"[Dify Error] status={resp.status_code} body={resp.text[:500]}")
    resp.raise_for_status()
    data = resp.json()

    # Cache conversation_id for multi-turn continuity
    if not fresh:
        new_conv_id = data.get("conversation_id")
        if new_conv_id:
            async with _conversation_lock:
                _conversation_ids[conversation_key] = new_conv_id
            print(f"[Dify] key={conversation_key} CACHED conversation_id={new_conv_id[:12]}...")

    answer = data.get("answer", "")
    result = _parse_json_answer(answer)
    # Always include conversation_id for downstream use
    result["_conversation_id"] = data.get("conversation_id", "")
    return result


def _fix_invalid_escapes(s: str) -> str:
    """把 JSON 字符串里非法的 \\x 转义修正为 \\\\x（保留合法转义）。

    模型偶尔会输出非法转义（如 `\\ ` `\\-` 等），导致 json.loads 抛
    `Invalid \\escape`。策略：把孤立的 \\（后面跟非合法 escape 字符）
    替换成 \\\\，让 JSON 合法，从而保留 ack 和 content。
    """
    legal = set('"\\/\bfnrtu')
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "u":
                # \\uXXXX 整体保留（6 个字符）
                out.append(s[i:i + 6])
                i += 6
                continue
            if nxt in legal:
                out.append(s[i:i + 2])
                i += 2
                continue
            # 非法转义：把单个 \\ 变成 \\\\，让 JSON 合法
            out.append("\\\\")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_json_answer(raw: str) -> dict:
    """Extract {ack, content} from Dify's answer text."""
    raw = raw.strip()

    # Strip <think>...</think> tags (some models output these)
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # 模型可能输出了非法转义（如 `\ ` `\-`），清理后重试
        try:
            fixed = _fix_invalid_escapes(raw)
            result = json.loads(fixed)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code block
            if "```" in raw:
                snippet = raw.split("```")[1]
                if snippet.startswith("json"):
                    snippet = snippet[4:]
                try:
                    result = json.loads(snippet.strip())
                except json.JSONDecodeError:
                    result = None
            else:
                result = None
            if result is None:
                # Last resort: find first { ... } in the text
                match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
                if match:
                    try:
                        result = json.loads(match.group())
                    except json.JSONDecodeError:
                        result = None
            if result is None:
                # Return raw text as content if no JSON found
                return {"ack": "已生成内容", "content": raw}

    return {
        "ack": result.get("ack", "") if isinstance(result, dict) else "",
        "content": result.get("content", "") if isinstance(result, dict) else str(result),
    }


async def generate_content(
    placeholder_key: str,
    message: str,
    history: list[dict],
    system_prompt: str = None,
    user: str = "",
    session_id: str = "",
    is_first_turn: bool = True,
) -> dict:
    """
    Multi-turn conversation generation for a single placeholder.

    Args:
        placeholder_key: The placeholder being filled
        message: Current user message
        history: Previous conversation [{ role: 'user'|'assistant', content: '...' }]
        system_prompt: Optional override for the default system prompt
        user: User identifier
        session_id: Per-report UUID; isolates Dify conversations across concurrent reports
        is_first_turn: 仅首轮为 True 时把 system_prompt 拼到 query 前面；
            多轮对话时 Dify 会话历史已含完整上下文，传 False 直接发 message，
            避免 system prompt 被当作新用户消息重复注入。

    Returns:
        { ack: str, content: str }
    """
    if not message.strip():
        return {"ack": "", "content": ""}

    if not DIFY_API_KEY or not DIFY_BASE_URL:
        return _stub_generate(placeholder_key, message)

    # 仅首轮拼接 system prompt；多轮对话复用 Dify 会话历史，不再注入
    if is_first_turn:
        effective_system = (system_prompt or "").strip()
        query = f"{effective_system}\n\n---\n\n{message}" if effective_system else message
    else:
        query = message

    try:
        return await _call_dify(
            query,
            conversation_key=f"{user}:{session_id}:{placeholder_key}",
            user=user,
        )
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


def _extract_case_info(rag_context: str) -> str:
    """
    从 RAG 检索结果中用正则提取每条片段的 Case 和报告人字段，
    拼成摘要追加到 extracted_data 尾部。
    """
    if not rag_context:
        return ""
    fragments = re.split(r'(?=【检索片段\s*\d+】)', rag_context)
    entries = []
    for frag in fragments:
        frag = frag.strip()
        if not frag:
            continue
        case_match = re.search(r'Case[：:]\s*(.+)', frag)
        reporter_match = re.search(r'报告人[：:]\s*(.+)', frag)
        if case_match or reporter_match:
            parts = []
            if case_match:
                parts.append(f"Case：{case_match.group(1).strip()}")
            if reporter_match:
                parts.append(f"报告人：{reporter_match.group(1).strip()}")
            entries.append(" | ".join(parts))
    if not entries:
        return ""
    return "\n".join(f"【检索片段 {i+1}】{e}" for i, e in enumerate(entries))


async def execute_pipeline(
    steps: list[dict[str, Any]],
    initial_vars: dict[str, str],
    system_prompt: str,
    conversation_prefix: str,
    user: str = "",
) -> dict:
    """
    通用 pipeline 执行器：遍历 steps 数组，依次调用 Dify。

    每个 step 定义：
    - name: 步骤名称（用于 debug 和 conversation_key）
    - prompt: Jinja2 模板（使用 {{var}} 占位）
    - input_vars: 该步骤需要的输入变量名列表
    - output_var: 该步骤输出存储的变量名（供后续步骤使用）

    Args:
        steps: yaml 中定义的 steps 数组
        initial_vars: 初始变量（rag_context, context_background 等）
        system_prompt: 系统提示词
        conversation_prefix: 会话前缀（用于 conversation_key）
        user: 用户标识

    Returns:
        {"ack": ..., "content": ..., "_debug": {...}}
    """
    from core.prompt_builder import build_prompt

    if not DIFY_API_KEY or not DIFY_BASE_URL:
        return _stub_pipeline(steps, initial_vars)

    vars = dict(initial_vars)
    debug = {}
    reason_conv_id = ""

    for i, step in enumerate(steps):
        step_name = step.get("name", f"step_{i}")

        # 本地提取步骤：无需 LLM，直接正则提取 RAG 章节
        if step.get("type") == "local_extract":
            from core.rag_extractor import extract_sections_from_rag
            section_key = step.get("section_key", "")
            rag_ctx = vars.get("rag_context", "")
            content_text = extract_sections_from_rag(rag_ctx, section_key)
            output_var = step.get("output_var", f"step{i}_result")
            vars[output_var] = content_text
            debug[step_name] = {
                "ack": f"已從知識庫本地提取資料（章節：{section_key}）",
                "content": content_text,
            }
            continue

        # 收集该步骤需要的输入变量
        input_vars = {}
        for var_name in step.get("input_vars", []):
            input_vars[var_name] = vars.get(var_name, "")

        # 渲染 prompt
        rendered_prompt = build_prompt(step["prompt"], input_vars)

        # 调用 Dify
        query = f"{system_prompt}\n\n---\n\n{rendered_prompt}" if system_prompt else rendered_prompt
        conversation_key = f"{conversation_prefix}:pipeline:{step_name}"

        # 选择 API key：step 声明 model: flash 时用 flash key
        step_api_key = DIFY_API_KEY_FLASH if step.get("model") == "flash" else ""

        try:
            result = await _call_dify(query, conversation_key=conversation_key, user=user, fresh=True, api_key=step_api_key)
        except Exception as e:
            return {
                "ack": f"[Pipeline 错误] step={step_name}",
                "content": f"Pipeline 执行失败: {str(e)[:200]}",
                "_debug": debug,
            }

        # 存储输出变量，供后续步骤使用
        output_var = step.get("output_var", f"step{i}_result")
        vars[output_var] = result.get("content", "")
        debug[step_name] = {
            "ack": result.get("ack", ""),
            "content": result.get("content", ""),
        }

        # 记录 reason 步骤的 conversation_id，供多轮对话复用
        # reason 步骤拥有最完整的上下文（metadata + issue + 上游 + extract 结果 + 原始推理），
        # 多轮对话挂在它的会话上，模型才能回溯完整推理过程。
        if step_name == "reason":
            reason_conv_id = result.get("_conversation_id", "")

    # reason 步骤的 conversation_id 缓存到 generate_content 的 key 下，供多轮对话复用
    if reason_conv_id:
        async with _conversation_lock:
            _conversation_ids[conversation_prefix] = reason_conv_id
        print(f"[Dify] pipeline→multi-turn bridge: key={conversation_prefix} conversation_id={reason_conv_id[:12]}... (reason)")

    # 最后一步的输出作为最终结果
    final_output_var = steps[-1].get("output_var", f"step{len(steps)-1}_result")
    final_content = vars.get(final_output_var, "")

    # 直接从 step1（extract）的输出中提取资料分析
    extracted_data = vars.get("extract_result", "")

    # 从原始 RAG 结果中提取 Case/报告人 信息追加到尾部
    rag_ctx = initial_vars.get("rag_context", "")
    case_info = _extract_case_info(rag_ctx)
    if case_info:
        extracted_data = f"{extracted_data}\n\n{case_info}" if extracted_data else case_info

    return {
        "ack": "已完成生成",
        "content": final_content,
        "extracted_data": extracted_data,
        "_debug": debug,
    }


def _stub_pipeline(steps: list[dict], initial_vars: dict) -> dict:
    """离线测试用 stub。"""
    debug = {}
    for i, step in enumerate(steps):
        step_name = step.get("name", f"step_{i}")
        debug[step_name] = {
            "ack": f"[测试] {step_name}",
            "content": f"[Pipeline 测试] {step_name} — input_vars: {list(initial_vars.keys())}",
        }
    return {
        "ack": "[测试] Pipeline 执行完成",
        "content": f"[Pipeline 测试] 共 {len(steps)} 步",
        "_debug": debug,
    }
