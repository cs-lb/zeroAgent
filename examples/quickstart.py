"""最小可用示例：模型切换 + 流式。

运行前：
    cp .env.example .env  # 填入 key
    uv run python examples/quickstart.py
"""

from __future__ import annotations

import asyncio

from zeroagent import Agent


async def main() -> None:
    agent = Agent.from_config("config/agent.yaml")

    # 1) 非流式
    msg = await agent.chat("用一句话解释什么是 Harness Engineer")
    print(f"[{agent.current_provider}] {msg.content}\n")

    # 2) 切换到本地模型（如果你跑了 ollama）
    # agent.use_llm("local-qwen")

    # 3) 流式
    print("[stream] ", end="", flush=True)
    async for chunk in agent.stream("再用英文说一遍"):
        if chunk.delta:
            print(chunk.delta, end="", flush=True)
    print()

    await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
