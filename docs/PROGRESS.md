# zeroAgent 项目进度与交接文档

> 本文件面向**接手开发的 AI / 工程师**，提供：当前能力边界、关键文件索引、设计约束、后续任务清单。
> 任何后续 AI 在动手前，**必须先读完本文 + `docs/REQUIREMENTS.md`**，以避免与既有约定冲突。
>
> 最后更新：2026-05-19
> 当前版本：v0.1.1（M1.0 + M2.0 + Web UI 完成）
> 测试状态：**28/28 通过**

---

## 0. 一句话现状

zeroAgent 已具备「**多模型对话 + ReAct 工具循环 + 内置工具集**」的最小闭环。
可通过 `uv run zeroagent run "..."` 端到端跑通"读文件 → 推理 → 写文件"类任务。

---

## 1. 已完成里程碑

### M1.0 ｜ 模型层骨架 ✅

| 模块 | 文件 | 能力 |
| --- | --- | --- |
| 数据模型 | `src/zeroagent/llm/base.py` | `ChatMessage` / `ChatRequest` / `ChatResponse` / `ChatChunk` / `ToolCall` / `BaseLLMProvider` |
| 错误归一化 | `src/zeroagent/llm/errors.py` | 6 类标准异常：`AuthError` / `RateLimitError` / `TimeoutError` / `BadRequestError` / `ServerError` / `LLMError` |
| OpenAI 协议适配 | `src/zeroagent/llm/openai_compat.py` | 同时覆盖 OpenAI / DeepSeek / Ollama / vLLM / 任意兼容端点；含流式 |
| Provider 工厂 | `src/zeroagent/llm/registry.py` | 按 `kind` 字段构造 Provider |
| 配置加载 | `src/zeroagent/config.py` | YAML + `${ENV}` 插值 + pydantic 校验 |
| Agent 门面 | `src/zeroagent/agent.py` | `from_config` / `use_llm` / `chat` / `stream` |
| CLI | `src/zeroagent/cli.py` | `chat` / `providers` / `version` |

**未完成的 M1 子项**（已识别为后续任务，见 §6）：
- M1.1 Anthropic 原生 Provider（Claude messages API，非 OpenAI 兼容）
- M1.1 DashScope（通义）原生 Provider
- M1.2 tenacity 重试装饰器

### M2.0 ｜ 工具系统 + ReAct 主循环 ✅

| 模块 | 文件 | 能力 |
| --- | --- | --- |
| 工具抽象 | `src/zeroagent/tools/base.py` | `Tool` / `ToolContext` / `ToolResult` / `function_tool` 装饰器 / `safe_invoke`（超时 + 异常归一化） |
| 注册表 | `src/zeroagent/tools/registry.py` | 唯一性、schema 导出（OpenAI tool format）、并行派发 |
| 审批策略 | `src/zeroagent/tools/policy.py` | `AlwaysAllowPolicy` / `DenyPolicy` / `PromptPolicy`（终端交互） |
| 内置工具 | `src/zeroagent/tools/builtin/` | `fs_read` / `fs_write` / `list_dir`（带 workspace 边界保护）/ `http_get` / `python_eval`（受限 builtins） |
| Trace | `src/zeroagent/core/trace.py` | `Trace` / `TraceStep` / `step()` ctx mgr / JSON dump |
| 主循环 | `src/zeroagent/core/loop.py` | ReAct + 同轮 `tool_calls` 并行（`asyncio.gather`）+ `max_steps` 截断 + Policy 拦截 |
| Agent 升级 | `src/zeroagent/agent.py` | `register_tool` / `register_tools` / `use_policy` / `configure` / `run()` |
| CLI 升级 | `src/zeroagent/cli.py` | `zeroagent run "<task>" --workspace ... --allow-write --allow-exec --trace-out ...` |

---

## 2. 当前可用能力边界

### ✅ 现在能做

- 通过 YAML 同时声明多个 Provider，运行时一行切换：`agent.use_llm("xxx")`
- 调任何 OpenAI 兼容端点（含 DeepSeek / Ollama / 本地 vLLM）做对话和流式
- 通过 `@function_tool` 装饰器把任意 Python 函数变工具
- 让 LLM 自动调用工具完成多步任务（ReAct 循环）
- 同一轮多个工具并行执行
- 工具调用前由 Policy 审批，越权直接拒绝
- 完整 Trace 落盘（每步 LLM 输入/输出 + 工具调用 + 时长）

### ❌ 现在做不了（待 M2.1+ / M3）

- 接入 MCP server（filesystem / git / playwright 等生态尚未打通）
- 加载磁盘上的 Skills（SKILL.md 格式）
- 把任意 shell 命令声明式地包成工具（CLI Wrapper）
- 多 Agent 协作 / DAG 编排
- 沙箱化执行（目前 `python_eval` 仅做了 builtins 白名单，不算真沙箱）
- 长期记忆（Episodic / Semantic / Procedural）
- 评测集 + CI 回归
- HTTP API 服务化

---

## 3. 关键文件索引（AI 接手必读）

> 优先级从高到低，建议按顺序通读。

| 优先级 | 文件 | 为什么重要 |
| --- | --- | --- |
| ⭐⭐⭐ | `docs/REQUIREMENTS.md` | 三阶段全量需求 + 验收标准，所有后续工作的总纲 |
| ⭐⭐⭐ | `docs/PROGRESS.md` | 本文，进度与边界 |
| ⭐⭐⭐ | `src/zeroagent/llm/base.py` | 所有 Provider 必须实现的接口契约 |
| ⭐⭐⭐ | `src/zeroagent/tools/base.py` | 所有工具必须遵守的 `Tool` 契约 + `ToolResult` 形状 |
| ⭐⭐⭐ | `src/zeroagent/core/loop.py` | ReAct 主循环逻辑，新增能力（Memory / Workflow）的接入点 |
| ⭐⭐ | `src/zeroagent/agent.py` | 门面层，新增对外 API 在这里 |
| ⭐⭐ | `src/zeroagent/config.py` | 配置 schema，新增配置字段需在此扩展 |
| ⭐⭐ | `config/agent.yaml` | Provider 声明示例，新增 Provider 时参考 |
| ⭐ | `tests/unit/test_loop.py` | `FakeProvider` 范式，写新功能测试时直接抄 |
| ⭐ | `examples/run_with_tools.py` | 端到端用法范例 |

---

## 4. 设计约束（动代码前必须遵守）

这些约束是设计决策，不要轻易破坏。如需突破必须先记 ADR（`docs/adr/`）。

1. **Schema First**：所有跨边界的数据结构用 pydantic v2 BaseModel，禁止 dict 满天飞。
2. **Async First**：Provider / Tool 的执行入口必须是 `async`。同步函数通过 `function_tool` 自动包装。
3. **不绑定 LangChain / LlamaIndex**：自研适配层，避免被生态卡脖子。需要某个能力时优先看官方 SDK（如 `mcp` / `anthropic` / `openai`）。
4. **配置驱动**：增加 Provider 或 Tool 都应能"零代码"通过 YAML / 装饰器声明，不要把硬编码塞进框架核心。
5. **错误归一化**：Provider 的 HTTP 异常必须映射成 `llm/errors.py` 里的 6 类。Tool 的异常必须由 `safe_invoke` 包成 `ToolResult(ok=False, error=...)`，不能让主循环崩溃。
6. **Trace 全覆盖**：任何新增的"会调用外部资源 / LLM"的环节都要进 `Trace`。
7. **测试先行**：新增模块必须有 mock-based 单测；用 `FakeProvider`（见 `test_loop.py`）避免真打 LLM。
8. **目录边界**：`fs_*` 工具必须经过 `_safe_path` 过滤，禁止越过 workspace。新增类似工具沿用此模式。
9. **`__init__.py` 是公共 API**：只在此文件 re-export 稳定接口，私有实现别外泄。

---

## 5. 项目当前结构（实际落地）

```
zeroAgent/
├── pyproject.toml                  # uv + hatchling
├── uv.lock
├── .env.example                    # API key 模板
├── .gitignore
├── README.md                       # 项目入口
├── config/
│   └── agent.yaml                  # Provider 声明
├── docs/
│   ├── REQUIREMENTS.md             # 全量需求（三阶段）
│   └── PROGRESS.md                 # ← 本文
├── examples/
│   ├── quickstart.py               # M1：对话 + 流式 + 切换
│   └── run_with_tools.py           # M2：工具循环
├── src/zeroagent/
│   ├── __init__.py                 # 公共 API re-export
│   ├── agent.py                    # 门面：use_llm / chat / stream / run
│   ├── cli.py                      # typer：chat / run / providers / version
│   ├── config.py                   # YAML + ${ENV} 加载
│   ├── llm/
│   │   ├── base.py                 # 数据模型 + BaseLLMProvider
│   │   ├── errors.py               # 6 类标准异常
│   │   ├── openai_compat.py        # OpenAI 协议（覆盖 4 家）
│   │   └── registry.py             # 工厂
│   ├── tools/
│   │   ├── base.py                 # Tool / ToolContext / ToolResult / function_tool
│   │   ├── registry.py             # ToolRegistry
│   │   ├── policy.py               # 三档审批
│   │   └── builtin/
│   │       ├── fs.py               # fs_read / fs_write / list_dir
│   │       ├── http.py             # http_get
│   │       └── python_eval.py      # python_eval（受限）
│   └── core/
│       ├── trace.py                # Trace / TraceStep
│       └── loop.py                 # ReAct 主循环
└── tests/
    ├── conftest.py
    └── unit/
        ├── test_openai_compat.py   # mock httpx，4 用例
        ├── test_config.py
        ├── test_agent.py           # Provider 切换
        ├── test_tools_basic.py     # 装饰器 / Registry / fs 边界 / Policy
        └── test_loop.py            # FakeProvider 全场景
```

---

## 6. 后续任务清单（按建议优先级排）

> 每项都给出：**目标 / 涉及文件 / 验收标准 / 估时**，方便 AI 直接领单。

### 🔥 P0 ｜ M2.1 MCP 客户端集成

- **目标**：把 MCP server（filesystem / git / playwright / sqlite 等）作为工具源接入 `ToolRegistry`。
- **涉及**：
  - 新增 `src/zeroagent/mcp/client.py`：封装官方 `mcp` Python SDK 的 stdio + SSE transport
  - 新增 `src/zeroagent/mcp/adapter.py`：把 MCP `tools/list` 返回的 schema 转成 `Tool` 实例
  - 配置扩展 `config/agent.yaml`：`mcp.servers[]` 字段
  - `Agent.connect_mcp(name)` API
- **验收**：
  - `uv run zeroagent run "列出当前目录" --mcp filesystem` 可走通
  - 单测用 in-memory MCP server（SDK 自带）覆盖 list_tools / call_tool
- **估时**：1 天
- **依赖**：`mcp>=1.0` 已声明于 `pyproject.toml` 的 optional `[mcp]` extra

### 🔥 P0 ｜ M2.2 Skills 系统

- **目标**：扫描 `skills/` 目录，按 `SKILL.md` front-matter 注册可懒加载的"复合工具"。
- **涉及**：
  - 新增 `src/zeroagent/skills/loader.py`：解析 front-matter（YAML） + body（指令模板）
  - 新增 `src/zeroagent/skills/skill.py`：Skill 类，`activate()` 时把指令注入 system prompt 并附加配套工具
  - 目录约定 `skills/<name>/SKILL.md` + `skills/<name>/scripts/*`
- **验收**：
  - 至少落 1 个示例 Skill（如 `pdf-extract`），跑通
  - 懒加载：未激活的 Skill 不进 system prompt（节省 token）
- **估时**：1 天

### 🟡 P1 ｜ M2.3 CLI Wrapper

- **目标**：声明式把任意 shell 命令变成 `Tool`（`git status` / `rg ...` / `pytest` 等）。
- **涉及**：
  - 新增 `src/zeroagent/tools/cli_wrapper.py`：YAML 声明 → 动态 `Tool`
  - 参数白名单 + shell 注入防护（用 `shlex` + 禁用 `shell=True`）
- **验收**：
  - 单测覆盖：参数正常 / 参数含 `;` 等危险字符被拒绝 / 超时
- **估时**：半天

### 🟡 P1 ｜ M1 补完

- **M1.1a Anthropic 原生 Provider**：`src/zeroagent/llm/anthropic.py`，调 `messages` API，处理 `tool_use` / `tool_result` content block
- **M1.1b DashScope Provider**：`src/zeroagent/llm/dashscope.py`，处理 `input.messages` 嵌套结构
- **M1.2 tenacity 重试装饰器**：在 `BaseLLMProvider.complete` / `stream` 上挂指数退避，对 `RateLimitError` / `ServerError` / `TimeoutError` 重试 3 次
- **估时**：合计 1 天

### 🟢 P2 ｜ M3 工程化（按需启动）

| 子项 | 目标 | 涉及 |
| --- | --- | --- |
| Memory | `core/memory/`：Working / Episodic（SQLite）/ Semantic（向量库） | 接 `loop.py` 的消息裁剪 hook |
| Workflow | `core/workflow.py`：DAG 编排，Planner-Coder-Reviewer 多 Agent | 复用现有 `Agent` 实例 |
| Sandbox | `core/sandbox/`：进程→firejail→Docker→microVM 四级 | 替换 `python_eval` 实现 |
| Eval | `evals/`：≥ 50 case + `pytest-benchmark` + CI 阈值 block PR | 新增 GitHub Actions |
| Observability | OpenTelemetry GenAI semconv 全链路 | `core/trace.py` 增加 OTel exporter |
| HTTP API | `serve/api.py`：FastAPI，`POST /v1/chat` `POST /v1/run` | 新增 `serve` extra |

---

## 7. 给后续 AI 的操作指南

### 7.1 接手前必做

1. 读 `docs/REQUIREMENTS.md` 全文（尤其第 4/5/6 节）。
2. 读本文 §3 列出的所有 ⭐⭐⭐ 文件。
3. 跑一次 `uv sync --extra dev && uv run pytest -v`，确认 baseline 22/22 全过。
4. 跑一次 `uv run zeroagent --help`，了解现有 CLI 形态。

### 7.2 写新代码的 Checklist

- [ ] 是否新增了 pydantic schema？放对位置了吗？
- [ ] 函数是否 `async`？
- [ ] 异常是否归一化（LLM 走 `errors.py`，Tool 走 `ToolResult`）？
- [ ] 是否进了 `Trace`？
- [ ] 是否写了 mock-based 单测？是否复用了 `FakeProvider`？
- [ ] 是否在 `__init__.py` re-export？
- [ ] `read_lints` 通过吗？`uv run pytest` 通过吗？覆盖率有没有掉到 70% 以下？
- [ ] 公共 API 改动是否同步到 `README.md` / `examples/`？

### 7.3 常用命令速查

```bash
# 同步依赖
uv sync --extra dev

# 跑测试 + 覆盖率
uv run pytest -v --cov

# 只跑一个文件
uv run pytest tests/unit/test_loop.py -v

# CLI 自检
uv run zeroagent providers
uv run zeroagent version

# 端到端跑工具循环（需要 .env 里有 key）
uv run zeroagent run "读取 README.md 第一段并总结" --provider deepseek-chat

# Lint（如已装 ruff）
uv run ruff check src/ tests/
```

### 7.4 不要做的事

- ❌ 不要引入 LangChain / LlamaIndex / Semantic Kernel
- ❌ 不要把 OpenAI / Anthropic SDK 直接塞进上层（必须经 `BaseLLMProvider`）
- ❌ 不要在主循环里 `print` 或 `input`（输出走 `Trace`，交互走 `Policy`）
- ❌ 不要让工具直接 `os.system` / `subprocess.run(shell=True)`
- ❌ 不要在测试里真打 LLM API（用 `FakeProvider` 或 `respx` mock）
- ❌ 不要删除 `.codebuddy/` 目录

---

## 8. 变更记录（Changelog）

| 日期 | 版本 | 内容 |
| --- | --- | --- |
| 2026-05-19 | v0.1.0 | M1.0 模型层 + M2.0 工具系统 + ReAct 主循环。22/22 测试通过，覆盖率 73%。 |
| 2026-05-19 | v0.1.1 | DeepSeek 模型升级到 v4（`deepseek-v4-flash` / `deepseek-v4-pro`，含思考模式）；新增 Web 对话 UI（FastAPI + SSE + 静态前端）；CLI 增 `zeroagent serve`。28/28 测试通过。 |

---

## 9. 联系 / 决策记录位置

- 设计决策：`docs/adr/`（待建）
- 需求总纲：`docs/REQUIREMENTS.md`
- 进度（本文）：`docs/PROGRESS.md`
- 配置示例：`config/agent.yaml`
- 用法示例：`examples/`
