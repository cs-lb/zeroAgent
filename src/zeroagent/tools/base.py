"""Tool 抽象 + 函数式装饰器。

每个工具都是一个 callable：
- 描述（name/description/input_schema）→ 用于 LLM 选择
- 副作用标记（none/read/write/exec）→ 用于 Policy 审批
- invoke() → 实际执行，返回 ToolResult
"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

SideEffect = Literal["none", "read", "write", "exec"]


class ToolError(Exception):
    """工具执行错误。"""

    def __init__(self, message: str, *, tool: str | None = None):
        super().__init__(message)
        self.tool = tool


class ToolTimeoutError(ToolError):
    """工具执行超时。"""


@dataclass
class ToolContext:
    """工具执行上下文。

    通过 ctx 把会话级别的资源/限制传递给工具，避免全局状态。
    """

    workspace: str = "."
    """工作目录（fs/exec 类工具应限制在此目录）。"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """任意附加信息（trace_id / user_id 等）。"""


class ToolResult(BaseModel):
    """工具执行结果。content 必须能 JSON 序列化为 str。"""

    content: str
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, content: str, **meta: Any) -> ToolResult:
        return cls(content=content, is_error=False, metadata=meta)

    @classmethod
    def error(cls, message: str, **meta: Any) -> ToolResult:
        return cls(content=message, is_error=True, metadata=meta)


class Tool(ABC):
    """所有工具的抽象基类。"""

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {}
    side_effect: SideEffect = "none"
    timeout_s: float = 30.0
    requires_approval: bool = False

    def to_openai_schema(self) -> dict[str, Any]:
        """导出为 OpenAI tools 字段的 schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }

    @abstractmethod
    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行工具。子类必须实现。"""

    async def safe_invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """带超时与异常归一化的执行入口。"""
        try:
            return await asyncio.wait_for(self.invoke(args, ctx), timeout=self.timeout_s)
        except asyncio.TimeoutError as e:
            return ToolResult.error(f"tool '{self.name}' timeout after {self.timeout_s}s")
        except ToolError as e:
            return ToolResult.error(f"{self.name}: {e}")
        except Exception as e:  # noqa: BLE001
            return ToolResult.error(f"{self.name} raised {type(e).__name__}: {e}")


# ---------- 函数式装饰器：把普通函数包成 Tool ----------


class _FunctionTool(Tool):
    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        side_effect: SideEffect = "none",
        timeout_s: float = 30.0,
        requires_approval: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.side_effect = side_effect
        self.timeout_s = timeout_s
        self.requires_approval = requires_approval
        self._fn = fn
        self._is_coro = inspect.iscoroutinefunction(fn)

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        # 如果函数签名里有 ctx 形参，自动注入
        sig = inspect.signature(self._fn)
        kwargs = dict(args)
        if "ctx" in sig.parameters:
            kwargs["ctx"] = ctx

        if self._is_coro:
            ret = await self._fn(**kwargs)
        else:
            ret = await asyncio.to_thread(self._fn, **kwargs)

        if isinstance(ret, ToolResult):
            return ret
        if isinstance(ret, str):
            return ToolResult.ok(ret)
        # 兜底：把任意返回值 str() 化
        return ToolResult.ok(str(ret))


def function_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any] | None = None,
    side_effect: SideEffect = "none",
    timeout_s: float = 30.0,
    requires_approval: bool = False,
) -> Callable[[Callable[..., Any]], Tool]:
    """把普通函数包成 Tool 的装饰器。

    示例：

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
    """

    def deco(fn: Callable[..., Any]) -> Tool:
        return _FunctionTool(
            fn,
            name=name,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            side_effect=side_effect,
            timeout_s=timeout_s,
            requires_approval=requires_approval,
        )

    return deco


# 类型别名（给上层用）
ToolInvokeFn = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]
