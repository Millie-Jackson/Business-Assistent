"""
src/orchestrator/models.py

Pydantic models for tool-calling I/O and audit entries.
"""


from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolCall(BaseModel):

    name:str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):

    name: str
    ok: bool
    output: Any
    error: Optional[str] = None


class AuditEntry(BaseModel):

    step:str
    ok: bool
    detail: str
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[ToolResult] = None


class OrchestratorResult(BaseModel):

    summary: str
    messages: List[Dict[str, Any]] # Final chat messages
    audit: List[AuditEntry]