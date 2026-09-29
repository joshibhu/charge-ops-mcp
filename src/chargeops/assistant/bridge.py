"""Translate MCP tool definitions into the shape OpenAI expects.

Same information, different nesting. MCP puts the schema in `inputSchema` at
the top level; OpenAI wants it as `parameters` inside a `function` object.
Nobody's fault — two specs written independently.

This is the only place that knows both shapes. If a third client format
appears, it gets a function here and nothing else changes.
"""

from typing import Any


def to_openai_tools(mcp_tools: list[Any]) -> list[dict]:
    """MCP's tool list -> OpenAI's `tools` parameter."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                # MCP: inputSchema (top level).  OpenAI: function.parameters.
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        }
        for tool in mcp_tools
    ]
