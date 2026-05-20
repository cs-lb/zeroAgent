"""文件系统工具：读/写/列目录。

所有路径必须在 ctx.workspace 下，防止越界访问。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zeroagent.tools.base import Tool, ToolContext, ToolResult


def _safe_path(workspace: str, raw: str) -> Path:
    """把用户传入的 path 限定在 workspace 内。"""
    ws = Path(workspace).resolve()
    target = (ws / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        target.relative_to(ws)
    except ValueError as e:
        raise ValueError(f"path '{raw}' escapes workspace '{ws}'") from e
    return target


class FsReadTool(Tool):
    name = "fs_read"
    description = "Read a UTF-8 text file from the workspace."
    side_effect = "read"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to workspace."},
            "max_bytes": {"type": "integer", "default": 200_000},
        },
        "required": ["path"],
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _safe_path(ctx.workspace, args["path"])
        if not path.exists():
            return ToolResult.error(f"file not found: {args['path']}")
        if not path.is_file():
            return ToolResult.error(f"not a file: {args['path']}")
        max_bytes = int(args.get("max_bytes", 200_000))
        data = path.read_bytes()[:max_bytes]
        return ToolResult.ok(
            data.decode("utf-8", errors="replace"),
            path=str(path),
            size=len(data),
        )


class FsWriteTool(Tool):
    name = "fs_write"
    description = "Write text content to a file inside the workspace (overwrite)."
    side_effect = "write"
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _safe_path(ctx.workspace, args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return ToolResult.ok(f"wrote {len(args['content'])} chars to {path}")


class ListDirTool(Tool):
    name = "list_dir"
    description = "List entries (non-recursive) of a directory inside the workspace."
    side_effect = "read"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
        },
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _safe_path(ctx.workspace, args.get("path", "."))
        if not path.exists():
            return ToolResult.error(f"not found: {path}")
        if not path.is_dir():
            return ToolResult.error(f"not a directory: {path}")
        entries = []
        for child in sorted(path.iterdir()):
            kind = "dir" if child.is_dir() else "file"
            entries.append(f"{kind}\t{child.name}")
        return ToolResult.ok("\n".join(entries) or "(empty)")
