"""OpenAICompatibleProvider 单元测试（mock HTTP）。"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zeroagent.llm.base import ChatMessage, ChatRequest
from zeroagent.llm.errors import LLMAuthError, LLMRateLimitError, LLMServerError
from zeroagent.llm.openai_compat import OpenAICompatibleProvider

BASE = "https://api.fake.com/v1"


def _make_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(model="test-model", api_key="sk-test", base_url=BASE)


@pytest.mark.asyncio
@respx.mock
async def test_chat_ok(fake_openai_response: dict) -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=fake_openai_response)
    )
    p = _make_provider()
    try:
        resp = await p.chat(
            ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="hi")],
            )
        )
    finally:
        await p.aclose()

    assert route.called
    assert resp.message.role == "assistant"
    assert resp.message.content == "hello world"
    assert resp.usage.total_tokens == 7
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "status,exc",
    [
        (401, LLMAuthError),
        (429, LLMRateLimitError),
        (500, LLMServerError),
    ],
)
async def test_chat_errors(status: int, exc: type[Exception]) -> None:
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(status, json={"error": {"message": "boom"}})
    )
    p = _make_provider()
    try:
        with pytest.raises(exc):
            await p.chat(
                ChatRequest(
                    model="test-model",
                    messages=[ChatMessage(role="user", content="hi")],
                )
            )
    finally:
        await p.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_stream_ok() -> None:
    chunks = [
        {"choices": [{"delta": {"role": "assistant", "content": "He"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "llo"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    p = _make_provider()
    collected: list[str] = []
    finish: str | None = None
    total: int = 0
    try:
        async for chunk in p.stream(
            ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="hi")],
                stream=True,
            )
        ):
            if chunk.delta:
                collected.append(chunk.delta)
            if chunk.finish_reason:
                finish = chunk.finish_reason
            if chunk.usage:
                total = chunk.usage.total_tokens
    finally:
        await p.aclose()

    assert "".join(collected) == "Hello"
    assert finish == "stop"
    assert total == 3
