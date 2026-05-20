"""Python 表达式求值（受限）。

仅用于演示 exec 类工具的 Policy 流程，**不是真正的沙箱**。
M3 阶段会被替换为 Docker / microVM 沙箱。
"""

from __future__ import annotations

from typing import Any

from zeroagent.tools.base import Tool, ToolContext, ToolResult


class PythonEvalTool(Tool):
    name = "python_eval"
    description = (
        "Evaluate a Python expression (read-only built-ins). "
        "WARNING: not a real sandbox. Use only in trusted environments."
    )
    side_effect = "exec"
    requires_approval = True
    timeout_s = 5.0
    input_schema = {
        "type": "object",
        "properties": {"expr": {"type": "string"}},
        "required": ["expr"],
    }

    _SAFE_BUILTINS: dict[str, Any] = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "len": len,
        "range": range,
        "round": round,
        "sorted": sorted,
        "int": int,
        "float": float,
        "str": str,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        expr = args["expr"]
        try:
            val = eval(  # noqa: S307
                expr, {"__builtins__": self._SAFE_BUILTINS}, {}
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult.error(f"eval error: {type(e).__name__}: {e}")
        return ToolResult.ok(repr(val))
