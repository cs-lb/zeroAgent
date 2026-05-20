"""内置工具集。"""

from zeroagent.tools.builtin.fs import FsReadTool, FsWriteTool, ListDirTool
from zeroagent.tools.builtin.http import HttpGetTool
from zeroagent.tools.builtin.python_eval import PythonEvalTool


def default_builtin_tools(*, allow_write: bool = False, allow_exec: bool = False) -> list:
    """返回一组安全默认工具。"""
    tools = [
        FsReadTool(),
        ListDirTool(),
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
    "HttpGetTool",
    "PythonEvalTool",
    "default_builtin_tools",
]
