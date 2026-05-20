"""LLM Provider 抽象 + 统一数据模型。

设计目标：
- 所有 Provider 产出/消费同一套 Pydantic 模型，业务代码与厂商解耦。
- 支持流式与非流式两种调用。
- tool_calls 字段为 M2（工具系统）预留。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    """assistant 发起的工具调用请求（OpenAI tool_calls 风格）。"""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """统一对话消息。content 暂只支持纯文本，多模态在 M2 之后扩展。"""

    model_config = ConfigDict(extra="ignore")

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    # Reasoning 模型（DeepSeek thinking / o1 / Qwen3-thinking 等）的思维链。
    # 多轮调用时必须把上一轮的 reasoning_content 原样回传给 API，否则会 400。
    reasoning_content: str | None = None


class ChatRequest(BaseModel):
    """对 Provider 发起的对话请求。"""

    model: str
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    """Provider 私有参数，按需透传。"""


class Usage(BaseModel):
    """token 用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    """非流式响应。"""

    message: ChatMessage
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str | None = None
    model: str | None = None
    raw: dict[str, Any] | None = None


class ChatChunk(BaseModel):
    """流式响应的单帧增量。"""

    delta: str = ""
    role: Role | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: Usage | None = None
    reasoning_delta: str = ""


class BaseLLMProvider(ABC):
    """所有 LLM Provider 必须实现的抽象。"""

    name: str = "base"

    def __init__(self, *, model: str, **kwargs: Any) -> None:
        self.model = model
        self.options = kwargs

    @abstractmethod
    async def chat(self, req: ChatRequest) -> ChatResponse:
        """非流式对话。"""

    @abstractmethod
    def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        """流式对话。返回一个异步迭代器（不是协程）。"""

    async def aclose(self) -> None:
        """释放底层资源（连接池等）。子类可覆盖。"""
        return None
