"""
FastAPI entry point for the template-based PPTX generation system.
"""
import os
import shutil
import tempfile
from io import BytesIO

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.ppt_core import PPTCore
from core.llm_engine import generate_content
from models.schemas import GenerateRequest, ExportRequest

app = FastAPI(title="PPTX AI Generator")

# ── Mount static files ────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── Template path ─────────────────────────────────────────────────────────────
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
DEFAULT_TEMPLATE = os.path.join(TEMPLATE_DIR, "base_template.pptx")

# Global state: the currently active template path
_active_template: str = DEFAULT_TEMPLATE

ppt_core = PPTCore()


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/upload")
async def upload_template(file: UploadFile = File(...)):
    """Upload a custom .pptx template."""
    global _active_template
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    path = os.path.join(TEMPLATE_DIR, "uploaded_template.pptx")
    with open(path, "wb") as f:
        content = await file.read()
        f.write(content)
    _active_template = path
    return {"status": "ok", "filename": file.filename}


@app.get("/api/placeholders")
async def get_placeholders():
    """Scan the active template and return all {{...}} placeholders."""
    if not os.path.exists(_active_template):
        raise HTTPException(404, "模板文件不存在。请先上传一个 .pptx 模板。")
    try:
        result = ppt_core.scan_placeholders(_active_template)
        return result
    except Exception as e:
        raise HTTPException(500, f"解析模板失败: {e}")


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Call LLM to generate content for selected placeholders."""
    if not req.items:
        raise HTTPException(400, "未选择任何占位符")
    try:
        content = await generate_content(req.user_input, req.items)
        return {"content": content}
    except Exception as e:
        raise HTTPException(500, f"AI 生成失败: {e}")


@app.post("/api/export")
async def export_pptx(req: ExportRequest):
    """Fill the template with final content and return the .pptx for download."""
    if not os.path.exists(_active_template):
        raise HTTPException(404, "模板文件不存在")
    try:
        data = ppt_core.fill_to_bytes(_active_template, req.content)
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
