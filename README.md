# zeroAgent

一个**模型无关、工具可插拔、工程可演进**的 Python Agent 框架。
最终目标：演进为 Harness Engineer 级的工程型智能体。

## 三阶段路线

| 阶段 | 目标 | 关键能力 |
| --- | --- | --- |
| **M1 前期** | 调通大模型 + 切换 | OpenAI / Anthropic / 通义 / DeepSeek / Ollama 统一适配，配置驱动切换，流式 + 错误归一化 |
| **M2 中期** | 工具系统 | MCP 客户端、Skills 目录化、CLI Wrapper、ReAct 主循环、并行工具调用、Policy 审批 |
| **M3 后期** | Harness 工程化 | Workflow 编排、沙箱执行、长期记忆、评测体系、OpenTelemetry、HTTP API、CI 集成 |

- 全量需求与方法：[docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)
- **当前进度与后续任务（AI 接手必读）**：[docs/PROGRESS.md](docs/PROGRESS.md)

> 当前版本 **v0.1.0**：M1.0 模型层 + M2.0 工具系统已完成，22/22 测试通过，覆盖率 73%。

## 技术栈

Python 3.11+ · pydantic v2 · httpx · asyncio · typer · FastAPI · MCP SDK · OpenTelemetry · pytest

## 目录（规划）

```
src/zeroagent/   # 框架代码
config/          # 配置（模型/MCP/CLI 工具）
skills/          # 内置 Skills
docs/            # 需求 / 架构 / ADR
tests/           # 单测 + 集成测 + 评测集
examples/        # 上手示例
```

## Quick Start（M1 完成后）

```python
import asyncio
from zeroagent import Agent

async def main():
    agent = Agent.from_config("config/agent.yaml")
    agent.use_llm("deepseek-chat")
    print((await agent.chat("Hello")).content)

    agent.use_llm("claude")        # 一行切换
    async for c in agent.stream("用英文再说一遍"):
        print(c.delta, end="")

asyncio.run(main())
```

## 里程碑

约 11–12 周（单人）或 6–8 周（并行）。详见需求文档第 8 节。
