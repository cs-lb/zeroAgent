"""工具系统基础测试：注册表 / 装饰器 / 内置 fs。"""

from __future__ import annotations

from pathlib import Path

import pytest

from zeroagent.tools import (
    DenyPolicy,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    function_tool,
)
from zeroagent.tools.builtin.fs import FsReadTool, FsWriteTool, ListDirTool


# ---------- 装饰器 ----------


@pytest.mark.asyncio
async def test_function_tool_sync() -> None:
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

    assert isinstance(add, Tool)
    res = await add.safe_invoke({"a": 1, "b": 2}, ToolContext())
    assert res.is_error is False
    assert res.content == "3"

    schema = add.to_openai_schema()
    assert schema["function"]["name"] == "add"


@pytest.mark.asyncio
async def test_function_tool_async_with_ctx() -> None:
    @function_tool(name="echo_ws", description="echo workspace")
    async def echo_ws(ctx: ToolContext) -> ToolResult:
        return ToolResult.ok(ctx.workspace)

    res = await echo_ws.safe_invoke({}, ToolContext(workspace="/tmp/x"))
    assert res.content == "/tmp/x"


@pytest.mark.asyncio
async def test_function_tool_timeout() -> None:
    import asyncio

    @function_tool(name="slow", description="slow", timeout_s=0.05)
    async def slow() -> str:
        await asyncio.sleep(1)
        return "done"

    res = await slow.safe_invoke({}, ToolContext())
    assert res.is_error
    assert "timeout" in res.content.lower()


# ---------- Registry ----------


@pytest.mark.asyncio
async def test_registry_unique_names() -> None:
    @function_tool(name="t", description="x")
    def t1() -> str:
        return "1"

    @function_tool(name="t", description="x")
    def t2() -> str:
        return "2"

    reg = ToolRegistry()
    reg.register(t1)
    with pytest.raises(ValueError):
        reg.register(t2)
    reg.register(t2, override=True)
    assert (await reg.invoke("t", {}, ToolContext())).content == "2"


@pytest.mark.asyncio
async def test_registry_unknown_tool() -> None:
    reg = ToolRegistry()
    res = await reg.invoke("nope", {}, ToolContext())
    assert res.is_error


# ---------- Builtin fs ----------


@pytest.mark.asyncio
async def test_fs_read_write_list(tmp_path: Path) -> None:
    ws = tmp_path
    ctx = ToolContext(workspace=str(ws))

    write = FsWriteTool()
    res = await write.invoke({"path": "a.txt", "content": "hello"}, ctx)
    assert res.is_error is False
    assert (ws / "a.txt").read_text() == "hello"

    read = FsReadTool()
    res = await read.invoke({"path": "a.txt"}, ctx)
    # 升级后输出带行号前缀，原文需出现在结果里
    assert "hello" in res.content
    assert res.metadata.get("total_lines") == 1

    ls = ListDirTool()
    res = await ls.invoke({"path": "."}, ctx)
    assert "a.txt" in res.content


@pytest.mark.asyncio
async def test_fs_path_escape(tmp_path: Path) -> None:
    """禁止越界访问 workspace 之外的文件。"""
    ctx = ToolContext(workspace=str(tmp_path))
    read = FsReadTool()
    res = await read.safe_invoke({"path": "../../etc/passwd"}, ctx)
    assert res.is_error
    assert "escape" in res.content.lower() or "fs_read" in res.content.lower()


# ---------- Policy ----------


@pytest.mark.asyncio
async def test_deny_policy_blocks_writes() -> None:
    policy = DenyPolicy()
    write = FsWriteTool()
    read = FsReadTool()

    d_w = await policy.check(write, {"path": "x", "content": "y"})
    assert not d_w.allowed

    d_r = await policy.check(read, {"path": "x"})
    assert d_r.allowed
