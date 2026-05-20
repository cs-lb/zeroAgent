"""AgentLoop（ReAct 主循环）测试。

用 FakeProvider 模拟 LLM，避免真实 API 调用。
覆盖：
- 直接给最终答复（0 工具调用）
- 一轮 tool_call → 最终答复
- 多个 tool_call 并行
- 未知工具
- max_steps 截断
- DenyPolicy 拦截
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from zeroagent.core.loop import AgentLoop
from zeroagent.llm.base import (
    BaseLLMProvider,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    Usage,
)
from zeroagent.tools import DenyPolicy, ToolRegistry, function_tool


class FakeProvider(BaseLLMProvider):
    """按预设序列返回 ChatResponse。"""

    name = "fake"

    def __init__(self, *, model: str = "fake-1", responses: list[ChatResponse]) -> None:
        super().__init__(model=model)
        self._responses = list(responses)
        self.calls: list[ChatRequest] = []

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.calls.append(req)
        if not self._responses:
            raise AssertionError("no more fake responses")
        return self._responses.pop(0)

    def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:  # pragma: no cover
        async def _it() -> AsyncIterator[ChatChunk]:
            if False:
                yield ChatChunk()

        return _it()


def _resp(content: str = "", tool_calls: list[ToolCall] | None = None) -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role="assistant", content=content, tool_calls=tool_calls),
        usage=Usage(),
        finish_reason="stop" if tool_calls is None else "tool_calls",
    )


def _make_registry() -> ToolRegistry:
    @function_tool(
        name="add",
        description="add two numbers",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    )
    def add(a: float, b: float) -> str:
        return str(a + b)

    @function_tool(
        name="upper",
        description="upper case",
        input_schema={
            "type": "object",
            "properties": {"s": {"type": "string"}},
            "required": ["s"],
        },
    )
    def upper(s: str) -> str:
        return s.upper()

    @function_tool(
        name="dangerous",
        description="write something",
        side_effect="write",
        requires_approval=True,
    )
    def dangerous() -> str:
        return "did write"

    reg = ToolRegistry()
    reg.register(add)
    reg.register(upper)
    reg.register(dangerous)
    return reg


# ---------- 用例 ----------


@pytest.mark.asyncio
async def test_no_tool_calls() -> None:
    provider = FakeProvider(responses=[_resp("hello")])
    loop = AgentLoop.build(provider=provider, registry=_make_registry())
    result = await loop.run("hi")
    assert result.message.content == "hello"
    assert result.tool_calls == 0
    assert result.steps == 1
    assert result.stopped_reason == "final_answer"


@pytest.mark.asyncio
async def test_single_tool_then_answer() -> None:
    provider = FakeProvider(
        responses=[
            _resp(tool_calls=[ToolCall(id="c1", name="add", arguments={"a": 1, "b": 2})]),
            _resp("the answer is 3"),
        ]
    )
    loop = AgentLoop.build(provider=provider, registry=_make_registry())
    result = await loop.run("compute 1+2")
    assert result.message.content == "the answer is 3"
    assert result.tool_calls == 1
    assert result.steps == 2

    # 第二次 LLM 调用应该看到 tool result
    last_messages = provider.calls[-1].messages
    tool_msgs = [m for m in last_messages if m.role == "tool"]
    assert tool_msgs and tool_msgs[0].content == "3"


@pytest.mark.asyncio
async def test_parallel_tool_calls() -> None:
    provider = FakeProvider(
        responses=[
            _resp(
                tool_calls=[
                    ToolCall(id="a", name="add", arguments={"a": 2, "b": 3}),
                    ToolCall(id="b", name="upper", arguments={"s": "hi"}),
                ]
            ),
            _resp("done"),
        ]
    )
    loop = AgentLoop.build(provider=provider, registry=_make_registry())
    result = await loop.run("do both")
    assert result.tool_calls == 2
    last = provider.calls[-1].messages
    contents = sorted(m.content for m in last if m.role == "tool")
    assert contents == ["5", "HI"]


@pytest.mark.asyncio
async def test_unknown_tool() -> None:
    provider = FakeProvider(
        responses=[
            _resp(tool_calls=[ToolCall(id="x", name="ghost", arguments={})]),
            _resp("ok"),
        ]
    )
    loop = AgentLoop.build(provider=provider, registry=_make_registry())
    result = await loop.run("call ghost")
    last = provider.calls[-1].messages
    assert any("unknown tool" in m.content for m in last if m.role == "tool")
    assert result.message.content == "ok"


@pytest.mark.asyncio
async def test_max_steps() -> None:
    # 永远返回 tool_call → 触发上限
    provider = FakeProvider(
        responses=[
            _resp(tool_calls=[ToolCall(id=f"c{i}", name="add", arguments={"a": 1, "b": 1})])
            for i in range(10)
        ]
    )
    loop = AgentLoop.build(provider=provider, registry=_make_registry(), max_steps=3)
    result = await loop.run("loop forever")
    assert result.stopped_reason == "max_steps"
    assert result.steps == 3


@pytest.mark.asyncio
async def test_deny_policy_blocks_dangerous_tool() -> None:
    provider = FakeProvider(
        responses=[
            _resp(tool_calls=[ToolCall(id="d", name="dangerous", arguments={})]),
            _resp("blocked, fallback answer"),
        ]
    )
    loop = AgentLoop.build(
        provider=provider, registry=_make_registry(), policy=DenyPolicy()
    )
    result = await loop.run("try dangerous")
    last = provider.calls[-1].messages
    tool_msg = next(m for m in last if m.role == "tool")
    assert "denied by policy" in tool_msg.content
    assert result.message.content == "blocked, fallback answer"
