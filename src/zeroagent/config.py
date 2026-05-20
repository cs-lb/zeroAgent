"""配置加载：YAML + 环境变量插值。

- 支持 ${VAR} 语法引用环境变量
- 自动加载项目根的 .env
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


class ProviderConfig(BaseModel):
    type: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    default: str
    providers: dict[str, ProviderConfig]


class AgentConfig(BaseModel):
    llm: LLMConfig


def _expand_env(value: Any) -> Any:
    """递归把字符串里的 ${VAR} 替换成环境变量值。"""
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str | Path) -> AgentConfig:
    """从 YAML 加载配置。"""
    # 自动加载 .env（如果存在）
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")

    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    expanded = _expand_env(raw)
    return AgentConfig.model_validate(expanded)
