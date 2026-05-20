"""AgentLoop on_event 回调 + AsyncApprovalPolicy 单测。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from zeroagent.core.loop import AgentLoop
from zeroagent.llm.base import (
    BaseLLMProvider,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    Usage,
)
from zeroagent.tools.base import Tool, ToolContext, ToolResult
from zeroagent.tools.policy import AsyncApprovalPolicy
from zeroagent.tools.registry import ToolRegistry


class _FakeProvider(BaseLLMProvider):
    name = "fake"

    def __init__(self, scripted: list[ChatMessage]):
        self._scripted = list(scripted)
        self.model = "fake-model"

    async def chat(self, req: ChatRequest) -> ChatResponse:  # type: ignore[override]
        msg = self._scripted.pop(0)
        return ChatResponse(
            message=msg,
            finish_reason="tool_calls" if msg.tool_calls else "stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    def stream(self, req: ChatRequest):  # type: ignore[override]
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class _WriteTool(Tool):
    name = "writer"
    description = "fake write"
    side_effect = "write"
    input_schema = {"type": "object", "properties": {"v": {"type": "string"}}}
    requires_approval = False

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult.ok(f"wrote {args.get('v')}")


def _tc(name: str, args: dict, *, id_: str = "c1") -> ToolCall:
    return ToolCall(id=id_, name=name, arguments=args)


@pytest.mark.asyncio
async def test_on_event_emits_full_lifecycle():
    provider = _FakeProvider([
        ChatMessage(role="assistant", content="", tool_calls=[_tc("writer", {"v": "x"})]),
        ChatMessage(role="assistant", content="done"),
    ])
    reg = ToolRegistry()
    reg.register(_WriteTool())

    events: list[tuple[str, dict]] = []

    async def on_event(e: str, p: dict) -> None:
        events.append((e, p))

    loop = AgentLoop.build(
        provider=provider,
        registry=reg,
        on_event=on_event,
    )
    result = await loop.run("hi")
    assert result.stopped_reason == "final_answer"
    assert result.tool_calls == 1

    names = [e for e, _ in events]
    # 关键事件全到位
    assert "run_start" in names
    assert names.count("step_start") >= 2
    assert "llm_message" in names
    assert "policy_check" in names
    assert "policy_decision" in names
    assert "tool_call_start" in names
    assert "tool_call_result" in names
    assert names[-1] == "done"


@pytest.mark.asyncio
async def test_async_approval_policy_allow_and_deny():
    tool = _WriteTool()
    # 同意
    p_yes = AsyncApprovalPolicy(lambda t, a: _coro(True))
    d = await p_yes.check(tool, {"v": "x"})
    assert d.allowed

    # 拒绝
    p_no = AsyncApprovalPolicy(lambda t, a: _coro(False))
    d = await p_no.check(tool, {"v": "x"})
    assert not d.allowed
    assert d.reason == "user-approval"


@pytest.mark.asyncio
async def test_async_approval_policy_timeout():
    async def _never(_t, _a):
        await asyncio.sleep(10)
        return True

    pol = AsyncApprovalPolicy(_never, timeout_s=0.05)
    d = await pol.check(_WriteTool(), {})
    assert not d.allowed
    assert d.reason == "approval-timeout"


@pytest.mark.asyncio
async def test_async_approval_policy_passthrough_for_read():
    class _ReadTool(_WriteTool):
        side_effect = "read"

    called = False

    async def _req(_t, _a):
        nonlocal called
        called = True
        return True

    pol = AsyncApprovalPolicy(_req)
    d = await pol.check(_ReadTool(), {})
    assert d.allowed
    assert called is False  # read 直接放行，不触发审批


async def _coro(v: bool) -> bool:
    return v
