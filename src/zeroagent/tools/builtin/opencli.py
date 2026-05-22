"""OpenCLI 工具：通过 `@jackwener/opencli` 命令行获取网页内容 / 操控浏览器。

设计要点
========
- **只读优先**：默认仅放行公开数据读取类命令（hot/search/top/state/extract...），
  写操作（post/publish/like/follow/comment/...）默认拒绝；如需允许，把工具的
  `requires_approval` 与具体子命令交给上层 Policy 审批。
- **退出码语义**（来自 opencli docs，sysexits.h 派生）：
    0   成功
    66  无数据
    69  Browser Bridge 未连接
    75  超时
    77  需要认证（登录态过期）
    78  配置错误
    130 Ctrl-C
- **不解析子命令语义**：opencli 子命令几百个，本工具不试图维护"哪个站点有哪些
  子命令"的清单——只在"动作动词层"做白/黑名单（read-only verbs / write verbs），
  避免信息过期。
- **超时与僵尸**：`asyncio.wait_for` + `proc.kill() + await proc.wait()`。

使用示例（LLM 视角）
====================
- 读 HackerNews Top 10 JSON：
    {"args": ["hackernews", "top", "--limit", "10"], "format": "json"}
- 读 B 站热门 Markdown：
    {"args": ["bilibili", "hot", "--limit", "5"], "format": "md"}
- 列出全部命令：
    {"args": ["list"]}
- 健康检查：
    {"args": ["doctor"]}
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from zeroagent.tools.base import Tool, ToolContext, ToolResult

# ---------- 命令分类 ----------

# 顶层只读子命令（不属于"站点适配器"那一档，但也是只读）
_TOP_LEVEL_READ = {"list", "doctor", "help", "--help", "-h", "--version", "-v"}

# 适配器/浏览器层的"读取类动词"：动作动词命中即视为只读
_READ_VERBS = {
    # 通用读
    "list",
    "get",
    "read",
    "detail",
    "state",
    "extract",
    "find",
    "frames",
    "screenshot",
    "history",
    "feed",
    "timeline",
    "trending",
    "top",
    "hot",
    "new",
    "best",
    "ask",
    "show",
    "jobs",
    "search",
    "ranking",
    "rankings",
    "bestsellers",
    "summary",
    "subtitle",
    "thread",
    "question",
    "answer",  # zhihu answer 是读
    "user",
    "user-videos",
    "people-search",
    "profile",
    "frontpage",
    "popular",
    "subreddit",
    "favorite",  # 读收藏列表
    "bookmarks",
    "notifications",
    "notebook",
    "creator-stats",
    "creator-notes",
    "current",
    "note",
    "note-list",
    "source-list",
    "comments",
    "dynamic",
    "following",
    "followers",
    "me",
    "inbox",
    "status",
    "open",  # browser open 是读类（只是打开页面，不提交表单）
    "wait",
    "verify",
    "init",
    "scroll",
    "back",
    "eval",  # browser eval：本质是读，但能跑 JS → 提升一档审批
    "network",
}

# 明确写/有副作用动词：默认拒绝（除非用户层面把工具开成 requires_approval）
_WRITE_VERBS = {
    "post",
    "publish",
    "send",
    "safe-send",
    "reply",
    "like",
    "unlike",
    "follow",
    "unfollow",
    "subscribe",
    "unsubscribe",
    "connect",
    "block",
    "comment",
    "save",  # reddit save 算写（改变账号状态）
    "upvote",
    "downvote",
    "click",  # 点击会触发表单提交/状态变更
    "type",
    "fill",
    "select",
    "keys",
    "close",  # 关闭 session/tab
    "download",  # 下载落盘 → side_effect=write
    "transcript",  # 同上
    "register",  # external register
    "uninstall",
    "install",
    "update",
    "eject",
    "reset",
}

# 需要单独提一档审批的"读但能执行任意 JS"
_DANGEROUS_READ_VERBS = {"eval"}


def _classify(args: list[str]) -> tuple[str, str]:
    """根据 args 推断 (类别, 命中的动词)。

    类别：
      - "read":          公开/账号读，免审批
      - "read_dangerous": 读但能跑 JS（browser eval），强制审批
      - "write":         写/有副作用，强制审批
      - "unknown":       识别不出来 → 走审批兜底
    """
    if not args:
        return "unknown", ""

    head = args[0]
    if head in _TOP_LEVEL_READ:
        return "read", head

    # opencli browser <session> <verb> ...
    if head == "browser":
        # browser <session> <verb>
        if len(args) >= 3:
            verb = args[2]
        elif len(args) == 2:
            # browser <session> 这种不完整命令
            return "unknown", ""
        else:
            return "unknown", ""
        if verb in _DANGEROUS_READ_VERBS:
            return "read_dangerous", verb
        if verb in _WRITE_VERBS:
            return "write", verb
        if verb in _READ_VERBS:
            return "read", verb
        # browser tab list / browser tab new ...
        if verb == "tab" and len(args) >= 4:
            sub = args[3]
            if sub in {"list", "select"}:
                return "read", f"tab {sub}"
            if sub in {"new", "close"}:
                return "write", f"tab {sub}"
        return "unknown", verb

    # 站点适配器：opencli <site> <verb> ...
    if len(args) >= 2:
        verb = args[1]
        if verb in _DANGEROUS_READ_VERBS:
            return "read_dangerous", verb
        if verb in _WRITE_VERBS:
            return "write", verb
        if verb in _READ_VERBS:
            return "read", verb
        return "unknown", verb

    return "unknown", head


# ---------- 退出码 ----------

_EXIT_HINT = {
    0: "ok",
    66: "no-data",
    69: "browser-bridge-not-connected",
    75: "timeout",
    77: "auth-required (登录态过期，请到 Chrome 重新登录)",
    78: "config-error",
    130: "interrupted",
}


class OpenCliTool(Tool):
    name = "opencli"
    description = (
        "Run the local `opencli` CLI to fetch web content from popular sites "
        "(hackernews/bilibili/zhihu/twitter/reddit/...) using the user's existing "
        "browser login session, OR drive Chrome via `opencli browser <session> ...`.\n"
        "\n"
        "READ-ONLY by default. Side-effecting verbs (post/publish/send/like/follow/"
        "comment/click/type/fill/download/...) require user approval per Policy.\n"
        "\n"
        "USAGE TIPS:\n"
        "- Pass argv as a string array, e.g. args=['hackernews','top','--limit','10'].\n"
        "- Prefer format='json' for machine-readable output (default).\n"
        "- Common read examples:\n"
        "    args=['list']                            -> list all available commands\n"
        "    args=['doctor']                          -> environment health check\n"
        "    args=['hackernews','top','--limit','5']  -> HN top 5\n"
        "    args=['bilibili','hot','--limit','10']   -> Bilibili hot 10\n"
        "    args=['zhihu','search','--query','LLM']  -> zhihu search\n"
        "    args=['twitter','timeline','--limit','20']\n"
        "- Exit-code semantics: 0 ok, 66 no-data, 69 extension not connected, "
        "75 timeout, 77 needs login, 78 config error.\n"
    )
    side_effect = "read"  # 默认只读；动态根据 args 升级到 "write"
    timeout_s = 90.0  # 含浏览器交互，给宽一点；外层还有 wait_for 兜底
    input_schema = {
        "type": "object",
        "properties": {
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "Argv to pass to opencli (without the leading 'opencli'). "
                    "Example: ['bilibili','hot','--limit','5']."
                ),
            },
            "format": {
                "type": "string",
                "enum": ["json", "md", "yaml", "csv", "table"],
                "default": "json",
                "description": (
                    "Output format. Default 'json' (best for LLM). Adapter must "
                    "support `-f`; if it doesn't, omit by passing format='' (empty)."
                ),
            },
            "max_chars": {
                "type": "integer",
                "default": 16_000,
                "description": "Truncate stdout to this many chars to control tokens.",
            },
            "timeout_s": {
                "type": "number",
                "default": 60.0,
                "description": "Per-call timeout in seconds (also bounded by tool timeout_s).",
            },
        },
        "required": ["args"],
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        argv: list[str] = list(args.get("args") or [])
        if not argv:
            return ToolResult.error("opencli: 'args' must be a non-empty string array")

        # 安全分类
        category, verb = _classify(argv)
        if category in ("write", "read_dangerous", "unknown"):
            # 这些类别要求工具被声明为 requires_approval 才允许跑。
            # 由上层 Policy 真正弹审批；这里只是兜底校验。
            if not self.requires_approval:
                return ToolResult.error(
                    f"opencli: refused — verb '{verb or argv[0]}' is "
                    f"classified as '{category}'. To allow, run this tool under an "
                    "approval-required policy (set requires_approval=True), or use a "
                    "read-only verb. See description for safe examples."
                )

        bin_path = shutil.which("opencli")
        if not bin_path:
            return ToolResult.error(
                "opencli: binary not found in PATH. Install via "
                "`npm install -g @jackwener/opencli` (requires Node.js >= 20)."
            )

        fmt = args.get("format", "json")
        max_chars = int(args.get("max_chars", 16_000))
        per_call_timeout = float(args.get("timeout_s", 60.0))

        cmd: list[str] = [bin_path, *argv]
        # 只有当用户没自己加 -f / --format 时，才追加 format
        if fmt and not _has_format_flag(argv) and not _is_meta_command(argv):
            cmd.extend(["-f", fmt])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=per_call_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult.error(
                f"opencli: command timeout after {per_call_timeout}s "
                f"(cmd: {' '.join(argv)})"
            )

        rc = proc.returncode if proc.returncode is not None else -1
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace").strip()
        hint = _EXIT_HINT.get(rc, f"exit {rc}")

        # 截断 stdout
        truncated = len(stdout) > max_chars
        body = stdout[:max_chars] + ("\n... (truncated)" if truncated else "")

        meta: dict[str, Any] = {
            "exit_code": rc,
            "exit_hint": hint,
            "verb": verb,
            "category": category,
            "format": fmt or None,
            "truncated": truncated,
            "stdout_size": len(stdout),
        }
        if stderr:
            meta["stderr"] = stderr[:2000]

        if rc == 0:
            return ToolResult.ok(body or "(empty)", **meta)
        if rc == 66:
            return ToolResult.ok("(no data)", **meta)
        # 其它非零：业务/环境错误
        msg = body.strip() or stderr or hint
        return ToolResult.error(f"opencli failed [{hint}]: {msg}", **meta)


def _has_format_flag(argv: list[str]) -> bool:
    for i, a in enumerate(argv):
        if a in ("-f", "--format"):
            return True
        if a.startswith("--format="):
            return True
    return False


def _is_meta_command(argv: list[str]) -> bool:
    """元命令（list/doctor/help/版本/插件管理）不接受 -f。"""
    if not argv:
        return False
    head = argv[0]
    return head in {"list", "doctor", "help", "plugin", "external", "adapter"} or head.startswith(
        "-"
    )
