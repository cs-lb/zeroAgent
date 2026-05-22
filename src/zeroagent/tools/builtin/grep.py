"""Grep 工具：仓库内容检索（优先 ripgrep，回退纯 Python）。

设计目标：对标 Claude Code 的 Grep 工具，让 LLM 通过精确正则匹配 + 多次
组合调用的方式高效检索代码，避免使用昂贵的向量索引。

关键策略写在 description 里，引导模型：
  - 先 files_with_matches 定位文件
  - 再 content 模式拿到上下文
  - 用 glob 缩范围、用 head_limit 控制输出
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from zeroagent.tools.base import Tool, ToolContext, ToolResult

# 默认排除目录（与 ripgrep 默认 .gitignore 行为协同；纯 Python 回退也用这套）
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


class GrepTool(Tool):
    name = "grep"
    description = (
        "Fast content search across files using ripgrep (with Python fallback).\n"
        "\n"
        "USAGE STRATEGY (READ THIS):\n"
        "- Use this for EXACT pattern / regex matching, not semantic search.\n"
        "- Prefer output_mode='files_with_matches' first to locate files,\n"
        "  then re-grep with output_mode='content' on the narrowed set.\n"
        "- Use `glob` to scope (e.g. '*.py', '**/*.ts') — much faster.\n"
        "- For large result sets use head_limit (default 50) and offset.\n"
        "- ALWAYS prefer this over reading whole files when you need to find\n"
        "  symbols, references, TODOs, or specific strings.\n"
        "\n"
        "Pattern is a regular expression (Rust regex when ripgrep is available;\n"
        "Python re otherwise). Escape special chars to do literal match.\n"
    )
    side_effect = "read"
    timeout_s = 30.0
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "default": ".",
                "description": "Directory (relative to workspace) to search in.",
            },
            "glob": {
                "type": "string",
                "description": "Glob filter, e.g. '*.py', '**/*.{ts,tsx}'.",
            },
            "output_mode": {
                "type": "string",
                "enum": ["files_with_matches", "content", "count"],
                "default": "files_with_matches",
                "description": (
                    "files_with_matches: only file paths (cheapest, use first); "
                    "content: matching lines with file:line:text; "
                    "count: per-file match counts."
                ),
            },
            "case_sensitive": {"type": "boolean", "default": False},
            "context_before": {
                "type": "integer",
                "default": 0,
                "description": "Lines of context before each match (content mode only).",
            },
            "context_after": {
                "type": "integer",
                "default": 0,
                "description": "Lines of context after each match (content mode only).",
            },
            "head_limit": {
                "type": "integer",
                "default": 50,
                "description": "Max lines/files in output. Use to avoid token blowup.",
            },
            "multiline": {
                "type": "boolean",
                "default": False,
                "description": "Allow . to match newline (rg -U). Content mode only.",
            },
        },
        "required": ["pattern"],
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        pattern: str = args["pattern"]
        path = _safe_path(ctx.workspace, args.get("path", "."))
        if not path.exists():
            return ToolResult.error(f"path not found: {args.get('path', '.')}")

        output_mode: str = args.get("output_mode", "files_with_matches")
        case_sensitive: bool = bool(args.get("case_sensitive", False))
        glob: str | None = args.get("glob")
        ctx_before: int = int(args.get("context_before", 0))
        ctx_after: int = int(args.get("context_after", 0))
        head_limit: int = int(args.get("head_limit", 50))
        multiline: bool = bool(args.get("multiline", False))

        rg = shutil.which("rg")
        if rg:
            return await self._run_ripgrep(
                rg,
                pattern=pattern,
                path=path,
                output_mode=output_mode,
                case_sensitive=case_sensitive,
                glob=glob,
                ctx_before=ctx_before,
                ctx_after=ctx_after,
                head_limit=head_limit,
                multiline=multiline,
            )
        # fallback
        return await asyncio.to_thread(
            self._run_python,
            pattern=pattern,
            path=path,
            output_mode=output_mode,
            case_sensitive=case_sensitive,
            glob=glob,
            head_limit=head_limit,
        )

    # ---------- ripgrep 实现 ----------

    async def _run_ripgrep(
        self,
        rg: str,
        *,
        pattern: str,
        path: Path,
        output_mode: str,
        case_sensitive: bool,
        glob: str | None,
        ctx_before: int,
        ctx_after: int,
        head_limit: int,
        multiline: bool,
    ) -> ToolResult:
        cmd: list[str] = [rg, "--no-config"]

        # 显式排除常见无关目录，行为与 Python fallback 对齐，
        # 避免依赖 .gitignore 是否存在导致 LLM 看到 .venv / node_modules 噪声。
        for d in _DEFAULT_EXCLUDES:
            cmd.extend(["-g", f"!**/{d}/**"])

        if not case_sensitive:
            cmd.append("-i")
        if glob:
            cmd.extend(["-g", glob])

        if output_mode == "files_with_matches":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        else:  # content
            cmd.extend(["-n", "-H"])  # 行号 + 文件名
            if ctx_before:
                cmd.extend(["-B", str(ctx_before)])
            if ctx_after:
                cmd.extend(["-A", str(ctx_after)])
            if multiline:
                cmd.extend(["-U", "--multiline-dotall"])

        cmd.extend(["--", pattern, str(path)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=25.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult.error("grep: ripgrep timeout (25s)")

        # rg 退出码: 0=有匹配, 1=无匹配, 2=错误
        if proc.returncode == 1:
            return ToolResult.ok(
                "(no matches)",
                engine="ripgrep",
                matches=0,
            )
        if proc.returncode not in (0, 1):
            err = stderr_b.decode("utf-8", errors="replace").strip()
            return ToolResult.error(f"grep: ripgrep failed: {err or proc.returncode}")

        text = stdout_b.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        truncated = total > head_limit
        if truncated:
            lines = lines[:head_limit]

        body = "\n".join(lines)
        suffix = f"\n... (truncated, showing {head_limit}/{total})" if truncated else ""

        return ToolResult.ok(
            body + suffix if body else "(no matches)",
            engine="ripgrep",
            mode=output_mode,
            total=total,
            shown=len(lines),
            truncated=truncated,
        )

    # ---------- Python fallback ----------

    def _run_python(
        self,
        *,
        pattern: str,
        path: Path,
        output_mode: str,
        case_sensitive: bool,
        glob: str | None,
        head_limit: int,
    ) -> ToolResult:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult.error(f"grep: invalid regex: {e}")

        if path.is_file():
            files = [path]
        else:
            files = self._collect_files(path, glob)

        out_lines: list[str] = []
        per_file_count: dict[str, int] = {}
        files_with: list[str] = []
        total_matches = 0

        for f in files:
            try:
                if not f.is_file():
                    continue
                # 跳过明显的二进制
                with f.open("rb") as fh:
                    head = fh.read(2048)
                if b"\x00" in head:
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            file_matches = 0
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    file_matches += 1
                    total_matches += 1
                    if output_mode == "content":
                        out_lines.append(f"{f}:{i}:{line}")
                        if len(out_lines) >= head_limit:
                            break
            if file_matches:
                files_with.append(str(f))
                per_file_count[str(f)] = file_matches
            if output_mode == "content" and len(out_lines) >= head_limit:
                break

        if output_mode == "files_with_matches":
            shown = files_with[:head_limit]
            body = "\n".join(shown) if shown else "(no matches)"
            return ToolResult.ok(
                body,
                engine="python",
                mode=output_mode,
                total=len(files_with),
                shown=len(shown),
                truncated=len(files_with) > head_limit,
            )
        if output_mode == "count":
            items = sorted(per_file_count.items(), key=lambda x: -x[1])[:head_limit]
            body = "\n".join(f"{p}:{c}" for p, c in items) if items else "(no matches)"
            return ToolResult.ok(body, engine="python", mode=output_mode, total=len(per_file_count))
        # content
        body = "\n".join(out_lines) if out_lines else "(no matches)"
        return ToolResult.ok(
            body,
            engine="python",
            mode=output_mode,
            total=total_matches,
            shown=len(out_lines),
        )

    def _collect_files(self, root: Path, glob: str | None) -> list[Path]:
        """递归收集文件，自动跳过常见无关目录。"""
        out: list[Path] = []
        if root.is_file():
            return [root]

        # 用 os.walk 才能在过程中剪枝
        import os

        for dirpath, dirnames, filenames in os.walk(root):
            # 原地修改 dirnames 以剪枝
            dirnames[:] = [d for d in dirnames if d not in _DEFAULT_EXCLUDES]
            for fn in filenames:
                p = Path(dirpath) / fn
                if glob:
                    if not p.match(glob):
                        # 兜底：尝试相对 root 的 match（兼容 **/*.py 这种）
                        try:
                            rel = p.relative_to(root)
                        except ValueError:
                            continue
                        if not rel.match(glob):
                            continue
                out.append(p)
        return out
