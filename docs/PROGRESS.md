# zeroAgent 项目进度与交接文档

> 本文件面向**接手开发的 AI / 工程师**，提供：当前能力边界、关键文件索引、设计约束、后续任务清单。
> 任何后续 AI 在动手前，**必须先读完本文 + `docs/REQUIREMENTS.md`**，以避免与既有约定冲突。
>
> 最后更新：2026-05-22
> 当前版本：v0.2.0（M1.0 + M2.0 + M2.2 Skills + Web UI + Agentic Search + OpenCLI）
> 测试状态：**92/92 通过**

---

## 0. 一句话现状

zeroAgent 已经是一个**能在 Web UI 里聊天 + 自主调用工具完成实际任务**的 Agent：
具备多模型对话、ReAct 工具循环、agentic 代码检索（grep/glob/code_explorer）、Skills 懒加载、
Web UI（流式 + 工具审批弹层）、以及通过 `opencli` 抓取真实站点数据的能力。
通过 `uv run zeroagent serve` 即可启服务，在浏览器里聊天调工具。

---

## 1. 已完成里程碑

### M1.0 ｜ 模型层骨架 ✅

| 模块 | 文件 | 能力 |
| --- | --- | --- |
| 数据模型 | `src/zeroagent/llm/base.py` | `ChatMessage` / `ChatRequest` / `ChatResponse` / `ChatChunk` / `ToolCall` / `BaseLLMProvider` |
| 错误归一化 | `src/zeroagent/llm/errors.py` | 6 类标准异常：`AuthError` / `RateLimitError` / `TimeoutError` / `BadRequestError` / `ServerError` / `LLMError` |
| OpenAI 协议适配 | `src/zeroagent/llm/openai_compat.py` | 同时覆盖 OpenAI / DeepSeek（v4，含思考模式）/ Ollama / vLLM / 任意兼容端点；含流式 |
| Provider 工厂 | `src/zeroagent/llm/registry.py` | 按 `kind` 字段构造 Provider |
| 配置加载 | `src/zeroagent/config.py` | YAML + `${ENV}` 插值 + pydantic 校验 |
| Agent 门面 | `src/zeroagent/agent.py` | `from_config` / `use_llm` / `chat` / `stream` / `run` |
| CLI | `src/zeroagent/cli.py` | `chat` / `run` / `serve` / `providers` / `version` |

**未完成的 M1 子项**（已识别为后续任务，见 §6）：
- M1.1 Anthropic 原生 Provider（Claude messages API，非 OpenAI 兼容）
- M1.1 DashScope（通义）原生 Provider
- M1.2 tenacity 重试装饰器

### M2.0 ｜ 工具系统 + ReAct 主循环 ✅

| 模块 | 文件 | 能力 |
| --- | --- | --- |
| 工具抽象 | `src/zeroagent/tools/base.py` | `Tool` / `ToolContext` / `ToolResult` / `function_tool` 装饰器 / `safe_invoke`（超时 + 异常归一化） |
| 注册表 | `src/zeroagent/tools/registry.py` | 唯一性、schema 导出（OpenAI tool format）、并行派发 |
| 审批策略 | `src/zeroagent/tools/policy.py` | `AlwaysAllowPolicy` / `DenyPolicy` / `PromptPolicy`（终端交互）/ `AsyncApprovalPolicy`（Web UI 弹层） |
| Trace | `src/zeroagent/core/trace.py` | `Trace` / `TraceStep` / `step()` ctx mgr / JSON dump |
| 主循环 | `src/zeroagent/core/loop.py` | ReAct + 同轮 `tool_calls` 并行（`asyncio.gather`）+ `max_steps` 截断 + Policy 拦截 + 事件流（供 SSE） |

### M2.0a ｜ 内置工具集（Agentic Search & I/O） ✅

> 对标 Claude Code / Cursor 的 agentic 检索能力，**不引入向量库**，靠 ripgrep + glob + 自己写的 explorer skill 解决"从哪开始读代码"的问题。

| 工具 | 文件 | 说明 |
| --- | --- | --- |
| `fs_read` / `fs_write` / `list_dir` | `src/zeroagent/tools/builtin/fs.py` | 带 workspace 边界保护；`fs_read` 支持行号、`offset` / `limit` 切片 |
| `http_get` | `src/zeroagent/tools/builtin/http.py` | 简单 GET，响应截断 |
| `python_eval` | `src/zeroagent/tools/builtin/python_eval.py` | 受限 builtins，可选挂载，副作用 = exec |
| `grep` | `src/zeroagent/tools/builtin/grep.py` | ripgrep 优先 + 纯 Python fallback；返回带行号的命中 |
| `glob` | `src/zeroagent/tools/builtin/glob.py` | 文件名模式匹配，支持多 root / ignore |
| `code_explorer` | `src/zeroagent/tools/builtin/code_explorer.py` | 复合检索（list_dir + grep + glob + 摘要），给"从零探索仓库"用 |
| `opencli` | `src/zeroagent/tools/builtin/opencli.py` | 包 [@jackwener/opencli](https://github.com/jackwener/opencli) 二进制，借浏览器登录态抓站点（hackernews/bilibili/zhihu/twitter 等），写操作走审批 |

**统一入口**：`tools/builtin/__init__.py` 暴露 `default_builtin_tools(allow_write=…, allow_exec=…, allow_opencli=…)`。

### M2.2 ｜ Skills 系统 ✅

| 模块 | 文件 | 能力 |
| --- | --- | --- |
| 加载器 | `src/zeroagent/skills/loader.py` | 扫描 `skills/<name>/SKILL.md`，解析 YAML front-matter |
| Skill 模型 | `src/zeroagent/skills/skill.py` | `name` / `description` / `triggers` / `allowed_tools` / `body` |
| 内置示例 | `skills/code-explorer/SKILL.md` | "从零探索仓库"的 SOP，配合 grep/glob/code_explorer |
| 内置示例 | `skills/web-fetch/SKILL.md` | 抓网页内容的 SOP（基于 `http_get` / `opencli`） |

加载策略：启动只把 `name + description` 注入 system prompt（节省 token），用到时才把 body + 配套工具拉进上下文。

### M2.x ｜ Web UI（HTTP API + 静态前端） ✅

| 模块 | 文件 | 能力 |
| --- | --- | --- |
| FastAPI 服务 | `src/zeroagent/serve/api.py` | `POST /v1/chat`（SSE 流式）+ `POST /v1/approve`（工具审批回写）+ 静态托管 |
| 静态前端 | `src/zeroagent/serve/web/` | 单页对话 UI（HTML+CSS+原生 JS），流式增量、工具调用气泡、审批弹层 |
| 异步审批 Policy | `tools/policy.py::AsyncApprovalPolicy` | 工具调用前 emit 事件 → 前端弹层 → 用户点同意/拒绝 → Future resolve |
| 启动入口 | `src/zeroagent/cli.py::serve` | `uv run zeroagent serve --host 127.0.0.1 --port 8765` |

默认工具集：`default_builtin_tools(allow_write=True, allow_exec=True, allow_opencli=True)`，写/执行类全部走审批。

---

## 2. 当前可用能力边界

### ✅ 现在能做

- 通过 YAML 同时声明多个 Provider，运行时一行切换：`agent.use_llm("xxx")`
- 调任何 OpenAI 兼容端点（含 DeepSeek v4 / Ollama / 本地 vLLM）做对话和流式
- 通过 `@function_tool` 装饰器把任意 Python 函数变工具
- 让 LLM 自动调用工具完成多步任务（ReAct 循环）
- 同一轮多个工具并行执行
- 工具调用前由 Policy 审批，越权直接拒绝；Web 端弹层确认
- Skills 懒加载：description 入 prompt，body 按需展开
- **agentic 代码检索**：grep / glob / code_explorer 三件套，跑大仓库不靠向量库
- **抓真实网页数据**：通过 opencli 借浏览器登录态拉公开/账号内容，写操作受审批守门
- **Web UI**：开服务 → 浏览器对话，工具流和审批可视
- 完整 Trace 落盘（每步 LLM 输入/输出 + 工具调用 + 时长）

### ❌ 现在做不了（待 M2.1 / M2.3 / M3）

- 接入 MCP server（filesystem / git / playwright 等生态尚未打通）
- 把任意 shell 命令声明式地包成工具（CLI Wrapper，opencli 只是单点实现）
- 多 Agent 协作 / DAG 编排
- 沙箱化执行（目前 `python_eval` 仅做了 builtins 白名单，不算真沙箱）
- 长期记忆（Episodic / Semantic / Procedural）
- 评测集 + CI 回归
- OpenTelemetry 全链路 trace（目前只有自研 `Trace`）

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
| ⭐⭐ | `src/zeroagent/serve/api.py` | Web UI 后端，SSE 事件协议 + 审批回写 |
| ⭐⭐ | `src/zeroagent/tools/builtin/__init__.py` | `default_builtin_tools` 是工具默认装配点，新增工具需在此挂 |
| ⭐⭐ | `src/zeroagent/tools/builtin/opencli.py` | 包外部 CLI 的范式样本（白/黑名单 + 退出码语义化） |
| ⭐⭐ | `src/zeroagent/skills/loader.py` | Skills 加载与懒激活逻辑 |
| ⭐⭐ | `config/agent.yaml` | Provider 声明示例，新增 Provider 时参考 |
| ⭐ | `tests/unit/test_loop.py` | `FakeProvider` 范式，写新功能测试时直接抄 |
| ⭐ | `tests/unit/test_tools_opencli.py` | mock subprocess 测外部 CLI 的范式 |
| ⭐ | `examples/run_with_tools.py` | 端到端用法范例 |

---

## 4. 设计约束（动代码前必须遵守）

这些约束是设计决策，不要轻易破坏。如需突破必须先记 ADR（`docs/adr/`）。

1. **Schema First**：所有跨边界的数据结构用 pydantic v2 BaseModel，禁止 dict 满天飞。
2. **Async First**：Provider / Tool 的执行入口必须是 `async`。同步函数通过 `function_tool` 自动包装。
3. **不绑定 LangChain / LlamaIndex**：自研适配层，避免被生态卡脖子。需要某个能力时优先看官方 SDK（如 `mcp` / `anthropic` / `openai`）。
4. **配置驱动**：增加 Provider 或 Tool 都应能"零代码"通过 YAML / 装饰器声明，不要把硬编码塞进框架核心。
5. **错误归一化**：Provider 的 HTTP 异常必须映射成 `errors.py` 里的 6 类。Tool 的异常必须由 `safe_invoke` 包成 `ToolResult(is_error=True)`，不能让主循环崩溃。
6. **Trace 全覆盖**：任何新增的"会调用外部资源 / LLM"的环节都要进 `Trace`。
7. **测试先行**：新增模块必须有 mock-based 单测；用 `FakeProvider`（见 `test_loop.py`）和 mock subprocess（见 `test_tools_opencli.py`）避免真打外部依赖。
8. **目录边界**：`fs_*` / `grep` / `glob` / `code_explorer` 等读类工具必须经过 workspace 边界过滤，禁止越界。
9. **副作用闸门**：包外部 CLI / 写操作的工具，必须在工具内部做"读/写/危险"分类（参考 `opencli.py::_classify`），写操作交给 Policy。
10. **`__init__.py` 是公共 API**：只在此文件 re-export 稳定接口，私有实现别外泄。

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
├── skills/                         # 内置 Skills（被 SkillLoader 扫描）
│   ├── code-explorer/SKILL.md      # 从零探索仓库 SOP
│   └── web-fetch/SKILL.md          # 抓网页内容 SOP
├── src/zeroagent/
│   ├── __init__.py                 # 公共 API re-export
│   ├── agent.py                    # 门面：use_llm / chat / stream / run
│   ├── cli.py                      # typer：chat / run / serve / providers / version
│   ├── config.py                   # YAML + ${ENV} 加载
│   ├── llm/
│   │   ├── base.py                 # 数据模型 + BaseLLMProvider
│   │   ├── errors.py               # 6 类标准异常
│   │   ├── openai_compat.py        # OpenAI 协议（覆盖 4 家）
│   │   └── registry.py             # 工厂
│   ├── tools/
│   │   ├── base.py                 # Tool / ToolContext / ToolResult / function_tool
│   │   ├── registry.py             # ToolRegistry
│   │   ├── policy.py               # AlwaysAllow / Deny / Prompt / AsyncApproval
│   │   └── builtin/
│   │       ├── __init__.py         # default_builtin_tools(...)
│   │       ├── fs.py               # fs_read（带行号/切片）/ fs_write / list_dir
│   │       ├── http.py             # http_get
│   │       ├── python_eval.py      # python_eval（受限）
│   │       ├── grep.py             # ripgrep + Python fallback
│   │       ├── glob.py             # 文件名模式
│   │       ├── code_explorer.py    # 复合代码检索
│   │       └── opencli.py          # @jackwener/opencli 包装
│   ├── skills/
│   │   ├── loader.py               # 扫描 + front-matter 解析
│   │   └── skill.py                # Skill 数据模型
│   ├── core/
│   │   ├── trace.py                # Trace / TraceStep
│   │   └── loop.py                 # ReAct 主循环 + 事件流
│   └── serve/
│       ├── api.py                  # FastAPI：/v1/chat (SSE) + /v1/approve
│       ├── _reload_target.py
│       └── web/                    # 静态前端（HTML/CSS/JS）
└── tests/
    ├── conftest.py
    └── unit/
        ├── test_openai_compat.py       # 5 用例（mock httpx）
        ├── test_config.py              # 2
        ├── test_agent.py               # 1
        ├── test_loop.py                # 6（FakeProvider）
        ├── test_loop_events.py         # 4（事件流）
        ├── test_serve_api.py           # 6（FastAPI TestClient）
        ├── test_skills.py              # 8
        ├── test_tools_basic.py         # 8
        ├── test_tools_search.py        # 11（grep / glob）
        ├── test_code_explorer.py       # 3
        └── test_tools_opencli.py       # 38（mock subprocess）
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

### 🟡 P1 ｜ M2.3 CLI Wrapper（声明式）

- **目标**：opencli 是单点实现；做一个**声明式**包装层，让任意 shell 命令都能用 YAML 变成 `Tool`（`git status` / `rg ...` / `pytest` 等）。
- **涉及**：
  - 新增 `src/zeroagent/tools/cli_wrapper.py`：YAML 声明 → 动态 `Tool`
  - 参数白名单 + shell 注入防护（用 `shlex` + 禁用 `shell=True`）
  - 把 opencli 工具改造成"基于声明式 wrapper + 自带分类策略"的形态（可选）
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

---

## 7. 给后续 AI 的操作指南

### 7.1 接手前必做

1. 读 `docs/REQUIREMENTS.md` 全文（尤其第 4/5/6 节）。
2. 读本文 §3 列出的所有 ⭐⭐⭐ 文件。
3. 跑一次 `uv sync --extra dev && uv run pytest -v`，确认 baseline **92/92** 全过。
4. 跑一次 `uv run zeroagent --help` 和 `uv run zeroagent serve --help`，了解现有 CLI 形态。
5. 浏览器打开 Web UI 跑一次"列出当前目录并总结 README"，看看工具流和审批弹层。

### 7.2 写新代码的 Checklist

- [ ] 是否新增了 pydantic schema？放对位置了吗？
- [ ] 函数是否 `async`？
- [ ] 异常是否归一化（LLM 走 `errors.py`，Tool 走 `ToolResult`）？
- [ ] 是否进了 `Trace`？
- [ ] 是否写了 mock-based 单测？是否复用了 `FakeProvider` / mock subprocess？
- [ ] 是否在 `__init__.py` re-export？工具是否进了 `default_builtin_tools`？
- [ ] 写/危险类工具：是否有内部白/黑名单分类 + `requires_approval=True`？
- [ ] `read_lints` 通过吗？`uv run pytest` 通过吗？覆盖率有没有掉到 70% 以下？
- [ ] 公共 API 改动是否同步到 `README.md` / `examples/` / 本文？

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
uv run zeroagent run "读取 README.md 第一段并总结" --provider deepseek-v4-flash

# 启 Web UI（默认 http://127.0.0.1:8765）
uv run zeroagent serve --host 127.0.0.1 --port 8765

# Lint
uv run ruff check src/ tests/
```

### 7.4 不要做的事

- ❌ 不要引入 LangChain / LlamaIndex / Semantic Kernel
- ❌ 不要把 OpenAI / Anthropic SDK 直接塞进上层（必须经 `BaseLLMProvider`）
- ❌ 不要在主循环里 `print` 或 `input`（输出走 `Trace` / 事件流，交互走 `Policy`）
- ❌ 不要让工具直接 `os.system` / `subprocess.run(shell=True)`；外部命令统一 `asyncio.create_subprocess_exec` + 参数列表
- ❌ 不要在测试里真打 LLM API / 真跑 opencli（用 `FakeProvider` 或 monkeypatch subprocess）
- ❌ 不要删除 `.codebuddy/` 目录

---

## 8. 变更记录（Changelog）

| 日期 | 版本 | 内容 |
| --- | --- | --- |
| 2026-05-19 | v0.1.0 | M1.0 模型层 + M2.0 工具系统 + ReAct 主循环。22/22 测试通过，覆盖率 73%。 |
| 2026-05-19 | v0.1.1 | DeepSeek 模型升级到 v4（`deepseek-v4-flash` / `deepseek-v4-pro`，含思考模式）；新增 Web 对话 UI（FastAPI + SSE + 静态前端）；CLI 增 `zeroagent serve`。28/28 测试通过。 |
| 2026-05-22 | v0.2.0 | 新增 agentic 检索三件套（grep / glob / code_explorer，ripgrep 优先 + Python fallback）；`fs_read` 增强行号读 + offset/limit 切片；落地 Skills 系统（loader + 内置 code-explorer / web-fetch 两个 SKILL.md）；新增 `opencli` 工具（@jackwener/opencli 包装，借浏览器登录态抓站点，写操作内置黑名单 + Policy 审批）。**92/92 测试通过**。 |

---

## 9. 联系 / 决策记录位置

- 设计决策：`docs/adr/`（待建）
- 需求总纲：`docs/REQUIREMENTS.md`
- 进度（本文）：`docs/PROGRESS.md`
- 配置示例：`config/agent.yaml`
- 用法示例：`examples/`
