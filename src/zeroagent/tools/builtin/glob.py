"""Glob 工具：按文件名 pattern 检索文件路径。

对标 Claude Code 的 Glob 工具。配合 grep 使用：
  - glob 先按 pattern 找一批候选文件
  - 再用 grep 在这批文件里精确搜内容
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from zeroagent.tools.base import Tool, ToolContext, ToolResult

# 与 grep 模块一致的剪枝集合
_DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".idea",
    ".vscode",
}


def _safe_path(workspace: str, raw: str) -> Path:
    ws = Path(workspace).resolve()
    target = (ws / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        target.relative_to(ws)
    except ValueError as e:
        raise ValueError(f"path '{raw}' escapes workspace '{ws}'") from e
    return target


class GlobTool(Tool):
    name = "glob"
    description = (
        "Find files by name pattern. Returns paths sorted by modification time\n"
        "(most recent first), useful for 'what changed recently' queries.\n"
        "\n"
        "USAGE:\n"
        "- pattern: '**/*.py', 'test_*.py', 'src/**/*.ts'\n"
        "- Combine with `grep` for content search inside the matched files.\n"
        "- Common excluded dirs: .git, .venv, node_modules, __pycache__ etc.\n"
    )
    side_effect = "read"
    timeout_s = 15.0
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '**/*.py', 'test_*.py'.",
            },
            "path": {
                "type": "string",
                "default": ".",
                "description": "Root directory (relative to workspace).",
            },
            "head_limit": {
                "type": "integer",
                "default": 100,
                "description": "Max paths returned.",
            },
            "sort_by": {
                "type": "string",
                "enum": ["mtime", "path"],
                "default": "mtime",
                "description": "mtime: most recent first; path: alphabetical.",
            },
        },
        "required": ["pattern"],
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        pattern: str = args["pattern"]
        root = _safe_path(ctx.workspace, args.get("path", "."))
        if not root.exists():
            return ToolResult.error(f"path not found: {args.get('path', '.')}")
        if not root.is_dir():
            return ToolResult.error(f"not a directory: {root}")

        head_limit = int(args.get("head_limit", 100))
        sort_by = args.get("sort_by", "mtime")

        matches: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _DEFAULT_EXCLUDES]
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    rel = p.relative_to(root)
                except ValueError:
                    continue
                # 同时支持绝对 match 与相对 match（**/*.py 走相对）
                if rel.match(pattern) or p.match(pattern):
                    matches.append(p)

        total = len(matches)
        if sort_by == "mtime":
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        else:
            matches.sort()

        truncated = total > head_limit
        shown = matches[:head_limit]
        body = "\n".join(str(p) for p in shown) if shown else "(no matches)"
        if truncated:
            body += f"\n... (truncated, showing {head_limit}/{total})"

        return ToolResult.ok(
            body,
            mode=sort_by,
            total=total,
            shown=len(shown),
            truncated=truncated,
        )
