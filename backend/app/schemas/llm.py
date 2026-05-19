"""Schemas for the local Ollama LLM connector."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LLMModelInfo(BaseModel):
    name: str
    model: Optional[str] = None
    modified_at: Optional[str] = None
    size: Optional[int] = None
    digest: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class LLMHealthResponse(BaseModel):
    available: bool
    base_url: str
    default_model: str
    default_model_available: bool
    models: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class LLMModelsResponse(BaseModel):
    models: List[LLMModelInfo]


class LLMGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class LLMGenerateResponse(BaseModel):
    model: str
    response: str
    done: bool


class LLMChatMessage(BaseModel):
    role: str
    content: str = Field(..., min_length=1)


class LLMChatRequest(BaseModel):
    messages: List[LLMChatMessage] = Field(..., min_length=1)
    model: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class LLMChatResponse(BaseModel):
    model: str
    message: LLMChatMessage
    done: bool
