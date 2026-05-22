"""grep / glob / fs_read 升级后的检索工具测试。

同时覆盖 ripgrep 路径与 Python fallback：当本机有 rg 时走真子进程，
没有时自动走纯 Python 实现。两条路径产物结构一致。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from zeroagent.tools import ToolContext
from zeroagent.tools.builtin import GlobTool, GrepTool
from zeroagent.tools.builtin.fs import FsReadTool


# ---------- 共用 fixture ----------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """构造一个迷你仓库：含多种语言、嵌套目录、需被忽略的目录。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def hello():\n    print('hello world')\n\nclass Agent:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "util.py").write_text(
        "def helper():\n    return 'agent helper'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "lib.ts").write_text(
        "export class Agent {}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text(
        "from src.main import Agent\n\ndef test_agent():\n    assert Agent\n",
        encoding="utf-8",
    )
    # 应被自动剪枝的目录
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "noise.py").write_text("class Agent: pass\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "trash.js").write_text("class Agent {}\n", encoding="utf-8")
    return tmp_path


# ---------- grep ----------


@pytest.mark.asyncio
async def test_grep_files_with_matches(repo: Path) -> None:
    tool = GrepTool()
    ctx = ToolContext(workspace=str(repo))
    res = await tool.invoke(
        {"pattern": r"class\s+Agent", "output_mode": "files_with_matches"},
        ctx,
    )
    assert res.is_error is False
    # 应命中 src/main.py、src/lib.ts、tests/test_main.py 中的引用
    # 但不应命中 .venv / node_modules 下的同名内容
    assert "main.py" in res.content
    assert ".venv" not in res.content
    assert "node_modules" not in res.content


@pytest.mark.asyncio
async def test_grep_content_mode_with_line_numbers(repo: Path) -> None:
    tool = GrepTool()
    ctx = ToolContext(workspace=str(repo))
    res = await tool.invoke(
        {"pattern": "hello world", "output_mode": "content"},
        ctx,
    )
    assert res.is_error is False
    # ripgrep 与 fallback 输出都包含 file:line:text 三段
    assert "main.py" in res.content
    assert "hello world" in res.content
    # 行号格式存在（":2:" 或类似）
    assert any(seg.isdigit() for seg in res.content.replace(":", " ").split())


@pytest.mark.asyncio
async def test_grep_glob_filter(repo: Path) -> None:
    tool = GrepTool()
    ctx = ToolContext(workspace=str(repo))
    res = await tool.invoke(
        {
            "pattern": "Agent",
            "glob": "*.ts",
            "output_mode": "files_with_matches",
        },
        ctx,
    )
    assert res.is_error is False
    assert "lib.ts" in res.content
    assert "main.py" not in res.content


@pytest.mark.asyncio
async def test_grep_no_match(repo: Path) -> None:
    tool = GrepTool()
    ctx = ToolContext(workspace=str(repo))
    res = await tool.invoke(
        {"pattern": "definitely_not_in_any_file_xyz", "output_mode": "files_with_matches"},
        ctx,
    )
    assert res.is_error is False
    assert "no matches" in res.content.lower()


@pytest.mark.asyncio
async def test_grep_path_escape_blocked(tmp_path: Path) -> None:
    tool = GrepTool()
    ctx = ToolContext(workspace=str(tmp_path))
    res = await tool.safe_invoke({"pattern": "x", "path": "../../etc"}, ctx)
    assert res.is_error
    assert "escape" in res.content.lower() or "grep" in res.content.lower()


@pytest.mark.asyncio
async def test_grep_python_fallback(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """强制走 Python 路径，验证 fallback 也能工作。"""
    tool = GrepTool()
    ctx = ToolContext(workspace=str(repo))
    monkeypatch.setattr(shutil, "which", lambda *_a, **_kw: None)
    res = await tool.invoke(
        {"pattern": "hello world", "output_mode": "content"},
        ctx,
    )
    assert res.is_error is False
    assert res.metadata.get("engine") == "python"
    assert "hello world" in res.content


# ---------- glob ----------


@pytest.mark.asyncio
async def test_glob_basic(repo: Path) -> None:
    tool = GlobTool()
    ctx = ToolContext(workspace=str(repo))
    res = await tool.invoke({"pattern": "**/*.py"}, ctx)
    assert res.is_error is False
    # 仓库内三个 .py 都应出现，且 .venv 下的不应出现
    for f in ("main.py", "util.py", "test_main.py"):
        assert f in res.content
    assert ".venv" not in res.content


@pytest.mark.asyncio
async def test_glob_head_limit(repo: Path) -> None:
    tool = GlobTool()
    ctx = ToolContext(workspace=str(repo))
    res = await tool.invoke({"pattern": "**/*.py", "head_limit": 1}, ctx)
    assert res.is_error is False
    assert res.metadata["truncated"] is True
    assert res.metadata["shown"] == 1


@pytest.mark.asyncio
async def test_glob_no_match(repo: Path) -> None:
    tool = GlobTool()
    ctx = ToolContext(workspace=str(repo))
    res = await tool.invoke({"pattern": "**/*.rs"}, ctx)
    assert res.is_error is False
    assert "no matches" in res.content.lower()


# ---------- fs_read 升级 ----------


@pytest.mark.asyncio
async def test_fs_read_with_line_numbers(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

    tool = FsReadTool()
    ctx = ToolContext(workspace=str(tmp_path))
    res = await tool.invoke({"path": "x.py"}, ctx)
    assert res.is_error is False
    # 行号前缀（右对齐宽度 4）
    assert "   1:a" in res.content
    assert "   5:e" in res.content
    assert res.metadata["total_lines"] == 5


@pytest.mark.asyncio
async def test_fs_read_offset_limit(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8")

    tool = FsReadTool()
    ctx = ToolContext(workspace=str(tmp_path))
    res = await tool.invoke({"path": "x.py", "offset": 5, "limit": 3}, ctx)
    assert res.is_error is False
    assert "line5" in res.content
    assert "line7" in res.content
    assert "line8" not in res.content
    # 应提示如何继续
    assert "offset=8" in res.content
    assert res.metadata["shown_lines"] == 3
