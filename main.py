"""
FastAPI entry point for the YAML-driven template-based PPTX generation system.
"""
import json
import os
import re
from io import BytesIO

from cachetools import TTLCache
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.ppt_core import PPTCore
from core.llm_engine import generate_content, execute_pipeline
from core.yaml_loader import YAMLLoader
from core.prompt_builder import build_prompt
from core.rag_stub import get_rag_context
from models.schemas import GenerateRequest, ExportRequest

app = FastAPI(title="PPTX AI Generator")

# ── Mount static files ────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── YAML template loader (loaded once at startup) ─────────────────────────────
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
yaml_loader = YAMLLoader(TEMPLATES_DIR)
yaml_loader.load_all()

ppt_core = PPTCore()

# RAG context is produced during /api/generate but consumed during /api/export.
# Keep a server-side copy so export does not depend only on the browser relaying it.
# Keyed by (template_id, session_id) so concurrent reports by the same user don't
# cross-contaminate. TTL=1h, maxsize=200 bound memory.
rag_context_cache: TTLCache = TTLCache(maxsize=200, ttl=3600)


def _rag_cache_key(template_id: str, session_id: str) -> str:
    return f"{template_id}:{session_id}"


def _remember_rag_context(template_id: str, session_id: str, rag_context: str) -> None:
    value = (rag_context or "").strip()
    if not value:
        return
    key = _rag_cache_key(template_id, session_id)
    cached = rag_context_cache.get(key, [])
    if value not in cached:
        cached.append(value)
    rag_context_cache[key] = cached


def _cached_rag_context(template_id: str, session_id: str) -> str:
    return "\n\n".join(rag_context_cache.get(_rag_cache_key(template_id, session_id), []))


def is_gibberish(text: str) -> str | None:
    """检测单条文本是否为乱码，返回拒绝原因或 None（表示正常）"""
    text = text.strip()

    # 保留字母、数字、中文字符
    cleaned = re.sub(r'[^\w\u4e00-\u9fff]', '', text)
    if len(cleaned) / max(len(text), 1) < 0.2:
        return "输入内容无效，请提供有意义的描述"

    if re.search(r'([^a-zA-Z0-9])\1{4,}', text):
        return "检测到重复字符，请提供有效信息"

    # 键盘连击模式（扩展列表）
    gibberish_patterns = [
        r'asdfgh', r'qwerty', r'zxcvbn', r'hjkl',
        r'qwertz', r'azerty', r'wasd', r'jkl;',
    ]
    lower = text.lower()
    for pat in gibberish_patterns:
        if pat in lower:
            return "检测到无意义输入，请提供有效信息"

    return None


def validate_user_inputs(user_inputs: dict) -> str | None:
    """校验 metadata 表单字段，返回拒绝原因或 None（表示正常）"""
    for key, value in user_inputs.items():
        if not isinstance(value, str) or not value.strip():
            continue
        reason = is_gibberish(value)
        if reason:
            return f"字段「{key}」{reason}"
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/templates")
async def get_templates():
    """Return template list from YAML registry."""
    return yaml_loader.list_all()


@app.get("/api/template/{template_id}")
async def get_template_config(template_id: str):
    """Return full YAML config for a template."""
    cfg = yaml_loader.get(template_id)
    if not cfg:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return cfg


@app.get("/api/validate/{template_id}")
async def validate_template(template_id: str):
    """Validate YAML placeholder alignment with PPTX placeholders."""
    cfg = yaml_loader.get(template_id)
    if not cfg:
        raise HTTPException(404, f"Template '{template_id}' not found")

    ppt_path = os.path.join(TEMPLATES_DIR, cfg["ppt_file_path"])
    if not os.path.exists(ppt_path):
        raise HTTPException(404, "PPTX file not found")

    # Collect all target_placeholders from YAML
    yaml_ph = set()
    for dm in cfg.get("direct_mappings", []):
        yaml_ph.add(dm["target_placeholder"])
    for t in cfg.get("llm_tasks", []):
        yaml_ph.add(t["target_placeholder"])
    for t in cfg.get("closure_tasks", []):
        yaml_ph.add(t["target_placeholder"])

    # Get actual PPTX placeholders
    scan = ppt_core.scan_placeholders(ppt_path)
    pptx_ph = set(scan["unique_placeholders"])

    matched = sorted(yaml_ph & pptx_ph)
    missing_in_pptx = sorted(yaml_ph - pptx_ph)
    unused_in_yaml = sorted(pptx_ph - yaml_ph)

    return {
        "template_id": template_id,
        "matched": matched,
        "missing_in_pptx": missing_in_pptx,
        "unused_in_yaml": unused_in_yaml,
        "status": "ok" if not missing_in_pptx else "mismatch",
    }


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """
    Generate content for a single placeholder via LLM.

    Builds the prompt from YAML template using Jinja2 substitution,
    optionally retrieves RAG context, then calls the LLM.
    """
    cfg = yaml_loader.get(req.template_id)
    if not cfg:
        raise HTTPException(404, f"Template '{req.template_id}' not found")

    # 垃圾输入检测：校验 metadata 表单 + 对话框消息
    if req.user_inputs:
        reject_reason = validate_user_inputs(req.user_inputs)
        if reject_reason:
            return {"ack": "输入被拒绝", "content": reject_reason}
    reject_reason = is_gibberish(req.message)
    if reject_reason:
        return {"ack": "输入被拒绝", "content": reject_reason}

    # Find the LLM task for this placeholder (search llm_tasks + closure_tasks)
    task = None
    for t in cfg.get("llm_tasks", []):
        if t["target_placeholder"] == req.placeholder_key:
            task = t
            break
    if not task:
        for t in cfg.get("closure_tasks", []):
            if t["target_placeholder"] == req.placeholder_key:
                task = t
                break
    if not task:
        raise HTTPException(400, f"No LLM task defined for placeholder '{req.placeholder_key}'")

    # Build prompt with Jinja2 substitution from user_inputs + upstream context
    render_inputs = dict(req.user_inputs or {})

    # Group metadata fields into a single dict
    user_inputs_cfg = cfg.get("user_inputs", [])
    metadata_ids = [u["id"] for u in user_inputs_cfg if u.get("group") == "metadata"]
    metadata = {k: v for k, v in render_inputs.items() if k in metadata_ids}
    render_inputs["metadata"] = metadata

    for k, v in (req.context or {}).items():
        if v and v.strip():
            render_inputs[f"context_{k}"] = v
    rendered_prompt = build_prompt(task["prompt"], render_inputs)

    # RAG context — 只检索一次，缓存后复用
    rag_context = _cached_rag_context(req.template_id, req.session_id)
    if not rag_context and task.get("use_rag"):
        issue_desc = req.user_inputs.get("issue_description", "")
        rag_query = f"{metadata} {issue_desc}".strip()
        rag_context = await get_rag_context(task.get("rag_tag", ""), rag_query)
        _remember_rag_context(req.template_id, req.session_id, rag_context)

    # Build system prompt (task-specific or YAML-level)
    system_prompt = task.get("system_prompt") or cfg.get("system_prompt", "")

    history = [h.model_dump() for h in req.history]

    # 判断是否走 pipeline
    pipeline_config = task.get("pipeline", {})
    user_turn_count = sum(1 for h in req.history if h.role == "user")
    is_multi_turn = user_turn_count > 0
    turn_index = user_turn_count  # 0=首轮, 1=第二次多轮, 2+=第三次及以后

    # 多轮时追加意图判断指令
    if turn_index >= 1:
        intent_instruction = """
## 输出规则

1. **探讨方案**：用户在讨论思路、询问原因、探讨可能性、寻求解释、或意图不明确
   - 关键词示例：为什么、怎么理解、你觉得、还有其他、如果...会怎样
   - 输出格式：返回详细的 ack，不返回 content

2. **强指令修改**：用户明确、直接、无歧义地要求修改报告内容
   - 关键词示例：把...改成、删掉、加上、修改为、更新为
   - 输出格式：返回简短 ack + content

注意：如果用户同时讨论和要求修改，视为探讨方案，只返回 ack。不要输出你对用户意图的判断过程，直接按规则输出。"""
        system_prompt += intent_instruction

    if not is_multi_turn:
        # 首轮：走 pipeline（若启用且有 RAG）或单次生成
        if pipeline_config.get("enabled") and rag_context:
            initial_vars = {
                "rag_context": rag_context,
                "context_background": _build_context_background(render_inputs, req.context),
                "module_label": task.get("module_label", task.get("module", "")),
                # 注入用户输入变量
                **{k: v for k, v in render_inputs.items() if not k.startswith("context_")},
                # 注入上游上下文变量
                **{f"context_{k}": v for k, v in (req.context or {}).items() if v and v.strip()},
            }

            result = await execute_pipeline(
                steps=pipeline_config["steps"],
                initial_vars=initial_vars,
                system_prompt=system_prompt,
                conversation_prefix=f"{req.user.username}:{req.session_id}:{req.placeholder_key}",
                user=req.user.username,
            )
        else:
            # 无 pipeline 的首轮：发完整 prompt
            if rag_context:
                rendered_prompt += f"\n\n参考知识库内容：\n{rag_context}"
            result = await generate_content(
                req.placeholder_key, rendered_prompt, history,
                system_prompt=system_prompt,
                user=req.user.username,
                session_id=req.session_id,
                is_first_turn=True,
            )
    else:
        # 第二次及以后的多轮对话
        if turn_index == 1:
            # 第二次多轮：渲染 multi_turn_prompt，注入 current_content（脱敏版）+ user_message
            multi_turn_prompt_tpl = task.get("multi_turn_prompt")
            if multi_turn_prompt_tpl:
                mt_inputs = {
                    "current_content": req.current_content or "",
                    "user_message": req.message,
                }
                query = build_prompt(multi_turn_prompt_tpl, mt_inputs)
            else:
                query = req.message
        else:
            # 第三次及以后：直接发用户消息
            query = req.message

        # 追加意图判断指令到消息末尾（强调）
        query = f"{query}\n\n{intent_instruction}"

        result = await generate_content(
            req.placeholder_key, query, history,
            system_prompt=system_prompt,
            user=req.user.username,
            session_id=req.session_id,
            is_first_turn=False,
        )

    # 返回 RAG 检索结果，前端可存储并在导出时传回
    if rag_context:
        result["rag_context"] = rag_context

    return result


def _build_context_background(render_inputs: dict, context: dict | None) -> str:
    """
    拼接上下文背景：用户输入 + 上游生成结果。

    Args:
        render_inputs: 用户输入（含 metadata dict）
        context: 上游环节的生成结果 {placeholder_key: content}

    Returns:
        拼接后的上下文文本
    """
    parts = []

    # 用户输入（排除 context_ 前缀和 metadata dict）
    for k, v in render_inputs.items():
        if k.startswith("context_") or k == "metadata":
            continue
        if v and isinstance(v, str) and v.strip():
            parts.append(f"【{k}】: {v}")

    # metadata dict
    metadata = render_inputs.get("metadata", {})
    if metadata:
        meta_str = " | ".join(f"{k}: {v}" for k, v in metadata.items() if v)
        if meta_str:
            parts.append(f"【Meta Data】: {meta_str}")

    # 上游生成结果
    for k, v in (context or {}).items():
        if v and v.strip():
            parts.append(f"【{k}】:\n{v}")

    return "\n\n".join(parts)


@app.post("/api/export")
async def export_pptx(req: ExportRequest):
    """Fill a single template slide with final content and return the .pptx."""
    cfg = yaml_loader.get(req.template_id)
    if not cfg:
        raise HTTPException(404, f"Template '{req.template_id}' not found")

    ppt_path = os.path.join(TEMPLATES_DIR, cfg["ppt_file_path"])
    if not os.path.exists(ppt_path):
        raise HTTPException(404, "PPTX file not found")

    # Build content_map: merge direct_mappings + AI results + closure
    content_map = {}

    # Direct mappings: user input → PPT placeholder
    for dm in cfg.get("direct_mappings", []):
        uid = dm["user_input_id"]
        target = dm["target_placeholder"]
        if uid in req.user_inputs:
            content_map[target] = req.user_inputs[uid]

    # AI results + closure inputs
    content_map.update(req.final_data)

    # RAG 参考资料 → Related_text / Related_text_2 占位符（第二页）
    reference_placeholders = {"Related_text", "Related_text_2"}
    has_reference_slide = bool(reference_placeholders & set(ppt_core.scan_placeholders(ppt_path)["unique_placeholders"]))
    rag_results = req.rag_results.strip() or _cached_rag_context(req.template_id, req.session_id)
    if rag_results:
        fragments = re.split(r'(?=【检索片段\s*\d+】)', rag_results)
        fragments = [f.strip() for f in fragments if f.strip()]
        if len(fragments) >= 1:
            content_map["Related_text"] = fragments[0]
        if len(fragments) >= 2:
            content_map["Related_text_2"] = "\n\n".join(fragments[1:])
        elif has_reference_slide:
            content_map["Related_text_2"] = ""
    elif has_reference_slide:
        content_map["Related_text"] = "未检索到相关参考资料。"
        content_map["Related_text_2"] = ""

    # 拼接标题: 机种｜制程 关键词 FACA
    if "REPORT_TITLE" not in content_map:
        title_parts = []
        for field in ["ipad_type", "build", "process", "keywords"]:
            val = req.user_inputs.get(field, "").strip()
            if val:
                title_parts.append(val)
        title_parts.append("FACA")
        content_map["REPORT_TITLE"] = re.sub(r' +', ' ', title_parts[0] + "｜" + " ".join(title_parts[1:]))

    data = ppt_core.fill_to_bytes(ppt_path, content_map)
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": "attachment; filename=final_output.pptx"},
    )


# ══════════════════════════════════════════════════════════════════════════════
#  DEV SERVER
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
