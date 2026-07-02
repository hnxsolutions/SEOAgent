import json

import httpx
import pytest

from app.services.local_llm import (
    LocalLLMService,
    OllamaModelNotFoundError,
    OllamaUnavailableError,
)


def tags_payload():
    return {
        "models": [
            {
                "name": "qwen2.5:3b",
                "model": "qwen2.5:3b",
                "modified_at": "2026-05-18T00:00:00Z",
                "size": 123,
                "digest": "abc",
            }
        ]
    }


@pytest.mark.asyncio
async def test_health_check_reports_available_default_model():
    async def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json=tags_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        service = LocalLLMService(base_url="http://ollama.test", client=client)
        health = await service.health_check()

    assert health["available"] is True
    assert health["default_model"] == "qwen2.5:3b"
    assert health["default_model_available"] is True
    assert health["models"] == ["qwen2.5:3b"]


@pytest.mark.asyncio
async def test_generate_uses_stream_false_and_default_model():
    seen_requests = []

    async def handler(request):
        seen_requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags_payload())
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        assert body["model"] == "qwen2.5:3b"
        assert body["prompt"] == "Write one SEO title."
        assert body["stream"] is False
        assert body["options"] == {"temperature": 0.2}
        return httpx.Response(200, json={"response": "Local SEO title", "done": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        service = LocalLLMService(base_url="http://ollama.test", client=client)
        result = await service.generate("Write one SEO title.", options={"temperature": 0.2})

    assert result["response"] == "Local SEO title"
    assert result["done"] is True
    assert [request.url.path for request in seen_requests] == ["/api/tags", "/api/generate"]


@pytest.mark.asyncio
async def test_debug_check_confirms_generation_round_trip():
    async def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags_payload())
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"response": "SEOAgent Ollama debug OK", "done": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        service = LocalLLMService(base_url="http://ollama.test", client=client)
        result = await service.debug_check()

    assert result["backend_can_reach_ollama"] is True
    assert result["configured_model_exists"] is True
    assert result["generation_succeeds"] is True
    assert result["generation_preview"] == "SEOAgent Ollama debug OK"


@pytest.mark.asyncio
async def test_chat_uses_stream_false_and_messages():
    async def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags_payload())
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["messages"][0] == {"role": "system", "content": "You are local."}
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "A local answer."},
                "done": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        service = LocalLLMService(base_url="http://ollama.test", client=client)
        result = await service.chat([{"role": "system", "content": "You are local."}])

    assert result["message"] == {"role": "assistant", "content": "A local answer."}
    assert result["done"] is True


@pytest.mark.asyncio
async def test_missing_model_is_graceful():
    async def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama3.2:1b"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        service = LocalLLMService(base_url="http://ollama.test", client=client)
        with pytest.raises(OllamaModelNotFoundError) as exc_info:
            await service.generate("hello", model="qwen2.5:3b")

    assert "qwen2.5:3b" in str(exc_info.value)
    assert "llama3.2:1b" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ollama_unavailable_is_graceful():
    async def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        service = LocalLLMService(base_url="http://ollama.test", client=client, max_retries=0)
        health = await service.health_check()

    assert health["available"] is False
    assert "not reachable" in health["error"]


@pytest.mark.asyncio
async def test_generate_json_parses_json_object_from_response_text():
    async def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags_payload())
        return httpx.Response(200, json={"response": 'Here is JSON: {"title": "Local SEO"}', "done": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        service = LocalLLMService(base_url="http://ollama.test", client=client)
        result = await service.generate_json("Return a title")

    assert result["json"] == {"title": "Local SEO"}
