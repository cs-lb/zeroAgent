"""Provider 工厂 / 注册表。

按 `type` 字段实例化 Provider，便于 YAML 配置驱动。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zeroagent.llm.base import BaseLLMProvider
from zeroagent.llm.openai_compat import OpenAICompatibleProvider

ProviderFactory = Callable[..., BaseLLMProvider]


class ProviderRegistry:
    """Provider 类型 → 工厂函数 的注册表。"""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, type_name: str, factory: ProviderFactory) -> None:
        self._factories[type_name] = factory

    def create(self, type_name: str, **cfg: Any) -> BaseLLMProvider:
        if type_name not in self._factories:
            raise ValueError(
                f"unknown provider type '{type_name}', "
                f"registered: {sorted(self._factories)}"
            )
        return self._factories[type_name](**cfg)


# 默认注册表
_default = ProviderRegistry()
_default.register("openai_compatible", OpenAICompatibleProvider)
# alias
_default.register("openai", OpenAICompatibleProvider)
_default.register("deepseek", OpenAICompatibleProvider)
_default.register("ollama", OpenAICompatibleProvider)


def build_provider(type_name: str, **cfg: Any) -> BaseLLMProvider:
    """便捷函数：用默认注册表建一个 Provider。"""
    return _default.create(type_name, **cfg)


def default_registry() -> ProviderRegistry:
    return _default
