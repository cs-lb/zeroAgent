---
name: code-explorer
description: 在工作区里检索/阅读任何文件（源码、配置、文档、数据），用 grep + glob + 行号 read 的标准套路，回答"X 在哪 / Y 怎么实现 / 这块逻辑怎么走 / 谁调用了 Z"等问题
when_to_use: 用户问任何涉及"项目里的文件/代码/配置/文档"的问题，包括但不限于：定位定义、追踪调用链、读懂某段逻辑、找出 TODO、查看某个 yaml/json/md 内容。**默认就走这个 skill。**
---

# Skill: code-explorer

定位：把"代码检索"这件事做成一个**有套路的工作流**，对标 Claude Code / Cursor Agent 的 agentic search。
**不要**走"层层 list_dir + 整文件 fs_read"那条老路——又慢又烧 token。

## 工具

- `glob(pattern, path?, head_limit?)`：按文件名 pattern 找文件，按 mtime 排序（**最近改的在前**），自动跳过 `.git/.venv/node_modules/__pycache__` 等。
- `grep(pattern, glob?, output_mode?, ...)`：ripgrep 内容检索。三种 `output_mode`：
  - `files_with_matches`（默认）：只返回路径，最省 token，**先用这个定位文件**。
  - `content`：返回匹配行（可加 `context_before`/`context_after`），用来看上下文。
  - `count`：每个文件的命中数，估"热度"用。
- `fs_read(path, offset?, limit?)`：带行号的文件读取，**默认上限 2000 行**，配合 `offset/limit` 分页。
- `list_dir(path)`：只在你完全没头绪时用一次，了解整体布局。
- `code_explorer(task)`（如果可用）：派子 agent 处理"复杂多步检索"，主 agent 不被中间过程污染。

## 标准工作流

### Step 1 — 选择切入点

| 情况 | 首选工具 |
|---|---|
| 已知**符号名** / 字面串 / 错误信息 | `grep` 直接搜，**比 list_dir 快得多** |
| 已知**文件名/路径模式** | `glob`，比如 `**/test_*.py`、`**/*config*.{yaml,toml}` |
| 完全陌生的项目 | 一次 `list_dir(".")` 看顶层布局，然后切回 grep/glob |

### Step 2 — 先定位，再读文件

**核心节奏：grep(files_with_matches) → grep(content) → fs_read(offset, limit)**

```
# 例：找 AgentLoop 在哪定义、在哪被实例化
grep("class AgentLoop", glob="*.py")          # → core/loop.py
grep(r"AgentLoop\(", glob="*.py")             # → agent.py:173, ...
fs_read("src/zeroagent/agent.py", offset=170, limit=20)
```

**永远不要**在不知道目标行号的情况下整文件读——先 grep 定位行，再 `fs_read` 带 `offset/limit` 取小段。

### Step 3 — 并行调用

独立的搜索**必须在同一轮里一次性发出**，不要串行等结果：

```
# 并行：
grep("def login")         |   grep(r"class\s+Auth")   |   glob("**/*auth*.py")
```

### Step 4 — 复杂问题派子 agent

若问题需要 ≥ 5 次检索 + 综合判断（如"登录鉴权链路怎么走的"），改用 `code_explorer(task=...)`，让子 agent 把脏活做完，**只把结论带回主上下文**。

## 输出风格

报告时：
- 用 `path:line` 形式给定位，便于用户跳转
- 引用代码只贴关键 1-3 行，不要整块粘
- 路径用相对 workspace 的形式，不要拼绝对路径

## 反模式（不要做）

- ❌ 一上来 `list_dir` 一层层翻——直接 `grep` 或 `glob`
- ❌ `fs_read` 读 2000 行只为找一个函数——先 `grep` 拿行号
- ❌ 串行做 3 个独立 grep——并行发
- ❌ 把 grep 结果整块塞进最终回答——只摘关键证据
- ❌ 改写代码前没看清现有实现就动手——必先 grep 用法 + read 上下文
