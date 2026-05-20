"""工具注册表。

职责：
- 收纳所有 Tool（无论来源）
- 名字冲突时报错
- 导出 LLM 可消费的 schemas
- 按名字派发执行
"""

from __future__ import annotations

from typing import Any

from zeroagent.tools.base import Tool, ToolContext, ToolResult


class ToolRegistry:
    """工具注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool, *, override: bool = False) -> None:
        if not tool.name:
            raise ValueError("tool name is required")
        if tool.name in self._tools and not override:
            raise ValueError(f"tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def register_many(self, tools: list[Tool], *, override: bool = False) -> None:
        for t in tools:
            self.register(t, override=override)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return list(self._tools)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """导出所有工具的 OpenAI tools schema。"""
        return [t.to_openai_schema() for t in self._tools.values()]

    async def invoke(
        self, name: str, args: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.error(f"unknown tool: {name}")
        return await tool.safe_invoke(args, ctx)
