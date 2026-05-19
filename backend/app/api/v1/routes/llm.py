"""Local Ollama LLM API routes."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.schemas.llm import (
    LLMChatRequest,
    LLMChatResponse,
    LLMGenerateRequest,
    LLMGenerateResponse,
    LLMHealthResponse,
    LLMModelsResponse,
)
from app.services.local_llm import (
    LocalLLMService,
    OllamaModelNotFoundError,
    OllamaRequestError,
    OllamaUnavailableError,
)

router = APIRouter()


@router.get("/health", response_model=LLMHealthResponse)
async def llm_health(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Check local Ollama server and default model availability."""
    return await LocalLLMService().health_check()


@router.get("/models", response_model=LLMModelsResponse)
async def llm_models(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """List locally installed Ollama models."""
    try:
        return LLMModelsResponse(models=await LocalLLMService().list_models())
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post("/generate", response_model=LLMGenerateResponse)
async def llm_generate(
    request: LLMGenerateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Generate text with the local Ollama /api/generate endpoint."""
    try:
        result = await LocalLLMService().generate(
            prompt=request.prompt,
            model=request.model,
            options=request.options,
        )
        return LLMGenerateResponse(**result)
    except OllamaModelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except OllamaRequestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/chat", response_model=LLMChatResponse)
async def llm_chat(
    request: LLMChatRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Chat with the local Ollama /api/chat endpoint."""
    try:
        result = await LocalLLMService().chat(
            messages=[message.model_dump() for message in request.messages],
            model=request.model,
            options=request.options,
        )
        return LLMChatResponse(**result)
    except OllamaModelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except OllamaRequestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
