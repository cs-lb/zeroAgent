"""Skills 子系统。

约定：
- 一个 Skill = 一个目录（skills/<name>/SKILL.md）
- SKILL.md 由 YAML front-matter + Markdown body 组成：

    ---
    name: pdf-extract
    description: 解析 PDF 提取文本和表格
    when_to_use: 用户给出 .pdf 文件路径或 URL，需要拿到文本内容时
    ---

    # 完整指令（仅在 use_skill 调用后注入）

    1. 收到路径后用 fs_read 检测大小
    2. ...

启动时只把 name + description + when_to_use 注入 system prompt（省 token）；
模型决定要用时，调用 `use_skill(name)` 元工具，把 body 写入对话上下文。
"""

from zeroagent.skills.skill import Skill, SkillSet
from zeroagent.skills.loader import load_skills

__all__ = ["Skill", "SkillSet", "load_skills"]
