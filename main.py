"""
FastAPI entry point for the YAML-driven template-based PPTX generation system.
"""
import os
import re
from io import BytesIO

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.ppt_core import PPTCore
from core.llm_engine import generate_content
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


def is_gibberish(text: str) -> str | None:
    """检测单条文本是否为乱码，返回拒绝原因或 None（表示正常）"""
    text = text.strip()

    if len(text) < 2:
        return "输入内容过短，请提供有效信息"

    cleaned = re.sub(r'[\s\W\d]', '', text)
    if len(cleaned) / max(len(text), 1) < 0.2:
        return "输入内容无效，请提供有意义的描述"

    if re.search(r'(.)\1{4,}', text):
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

    # 纯字母文本的进一步检测
    alpha_only = re.sub(r'[^a-zA-Z]', '', text)
    if len(alpha_only) >= 6:
        vowels = set('aeiouAEIOU')
        vowel_count = sum(1 for c in alpha_only if c in vowels)
        consonant_count = len(alpha_only) - vowel_count

        # 规则：辅音占比过高（随机乱码通常辅音密集）
        if len(alpha_only) > 0 and consonant_count / len(alpha_only) > 0.8:
            return "检测到无意义输入，请提供有效信息"

        # 规则：相同二字母组合重复出现（如 hehwehehgs 中 "he" 出现 3 次）
        bigrams = [alpha_only[i:i+2].lower() for i in range(len(alpha_only) - 1)]
        if len(bigrams) >= 4:
            from collections import Counter
            counts = Counter(bigrams)
            most_common_count = counts.most_common(1)[0][1]
            if most_common_count >= 3 and len(alpha_only) <= 15:
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

    # RAG context (stubbed — returns empty string, no impact when disabled)
    rag_context = ""
    if task.get("use_rag"):
        rag_context = await get_rag_context(task.get("rag_tag", ""), rendered_prompt)

    # Build system prompt (task-specific or YAML-level)
    system_prompt = task.get("system_prompt") or cfg.get("system_prompt", "")
    if rag_context:
        system_prompt += f"\n\n参考知识库内容：\n{rag_context}"

    # 首次生成问题分析/根本原因时，注入推测免责声明
    history = [h.model_dump() for h in req.history]
    first_turn_placeholders = {"ISSUE_ANALYSIS", "ROOT_CAUSE"}
    is_first_turn = not history and req.placeholder_key in first_turn_placeholders
    if is_first_turn:
        rendered_prompt = (
            "【提示】该内容为基于过往案例经验的推测，仅供参考，"
            "建议用户结合实际情况进行修正或补充更多细节以获得更精准的分析。\n\n"
            + rendered_prompt
        )

    result = await generate_content(
        req.placeholder_key, rendered_prompt, history,
        system_prompt=system_prompt,
        user=req.user.username,
    )

    # 首次生成时，强制在 ack 中附加免责声明
    if is_first_turn:
        disclaimer = "以上为基于过往经验的推测性分析，仅供参考。如您有更多现场细节，随时告诉我，我可以进一步完善。"
        result["ack"] = disclaimer

    return result


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

    # Export single slide (slide_index=1 since each YAML = one slide)
    slide_index = cfg.get("slide_index", 1)
    data = ppt_core.export_single_slide(ppt_path, slide_index, content_map)
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
