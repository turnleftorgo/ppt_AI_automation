"""
Pydantic data models for the YAML-driven template system.
"""
from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class PlaceholderInfo(BaseModel):
    """Records the location of a single {…} placeholder within the PPTX."""
    name: str = Field(..., description="Placeholder name without braces")
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


class UserContext(BaseModel):
    username: str = "anonymous"
    display_name: str | None = None
    email: str | None = None
    groups: list[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str


class GenerateRequest(BaseModel):
    template_id: str = Field(..., description="YAML template ID")
    placeholder_key: str = Field(..., description="target_placeholder from llm_tasks")
    message: str = Field(..., description="Current user message")
    history: List[ChatMessage] = Field(default_factory=list, description="Conversation history")
    user_inputs: Dict[str, str] = Field(
        default_factory=dict,
        description="Values from Characterize section for Jinja2 substitution",
    )
    context: Dict[str, str] = Field(
        default_factory=dict,
        description="Upstream placeholder results for downstream prompt injection",
    )
    user: UserContext = Field(
        default_factory=UserContext,
        description="User identity from URL query params",
    )


class GenerateResponse(BaseModel):
    ack: str = Field("", description="AI's brief acknowledgment (<=50 chars)")
    content: str = Field("", description="Updated placeholder content")


class ExportRequest(BaseModel):
    template_id: str = Field(..., description="YAML template ID")
    user_inputs: Dict[str, str] = Field(
        default_factory=dict,
        description="User inputs for direct mappings",
    )
    final_data: Dict[str, str] = Field(
        default_factory=dict,
        description="AI-generated + closure placeholder values",
    )
