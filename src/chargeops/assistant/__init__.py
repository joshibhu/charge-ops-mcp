"""The assistant: a CLIENT of the MCP server.

Nothing in here touches the database. It asks the server, over HTTP, with a
bearer token — exactly as Claude Code does. The guard, the read-only role and
the masked view are all on the far side of that boundary and unaware of it.
"""

from .bridge import to_openai_tools
from .loop import MAX_ROUNDS, Assistant
from .mcp_client import McpToolbox
from .memory import SYSTEM_PROMPT, Conversations

__all__ = [
    "MAX_ROUNDS", "SYSTEM_PROMPT", "Assistant",
    "Conversations", "McpToolbox", "to_openai_tools",
]
