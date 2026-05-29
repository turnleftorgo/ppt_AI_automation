"""
FastAPI entry point for the YAML-driven template-based PPTX generation system.
"""
import os
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
    uvicorn.run(app, host="0.0.0.0", port=8001)
