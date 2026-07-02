"""Local Ollama LLM connector.

This module only uses Ollama's local HTTP API. It does not call paid or remote
LLM providers.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class LocalLLMError(RuntimeError):
    """Base error for local Ollama connector failures."""


class OllamaUnavailableError(LocalLLMError):
    """Raised when the local Ollama server is not reachable."""


class OllamaModelNotFoundError(LocalLLMError):
    """Raised when the requested local Ollama model is not installed."""


class OllamaRequestError(LocalLLMError):
    """Raised when Ollama returns an invalid or failed response."""


class LocalLLMService:
    """Small wrapper around the official Ollama HTTP API."""

    def __init__(
        self,
        base_url: str = settings.OLLAMA_BASE_URL,
        default_model: str = settings.OLLAMA_DEFAULT_MODEL,
        timeout_seconds: float = settings.OLLAMA_TIMEOUT_SECONDS,
        max_retries: int = settings.OLLAMA_MAX_RETRIES,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, int(max_retries))
        self._client = client

    async def health_check(self) -> Dict[str, Any]:
        """Return local Ollama availability and installed model status."""
        try:
            models = await self.list_models(validate_default=False)
            model_names = [model["name"] for model in models]
            return {
                "available": True,
                "base_url": self.base_url,
                "default_model": self.default_model,
                "default_model_available": self.default_model in model_names,
                "models": model_names,
                "error": None,
            }
        except LocalLLMError as exc:
            return {
                "available": False,
                "base_url": self.base_url,
                "default_model": self.default_model,
                "default_model_available": False,
                "models": [],
                "error": str(exc),
            }

    async def debug_check(self) -> Dict[str, Any]:
        """Prove the configured Docker-to-Ollama path can list models and generate."""
        health = await self.health_check()
        result = {
            "backend_can_reach_ollama": bool(health["available"]),
            "base_url": health["base_url"],
            "configured_model": health["default_model"],
            "configured_model_exists": bool(health["default_model_available"]),
            "generation_succeeds": False,
            "generation_preview": None,
            "error": health["error"],
        }
        if not result["backend_can_reach_ollama"] or not result["configured_model_exists"]:
            return result

        try:
            generated = await self.generate(
                "Return exactly this text: SEOAgent Ollama debug OK",
                model=self.default_model,
                options={"temperature": 0, "num_predict": 32},
            )
            preview = (generated.get("response") or "").strip()
            result["generation_succeeds"] = bool(generated.get("done") and preview)
            result["generation_preview"] = preview[:200] or None
            result["error"] = None if result["generation_succeeds"] else "Ollama returned an empty generation."
        except LocalLLMError as exc:
            result["error"] = str(exc)
        return result

    async def list_models(self, validate_default: bool = False) -> List[Dict[str, Any]]:
        """List installed Ollama models using GET /api/tags."""
        payload = await self._request("GET", "/api/tags")
        models = payload.get("models") or []
        normalized = [
            {
                "name": model.get("name") or model.get("model"),
                "model": model.get("model") or model.get("name"),
                "modified_at": model.get("modified_at"),
                "size": model.get("size"),
                "digest": model.get("digest"),
                "details": model.get("details"),
            }
            for model in models
            if model.get("name") or model.get("model")
        ]
        if validate_default:
            self._ensure_model_available(self.default_model, normalized)
        return normalized

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate text using POST /api/generate with stream=false."""
        selected_model = model or self.default_model
        await self._validate_model(selected_model)
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
        }
        if options:
            payload["options"] = options

        response = await self._request("POST", "/api/generate", json_payload=payload)
        return {
            "model": selected_model,
            "response": response.get("response", ""),
            "done": bool(response.get("done")),
            "raw": response,
        }

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Chat using POST /api/chat with stream=false."""
        selected_model = model or self.default_model
        await self._validate_model(selected_model)
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        response = await self._request("POST", "/api/chat", json_payload=payload)
        message = response.get("message") or {}
        return {
            "model": selected_model,
            "message": {
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
            },
            "done": bool(response.get("done")),
            "raw": response,
        }

    async def generate_json(
        self,
        prompt: str,
        schema_hint: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate and parse JSON from local Ollama text output."""
        json_prompt = prompt.strip()
        if schema_hint:
            json_prompt += f"\n\nReturn only valid JSON matching this schema hint:\n{schema_hint}"
        else:
            json_prompt += "\n\nReturn only valid JSON."

        result = await self.generate(json_prompt, model=model)
        text = result["response"]
        return {
            **result,
            "json": self._parse_json_from_text(text),
        }

    async def _validate_model(self, model: str) -> None:
        models = await self.list_models()
        self._ensure_model_available(model, models)

    def _ensure_model_available(self, model: str, models: List[Dict[str, Any]]) -> None:
        model_names = {item["name"] for item in models if item.get("name")}
        if model not in model_names:
            available = ", ".join(sorted(model_names)) or "none"
            raise OllamaModelNotFoundError(
                f"Ollama model '{model}' is not installed. Available models: {available}."
            )

    async def _request(
        self,
        method: str,
        path: str,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._send(method, path, json_payload)
                if response.status_code >= 400:
                    raise OllamaRequestError(
                        f"Ollama request failed with status {response.status_code}: {response.text}"
                    )
                return response.json()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                raise OllamaUnavailableError(
                    f"Ollama is not reachable at {self.base_url}. Is the local server running?"
                ) from exc
            except json.JSONDecodeError as exc:
                raise OllamaRequestError("Ollama returned invalid JSON.") from exc

        raise OllamaUnavailableError(
            f"Ollama is not reachable at {self.base_url}: {last_error}"
        )

    async def _send(
        self,
        method: str,
        path: str,
        json_payload: Optional[Dict[str, Any]],
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, path, json=json_payload)

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
        ) as client:
            return await client.request(method, path, json=json_payload)

    def _parse_json_from_text(self, text: str) -> Any:
        stripped = text.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\}|\[.*\])", stripped, re.DOTALL)
            if not match:
                raise OllamaRequestError("Ollama response did not contain valid JSON.")
            return json.loads(match.group(1))
