"""内置工具集。"""

from zeroagent.tools.builtin.code_explorer import CodeExplorerTool
from zeroagent.tools.builtin.fs import FsReadTool, FsWriteTool, ListDirTool
from zeroagent.tools.builtin.glob import GlobTool
from zeroagent.tools.builtin.grep import GrepTool
from zeroagent.tools.builtin.http import HttpGetTool
from zeroagent.tools.builtin.python_eval import PythonEvalTool


def default_builtin_tools(*, allow_write: bool = False, allow_exec: bool = False) -> list:
    """返回一组安全默认工具。

    默认装备一套"代码检索"组合：fs_read + list_dir + grep + glob，
    对标 Claude Code 的 agentic search 能力，避免引入向量索引。
    """
    tools = [
        FsReadTool(),
        ListDirTool(),
        GrepTool(),
        GlobTool(),
        HttpGetTool(),
    ]
    if allow_write:
        tools.append(FsWriteTool())
    if allow_exec:
        tools.append(PythonEvalTool())
    return tools


__all__ = [
    "FsReadTool",
    "FsWriteTool",
    "ListDirTool",
    "GrepTool",
    "GlobTool",
    "HttpGetTool",
    "PythonEvalTool",
    "CodeExplorerTool",
    "default_builtin_tools",
]
