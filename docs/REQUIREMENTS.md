# zeroAgent —— 需求与方法文档（Python Agent 全栈方案）

> 版本：v0.1 （初稿）
> 作者：zerobliu
> 更新时间：2026-05-19
> 适用对象：自研 Agent 框架 / Harness Engineer 演进路线

---

## 0. 文档目的

本文档用于指导一个**基于 Python 的通用 Agent**从 0 到 1 的研发过程，涵盖：

- **前期（M1）**：稳定调用各家大模型，并支持运行时无缝切换。
- **中期（M2）**：接入 MCP / Skills / CLI 三类工具系统，形成"会用工具的 Agent"。
- **后期（M3）**：演进为 Harness Engineer（工程化 Agent 框架），具备任务编排、评测、可观测、沙箱执行、长期记忆等工程能力。

文档既是**需求规格说明（PRD）**，又是**技术方法论（HLD + 实施路径）**，可直接用于排期与开发。

---

## 1. 项目愿景与目标

### 1.1 愿景
打造一个**模型无关、工具可插拔、工程可演进**的 Python Agent 框架，最终成长为"Harness 级"的工程型智能体——既能写代码、用工具，也能被纳入 CI/CD、评测、回归体系。

### 1.2 核心目标（SMART）

| 目标 | 指标 | 阶段 |
| --- | --- | --- |
| 多模型统一调用 | 支持 ≥4 家厂商（OpenAI / Anthropic / 通义 / DeepSeek / 本地 vLLM），切换 < 1 行代码 | M1 |
| 工具系统 | 支持 MCP（stdio + SSE/HTTP）、Skills（Markdown 描述 + 脚本）、CLI 包装；同时挂载 ≥10 个工具仍稳定 | M2 |
| 工程化 | 具备任务编排、评测集（≥50 case）、Trace、沙箱、记忆、配置中心 | M3 |
| 可用性 | CLI 一键运行，HTTP API 可对外提供服务，单测覆盖率 ≥70% | 全周期 |

### 1.3 非目标（Non-Goals）
- 不重复造模型推理引擎（直接复用 vLLM / Ollama / 厂商 API）。
- 不做 GUI（M3 之后再考虑 Web Console）。
- 不绑定特定业务领域（保持框架通用性）。

---

## 2. 总体架构

### 2.1 分层架构图（文字版）

```
┌─────────────────────────────────────────────────────────┐
│                     Application 层                        │
│      CLI  │  HTTP API (FastAPI)  │  SDK (import zeroagent)│
├─────────────────────────────────────────────────────────┤
│                     Agent Core 层                         │
│   Planner │ Executor │ Memory │ Trace │ Policy │ Loop    │
├─────────────────────────────────────────────────────────┤
│                       Tooling 层                          │
│   MCP Client │ Skills Loader │ CLI Wrapper │ Builtin Tools│
├─────────────────────────────────────────────────────────┤
│                    Model Provider 层                      │
│  OpenAI │ Anthropic │ DashScope │ DeepSeek │ Ollama │ vLLM│
├─────────────────────────────────────────────────────────┤
│                      Infra 层                             │
│  Config │ Logger │ Sandbox │ Storage │ Observability      │
└─────────────────────────────────────────────────────────┘
```

### 2.2 关键设计原则
1. **Provider Pattern**：所有模型/工具均以 Provider 形式插拔，统一抽象接口。
2. **Schema First**：消息、工具调用、Trace 全部使用 `pydantic` 模型，强类型贯穿。
3. **Async First**：核心循环使用 `asyncio`，工具调用并行化。
4. **Config Driven**：行为通过 `YAML/TOML` 配置 + 环境变量注入，代码零改动切模型。
5. **Observability Built-in**：每一次 LLM/Tool 调用都有 Trace（OpenTelemetry 兼容）。

---

## 3. 技术选型

| 领域 | 选型 | 备注 |
| --- | --- | --- |
| 语言 / 版本 | Python ≥ 3.11 | 用 `match`、`TaskGroup` |
| 包管理 | `uv` 或 `poetry` | 推荐 `uv`（快） |
| 异步框架 | `asyncio` + `anyio` | 兼容 sync/async |
| 数据建模 | `pydantic v2` | Schema 校验 |
| HTTP 客户端 | `httpx` | 异步友好 |
| LLM SDK | 各家官方 SDK + 自研统一适配层 | 不绑定 LangChain |
| MCP | `mcp` 官方 Python SDK | stdio / SSE 都支持 |
| 配置 | `pydantic-settings` + `PyYAML` | 多源合并 |
| 日志 / Trace | `structlog` + `opentelemetry-sdk` | 结构化 |
| 测试 | `pytest` + `pytest-asyncio` + `respx` | mock HTTP |
| Lint / Format | `ruff` + `mypy` | 严格模式 |
| CLI | `typer` | 比 click 更现代 |
| HTTP API | `FastAPI` | M3 阶段引入 |
| 沙箱 | `docker` / `firejail` / `microvm` | M3 |
| 评测 | 自研 + `promptfoo` 兼容格式 | M3 |

---

## 4. 阶段一：前期（M1）—— 多模型调用与切换

### 4.1 需求清单

| ID | 需求 | 优先级 |
| --- | --- | --- |
| R1.1 | 统一 `ChatMessage` / `ChatRequest` / `ChatResponse` 数据模型 | P0 |
| R1.2 | 抽象 `BaseLLMProvider`，至少实现 OpenAI、Anthropic、DashScope（通义）、DeepSeek、Ollama 五个 | P0 |
| R1.3 | 通过配置文件 + 环境变量切换 provider，不改业务代码 | P0 |
| R1.4 | 支持流式（SSE）与非流式两种调用 | P0 |
| R1.5 | 支持 function calling / tool use 的统一抽象（为 M2 做准备） | P1 |
| R1.6 | 重试、超时、限流、错误归一化 | P1 |
| R1.7 | Token 计费统计（按模型计价表） | P2 |
| R1.8 | 单测覆盖率 ≥ 70%，关键 Provider 100% mock 测试 | P0 |

### 4.2 核心抽象（接口示例）

```python
# zeroagent/llm/base.py
from typing import AsyncIterator, Literal
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict]   # 支持多模态 part
    tool_calls: list["ToolCall"] | None = None
    tool_call_id: str | None = None

class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    tools: list[dict] | None = None
    temperature: float = 0.7
    stream: bool = False
    max_tokens: int | None = None

class ChatResponse(BaseModel):
    message: ChatMessage
    usage: "Usage"
    finish_reason: str
    raw: dict | None = None     # 原始响应，用于调试

class BaseLLMProvider:
    name: str

    async def chat(self, req: ChatRequest) -> ChatResponse: ...
    async def stream(self, req: ChatRequest) -> AsyncIterator["ChatChunk"]: ...
```

### 4.3 Provider 注册与切换

```yaml
# config/agent.yaml
llm:
  default: deepseek-chat
  providers:
    openai:
      type: openai
      api_key: ${OPENAI_API_KEY}
      base_url: https://api.openai.com/v1
    deepseek-chat:
      type: openai_compatible      # 直接复用 openai 协议
      api_key: ${DEEPSEEK_API_KEY}
      base_url: https://api.deepseek.com/v1
      model: deepseek-chat
    qwen:
      type: dashscope
      api_key: ${DASHSCOPE_API_KEY}
      model: qwen-max
    claude:
      type: anthropic
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-4-5
    local:
      type: ollama
      base_url: http://127.0.0.1:11434
      model: qwen2.5:7b
```

切换：

```python
agent = Agent.from_config("config/agent.yaml")
agent.use_llm("claude")          # 运行时切换
agent.use_llm("local")           # 切到本地
```

### 4.4 错误归一化

所有 Provider 异常统一映射为：

| 自研异常 | 含义 |
| --- | --- |
| `LLMAuthError` | 401 / 鉴权失败 |
| `LLMRateLimitError` | 429 |
| `LLMTimeoutError` | 超时 |
| `LLMBadRequestError` | 4xx 业务错误 |
| `LLMServerError` | 5xx |
| `LLMUnknownError` | 兜底 |

配合 `tenacity` 实现指数退避，仅对 `RateLimit / Timeout / Server` 重试。

### 4.5 验收标准（M1 Done Definition）
- ✅ `pytest` 全部通过，覆盖率 ≥ 70%
- ✅ 同一段对话代码，切换 5 个 provider 全部能跑通（含流式）
- ✅ 在 README 给出 quick start 示例（≤ 10 行代码完成对话）
- ✅ 提供 `zeroagent chat --provider xxx` CLI

---

## 5. 阶段二：中期（M2）—— 工具系统（MCP / Skills / CLI）

### 5.1 需求清单

| ID | 需求 | 优先级 |
| --- | --- | --- |
| R2.1 | 通用 `Tool` 抽象，支持 schema、权限、超时、副作用标记 | P0 |
| R2.2 | **MCP 客户端**：支持 stdio 与 SSE/HTTP 两种 transport，自动发现 server 暴露的 tools/resources/prompts | P0 |
| R2.3 | **Skills 系统**：以目录形式承载（`SKILL.md` + 脚本），支持懒加载、按需注入 system prompt | P0 |
| R2.4 | **CLI Wrapper**：将任意 shell 命令封装为 Tool，支持白名单、参数 schema | P1 |
| R2.5 | Agent Loop：ReAct + Tool Use 混合，工具调用并行化 | P0 |
| R2.6 | 工具调用 Trace 与回放 | P1 |
| R2.7 | 危险工具（写文件、执行命令）需 `policy` 层审批（CLI 提示 / 自动放行 / 拒绝） | P0 |

### 5.2 Tool 抽象

```python
class Tool(BaseModel):
    name: str
    description: str
    input_schema: dict           # JSON Schema
    side_effect: Literal["none", "read", "write", "exec"] = "none"
    timeout_s: float = 30
    requires_approval: bool = False

    async def invoke(self, args: dict, ctx: "ToolContext") -> "ToolResult": ...
```

三类 Tool 来源统一通过 `ToolRegistry` 注入：

```
ToolRegistry
 ├── BuiltinProvider      # fs/http/python eval 等内置
 ├── MCPProvider          # 来自 MCP server
 ├── SkillProvider        # 来自 skills 目录
 └── CLIProvider          # 来自 cli.yaml 声明
```

### 5.3 MCP 集成方案

- 复用官方 `mcp` Python SDK
- 配置：

```yaml
mcp:
  servers:
    filesystem:
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"]
    web:
      transport: sse
      url: http://127.0.0.1:8765/sse
```

- 启动时建立长连接，工具列表合并入 `ToolRegistry`，工具名加前缀 `mcp__<server>__<tool>` 防冲突。
- 支持热插拔：运行时 `/mcp reload`。

### 5.4 Skills 系统设计（参考 Anthropic Skills 设计）

**目录结构**：
```
skills/
  pdf/
    SKILL.md            # 描述 + 触发条件
    scripts/
      extract.py
    resources/
      template.pdf
  docx/
    SKILL.md
    ...
```

**SKILL.md 元信息（front-matter）**：
```markdown
---
name: pdf
description: Use when user wants to read/edit/merge PDF files.
triggers: ["pdf", ".pdf", "extract pdf"]
allowed_tools: ["fs.read", "shell.run"]
---

# Skill: PDF
当用户需要处理 PDF 时，按以下步骤……
```

**加载策略**：
- 启动时扫描所有 SKILL.md，仅把 `name + description` 注入 system prompt（节省 token）。
- Agent 在需要时调用 `use_skill(name)` 工具，框架将完整 SKILL.md 与脚本上下文动态加载到对话。

### 5.5 CLI Wrapper

通过声明式配置把任意 CLI 变成 Tool：

```yaml
cli_tools:
  - name: ripgrep
    description: Fast text search
    binary: rg
    args_schema:
      type: object
      properties:
        pattern: {type: string}
        path: {type: string, default: "."}
      required: ["pattern"]
    timeout_s: 15
    side_effect: read
```

执行通过 `asyncio.create_subprocess_exec` + 参数白名单校验，禁止 shell 注入。

### 5.6 Agent 主循环（ReAct + Tool Use）

```
loop:
  resp = llm.chat(messages, tools=registry.schemas())
  if resp.tool_calls:
      results = await asyncio.gather(*[exec_tool(c) for c in resp.tool_calls])
      messages += [resp.message, *results]
      continue
  else:
      return resp.message
```

- 并行执行同一轮的多个 tool_call
- 危险工具走 `policy.approve()`
- 每次 tool 调用记录 Trace（input/output/duration/error）
- 超过 `max_steps` 强制退出

### 5.7 验收标准（M2 Done Definition）
- ✅ 同一个 Agent 配置文件，能同时挂载 MCP 工具 + 2 个 Skills + 3 个 CLI Tools
- ✅ 通过 demo：让 Agent "读取本地 PDF → 总结 → 写到 docx"
- ✅ 工具调用 Trace 可导出 JSON，能用脚本回放
- ✅ 危险工具默认 `requires_approval=true`，CLI 模式有人工确认

---

## 6. 阶段三：后期（M3）—— Harness Engineer 工程化

> "Harness Engineer" 在本项目语境中指：**Agent 不再是单次对话，而是一个工程系统**——可被 CI 调用、可评测、可观测、可回归、可团队协作。

### 6.1 需求清单

| ID | 需求 | 优先级 |
| --- | --- | --- |
| R3.1 | **任务编排（Workflow）**：支持 DAG / 多 Agent 协作（Planner-Executor-Reviewer） | P0 |
| R3.2 | **沙箱执行**：代码/命令运行在 Docker 或 microVM 内，文件系统隔离 | P0 |
| R3.3 | **长期记忆**：向量库（Qdrant/Milvus）+ 结构化记忆（SQLite） | P0 |
| R3.4 | **评测体系**：用例集 + 自动化打分 + 回归报告 | P0 |
| R3.5 | **可观测性**：OpenTelemetry Trace / Metrics / Log 三件套 | P0 |
| R3.6 | **HTTP API & SDK**：FastAPI 暴露 `/chat`、`/runs`、`/tools`，发布 PyPI 包 | P1 |
| R3.7 | **多 Agent 协议**：兼容 A2A / AG-UI 等开放协议 | P2 |
| R3.8 | **配置中心**：支持热更新模型、工具、policy | P1 |
| R3.9 | **成本控制**：Token 预算、降级策略（贵模型→便宜模型） | P1 |
| R3.10 | **CI 集成**：GitHub Actions 跑评测，输出 markdown 报告 | P0 |

### 6.2 编排引擎

引入轻量 DAG：

```python
flow = Workflow("code-review")
flow.add(Step("plan", agent="planner"))
flow.add(Step("code", agent="coder", depends_on=["plan"]))
flow.add(Step("review", agent="reviewer", depends_on=["code"]))
flow.add(Step("test", tool="pytest", depends_on=["code"]))

result = await flow.run(input={"task": "实现 fib 函数"})
```

- 可视化：导出 mermaid
- 失败重试：每步独立 retry policy
- 检查点：步骤级 checkpoint，可断点恢复

### 6.3 沙箱

| 等级 | 实现 | 用途 |
| --- | --- | --- |
| L0 | 当前进程 + 工作目录限制 | 开发态 |
| L1 | `subprocess` + `seccomp/firejail` | Linux 本地 |
| L2 | Docker 容器（每个 run 一个） | 默认生产 |
| L3 | Firecracker microVM | 高安全场景 |

统一接口：

```python
class Sandbox:
    async def exec(self, cmd: list[str], env: dict, timeout: float) -> ExecResult: ...
    async def write_file(self, path: str, content: bytes): ...
    async def read_file(self, path: str) -> bytes: ...
```

### 6.4 记忆系统

| 类型 | 存储 | 用途 |
| --- | --- | --- |
| 短期（Working） | 内存 / Redis | 当前对话 messages |
| 情景（Episodic） | SQLite | 历史对话/任务 |
| 语义（Semantic） | 向量库 | 知识检索 |
| 程序（Procedural） | Skills 目录 | "怎么做"的知识 |

检索策略：每轮注入前用 RAG 召回 top-K 与当前任务相关的历史/知识。

### 6.5 评测体系

```
evals/
  cases/
    coding/fib.yaml
    tool_use/pdf_summary.yaml
    multi_turn/refactor.yaml
  scorers/
    exact_match.py
    llm_judge.py
    pytest_pass.py
  runs/2026-05-19/report.md
```

每个 case：

```yaml
id: fib-001
input: "用 Python 实现斐波那契，写到 fib.py"
checks:
  - type: file_exists
    path: workspace/fib.py
  - type: pytest_pass
    test: tests/test_fib.py
  - type: llm_judge
    rubric: "代码风格、正确性、是否处理负数"
```

- 在 CI 跑全量评测，输出对比表（vs 上一版本）。
- 支持回归阈值：分数下降 > 5% 自动 block PR。

### 6.6 可观测性

- **Trace**：每个 run 生成一个 trace_id，子 span 包含 LLM 调用、Tool 调用、Sandbox exec。
- **Metrics**：QPS、p95 延迟、token 用量、tool 错误率。
- **Log**：结构化 JSON，关联 trace_id。
- **导出**：OTLP → Jaeger / Tempo / Datadog 任选。

### 6.7 验收标准（M3 Done Definition）
- ✅ 评测集 ≥ 50 case，CI 自动跑，输出 markdown 报告
- ✅ 同一份 Workflow 能在本地 / Docker 沙箱 / 远程服务三种模式跑通
- ✅ 提供 PyPI 包 `pip install zeroagent`，README 含 5 分钟 quick start
- ✅ 接入 OpenTelemetry，能在 Jaeger 上看到完整调用链
- ✅ 至少跑通一个真实业务 demo（如"自动 PR Review Bot"）

---

## 7. 工程目录建议

```
zeroAgent/
├── pyproject.toml
├── README.md
├── docs/
│   ├── REQUIREMENTS.md           # 本文
│   ├── ARCHITECTURE.md
│   └── adr/                      # Architecture Decision Records
├── config/
│   ├── agent.yaml
│   └── mcp.yaml
├── src/zeroagent/
│   ├── __init__.py
│   ├── core/
│   │   ├── agent.py
│   │   ├── loop.py
│   │   ├── policy.py
│   │   └── memory.py
│   ├── llm/
│   │   ├── base.py
│   │   ├── openai_compat.py
│   │   ├── anthropic.py
│   │   ├── dashscope.py
│   │   └── ollama.py
│   ├── tools/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── builtin/
│   │   ├── mcp_provider.py
│   │   ├── skill_provider.py
│   │   └── cli_provider.py
│   ├── skills/                   # 内置 skills 示例
│   ├── workflow/
│   ├── sandbox/
│   ├── observability/
│   ├── api/                      # FastAPI
│   └── cli.py                    # typer 入口
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evals/
└── scripts/
    └── run_evals.py
```

---

## 8. 里程碑与排期建议（参考）

| 阶段 | 周期 | 关键交付 |
| --- | --- | --- |
| **M1.0** Provider 抽象 + OpenAI/DeepSeek | 1 周 | 能跑通对话 |
| **M1.1** 多 Provider + 流式 + CLI | 1 周 | quick start |
| **M1.2** 错误归一化 + 单测 | 0.5 周 | 覆盖率 70% |
| **M2.0** Tool 抽象 + Builtin + Loop | 1 周 | 能调用工具 |
| **M2.1** MCP 客户端 | 1 周 | 接入官方 server |
| **M2.2** Skills 系统 | 1 周 | PDF/Docx demo |
| **M2.3** CLI Wrapper + Policy | 0.5 周 | 危险命令审批 |
| **M3.0** Workflow 引擎 | 1 周 | DAG 跑通 |
| **M3.1** Sandbox（Docker） | 1 周 | 隔离执行 |
| **M3.2** Memory + RAG | 1 周 | 长期记忆 |
| **M3.3** Eval + CI | 1 周 | 报告输出 |
| **M3.4** Observability + API | 1 周 | OTel 接入 |
| **M3.5** 真实业务 demo + 发布 | 1 周 | PyPI v0.1 |

> 总计约 **11–12 周**（单人投入），并行可压缩到 6–8 周。

---

## 9. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 各家 LLM tool calling 协议不一致 | 自研适配层，内部统一为 OpenAI 风格，再翻译 |
| MCP 协议演进快 | 锁版本 + 集成测试覆盖关键 server |
| 工具滥用导致破坏环境 | 默认 sandbox + policy 审批 + 白名单 |
| 评测主观性 | LLM Judge + 客观断言混合，多模型交叉评分 |
| Token 成本失控 | 预算限制 + 降级策略 + 缓存（prompt cache） |
| 长 Trace 影响性能 | 采样策略 + 异步落盘 |

---

## 10. 参考与生态对标

| 项目 | 借鉴点 |
| --- | --- |
| **Anthropic Claude Code / Skills** | Skill 目录化、SKILL.md front-matter、按需加载 |
| **OpenAI Agents SDK** | Tool schema、Run 抽象 |
| **LangGraph** | 状态机/DAG 编排思想（不直接依赖） |
| **AutoGen / CrewAI** | 多 Agent 协作模式 |
| **MCP 官方 SDK** | 工具协议标准 |
| **OpenTelemetry GenAI semconv** | Trace 字段命名 |
| **promptfoo / OpenAI evals** | 评测框架格式 |

---

## 11. 附录 A：最小可用 Demo（M1 完成时）

```python
# examples/quickstart.py
import asyncio
from zeroagent import Agent

async def main():
    agent = Agent.from_config("config/agent.yaml")
    agent.use_llm("deepseek-chat")

    reply = await agent.chat("用一句话解释什么是 Harness Engineer")
    print(reply.content)

    agent.use_llm("claude")
    async for chunk in agent.stream("再用英文说一遍"):
        print(chunk.delta, end="", flush=True)

asyncio.run(main())
```

## 12. 附录 B：M2 完成时的 Demo

```python
agent = Agent.from_config("config/agent.yaml")
# 自动加载 mcp servers、skills、cli tools
result = await agent.run(
    "把 ./inputs/report.pdf 总结成 3 段，并写到 ./outputs/summary.docx"
)
print(result.trace_url)   # 本地 trace 文件
```

## 13. 附录 C：M3 完成时的 Demo

```bash
# 一键评测
$ zeroagent eval --suite coding --report report.md

# 启动服务
$ zeroagent serve --port 8080

# 在 CI 中
- name: Agent Eval
  run: zeroagent eval --suite all --baseline main --fail-on-regress 5
```

---

**End of Document — v0.1**
