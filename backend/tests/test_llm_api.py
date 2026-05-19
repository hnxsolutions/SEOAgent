from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import llm as llm_routes


def test_llm_api_smoke_flow(monkeypatch):
    class FakeLocalLLMService:
        async def health_check(self):
            return {
                "available": True,
                "base_url": "http://localhost:11434",
                "default_model": "qwen2.5:3b",
                "default_model_available": True,
                "models": ["qwen2.5:3b"],
                "error": None,
            }

        async def list_models(self):
            return [{"name": "qwen2.5:3b", "model": "qwen2.5:3b"}]

        async def generate(self, prompt, model=None, options=None):
            return {"model": model or "qwen2.5:3b", "response": "Generated locally", "done": True, "raw": {}}

        async def chat(self, messages, model=None, options=None):
            return {
                "model": model or "qwen2.5:3b",
                "message": {"role": "assistant", "content": "Chat locally"},
                "done": True,
                "raw": {},
            }

    monkeypatch.setattr(llm_routes, "LocalLLMService", FakeLocalLLMService)

    app = FastAPI()
    app.include_router(llm_routes.router, prefix="/llm")
    app.dependency_overrides[llm_routes.get_current_user] = lambda: {
        "tenant_id": uuid4(),
        "user_id": uuid4(),
    }
    client = TestClient(app)

    health_response = client.get("/llm/health")
    assert health_response.status_code == 200
    assert health_response.json()["default_model"] == "qwen2.5:3b"

    models_response = client.get("/llm/models")
    assert models_response.status_code == 200
    assert models_response.json()["models"][0]["name"] == "qwen2.5:3b"

    generate_response = client.post("/llm/generate", json={"prompt": "Write one title."})
    assert generate_response.status_code == 200
    assert generate_response.json()["response"] == "Generated locally"

    chat_response = client.post(
        "/llm/chat",
        json={"messages": [{"role": "user", "content": "Write one title."}]},
    )
    assert chat_response.status_code == 200
    assert chat_response.json()["message"]["content"] == "Chat locally"
