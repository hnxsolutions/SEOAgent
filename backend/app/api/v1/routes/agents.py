"""
SEO Agent SaaS - AI Agent Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, List

from app.core.database import get_db
from app.schemas.agents import AgentConfig, AgentRunRequest, AgentRunResponse, AgentResponse
from app.services.agents import AgentService
from app.core.security import get_current_user

router = APIRouter()


@router.get("/", response_model=List[AgentResponse])
async def list_agents(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """List available AI agents"""
    agent_service = AgentService(db)
    agents = await agent_service.get_available_agents()
    return agents


@router.post("/{agent_type}/run", response_model=AgentRunResponse)
async def run_agent(
    agent_type: str,
    run_request: AgentRunRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Run an AI agent with specific configuration"""
    agent_service = AgentService(db)
    
    # Validate agent type
    available_agents = await agent_service.get_available_agents()
    if not any(agent["type"] == agent_type for agent in available_agents):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent type '{agent_type}' not found"
        )
    
    # Execute agent
    result = await agent_service.execute_agent(
        agent_type=agent_type,
        config=run_request.config.model_dump() if run_request.config else None,
        input_data=run_request.input_data,
        tenant_id=current_user["tenant_id"]
    )
    
    return result
