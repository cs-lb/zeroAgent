"""HTTP GET 工具。"""

from __future__ import annotations

from typing import Any

import httpx

from zeroagent.tools.base import Tool, ToolContext, ToolResult


class HttpGetTool(Tool):
    name = "http_get"
    description = "HTTP GET a URL and return the response body (truncated)."
    side_effect = "read"
    timeout_s = 15.0
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_bytes": {"type": "integer", "default": 100_000},
        },
        "required": ["url"],
    }

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        url = args["url"]
        max_bytes = int(args.get("max_bytes", 100_000))
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as c:
            resp = await c.get(url)
        body = resp.content[:max_bytes].decode("utf-8", errors="replace")
        return ToolResult.ok(
            body,
            status=resp.status_code,
            url=str(resp.url),
            size=len(resp.content),
        )
