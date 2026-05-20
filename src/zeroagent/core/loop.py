"""Agent 主循环（ReAct + Tool Use）。

伪代码：
    while step < max_steps:
        resp = llm.chat(messages, tools=registry.schemas())
        if resp.tool_calls:
            results = await gather(*[exec(c) for c in resp.tool_calls])
            messages += [resp.message, *results]
            continue
        return resp.message

特性：
- 同一轮多个 tool_call 并行执行
- 每个 tool_call 走 Policy 审批
- 完整 Trace（LLM + Policy + Tool）
- max_steps / 异常归一化
- 可选事件回调（on_event）：把 step / tool_call / policy 实时推给上层（HTTP SSE 等）
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from zeroagent.core.trace import Trace, step
from zeroagent.llm.base import (
    BaseLLMProvider,
    ChatMessage,
    ChatRequest,
    ToolCall,
)
from zeroagent.tools.base import ToolContext, ToolResult
from zeroagent.tools.policy import AlwaysAllowPolicy, Policy
from zeroagent.tools.registry import ToolRegistry

# 事件回调签名：(event_type, payload) -> awaitable | None
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class RunResult(BaseModel):
    """一次 run 的最终输出。"""

    message: ChatMessage
    steps: int = 0
    tool_calls: int = 0
    trace: Trace = Field(default_factory=Trace)
    stopped_reason: str = "final_answer"


@dataclass
class AgentLoop:
    """ReAct 主循环。"""

    provider: BaseLLMProvider
    registry: ToolRegistry
    policy: Policy
    workspace: str = "."
    max_steps: int = 8
    temperature: float = 0.3
    on_event: EventCallback | None = None

    @classmethod
    def build(
        cls,
        *,
        provider: BaseLLMProvider,
        registry: ToolRegistry,
        policy: Policy | None = None,
        workspace: str = ".",
        max_steps: int = 8,
        temperature: float = 0.3,
        on_event: EventCallback | None = None,
    ) -> AgentLoop:
        return cls(
            provider=provider,
            registry=registry,
            policy=policy or AlwaysAllowPolicy(),
            workspace=workspace,
            max_steps=max_steps,
            temperature=temperature,
            on_event=on_event,
        )

    async def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            ret = self.on_event(event, payload)
            if inspect.isawaitable(ret):
                await ret
        except Exception:  # noqa: BLE001 - 事件回调出错不应影响主流程
            pass

    async def run(
        self,
        prompt: str | list[ChatMessage],
        *,
        system: str | None = None,
    ) -> RunResult:
        trace = Trace()
        messages = self._init_messages(prompt, system)
        ctx = ToolContext(workspace=self.workspace, metadata={"trace_id": trace.trace_id})
        tool_calls_total = 0

        await self._emit("run_start", {
            "trace_id": trace.trace_id,
            "model": self.provider.model,
            "provider": self.provider.name,
            "tools": self.registry.names(),
            "max_steps": self.max_steps,
        })

        for step_idx in range(self.max_steps):
            await self._emit("step_start", {"step": step_idx})

            # ---------- LLM ----------
            req = ChatRequest(
                model=self.provider.model,
                messages=messages,
                temperature=self.temperature,
                tools=self.registry.schemas() or None,
            )
            with step(
                trace, "llm", "chat",
                model=self.provider.model,
                provider=self.provider.name,
                msg_count=len(messages),
            ) as s:
                resp = await self.provider.chat(req)
                s.output = {
                    "finish_reason": resp.finish_reason,
                    "usage": resp.usage.model_dump(),
                    "has_tool_calls": bool(resp.message.tool_calls),
                }

            assistant_msg = resp.message
            messages.append(assistant_msg)

            await self._emit("llm_message", {
                "step": step_idx,
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in (assistant_msg.tool_calls or [])
                ],
                "usage": resp.usage.model_dump(),
            })

            # ---------- 没工具调用 → 终止 ----------
            if not assistant_msg.tool_calls:
                await self._emit("done", {
                    "stopped_reason": "final_answer",
                    "steps": step_idx + 1,
                    "tool_calls": tool_calls_total,
                })
                return RunResult(
                    message=assistant_msg,
                    steps=step_idx + 1,
                    tool_calls=tool_calls_total,
                    trace=trace,
                    stopped_reason="final_answer",
                )

            # ---------- 工具调用：并行 ----------
            tool_calls_total += len(assistant_msg.tool_calls)
            results = await asyncio.gather(
                *[self._run_one_tool(tc, ctx, trace) for tc in assistant_msg.tool_calls]
            )
            messages.extend(results)

        # 超出步数
        await self._emit("done", {
            "stopped_reason": "max_steps",
            "steps": self.max_steps,
            "tool_calls": tool_calls_total,
        })
        return RunResult(
            message=messages[-1] if messages else ChatMessage(role="assistant", content=""),
            steps=self.max_steps,
            tool_calls=tool_calls_total,
            trace=trace,
            stopped_reason="max_steps",
        )

    # ---------- 内部 ----------

    async def _run_one_tool(
        self, tc: ToolCall, ctx: ToolContext, trace: Trace
    ) -> ChatMessage:
        tool = self.registry.get(tc.name)
        if tool is None:
            await self._emit("tool_error", {
                "id": tc.id, "name": tc.name, "error": "unknown_tool",
            })
            return self._tool_msg(tc, f"unknown tool: {tc.name}", is_error=True)

        # Policy 审批
        await self._emit("policy_check", {
            "id": tc.id,
            "name": tc.name,
            "side_effect": tool.side_effect,
            "requires_approval": tool.requires_approval,
            "arguments": tc.arguments,
        })
        with step(trace, "policy", tc.name, args=tc.arguments) as s:
            decision = await self.policy.check(tool, tc.arguments)
            s.output = {"decision": decision.decision, "reason": decision.reason}
        await self._emit("policy_decision", {
            "id": tc.id,
            "name": tc.name,
            "decision": decision.decision,
            "reason": decision.reason,
        })
        if not decision.allowed:
            return self._tool_msg(
                tc, f"denied by policy: {decision.reason}", is_error=True
            )

        # 执行
        await self._emit("tool_call_start", {
            "id": tc.id,
            "name": tc.name,
            "arguments": tc.arguments,
            "side_effect": tool.side_effect,
        })
        with step(trace, "tool", tc.name, args=tc.arguments) as s:
            result: ToolResult = await self.registry.invoke(tc.name, tc.arguments, ctx)
            s.output = {
                "is_error": result.is_error,
                "size": len(result.content),
                "metadata": result.metadata,
            }
            if result.is_error:
                s.error = result.content
        await self._emit("tool_call_result", {
            "id": tc.id,
            "name": tc.name,
            "is_error": result.is_error,
            "content": _truncate(result.content, 4000),
            "metadata": result.metadata,
        })
        return self._tool_msg(tc, result.content, is_error=result.is_error)

    @staticmethod
    def _tool_msg(tc: ToolCall, content: str, *, is_error: bool) -> ChatMessage:
        prefix = "[error] " if is_error else ""
        return ChatMessage(
            role="tool",
            content=f"{prefix}{content}",
            tool_call_id=tc.id,
            name=tc.name,
        )

    @staticmethod
    def _init_messages(
        prompt: str | list[ChatMessage], system: str | None
    ) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        if system:
            msgs.append(ChatMessage(role="system", content=system))
        if isinstance(prompt, str):
            msgs.append(ChatMessage(role="user", content=prompt))
        else:
            msgs.extend(prompt)
        return msgs


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[truncated {len(s) - limit} chars]"


__all__ = ["AgentLoop", "RunResult", "EventCallback"]
