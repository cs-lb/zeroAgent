"""LLM 异常归一化。

各家 Provider 的原生异常统一映射到这里，方便上层做重试与降级策略。
"""

from __future__ import annotations


class LLMError(Exception):
    """所有 LLM 异常的基类。"""

    def __init__(self, message: str, *, provider: str | None = None, raw: object | None = None):
        super().__init__(message)
        self.provider = provider
        self.raw = raw


class LLMAuthError(LLMError):
    """401 / 鉴权失败。不应重试。"""


class LLMRateLimitError(LLMError):
    """429 / 限流。可重试。"""


class LLMTimeoutError(LLMError):
    """请求超时。可重试。"""


class LLMBadRequestError(LLMError):
    """4xx 业务错误（如参数非法）。不应重试。"""


class LLMServerError(LLMError):
    """5xx 服务端错误。可重试。"""


class LLMUnknownError(LLMError):
    """未归类异常，兜底。"""


RETRYABLE: tuple[type[LLMError], ...] = (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMServerError,
)
