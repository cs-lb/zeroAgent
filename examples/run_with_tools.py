"""M2 示例：让 Agent 用工具完成一个文件读写任务。

运行前：
    cp .env.example .env  # 填入 DEEPSEEK_API_KEY 等
    uv run python examples/run_with_tools.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from zeroagent import Agent, AlwaysAllowPolicy
from zeroagent.tools.builtin import default_builtin_tools


async def main() -> None:
    # 准备一个 workspace
    ws = Path("./workspace_demo").resolve()
    ws.mkdir(exist_ok=True)
    (ws / "input.txt").write_text("hello zeroagent\nthis is line 2\n", encoding="utf-8")

    agent = Agent.from_config("config/agent.yaml")
    agent.configure(workspace=str(ws), max_steps=6)
    agent.register_tools(default_builtin_tools(allow_write=True))
    agent.use_policy(AlwaysAllowPolicy())

    result = await agent.run(
        "读取 input.txt，统计有多少行，然后把结果写入 output.txt 并以一句话总结",
        system="你是一个会调用工具的助手。需要时先调用工具，再给出最终答复。",
    )

    print("=== Final ===")
    print(result.message.content)
    print()
    print("=== Trace ===")
    print(result.trace.summary())
    print(f"\nsteps={result.steps}  tool_calls={result.tool_calls}  reason={result.stopped_reason}")

    # dump trace 用于回放/调试
    result.trace.dump_json(ws / "trace.json")
    print(f"\ntrace dumped to {ws / 'trace.json'}")

    await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
