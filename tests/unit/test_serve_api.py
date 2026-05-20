"""serve.api 的单测：用 FastAPI TestClient 直接打接口。

不真实调用 LLM，所有 Provider 在 Agent 内部走 mock 替换。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sse_starlette")

from fastapi.testclient import TestClient

from zeroagent.llm.base import (
    BaseLLMProvider,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Usage,
)
from zeroagent.serve.api import create_app


CONFIG_YAML = """\
llm:
  default: fake-a
  providers:
    fake-a:
      type: openai_compatible
      api_key: x
      base_url: http://example.com/v1
      model: fake-model-a
    fake-b:
      type: openai_compatible
      api_key: x
      base_url: http://example.com/v1
      model: fake-model-b
"""


class FakeProvider(BaseLLMProvider):
    name = "openai_compatible"

    def __init__(self, *, model: str, reply: str = "ok", **kwargs: object) -> None:
        super().__init__(model=model)
        self.reply = reply

    async def chat(self, req: ChatRequest) -> ChatResponse:
        return ChatResponse(
            message=ChatMessage(role="assistant", content=f"[{self.model}] {self.reply}"),
            usage=Usage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
            finish_reason="stop",
            model=self.model,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:  # type: ignore[override]
        for piece in [f"[{self.model}]", " hi", "!"]:
            yield ChatChunk(delta=piece)
        yield ChatChunk(usage=Usage(prompt_tokens=3, completion_tokens=4, total_tokens=7))

    async def aclose(self) -> None:
        pass


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    cfg = tmp_path / "agent.yaml"
    cfg.write_text(CONFIG_YAML)

    # 把 build_provider 替换成 FakeProvider，避免真打 HTTP
    from zeroagent.llm import registry as reg

    def fake_build(kind: str, **kwargs: object) -> BaseLLMProvider:
        return FakeProvider(model=str(kwargs.get("model", "fake")))

    monkeypatch.setattr(reg, "build_provider", fake_build)
    # agent.py 是 from ... import build_provider，要打它的命名空间
    from zeroagent import agent as agent_mod

    monkeypatch.setattr(agent_mod, "build_provider", fake_build)

    app = create_app(cfg)
    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_providers(client: TestClient) -> None:
    r = client.get("/api/providers")
    assert r.status_code == 200
    data = r.json()
    assert data["default"] == "fake-a"
    assert data["current"] == "fake-a"
    names = {p["name"] for p in data["providers"]}
    assert names == {"fake-a", "fake-b"}


def test_chat_non_stream_default(client: TestClient) -> None:
    r = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert "fake-model-a" in data["content"]
    assert data["provider"] == "fake-a"


def test_chat_switch_provider(client: TestClient) -> None:
    r = client.post(
        "/api/chat",
        json={
            "provider": "fake-b",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200
    assert "fake-model-b" in r.json()["content"]


def test_chat_unknown_provider(client: TestClient) -> None:
    r = client.post(
        "/api/chat",
        json={
            "provider": "nope",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 400


def test_chat_stream(client: TestClient) -> None:
    r = client.post(
        "/api/chat/stream",
        json={
            "provider": "fake-b",
            "messages": [{"role": "user", "content": "stream me"}],
        },
    )
    assert r.status_code == 200
    body = r.text  # TestClient 会把 SSE 全收完
    assert "event: meta" in body
    assert "event: delta" in body
    # provider 元数据
    assert "fake-b" in body
    # 三段 delta 累加后应包含 "[fake-model-b] hi!"
    deltas: list[str] = []
    for line in body.split("\n"):
        if line.startswith("data: "):
            try:
                obj = json.loads(line[len("data: ") :])
                if "content" in obj:
                    deltas.append(obj["content"])
            except json.JSONDecodeError:
                continue
    joined = "".join(deltas)
    assert "fake-model-b" in joined
    assert joined.endswith("hi!")
