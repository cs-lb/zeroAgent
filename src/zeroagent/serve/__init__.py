"""zeroAgent Web 服务（FastAPI + SSE + 静态前端）。"""

from zeroagent.serve.api import create_app

__all__ = ["create_app"]
