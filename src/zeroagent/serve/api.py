"""FastAPI 后端：暴露对话接口 + 静态前端。

接口：
    GET  /api/providers            列出所有 Provider（含当前 default）
    GET  /api/tools                列出已挂载工具
    GET  /api/skills               列出已加载 Skills
    POST /api/chat                 非流式对话
    POST /api/chat/stream          SSE 流式对话
    POST /api/run/stream           SSE Agent 主循环（含工具调用 + 审批）
    POST /api/run/approve          审批回执（write/exec 工具）
    GET  /                         前端页面（静态）
    GET  /healthz                  健康检查

前端在 src/zeroagent/serve/web/ 下，独立 SPA。
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from zeroagent import __version__
from zeroagent.agent import Agent
from zeroagent.llm.base import ChatMessage
from zeroagent.llm.errors import LLMError
from zeroagent.tools.base import Tool
from zeroagent.tools.builtin import default_builtin_tools
from zeroagent.tools.policy import AsyncApprovalPolicy

WEB_DIR = Path(__file__).parent / "web"
SKILLS_DIR_DEFAULT = Path("skills")


# ---------- Schema ----------


class ChatTurn(BaseModel):
    """前端发来的一轮消息（仅 role/content）。"""

    role: str = Field(pattern=r"^(system|user|assistant)$")
    content: str


class ChatPayload(BaseModel):
    provider: str | None = None
    messages: list[ChatTurn]
    system: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None


class RunPayload(BaseModel):
    provider: str | None = None
    messages: list[ChatTurn]
    system: str | None = None
    temperature: float = 0.3
    max_steps: int = 8


class ApprovePayload(BaseModel):
    run_id: str
    call_id: str
    approve: bool


class ProviderInfo(BaseModel):
    name: str
    model: str
    type: str
    is_default: bool


class ProvidersResponse(BaseModel):
    default: str
    current: str
    providers: list[ProviderInfo]


class ToolInfo(BaseModel):
    name: str
    description: str
    side_effect: str
    requires_approval: bool


class SkillInfo(BaseModel):
    name: str
    description: str
    when_to_use: str


# ---------- 运行会话注册表 ----------


@dataclass
class _PendingApproval:
    future: asyncio.Future[bool]


@dataclass
class _RunSession:
    run_id: str
    pending: dict[str, _PendingApproval]


_runs: dict[str, _RunSession] = {}


def _truncate(s: str, limit: int = 4000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[truncated {len(s) - limit} chars]"


# ---------- App 工厂 ----------


def create_app(config_path: str | Path = "config/agent.yaml") -> FastAPI:
    """构造 FastAPI 应用；Agent 实例进程内单例。"""

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}")

    agent = Agent.from_config(config_path)
    # 默认挂内置工具：read 直跑，write/exec 走 AsyncApprovalPolicy 弹审批
    agent.register_tools(
        default_builtin_tools(allow_write=True, allow_exec=True),
    )
    # 加载 Skills（如果项目根有 skills 目录）
    skills_dir = Path(os.environ.get("ZEROAGENT_SKILLS_DIR") or SKILLS_DIR_DEFAULT)
    skills_loaded = 0
    if skills_dir.exists():
        skills_loaded = agent.load_skills(skills_dir)
    # 工作区 = config 同级（或环境变量覆盖）
    workspace = os.environ.get("ZEROAGENT_WORKSPACE") or str(config_path.parent.parent)
    agent.configure(workspace=workspace)

    # 锁，避免并发请求互踩 _current
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await agent.aclose()

    app = FastAPI(
        title="zeroAgent Web",
        version=__version__,
        description="zeroAgent 对话调试 UI",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- API ----------

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "tools": len(agent.tools),
            "skills": skills_loaded,
        }

    @app.get("/api/providers", response_model=ProvidersResponse)
    async def list_providers() -> ProvidersResponse:
        cfg = agent._config.llm  # noqa: SLF001 - 读取配置可接受
        items = [
            ProviderInfo(
                name=name,
                model=p.model,
                type=p.type,
                is_default=(name == cfg.default),
            )
            for name, p in cfg.providers.items()
        ]
        return ProvidersResponse(
            default=cfg.default,
            current=agent.current_provider,
            providers=items,
        )

    @app.get("/api/tools", response_model=list[ToolInfo])
    async def list_tools() -> list[ToolInfo]:
        return [
            ToolInfo(
                name=t.name,
                description=t.description,
                side_effect=t.side_effect,
                requires_approval=t.requires_approval,
            )
            for t in agent.tools.all()
        ]

    @app.get("/api/skills", response_model=list[SkillInfo])
    async def list_skills() -> list[SkillInfo]:
        return [
            SkillInfo(name=s.name, description=s.description, when_to_use=s.when_to_use)
            for s in agent.skills.all()
        ]

    def _to_messages(turns: list[ChatTurn], system: str | None) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        if system:
            msgs.append(ChatMessage(role="system", content=system))
        for t in turns:
            msgs.append(ChatMessage(role=t.role, content=t.content))
        return msgs

    @app.post("/api/chat")
    async def chat(payload: ChatPayload) -> dict[str, Any]:
        async with lock:
            if payload.provider:
                try:
                    agent.use_llm(payload.provider)
                except ValueError as e:
                    raise HTTPException(400, str(e)) from e
            try:
                msg = await agent.chat(
                    _to_messages(payload.messages, payload.system),
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                )
            except LLMError as e:
                raise HTTPException(502, f"{type(e).__name__}: {e}") from e

        return {
            "role": msg.role,
            "content": msg.content,
            "provider": agent.current_provider,
        }

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatPayload) -> EventSourceResponse:
        async with lock:
            if payload.provider:
                try:
                    agent.use_llm(payload.provider)
                except ValueError as e:
                    raise HTTPException(400, str(e)) from e
            current = agent.current_provider

        messages = _to_messages(payload.messages, payload.system)

        async def event_gen() -> AsyncIterator[dict[str, str]]:
            yield {"event": "meta", "data": json.dumps({"provider": current})}
            try:
                async for chunk in agent.stream(
                    messages,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                ):
                    if chunk.delta:
                        yield {
                            "event": "delta",
                            "data": json.dumps({"content": chunk.delta}),
                        }
                    if chunk.usage:
                        yield {
                            "event": "usage",
                            "data": json.dumps(
                                {
                                    "prompt_tokens": chunk.usage.prompt_tokens,
                                    "completion_tokens": chunk.usage.completion_tokens,
                                    "total_tokens": chunk.usage.total_tokens,
                                }
                            ),
                        }
            except LLMError as e:
                yield {
                    "event": "error",
                    "data": json.dumps({"type": type(e).__name__, "message": str(e)}),
                }
                return
            except Exception as e:  # noqa: BLE001
                yield {
                    "event": "error",
                    "data": json.dumps({"type": "InternalError", "message": str(e)}),
                }
                return

            yield {"event": "done", "data": "[DONE]"}

        return EventSourceResponse(event_gen())

    # ---------- /api/run（带工具的 ReAct） ----------

    @app.post("/api/run/stream")
    async def run_stream(payload: RunPayload) -> EventSourceResponse:
        async with lock:
            if payload.provider:
                try:
                    agent.use_llm(payload.provider)
                except ValueError as e:
                    raise HTTPException(400, str(e)) from e
            current = agent.current_provider

        messages = _to_messages(payload.messages, None)
        run_id = uuid.uuid4().hex[:12]
        session = _RunSession(run_id=run_id, pending={})
        _runs[run_id] = session

        # 队列承接事件
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def emit(evt: str, data: dict[str, Any]) -> None:
            await queue.put({"event": evt, "data": data})

        async def approval_requester(tool: Tool, args: dict[str, Any]) -> bool:
            call_id = uuid.uuid4().hex[:10]
            fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
            session.pending[call_id] = _PendingApproval(future=fut)
            await emit("approval_request", {
                "call_id": call_id,
                "tool": tool.name,
                "description": tool.description,
                "side_effect": tool.side_effect,
                "arguments": args,
            })
            try:
                return await fut
            finally:
                session.pending.pop(call_id, None)

        policy = AsyncApprovalPolicy(approval_requester, timeout_s=180.0)

        async def driver() -> None:
            try:
                result = await agent.run_with_events(
                    messages,
                    system=payload.system,
                    temperature=payload.temperature,
                    max_steps=payload.max_steps,
                    policy=policy,
                    on_event=lambda e, p: queue.put({"event": e, "data": p}),
                )
                await emit("result", {
                    "stopped_reason": result.stopped_reason,
                    "steps": result.steps,
                    "tool_calls": result.tool_calls,
                    "final_content": result.message.content or "",
                })
            except LLMError as e:
                await emit("error", {"type": type(e).__name__, "message": str(e)})
            except Exception as e:  # noqa: BLE001
                await emit("error", {"type": "InternalError", "message": str(e)})
            finally:
                await queue.put({"event": "_eof", "data": {}})

        task = asyncio.create_task(driver())

        async def event_gen() -> AsyncIterator[dict[str, str]]:
            yield {
                "event": "meta",
                "data": json.dumps({"provider": current, "run_id": run_id}),
            }
            try:
                while True:
                    item = await queue.get()
                    evt = item["event"]
                    if evt == "_eof":
                        break
                    yield {"event": evt, "data": json.dumps(item["data"], default=str)}
                yield {"event": "done", "data": "[DONE]"}
            finally:
                # 清理：取消所有挂起 future + 任务
                for pending in session.pending.values():
                    if not pending.future.done():
                        pending.future.set_result(False)
                _runs.pop(run_id, None)
                if not task.done():
                    task.cancel()

        return EventSourceResponse(event_gen())

    @app.post("/api/run/approve")
    async def run_approve(payload: ApprovePayload) -> dict[str, Any]:
        session = _runs.get(payload.run_id)
        if session is None:
            raise HTTPException(404, f"run not found: {payload.run_id}")
        pending = session.pending.get(payload.call_id)
        if pending is None:
            raise HTTPException(404, f"call not found: {payload.call_id}")
        if not pending.future.done():
            pending.future.set_result(payload.approve)
        return {"ok": True}

    # ---------- 静态前端 ----------

    if WEB_DIR.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(WEB_DIR / "assets")) if (WEB_DIR / "assets").exists() else StaticFiles(directory=str(WEB_DIR)),
            name="assets",
        )

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(str(WEB_DIR / "index.html"))

    return app
