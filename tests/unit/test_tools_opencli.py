"""OpenCliTool 测试：分类逻辑 + subprocess 集成（mock 二进制）。

不依赖本机是否真装了 `opencli` —— 全部用 monkeypatch 把
`shutil.which` 和 `asyncio.create_subprocess_exec` 替换成可控行为。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from zeroagent.tools import ToolContext
from zeroagent.tools.builtin.opencli import OpenCliTool, _classify


# ---------- 纯函数：命令分类 ----------


@pytest.mark.parametrize(
    "argv, expected_category",
    [
        # 顶层只读
        (["list"], "read"),
        (["doctor"], "read"),
        (["--version"], "read"),
        # 站点适配器：读
        (["hackernews", "top"], "read"),
        (["bilibili", "hot", "--limit", "5"], "read"),
        (["zhihu", "search", "--query", "x"], "read"),
        (["twitter", "timeline"], "read"),
        # 站点适配器：写
        (["twitter", "post", "--text", "hi"], "write"),
        (["zhihu", "comment", "--id", "1"], "write"),
        (["reddit", "upvote", "--id", "x"], "write"),
        (["bilibili", "download", "BV1xxx"], "write"),
        # browser：读类动词
        (["browser", "work", "open", "https://x.com"], "read"),
        (["browser", "work", "state"], "read"),
        (["browser", "work", "extract", "div"], "read"),
        # browser：写类动词
        (["browser", "work", "click", "button"], "write"),
        (["browser", "work", "type", "input", "x"], "write"),
        # browser：危险读
        (["browser", "work", "eval", "1+1"], "read_dangerous"),
        # browser tab list/select：读
        (["browser", "work", "tab", "list"], "read"),
        (["browser", "work", "tab", "select", "id"], "read"),
        # browser tab new/close：写
        (["browser", "work", "tab", "new"], "write"),
        (["browser", "work", "tab", "close"], "write"),
        # 不认识 → unknown
        (["mystery", "wat"], "unknown"),
        (["browser", "work", "wat"], "unknown"),
    ],
)
def test_classify(argv: list[str], expected_category: str) -> None:
    cat, _verb = _classify(argv)
    assert cat == expected_category, f"argv={argv} got={cat}"


def test_classify_empty_args() -> None:
    cat, verb = _classify([])
    assert cat == "unknown"
    assert verb == ""


# ---------- 工具实例：兜底拦截写命令 ----------


@pytest.mark.asyncio
async def test_invoke_refuses_write_when_not_approval() -> None:
    """默认 requires_approval=False，写命令必须被拒绝。"""
    tool = OpenCliTool()
    assert tool.requires_approval is False
    res = await tool.invoke(
        {"args": ["twitter", "post", "--text", "hi"]},
        ToolContext(workspace="."),
    )
    assert res.is_error
    assert "refused" in res.content
    assert "write" in res.content


@pytest.mark.asyncio
async def test_invoke_refuses_unknown_when_not_approval() -> None:
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["nosuchsite", "weirdverb"]},
        ToolContext(workspace="."),
    )
    assert res.is_error
    assert "unknown" in res.content


@pytest.mark.asyncio
async def test_invoke_refuses_eval_when_not_approval() -> None:
    """browser eval 可执行 JS → 必须强制审批；默认拒绝。"""
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["browser", "work", "eval", "1+1"]},
        ToolContext(workspace="."),
    )
    assert res.is_error
    assert "read_dangerous" in res.content


@pytest.mark.asyncio
async def test_empty_args() -> None:
    tool = OpenCliTool()
    res = await tool.invoke({"args": []}, ToolContext(workspace="."))
    assert res.is_error
    assert "non-empty" in res.content


@pytest.mark.asyncio
async def test_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zeroagent.tools.builtin.opencli.shutil.which", lambda _: None)
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["list"]},
        ToolContext(workspace="."),
    )
    assert res.is_error
    assert "binary not found" in res.content


# ---------- subprocess 集成：mock create_subprocess_exec ----------


class _FakeProc:
    """模拟 asyncio.subprocess.Process。"""

    def __init__(self, *, stdout: bytes, stderr: bytes, returncode: int) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode: int | None = returncode
        self._killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        self._killed = True

    async def wait(self) -> int:
        return self.returncode or 0


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
    capture: dict[str, Any] | None = None,
) -> None:
    """把 opencli 模块里的 shutil.which + create_subprocess_exec 都替换。"""
    monkeypatch.setattr(
        "zeroagent.tools.builtin.opencli.shutil.which",
        lambda _: "/usr/local/bin/opencli",
    )

    async def fake_exec(*cmd: str, **_kwargs: Any) -> _FakeProc:
        if capture is not None:
            capture["cmd"] = list(cmd)
        return _FakeProc(stdout=stdout, stderr=stderr, returncode=returncode)

    monkeypatch.setattr(
        "zeroagent.tools.builtin.opencli.asyncio.create_subprocess_exec",
        fake_exec,
    )


@pytest.mark.asyncio
async def test_run_list_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict[str, Any] = {}
    _patch_subprocess(
        monkeypatch,
        stdout=b"hackernews\nbilibili\nzhihu\n",
        returncode=0,
        capture=capture,
    )
    tool = OpenCliTool()
    res = await tool.invoke({"args": ["list"]}, ToolContext(workspace="."))
    assert not res.is_error
    assert "bilibili" in res.content
    assert res.metadata["exit_code"] == 0
    assert res.metadata["category"] == "read"
    # list 是 meta 命令，不应该追加 -f json
    assert "-f" not in capture["cmd"]


@pytest.mark.asyncio
async def test_run_appends_format_for_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict[str, Any] = {}
    _patch_subprocess(
        monkeypatch,
        stdout=b'[{"title":"hi"}]',
        returncode=0,
        capture=capture,
    )
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["hackernews", "top", "--limit", "3"], "format": "json"},
        ToolContext(workspace="."),
    )
    assert not res.is_error
    # 应自动追加 -f json
    assert "-f" in capture["cmd"]
    assert "json" in capture["cmd"]


@pytest.mark.asyncio
async def test_run_respects_user_format_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户已经在 args 里给了 -f，工具就不应再追加。"""
    capture: dict[str, Any] = {}
    _patch_subprocess(monkeypatch, stdout=b"ok", returncode=0, capture=capture)
    tool = OpenCliTool()
    await tool.invoke(
        {"args": ["bilibili", "hot", "-f", "md"], "format": "json"},
        ToolContext(workspace="."),
    )
    # 只能出现一次 -f
    assert capture["cmd"].count("-f") == 1
    assert "md" in capture["cmd"]
    assert "json" not in capture["cmd"]


@pytest.mark.asyncio
async def test_run_no_data_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, stdout=b"", returncode=66)
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["hackernews", "search", "--query", "no-such-thing"]},
        ToolContext(workspace="."),
    )
    # 66 = no-data 视为成功（空结果），不是错误
    assert not res.is_error
    assert res.metadata["exit_code"] == 66
    assert res.metadata["exit_hint"] == "no-data"


@pytest.mark.asyncio
async def test_run_extension_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(
        monkeypatch,
        stdout=b"",
        stderr=b"Extension not connected",
        returncode=69,
    )
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["bilibili", "hot"]},
        ToolContext(workspace="."),
    )
    assert res.is_error
    assert "browser-bridge-not-connected" in res.content
    assert res.metadata["exit_code"] == 69


@pytest.mark.asyncio
async def test_run_auth_required(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, stderr=b"401 Unauthorized", returncode=77)
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["zhihu", "hot"]},
        ToolContext(workspace="."),
    )
    assert res.is_error
    assert "auth-required" in res.content


@pytest.mark.asyncio
async def test_run_truncates_output(monkeypatch: pytest.MonkeyPatch) -> None:
    big = b"x" * 50_000
    _patch_subprocess(monkeypatch, stdout=big, returncode=0)
    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["hackernews", "top"], "max_chars": 1000},
        ToolContext(workspace="."),
    )
    assert not res.is_error
    assert res.metadata["truncated"] is True
    assert "(truncated)" in res.content
    # 截断后正文 + 标记 ≈ 1000 + 一行尾标
    assert len(res.content) < 1100


@pytest.mark.asyncio
async def test_run_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟超时：communicate 永远 sleep。"""
    monkeypatch.setattr(
        "zeroagent.tools.builtin.opencli.shutil.which",
        lambda _: "/usr/local/bin/opencli",
    )

    class _SlowProc:
        returncode: int | None = None

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(10)
            return b"", b""

        def kill(self) -> None:
            self.returncode = -9

        async def wait(self) -> int:
            return -9

    async def fake_exec(*_cmd: str, **_kwargs: Any) -> _SlowProc:
        return _SlowProc()

    monkeypatch.setattr(
        "zeroagent.tools.builtin.opencli.asyncio.create_subprocess_exec", fake_exec
    )

    tool = OpenCliTool()
    res = await tool.invoke(
        {"args": ["bilibili", "hot"], "timeout_s": 0.1},
        ToolContext(workspace="."),
    )
    assert res.is_error
    assert "timeout" in res.content


# ---------- approval 模式：写命令放行 ----------


@pytest.mark.asyncio
async def test_write_passes_when_requires_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """如果工具被声明为 requires_approval=True（上层 Policy 会弹审批），
    写命令在工具内部分类闸门处不再被一票否决。"""
    _patch_subprocess(monkeypatch, stdout=b"posted", returncode=0)
    tool = OpenCliTool()
    tool.requires_approval = True  # 模拟上层把这个工具声明成"需审批"
    res = await tool.invoke(
        {"args": ["twitter", "post", "--text", "hi"]},
        ToolContext(workspace="."),
    )
    assert not res.is_error
    assert res.metadata["category"] == "write"
