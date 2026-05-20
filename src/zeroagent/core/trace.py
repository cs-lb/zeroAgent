"""轻量 Trace：记录每一步 LLM/Tool 调用。

M3 阶段会替换为 OpenTelemetry，这里先做一个内存版供调试与回放。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

StepKind = Literal["llm", "tool", "policy"]


class TraceStep(BaseModel):
    kind: StepKind
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: float
    ended_at: float

    @property
    def duration_ms(self) -> float:
        return (self.ended_at - self.started_at) * 1000.0


class Trace(BaseModel):
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    steps: list[TraceStep] = Field(default_factory=list)

    def add(self, step: TraceStep) -> None:
        self.steps.append(step)

    def dump_json(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    def summary(self) -> str:
        lines = [f"trace {self.trace_id}  ({len(self.steps)} steps)"]
        for i, s in enumerate(self.steps):
            tag = "ERR " if s.error else "OK  "
            lines.append(f"  {i:02d} {tag}{s.kind:6s} {s.name:30s} {s.duration_ms:8.1f}ms")
        return "\n".join(lines)


class _StepTimer:
    """便捷上下文管理器，自动记录开始/结束时间并写入 Trace。"""

    def __init__(self, trace: Trace, kind: StepKind, name: str, payload: dict[str, Any]):
        self._trace = trace
        self._step = TraceStep(
            kind=kind,
            name=name,
            input=payload,
            started_at=0.0,
            ended_at=0.0,
        )

    def __enter__(self) -> TraceStep:
        self._step.started_at = time.time()
        return self._step

    def __exit__(self, exc_type, exc, tb) -> None:
        self._step.ended_at = time.time()
        if exc is not None and self._step.error is None:
            self._step.error = f"{exc_type.__name__}: {exc}"
        self._trace.add(self._step)


def step(trace: Trace, kind: StepKind, name: str, **input_payload: Any) -> _StepTimer:
    """快捷构造 step：

    with step(trace, "llm", "chat", model="gpt-4o") as s:
        ...
        s.output = {"tokens": 123}
    """
    # 过滤掉无法 JSON 化的内容
    safe: dict[str, Any] = {}
    for k, v in input_payload.items():
        try:
            json.dumps(v, default=str)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = repr(v)
    return _StepTimer(trace, kind, name, safe)
