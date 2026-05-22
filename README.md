# zeroAgent

一个**模型无关、工具可插拔、工程可演进**的 Python Agent 框架。
最终目标：演进为 Harness Engineer 级的工程型智能体。

## 当前版本：v0.2.0 · 92/92 测试通过

已经做到的：

- **多模型对话**：OpenAI / DeepSeek v4（含思考模式）/ Ollama / vLLM 等任意 OpenAI 兼容端点，运行时一行切换
- **ReAct 工具循环**：同轮 `tool_calls` 并行执行，Trace 全覆盖
- **Agentic 代码检索**：`grep` / `glob` / `code_explorer` 三件套，ripgrep 优先 + Python fallback，**不依赖向量库**就能在大仓库里导航
- **Skills 懒加载**：扫描 `skills/<name>/SKILL.md`，description 入 prompt，body 按需展开（已内置 `code-explorer` / `web-fetch`）
- **Web UI**：`zeroagent serve` 起 FastAPI + 静态前端，浏览器里聊天 + SSE 流式 + 工具审批弹层
- **OpenCLI 集成**：通过 [@jackwener/opencli](https://github.com/jackwener/opencli) 借真实浏览器登录态抓站点（HackerNews / Bilibili / 知乎 / Twitter ……），写操作走审批

## 三阶段路线

| 阶段 | 目标 | 关键能力 | 状态 |
| --- | --- | --- | --- |
| **M1** | 调通大模型 + 切换 | OpenAI / Anthropic / 通义 / DeepSeek / Ollama 统一适配，配置驱动切换，流式 + 错误归一化 | ✅ 主体完成 |
| **M2** | 工具系统 | MCP 客户端、Skills 目录化、CLI Wrapper、ReAct 主循环、并行工具调用、Policy 审批 | ✅ 除 MCP 外全部完成 |
| **M3** | Harness 工程化 | Workflow 编排、沙箱执行、长期记忆、评测体系、OpenTelemetry、HTTP API、CI 集成 | ⏳ 仅 HTTP API 落地 |

- 全量需求与方法：[docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)
- **当前进度与后续任务（AI 接手必读）**：[docs/PROGRESS.md](docs/PROGRESS.md)

## 技术栈

Python 3.11+ · pydantic v2 · httpx · asyncio · typer · FastAPI · MCP SDK · OpenTelemetry · pytest

## 目录

```
src/zeroagent/   # 框架代码（llm / tools / skills / core / serve）
config/          # 模型 Provider 配置
skills/          # 内置 Skills（code-explorer / web-fetch）
docs/            # 需求 / 进度 / ADR
tests/           # 单测（92 个）
examples/        # 上手示例
```

## Quick Start

### 1. 装依赖 + 配 key

```bash
uv sync --extra dev
cp .env.example .env   # 填上你的 DEEPSEEK_API_KEY / OPENAI_API_KEY 等
```

### 2. 命令行对话

```python
import asyncio
from zeroagent import Agent

async def main():
    agent = Agent.from_config("config/agent.yaml")
    agent.use_llm("deepseek-v4-flash")
    print((await agent.chat("Hello")).content)

    agent.use_llm("claude")        # 一行切换
    async for c in agent.stream("用英文再说一遍"):
        print(c.delta, end="")

asyncio.run(main())
```

### 3. Web UI（推荐）

```bash
uv run zeroagent serve --host 127.0.0.1 --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

默认装备：`fs_read` / `list_dir` / `grep` / `glob` / `http_get` / `fs_write` / `python_eval` / `opencli`，
写/执行类工具调用前会弹审批层。

### 4. 让 Agent 自己用工具完成任务（CLI）

```bash
uv run zeroagent run "扫一遍 src/ 找出所有用 asyncio.gather 的地方，总结调用模式" \
    --provider deepseek-v4-flash --workspace .
```

### 5. OpenCLI（可选）

需要本机先装好：

```bash
npm i -g @jackwener/opencli
# 然后装 Chrome 扩展（仓库 README 有说明） + 跑 `opencli doctor` 通过
```

之后 Agent 就能 `opencli(args=["hackernews","top","--limit","5"])` 抓真实站点数据。
**写操作（post / like / follow / comment / browser eval / ...）默认拒绝**，需要 Policy 审批通过才能执行。

## 跑测试

```bash
uv run pytest -v        # 92/92
```

## 里程碑

约 11–12 周（单人）或 6–8 周（并行）。详见 [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) 第 8 节。
