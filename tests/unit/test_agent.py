"""Agent 门面测试：切换 Provider + 通过 mock HTTP 完成对话。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from zeroagent.agent import Agent


def _write_cfg(p: Path) -> Path:
    cfg = p / "agent.yaml"
    cfg.write_text(
        """
llm:
  default: a
  providers:
    a:
      type: openai_compatible
      model: model-a
      api_key: sk-a
      base_url: https://a.test/v1
    b:
      type: openai_compatible
      model: model-b
      api_key: sk-b
      base_url: https://b.test/v1
""".strip(),
        encoding="utf-8",
    )
    return cfg


@pytest.mark.asyncio
@respx.mock
async def test_switch_provider(tmp_path: Path, fake_openai_response: dict) -> None:
    cfg = _write_cfg(tmp_path)
    agent = Agent.from_config(cfg)

    route_a = respx.post("https://a.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={**fake_openai_response, "model": "model-a"})
    )
    route_b = respx.post("https://b.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={**fake_openai_response, "model": "model-b"})
    )

    try:
        assert agent.current_provider == "a"
        msg1 = await agent.chat("hi")
        assert msg1.content == "hello world"
        assert route_a.called

        agent.use_llm("b")
        assert agent.current_provider == "b"
        msg2 = await agent.chat("hi")
        assert msg2.content == "hello world"
        assert route_b.called

        with pytest.raises(ValueError):
            agent.use_llm("nope")
    finally:
        await agent.aclose()
