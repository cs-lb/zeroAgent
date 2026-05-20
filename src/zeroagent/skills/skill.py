"""Skill 数据模型 + use_skill 元工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zeroagent.tools.base import Tool, ToolContext, ToolResult


@dataclass
class Skill:
    """一个技能包。

    name / description / when_to_use 用于 system prompt（省 token）。
    body 仅在 use_skill 调用后才注入到对话。
    """

    name: str
    description: str
    when_to_use: str = ""
    body: str = ""
    path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def headline(self) -> str:
        """system prompt 中展示的一行摘要。"""
        parts = [f"- **{self.name}**: {self.description}"]
        if self.when_to_use:
            parts.append(f"  · when_to_use: {self.when_to_use}")
        return "\n".join(parts)


class SkillSet:
    """skills 集合 + system prompt 拼装。"""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        for s in skills or []:
            self.add(s)

    def add(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def system_preamble(self) -> str:
        """注入到 system prompt 的简介段（不含 body）。"""
        if not self._skills:
            return ""
        lines = [
            "你具备以下 Skill（按需通过 `use_skill(name=\"…\")` 工具加载完整指令）：",
        ]
        for s in self._skills.values():
            lines.append(s.headline())
        lines.append(
            "调用 use_skill 后，你会在对话中看到该 Skill 的完整指令，请严格按照指令完成任务。"
        )
        return "\n".join(lines)

    def make_use_skill_tool(self) -> Tool:
        """返回一个 use_skill 工具，让 LLM 按需把 body 装载到上下文。"""
        return _UseSkillTool(self)


class _UseSkillTool(Tool):
    name = "use_skill"
    description = (
        "Load the full instruction body of a registered Skill by its name. "
        "Call this BEFORE attempting tasks that match a skill's when_to_use. "
        "Returns the markdown body which you must follow strictly."
    )
    side_effect = "read"
    timeout_s = 5.0
    requires_approval = False

    def __init__(self, skill_set: SkillSet) -> None:
        self._skills = skill_set
        self.input_schema = {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name. One of: " + ", ".join(skill_set.names()) or "(none)",
                    "enum": skill_set.names() or None,
                }
            },
            "required": ["name"],
        }
        # enum 为空数组时去掉，避免某些 provider 严格校验
        if not skill_set.names():
            self.input_schema["properties"]["name"].pop("enum", None)

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = (args.get("name") or "").strip()
        if not name:
            return ToolResult.error("argument 'name' is required")
        skill = self._skills.get(name)
        if skill is None:
            return ToolResult.error(
                f"unknown skill: {name}. available: {self._skills.names()}"
            )
        body = skill.body.strip() or skill.description
        header = f"# Skill: {skill.name}\n\n{skill.description}\n"
        if skill.when_to_use:
            header += f"\n_when_to_use_: {skill.when_to_use}\n"
        return ToolResult.ok(
            f"{header}\n---\n\n{body}",
            skill=name,
            body_chars=len(body),
        )


__all__ = ["Skill", "SkillSet"]
