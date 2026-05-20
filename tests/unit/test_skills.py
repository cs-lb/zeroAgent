"""Skills loader / SkillSet / use_skill 工具单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from zeroagent.skills import SkillSet, load_skills
from zeroagent.skills.loader import parse_skill_md
from zeroagent.skills.skill import Skill
from zeroagent.tools.base import ToolContext


def test_parse_skill_md_with_front_matter():
    content = """---
name: pdf-extract
description: extract pdf text
when_to_use: 用户给 .pdf
---

# Body

step 1
"""
    skill = parse_skill_md(content)
    assert skill.name == "pdf-extract"
    assert skill.description == "extract pdf text"
    assert skill.when_to_use == "用户给 .pdf"
    assert "step 1" in skill.body


def test_parse_skill_md_no_front_matter_uses_filename(tmp_path: Path):
    p = tmp_path / "my-skill" / "SKILL.md"
    p.parent.mkdir()
    p.write_text("just body", encoding="utf-8")
    skill = parse_skill_md(p.read_text(encoding="utf-8"), path=p)
    # 没 front-matter 时取父目录名 my-skill
    assert skill.name == "my-skill"
    assert skill.body == "just body"


def test_parse_skill_md_invalid_yaml(tmp_path: Path):
    bad = "---\nname: ok\n  bad-indent: [\n---\nbody"
    with pytest.raises(ValueError):
        parse_skill_md(bad, path=tmp_path / "x.md")


def test_load_skills_scans_subdirs(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "SKILL.md").write_text(
        "---\nname: a\ndescription: A\n---\nbody-a", encoding="utf-8"
    )
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "SKILL.md").write_text(
        "---\nname: b\ndescription: B\nwhen_to_use: when\n---\nbody-b",
        encoding="utf-8",
    )
    # 有效但 broken 的 skill 不应让整体崩
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "SKILL.md").write_text("---\nbad-yaml: [\n---", encoding="utf-8")

    skills = load_skills(tmp_path)
    assert set(skills.names()) == {"a", "b"}


def test_load_skills_missing_dir(tmp_path: Path):
    skills = load_skills(tmp_path / "no-such")
    assert len(skills) == 0


def test_skillset_system_preamble_contains_names():
    s = SkillSet([
        Skill(name="x", description="X tool", when_to_use="when X"),
        Skill(name="y", description="Y tool"),
    ])
    pre = s.system_preamble()
    assert "x" in pre and "X tool" in pre
    assert "when X" in pre
    assert "y" in pre
    assert "use_skill" in pre


def test_use_skill_tool_invoke_ok():
    skill_set = SkillSet([
        Skill(name="x", description="desc", body="full body"),
    ])
    tool = skill_set.make_use_skill_tool()
    assert tool.name == "use_skill"
    schema = tool.to_openai_schema()
    assert schema["function"]["name"] == "use_skill"
    # input_schema 含 enum
    enum = schema["function"]["parameters"]["properties"]["name"].get("enum")
    assert enum == ["x"]

    import asyncio

    res = asyncio.run(tool.invoke({"name": "x"}, ToolContext()))
    assert not res.is_error
    assert "full body" in res.content
    assert res.metadata.get("skill") == "x"


def test_use_skill_tool_unknown():
    import asyncio

    skill_set = SkillSet([Skill(name="a", description="A")])
    tool = skill_set.make_use_skill_tool()
    res = asyncio.run(tool.invoke({"name": "nope"}, ToolContext()))
    assert res.is_error
    assert "unknown skill" in res.content
