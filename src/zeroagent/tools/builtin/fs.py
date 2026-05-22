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
    description = (
        "Read a UTF-8 text file from the workspace, with line numbers.\n"
        "\n"
        "USAGE:\n"
        "- Output format: each line is prefixed with right-aligned line number + ':'\n"
        "  (matches standard grep output, easy to combine).\n"
        "- For large files, use `offset` (1-based start line) and `limit` (line count).\n"
        "- Default reads up to 2000 lines from the start. Use grep first to find\n"
        "  interesting line ranges, then read with offset/limit instead of dumping all.\n"
    )
    side_effect = "read"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to workspace."},
            "offset": {
                "type": "integer",
                "default": 1,
                "description": "1-based line number to start reading from.",
            },
            "limit": {
                "type": "integer",
                "default": 2000,
                "description": "Max number of lines to return.",
            },
            "max_bytes": {
                "type": "integer",
                "default": 1_000_000,
                "description": "Hard byte cap for safety.",
            },
        },
        "required": ["path"],
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _safe_path(ctx.workspace, args["path"])
        if not path.exists():
            return ToolResult.error(f"file not found: {args['path']}")
        if not path.is_file():
            return ToolResult.error(f"not a file: {args['path']}")

        offset = max(int(args.get("offset", 1)), 1)
        limit = max(int(args.get("limit", 2000)), 1)
        max_bytes = int(args.get("max_bytes", 1_000_000))

        data = path.read_bytes()
        total_bytes = len(data)
        if total_bytes > max_bytes:
            data = data[:max_bytes]
        text = data.decode("utf-8", errors="replace")

        all_lines = text.splitlines()
        total_lines = len(all_lines)
        start = offset - 1
        end = min(start + limit, total_lines)
        chunk = all_lines[start:end]

        # 行号宽度按总行数对齐（最小 4 位）
        width = max(len(str(end)), 4)
        numbered = "\n".join(
            f"{str(i).rjust(width)}:{line}"
            for i, line in enumerate(chunk, start=offset)
        )

        truncated = end < total_lines or total_bytes > max_bytes
        suffix = ""
        if end < total_lines:
            suffix = f"\n... ({total_lines - end} more lines, use offset={end + 1} to continue)"
        elif total_bytes > max_bytes:
            suffix = f"\n... (file truncated at {max_bytes} bytes)"

        return ToolResult.ok(
            numbered + suffix if numbered else "(empty file)",
            path=str(path),
            total_lines=total_lines,
            shown_lines=len(chunk),
            offset=offset,
            truncated=truncated,
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
