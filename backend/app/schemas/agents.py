"""
SEO Agent SaaS - AI Agent Schemas
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class AgentConfig(BaseModel):
    """Schema for agent configuration"""
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: Optional[str] = None


class AgentRunRequest(BaseModel):
    """Schema for agent run request"""
    config: Optional[AgentConfig] = None
    input_data: Dict[str, Any]


class AgentResponse(BaseModel):
    """Schema for agent response"""
    type: str
    name: str
    description: str
    version: str
    capabilities: List[str]


class AgentRunResponse(BaseModel):
    """Schema for agent run response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_type: str
    status: str
    result: Dict[str, Any]
    created_at: datetime
    completed_at: Optional[datetime] = None
