"""zeroAgent 命令行入口。

用法：
    zeroagent chat "你好"
    zeroagent chat "解释下 MCP" --provider deepseek-v4-flash --stream
    zeroagent run  "读取 README 并总结" --workspace .
    zeroagent serve --port 8000      # 启动 Web UI
    zeroagent providers
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from zeroagent import __version__
from zeroagent.agent import Agent
from zeroagent.tools.builtin import default_builtin_tools

app = typer.Typer(help="zeroAgent CLI", no_args_is_help=True, add_completion=False)
console = Console()

DEFAULT_CONFIG = Path("config/agent.yaml")


def _load(config: Path) -> Agent:
    if not config.exists():
        console.print(f"[red]config not found:[/red] {config}")
        raise typer.Exit(code=2)
    return Agent.from_config(config)


@app.command()
def version() -> None:
    """显示版本号。"""
    console.print(f"zeroAgent v{__version__}")


@app.command()
def providers(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="配置文件路径"),
) -> None:
    """列出可用的 Provider。"""
    agent = _load(config)
    cfg = agent._config.llm
    console.print(f"[bold]default:[/bold] {cfg.default}")
    for name, p in cfg.providers.items():
        marker = "*" if name == cfg.default else " "
        console.print(f" {marker} {name:24s} type={p.type:18s} model={p.model}")


@app.command()
def chat(
    prompt: str = typer.Argument(..., help="用户输入"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="指定 Provider"),
    system: str | None = typer.Option(None, "--system", "-s", help="system prompt"),
    stream: bool = typer.Option(False, "--stream", help="开启流式输出"),
    temperature: float = typer.Option(0.7, "--temperature", "-t"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
) -> None:
    """发起一次对话。"""
    asyncio.run(_run_chat(prompt, provider, system, stream, temperature, config))


async def _run_chat(
    prompt: str,
    provider: str | None,
    system: str | None,
    stream: bool,
    temperature: float,
    config: Path,
) -> None:
    agent = _load(config)
    if provider:
        agent.use_llm(provider)
    console.print(f"[dim]> using {agent.current_provider}[/dim]")
    try:
        if stream:
            async for chunk in agent.stream(prompt, system=system, temperature=temperature):
                if chunk.delta:
                    console.print(chunk.delta, end="", soft_wrap=True, highlight=False)
            console.print()
        else:
            msg = await agent.chat(prompt, system=system, temperature=temperature)
            console.print(msg.content)
    finally:
        await agent.aclose()


@app.command()
def run(
    prompt: str = typer.Argument(..., help="任务描述"),
    provider: str | None = typer.Option(None, "--provider", "-p"),
    workspace: Path = typer.Option(Path("."), "--workspace", "-w", help="工具工作目录"),
    system: str | None = typer.Option(
        "你是一个会调用工具的助手。需要时先调用工具，再给出最终答复。",
        "--system",
        "-s",
    ),
    max_steps: int = typer.Option(8, "--max-steps"),
    allow_write: bool = typer.Option(False, "--allow-write", help="挂载 fs_write 工具"),
    allow_exec: bool = typer.Option(False, "--allow-exec", help="挂载 python_eval 工具"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    trace_out: Path | None = typer.Option(None, "--trace-out", help="把 trace 写到 JSON"),
) -> None:
    """以 ReAct 主循环执行任务（自动调用工具）。"""
    asyncio.run(
        _run_task(
            prompt, provider, workspace, system, max_steps, allow_write, allow_exec,
            config, trace_out,
        )
    )


async def _run_task(
    prompt: str,
    provider: str | None,
    workspace: Path,
    system: str | None,
    max_steps: int,
    allow_write: bool,
    allow_exec: bool,
    config: Path,
    trace_out: Path | None,
) -> None:
    agent = _load(config)
    if provider:
        agent.use_llm(provider)
    agent.configure(workspace=str(workspace.resolve()), max_steps=max_steps)
    agent.register_tools(
        default_builtin_tools(allow_write=allow_write, allow_exec=allow_exec)
    )
    console.print(
        f"[dim]> provider={agent.current_provider}  tools={agent.tools.names()}  ws={workspace}[/dim]"
    )
    try:
        result = await agent.run(prompt, system=system)
    finally:
        await agent.aclose()

    console.rule("Final")
    console.print(result.message.content)
    console.rule("Trace")
    console.print(result.trace.summary())
    console.print(
        f"\nsteps={result.steps}  tool_calls={result.tool_calls}  "
        f"reason={result.stopped_reason}"
    )
    if trace_out:
        result.trace.dump_json(trace_out)
        console.print(f"[dim]trace dumped → {trace_out}[/dim]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    reload: bool = typer.Option(False, "--reload", help="开发模式自动重载"),
) -> None:
    """启动 Web 对话界面（FastAPI + SSE）。"""
    try:
        import uvicorn

        from zeroagent.serve import create_app
    except ImportError as e:
        console.print(
            "[red]缺少依赖[/red]，请先执行：\n  uv sync --extra serve"
        )
        raise typer.Exit(code=1) from e

    if not config.exists():
        console.print(f"[red]config not found:[/red] {config}")
        raise typer.Exit(code=2)

    console.print(f"[bold]zeroAgent Web[/bold]  http://{host}:{port}")
    console.print(f"[dim]config: {config}[/dim]")

    if reload:
        # reload 模式必须用 import 字符串，且 config 走环境变量
        import os
        os.environ["ZEROAGENT_CONFIG"] = str(config.resolve())
        uvicorn.run(
            "zeroagent.serve._reload_target:app",
            host=host,
            port=port,
            reload=True,
        )
    else:
        app_instance = create_app(config)
        uvicorn.run(app_instance, host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
