"""Policy 层：控制工具调用是否被允许。

规则：
- side_effect == "none" / "read" 默认放行
- side_effect == "write" / "exec" 或 requires_approval=True 走审批
- 不同 Policy 实现对应不同运行模式（CI/交互式/严格沙箱）
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from zeroagent.tools.base import Tool

Decision = Literal["allow", "deny"]


@dataclass
class PolicyDecision:
    decision: Decision
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


class Policy(ABC):
    @abstractmethod
    async def check(self, tool: Tool, args: dict[str, Any]) -> PolicyDecision: ...


class AlwaysAllowPolicy(Policy):
    """全部放行。开发态默认。"""

    async def check(self, tool: Tool, args: dict[str, Any]) -> PolicyDecision:
        return PolicyDecision("allow", "always-allow")


class DenyPolicy(Policy):
    """对 write/exec 或 requires_approval 的工具一律拒绝。CI / 严格模式可用。"""

    async def check(self, tool: Tool, args: dict[str, Any]) -> PolicyDecision:
        if tool.side_effect in ("write", "exec") or tool.requires_approval:
            return PolicyDecision(
                "deny", f"denied by policy: side_effect={tool.side_effect}"
            )
        return PolicyDecision("allow")


class PromptPolicy(Policy):
    """命令行交互审批（仅在 TTY 下使用）。

    回调签名: prompt(tool, args) -> bool
    便于在测试里 mock。
    """

    def __init__(self, prompt_fn: Any | None = None) -> None:
        self._prompt = prompt_fn or self._default_prompt

    async def check(self, tool: Tool, args: dict[str, Any]) -> PolicyDecision:
        if tool.side_effect in ("none", "read") and not tool.requires_approval:
            return PolicyDecision("allow")
        ok = await self._call(self._prompt, tool, args)
        return PolicyDecision("allow" if ok else "deny", "user-prompt")

    @staticmethod
    async def _call(fn: Any, tool: Tool, args: dict[str, Any]) -> bool:
        import inspect

        if inspect.iscoroutinefunction(fn):
            return bool(await fn(tool, args))
        return bool(fn(tool, args))

    @staticmethod
    def _default_prompt(tool: Tool, args: dict[str, Any]) -> bool:
        print(f"\n[approval] tool={tool.name}  side_effect={tool.side_effect}")
        print(f"            args={args}")
        ans = input("approve? [y/N]: ").strip().lower()
        return ans in ("y", "yes")


# ---------- 异步审批：前端弹层 / IPC 等场景使用 ----------

ApprovalRequester = Callable[[Tool, dict[str, Any]], Awaitable[bool]]


class AsyncApprovalPolicy(Policy):
    """让 read 直接放行，write/exec 通过外部异步钩子询问决策。

    requester(tool, args) -> awaitable[bool]
    - True  → allow
    - False → deny
    - 抛异常或超时 → deny

    适用场景：HTTP /api/run/stream + /api/run/approve 的前后端审批配合。
    """

    def __init__(
        self,
        requester: ApprovalRequester,
        *,
        timeout_s: float = 120.0,
    ) -> None:
        self._requester = requester
        self._timeout_s = timeout_s

    async def check(self, tool: Tool, args: dict[str, Any]) -> PolicyDecision:
        if tool.side_effect in ("none", "read") and not tool.requires_approval:
            return PolicyDecision("allow")
        try:
            ok = await asyncio.wait_for(
                self._requester(tool, args), timeout=self._timeout_s
            )
        except asyncio.TimeoutError:
            return PolicyDecision("deny", "approval-timeout")
        except Exception as e:  # noqa: BLE001
            return PolicyDecision("deny", f"approval-error: {e}")
        return PolicyDecision("allow" if ok else "deny", "user-approval")
