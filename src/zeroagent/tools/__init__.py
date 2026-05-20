"""工具系统：抽象 + 注册表 + 内置工具。

设计要点：
- 所有外部能力（MCP / Skills / CLI / Builtin）统一为 Tool 抽象
- ToolRegistry 负责合并多来源工具，并产出 LLM 可消费的 schema
- 通过 Policy 控制写/执行类工具的审批
"""

from zeroagent.tools.base import (
    Tool,
    ToolContext,
    ToolError,
    ToolResult,
    ToolTimeoutError,
    function_tool,
)
from zeroagent.tools.policy import (
    AlwaysAllowPolicy,
    DenyPolicy,
    Policy,
    PolicyDecision,
    PromptPolicy,
)
from zeroagent.tools.registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolError",
    "ToolTimeoutError",
    "function_tool",
    "ToolRegistry",
    "Policy",
    "PolicyDecision",
    "AlwaysAllowPolicy",
    "DenyPolicy",
    "PromptPolicy",
]
