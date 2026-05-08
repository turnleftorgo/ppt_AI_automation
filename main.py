"""
FastAPI entry point for the template-based PPTX generation system.
"""
import os
from io import BytesIO

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.ppt_core import PPTCore
from core.llm_engine import generate_content
from models.schemas import GenerateRequest, ExportRequest

app = FastAPI(title="PPTX AI Generator")

# ── Mount static files ────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── Built-in template path ────────────────────────────────────────────────────
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
BUILTIN_TEMPLATE = os.path.join(TEMPLATE_DIR, "品質改善報告模板Template.pptx")

ppt_core = PPTCore()


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/templates")
async def get_templates():
    """Return the list of built-in templates with their placeholders."""
    if not os.path.exists(BUILTIN_TEMPLATE):
        raise HTTPException(404, "内置模板文件不存在。")
    try:
        return ppt_core.list_templates(BUILTIN_TEMPLATE)
    except Exception as e:
        raise HTTPException(500, f"解析模板失败: {e}")


@app.get("/api/placeholders/{template_id}")
async def get_placeholders(template_id: int):
    """Return placeholders for a specific template (by slide index)."""
    if not os.path.exists(BUILTIN_TEMPLATE):
        raise HTTPException(404, "内置模板文件不存在。")
    try:
        all_templates = ppt_core.list_templates(BUILTIN_TEMPLATE)
        for t in all_templates:
            if t["template_id"] == template_id:
                return t
        raise HTTPException(404, f"模板 ID {template_id} 不存在。")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"解析占位符失败: {e}")


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Call LLM to generate content for a single placeholder (multi-turn)."""
    if not req.placeholder_key or not req.message:
        raise HTTPException(400, "缺少占位符名称或消息")
    try:
        history = [h.model_dump() for h in req.history]
        result = await generate_content(req.placeholder_key, req.message, history)
        return result  # { ack, content }
    except Exception as e:
        raise HTTPException(500, f"AI 生成失败: {e}")


@app.post("/api/export")
async def export_pptx(req: ExportRequest):
    """Fill a single template slide with final content and return the .pptx."""
    if not os.path.exists(BUILTIN_TEMPLATE):
        raise HTTPException(404, "内置模板文件不存在")
    try:
        data = ppt_core.export_single_slide(BUILTIN_TEMPLATE, req.template_id, req.final_data)
        return StreamingResponse(
            BytesIO(data),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": "attachment; filename=final_output.pptx"},
        )
    except Exception as e:
        raise HTTPException(500, f"导出失败: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  DEV SERVER
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
