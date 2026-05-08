"""
Pydantic data models for the template-based PPTX generation system.
"""
from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class PlaceholderInfo(BaseModel):
    """Records the location of a single {{...}} placeholder within the PPTX."""
    name: str = Field(..., description="Placeholder name without braces, e.g. 'User_Input_Title'")
    slide_index: int = Field(..., description="1-based slide index")
    container_type: str = Field(..., description="text_box | table_cell | notes | smartart")
    text_box_index: Optional[int] = None
    paragraph_index: int = 0
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    cell_index: Optional[int] = None
    paragraph_text: str = Field("", description="Full merged text of the paragraph")
    run_texts: List[str] = Field(default_factory=list)
    run_styles: List[dict] = Field(default_factory=list)
    run_lengths: List[int] = Field(default_factory=list)
    xpath: str = Field("", description="Extra path info (e.g. diagram drawing path)")


class SlidePlaceholderGroup(BaseModel):
    slide_index: int
    placeholders: List[PlaceholderInfo]


class ScanResult(BaseModel):
    total_placeholders: int
    unique_placeholders: List[str] = Field(..., description="Deduplicated placeholder names")
    details: List[PlaceholderInfo]
    slides: List[SlidePlaceholderGroup]


class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str


class GenerateRequest(BaseModel):
    placeholder_key: str = Field(..., description="The placeholder name to generate content for")
    message: str = Field(..., description="Current user message")
    history: List[ChatMessage] = Field(default_factory=list, description="Conversation history")


class GenerateResponse(BaseModel):
    ack: str = Field("", description="AI's brief acknowledgment (<=50 chars)")
    content: str = Field("", description="Updated placeholder content")


class TemplateInfo(BaseModel):
    template_id: int = Field(..., description="1-based slide index")
    template_name: str = Field(..., description="Display name of the template")
    placeholders: List[str] = Field(default_factory=list, description="Unique placeholder names in this template")


class ExportRequest(BaseModel):
    template_id: int = Field(..., description="Which template slide to export")
    final_data: Dict[str, str] = Field(
        default_factory=dict,
        description="Placeholder name -> final text (after AI + manual editing)",
    )
