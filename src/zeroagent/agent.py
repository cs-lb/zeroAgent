"""Agent 门面：Provider 切换 + 对话 + 工具循环。

M1：统一对话入口、Provider 运行时切换。
M2：挂载工具（builtin / MCP / Skills / CLI），通过 ReAct 主循环执行任务。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Self

from zeroagent.config import AgentConfig, ProviderConfig, load_config
from zeroagent.core.loop import AgentLoop, EventCallback, RunResult
from zeroagent.llm.base import (
    BaseLLMProvider,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)
from zeroagent.llm.registry import build_provider
from zeroagent.skills import SkillSet, load_skills
from zeroagent.tools.base import Tool
from zeroagent.tools.policy import AlwaysAllowPolicy, Policy
from zeroagent.tools.registry import ToolRegistry


class Agent:
    """zeroAgent 的高层入口。"""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._providers: dict[str, BaseLLMProvider] = {}
        self._current: str = config.llm.default
        if self._current not in config.llm.providers:
            raise ValueError(
                f"default provider '{self._current}' not in providers: "
                f"{list(config.llm.providers)}"
            )
        # 工具系统
        self._registry: ToolRegistry = ToolRegistry()
        self._policy: Policy = AlwaysAllowPolicy()
        self._workspace: str = "."
        self._max_steps: int = 8
        # Skills
        self._skills: SkillSet = SkillSet()

    # ---------- 构造 ----------

    @classmethod
    def from_config(cls, path: str | Path) -> Self:
        return cls(load_config(path))

    # ---------- Provider 管理 ----------

    def use_llm(self, name: str) -> None:
        """运行时切换 Provider。"""
        if name not in self._config.llm.providers:
            raise ValueError(
                f"unknown provider '{name}', available: {list(self._config.llm.providers)}"
            )
        self._current = name

    @property
    def current_provider(self) -> str:
        return self._current

    def _get_provider(self) -> BaseLLMProvider:
        if self._current not in self._providers:
            cfg: ProviderConfig = self._config.llm.providers[self._current]
            self._providers[self._current] = build_provider(
                cfg.type,
                model=cfg.model,
                api_key=cfg.api_key or "",
                base_url=cfg.base_url or "https://api.openai.com/v1",
                timeout=cfg.timeout,
                **cfg.extra,
            )
        return self._providers[self._current]

    # ---------- 对话 ----------

    async def chat(
        self,
        prompt: str | list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatMessage:
        provider = self._get_provider()
        messages = self._build_messages(prompt, system)
        resp: ChatResponse = await provider.chat(
            ChatRequest(
                model=provider.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        return resp.message

    async def stream(
        self,
        prompt: str | list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ChatChunk]:
        provider = self._get_provider()
        messages = self._build_messages(prompt, system)
        async for chunk in provider.stream(
            ChatRequest(
                model=provider.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
        ):
            yield chunk

    @staticmethod
    def _build_messages(
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

    # ---------- 工具系统（M2） ----------

    @property
    def tools(self) -> ToolRegistry:
        return self._registry

    def register_tool(self, tool: Tool, *, override: bool = False) -> None:
        self._registry.register(tool, override=override)

    def register_tools(self, tools: list[Tool], *, override: bool = False) -> None:
        self._registry.register_many(tools, override=override)

    def enable_code_explorer(self, *, max_steps: int = 12, override: bool = True) -> None:
        """注册 `code_explorer` 子 Agent 工具。

        子 Agent 复用当前 Provider，专做"agentic 代码检索"——主 Agent 上下文
        不被几十次 grep/read 结果污染，只拿到子 Agent 的最终结论。

        注意：必须在 `use_llm` 切到目标 Provider 后调用，否则子 Agent 会绑定
        当前默认 Provider。需要换 Provider 时重新调用即可。
        """
        from zeroagent.tools.builtin.code_explorer import CodeExplorerTool

        tool = CodeExplorerTool(
            provider=self._get_provider(),
            policy=self._policy,
            default_max_steps=max_steps,
        )
        self._registry.register(tool, override=override)

    def use_policy(self, policy: Policy) -> None:
        self._policy = policy

    def configure(
        self,
        *,
        workspace: str | None = None,
        max_steps: int | None = None,
    ) -> None:
        if workspace is not None:
            self._workspace = workspace
        if max_steps is not None:
            self._max_steps = max_steps

    async def run(
        self,
        prompt: str | list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_steps: int | None = None,
    ) -> RunResult:
        """以 ReAct 主循环跑一个任务，自动调用已注册工具。"""
        loop = AgentLoop.build(
            provider=self._get_provider(),
            registry=self._registry,
            policy=self._policy,
            workspace=self._workspace,
            max_steps=max_steps if max_steps is not None else self._max_steps,
            temperature=temperature,
        )
        return await loop.run(prompt, system=self._compose_system(system))

    async def run_with_events(
        self,
        prompt: str | list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_steps: int | None = None,
        policy: Policy | None = None,
        on_event: EventCallback | None = None,
    ) -> RunResult:
        """带事件回调的 run（HTTP SSE 接口用）。

        - policy：可临时覆盖默认 policy（例如换成 AsyncApprovalPolicy）
        - on_event：收 step / tool_call_start / tool_call_result / policy_* 等事件
        """
        loop = AgentLoop.build(
            provider=self._get_provider(),
            registry=self._registry,
            policy=policy or self._policy,
            workspace=self._workspace,
            max_steps=max_steps if max_steps is not None else self._max_steps,
            temperature=temperature,
            on_event=on_event,
        )
        return await loop.run(prompt, system=self._compose_system(system))

    # ---------- Skills ----------

    @property
    def skills(self) -> SkillSet:
        return self._skills

    def load_skills(self, root: str | Path) -> int:
        """从目录加载 Skills，并自动注册 use_skill 元工具。

        返回加载到的 Skill 数量。
        """
        self._skills = load_skills(root)
        # 注册（或覆盖）use_skill 工具
        self._registry.register(self._skills.make_use_skill_tool(), override=True)
        return len(self._skills)

    def _compose_system(self, user_system: str | None) -> str | None:
        """把 skills 简介拼到 system prompt 前面。"""
        skill_block = self._skills.system_preamble()
        if not skill_block and not user_system:
            return None
        if not skill_block:
            return user_system
        if not user_system:
            return skill_block
        return f"{skill_block}\n\n---\n\n{user_system}"

    # ---------- 资源 ----------

    async def aclose(self) -> None:
        for p in self._providers.values():
            await p.aclose()
        self._providers.clear()
