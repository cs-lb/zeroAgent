"""code_explorer 子 Agent 工具测试。

用 FakeProvider 让子循环：
- 第 1 步：调一次 grep（验证工具能在子 registry 里被正确调用）
- 第 2 步：直接给最终结论（不再调工具）
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from zeroagent.llm.base import (
    BaseLLMProvider,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    Usage,
)
from zeroagent.tools.base import ToolContext
from zeroagent.tools.builtin.code_explorer import CodeExplorerTool


class _FakeProvider(BaseLLMProvider):
    name = "fake"

    def __init__(self, responses: list[ChatResponse]) -> None:
        super().__init__(model="fake-1")
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


@pytest.mark.asyncio
async def test_code_explorer_runs_subloop_and_returns_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "a.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

        # 子循环预设：先 grep 找 "def hello"，再吐结论
        provider = _FakeProvider(
            responses=[
                _resp(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="grep",
                            arguments={
                                "pattern": "def hello",
                                "glob": "*.py",
                                "output_mode": "files_with_matches",
                            },
                        )
                    ],
                ),
                _resp(content="Found in a.py:1 — defines hello()."),
            ]
        )

        tool = CodeExplorerTool(provider=provider)
        ctx = ToolContext(workspace=str(ws))
        result = await tool.invoke({"task": "where is hello defined?"}, ctx)

        assert not result.is_error, result.content
        assert "a.py" in result.content
        assert "hello" in result.content
        assert result.metadata["sub_steps"] == 2
        assert result.metadata["sub_tool_calls"] == 1
        assert result.metadata["stopped_reason"] == "final_answer"

        # 子循环第一轮请求里应该已经包含 grep 工具的 schema
        first_req = provider.calls[0]
        tool_names = {t["function"]["name"] for t in (first_req.tools or [])}
        assert {"grep", "glob", "fs_read", "list_dir"}.issubset(tool_names)
        # code_explorer 自己不应递归出现在子 registry 里
        assert "code_explorer" not in tool_names


@pytest.mark.asyncio
async def test_code_explorer_rejects_empty_task() -> None:
    provider = _FakeProvider(responses=[])
    tool = CodeExplorerTool(provider=provider)
    ctx = ToolContext(workspace=".")
    result = await tool.invoke({"task": "  "}, ctx)
    assert result.is_error
    assert "non-empty" in result.content


@pytest.mark.asyncio
async def test_code_explorer_handles_subloop_max_steps() -> None:
    """子循环超步数时应当返回非空 report 而不是崩溃。"""
    # 让子循环一直要求调 grep，永远不收敛 → 触发 max_steps
    looping_resp = _resp(
        tool_calls=[
            ToolCall(
                id="c1",
                name="grep",
                arguments={"pattern": "x", "output_mode": "files_with_matches"},
            )
        ],
    )
    provider = _FakeProvider(responses=[looping_resp] * 5)

    with tempfile.TemporaryDirectory() as tmp:
        tool = CodeExplorerTool(provider=provider, default_max_steps=3)
        ctx = ToolContext(workspace=tmp)
        result = await tool.invoke({"task": "loop forever"}, ctx)

    # max_steps 截停时 result.message.content 可能为空，工具会写一个兜底文案
    assert not result.is_error
    assert result.metadata["stopped_reason"] == "max_steps"
    assert result.content  # 不为空字符串
