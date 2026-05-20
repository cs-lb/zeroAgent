"""Skills loader：扫描目录，解析 SKILL.md（YAML front-matter + body）。"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from zeroagent.skills.skill import Skill, SkillSet

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def parse_skill_md(content: str, *, path: Path | None = None) -> Skill:
    """解析单个 SKILL.md 文本。

    格式：
        ---
        name: ...
        description: ...
        when_to_use: ...
        ---
        body...

    没有 front-matter 时，name 取目录名 / 文件名；description 留空。
    """
    m = _FRONT_MATTER_RE.match(content)
    meta: dict = {}
    body = content
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"invalid YAML front-matter in {path}: {e}") from e
        body = m.group(2)
    if not isinstance(meta, dict):
        raise ValueError(f"front-matter must be a mapping in {path}")

    name = str(meta.get("name") or "").strip()
    if not name and path is not None:
        # 退化：取父目录名（skills/<name>/SKILL.md）或文件名
        name = path.parent.name if path.name.lower() == "skill.md" else path.stem
    if not name:
        raise ValueError(f"skill name missing in {path}")

    description = str(meta.get("description") or "").strip()
    when_to_use = str(meta.get("when_to_use") or meta.get("trigger") or "").strip()
    extra = {k: v for k, v in meta.items() if k not in ("name", "description", "when_to_use", "trigger")}

    return Skill(
        name=name,
        description=description,
        when_to_use=when_to_use,
        body=body.strip(),
        path=path,
        extra=extra,
    )


def load_skills(root: str | Path) -> SkillSet:
    """扫描 root 目录下所有 `*/SKILL.md`，返回 SkillSet。

    约定：
        skills/
        ├── pdf-extract/
        │   └── SKILL.md
        └── web-fetch/
            └── SKILL.md

    也兼容直接放在 root 下的 *.skill.md / SKILL.md 单文件。
    """
    root_path = Path(root)
    skills: list[Skill] = []
    if not root_path.exists():
        return SkillSet(skills)

    candidates: list[Path] = []
    # 子目录里的 SKILL.md（推荐）
    for sub in sorted(root_path.iterdir()):
        if sub.is_dir():
            md = sub / "SKILL.md"
            if md.exists():
                candidates.append(md)
    # 顶层兼容
    for f in sorted(root_path.glob("*.skill.md")):
        candidates.append(f)

    seen_names: set[str] = set()
    for p in candidates:
        try:
            skill = parse_skill_md(p.read_text(encoding="utf-8"), path=p)
        except Exception:  # noqa: BLE001 - loader 容错；坏的 skill 不应炸全局
            continue
        if skill.name in seen_names:
            continue
        seen_names.add(skill.name)
        skills.append(skill)

    return SkillSet(skills)


__all__ = ["load_skills", "parse_skill_md"]
