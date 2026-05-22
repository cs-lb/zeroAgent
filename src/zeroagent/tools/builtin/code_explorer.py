"""code_explorer：派一个子 Agent 专做代码仓库探索。

设计目标（对标 Claude Code 的 `Task` 工具）：

- 主 Agent 上下文不被几十次 grep / read 结果撑爆
- 子 Agent 只装"代码检索"四件套：grep / glob / fs_read / list_dir
- 子 Agent 复用主 Agent 的 LLM provider（同模型，省得另配 key）
- 主 Agent 只拿到子 Agent 的最终结论字符串

注意：
- 这个工具**不包含**在 `default_builtin_tools()` 里，因为它强依赖 provider。
  请通过 `Agent.enable_code_explorer()` 或显式构造注册。
- 子循环的 max_steps 默认给 12，比主循环更宽，因为探索常需要多轮 grep。
"""

from __future__ import annotations

from typing import Any

from zeroagent.llm.base import BaseLLMProvider
from zeroagent.tools.base import Tool, ToolContext, ToolResult
from zeroagent.tools.policy import AlwaysAllowPolicy, Policy
from zeroagent.tools.registry import ToolRegistry

_SUB_SYSTEM_PROMPT = """You are a code-exploration sub-agent.

Your ONLY job: answer the question by exploring the workspace with the tools
available to you, then return a concise, factual report.

TOOLS YOU HAVE
- glob(pattern, path?, head_limit?)        → find files by name pattern
- grep(pattern, glob?, output_mode?, ...)  → ripgrep-style content search
- fs_read(path, offset?, limit?)           → read a file slice with line numbers
- list_dir(path)                           → list directory entries

STRATEGY (follow strictly)
1. Plan: identify what evidence answers the question (definitions, call sites,
   config keys, etc.). Decide which patterns / file globs to search.
2. Narrow first: use `glob` and `grep` with `output_mode='files_with_matches'`
   to locate candidate files BEFORE reading them.
3. Read precisely: only call `fs_read` on the few lines you actually need
   (use `offset`/`limit`). Never dump entire large files.
4. Parallelize independent searches in the SAME tool-call round when you can.
5. Stop when you have enough evidence. Do not over-explore.

OUTPUT FORMAT (your final assistant message)
- Start with a 1-2 sentence direct answer.
- Then a "Key locations" list: `path:line  — what's there`
- Then (optional) a short explanation tying the locations together.
- Never paste large code blocks. Quote only the lines that prove your point.
- Keep the whole answer under ~400 words.
"""


class CodeExplorerTool(Tool):
    """派一个子 AgentLoop 专门做代码仓库探索。"""

    name = "code_explorer"
    description = (
        "Spawn a specialized sub-agent to explore the codebase and answer a "
        "broad question (e.g. 'how is auth implemented', 'where is X used'). "
        "It uses grep/glob/read internally and returns a concise final report.\n"
        "\n"
        "USE THIS WHEN:\n"
        "- The question requires SEVERAL searches across many files.\n"
        "- You don't want to pollute your own context with raw grep dumps.\n"
        "- You only need the conclusion, not the intermediate evidence.\n"
        "\n"
        "DO NOT USE WHEN:\n"
        "- A single grep / fs_read call would clearly suffice — call those directly.\n"
        "- The user just asked to read one specific file.\n"
    )
    side_effect = "read"
    timeout_s = 120.0  # 子循环可能跑十几步，给宽松点
    input_schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "Self-contained question for the sub-agent. Include any "
                    "context it needs (file hints, what 'good answer' looks like). "
                    "The sub-agent does NOT see your conversation history."
                ),
            },
            "max_steps": {
                "type": "integer",
                "default": 12,
                "description": "Sub-loop step budget. Default 12.",
            },
        },
        "required": ["task"],
    }

    def __init__(
        self,
        *,
        provider: BaseLLMProvider,
        policy: Policy | None = None,
        default_max_steps: int = 12,
    ) -> None:
        self._provider = provider
        self._policy = policy or AlwaysAllowPolicy()
        self._default_max_steps = default_max_steps

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        # 延迟 import：避免 tools.builtin 在加载时就依赖 core.loop（防循环 import）
        from zeroagent.core.loop import AgentLoop
        from zeroagent.tools.builtin.fs import FsReadTool, ListDirTool
        from zeroagent.tools.builtin.glob import GlobTool
        from zeroagent.tools.builtin.grep import GrepTool

        task = args.get("task")
        if not isinstance(task, str) or not task.strip():
            return ToolResult.error("`task` must be a non-empty string")
        max_steps = int(args.get("max_steps", self._default_max_steps))

        # 子 registry：只挂检索工具，且都是只读
        sub_registry = ToolRegistry()
        sub_registry.register_many(
            [GrepTool(), GlobTool(), FsReadTool(), ListDirTool()]
        )

        sub_loop = AgentLoop.build(
            provider=self._provider,
            registry=sub_registry,
            policy=self._policy,
            workspace=ctx.workspace,
            max_steps=max_steps,
            temperature=0.2,
        )

        try:
            result = await sub_loop.run(task, system=_SUB_SYSTEM_PROMPT)
        except Exception as e:  # noqa: BLE001
            return ToolResult.error(
                f"code_explorer sub-agent crashed: {type(e).__name__}: {e}"
            )

        report = (result.message.content or "").strip()
        if not report:
            report = "(sub-agent produced no textual answer)"

        return ToolResult.ok(
            report,
            sub_steps=result.steps,
            sub_tool_calls=result.tool_calls,
            stopped_reason=result.stopped_reason,
        )


__all__ = ["CodeExplorerTool"]
