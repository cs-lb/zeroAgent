"""OpenAI 协议兼容 Provider。

覆盖：OpenAI 官方、DeepSeek、Moonshot、Together、本地 Ollama / vLLM 等
任何走 `/v1/chat/completions` 协议的服务。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from zeroagent.llm.base import (
    BaseLLMProvider,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    Usage,
)
from zeroagent.llm.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMUnknownError,
)


def _msg_to_openai(m: ChatMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content or ""}
    if m.name:
        d["name"] = m.name
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in m.tool_calls
        ]
    # Reasoning 模型（DeepSeek thinking / o1 等）要求把上一轮的思维链原样回传。
    if m.reasoning_content:
        d["reasoning_content"] = m.reasoning_content
    return d


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall] | None:
    if not raw:
        return None
    out: list[ToolCall] = []
    for tc in raw:
        fn = tc.get("function", {})
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        out.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
    return out


def _map_http_error(status: int, body: str, provider: str) -> Exception:
    if status == 401 or status == 403:
        return LLMAuthError(f"auth failed: {body}", provider=provider, raw=body)
    if status == 429:
        return LLMRateLimitError(f"rate limited: {body}", provider=provider, raw=body)
    if 400 <= status < 500:
        return LLMBadRequestError(f"bad request {status}: {body}", provider=provider, raw=body)
    if status >= 500:
        return LLMServerError(f"server error {status}: {body}", provider=provider, raw=body)
    return LLMUnknownError(f"unknown {status}: {body}", provider=provider, raw=body)


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI `/chat/completions` 协议兼容实现。"""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    # ---------- 内部 ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, req: ChatRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": req.model or self.model,
            "messages": [_msg_to_openai(m) for m in req.messages],
            "temperature": req.temperature,
            "stream": stream,
        }
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        if req.tools:
            payload["tools"] = req.tools
        if req.tool_choice is not None:
            payload["tool_choice"] = req.tool_choice
        payload.update(req.extra)
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    # ---------- 非流式 ----------

    async def chat(self, req: ChatRequest) -> ChatResponse:
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(req, stream=False)
        try:
            resp = await self._client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(str(e), provider=self.name) from e
        except httpx.HTTPError as e:
            raise LLMUnknownError(str(e), provider=self.name) from e

        if resp.status_code >= 400:
            raise _map_http_error(resp.status_code, resp.text, self.name)

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        usage_d = data.get("usage") or {}
        return ChatResponse(
            message=ChatMessage(
                role=msg.get("role", "assistant"),
                content=msg.get("content") or "",
                tool_calls=_parse_tool_calls(msg.get("tool_calls")),
                reasoning_content=msg.get("reasoning_content") or None,
            ),
            usage=Usage(
                prompt_tokens=usage_d.get("prompt_tokens", 0),
                completion_tokens=usage_d.get("completion_tokens", 0),
                total_tokens=usage_d.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason"),
            model=data.get("model"),
            raw=data,
        )

    # ---------- 流式 ----------

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:  # type: ignore[override]
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(req, stream=True)

        try:
            async with self._client.stream(
                "POST", url, json=payload, headers=self._headers()
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise _map_http_error(resp.status_code, body, self.name)

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        evt = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    chunk = self._parse_stream_event(evt)
                    if chunk is not None:
                        yield chunk
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(str(e), provider=self.name) from e

    @staticmethod
    def _parse_stream_event(evt: dict[str, Any]) -> ChatChunk | None:
        choices = evt.get("choices") or []
        usage_d = evt.get("usage")
        if not choices:
            if usage_d:
                return ChatChunk(
                    usage=Usage(
                        prompt_tokens=usage_d.get("prompt_tokens", 0),
                        completion_tokens=usage_d.get("completion_tokens", 0),
                        total_tokens=usage_d.get("total_tokens", 0),
                    )
                )
            return None
        c0 = choices[0]
        delta = c0.get("delta") or {}
        return ChatChunk(
            delta=delta.get("content") or "",
            role=delta.get("role"),
            tool_calls=_parse_tool_calls(delta.get("tool_calls")),
            finish_reason=c0.get("finish_reason"),
            reasoning_delta=delta.get("reasoning_content") or "",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
