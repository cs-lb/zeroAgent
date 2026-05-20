"""uvicorn --reload 用的固定入口。

通过环境变量 ZEROAGENT_CONFIG 传入配置路径。
"""

from __future__ import annotations

import os

from zeroagent.serve.api import create_app

_config = os.environ.get("ZEROAGENT_CONFIG", "config/agent.yaml")
app = create_app(_config)
