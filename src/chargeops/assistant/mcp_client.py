"""Talk to the MCP server over HTTP.

ONE session is held open for the whole conversation. The MCP handshake
(initialize + tools/list) is designed to happen once per session; doing it
per question would work but adds two round trips to every message — the kind
of thing that looks fine locally and shows up as latency in production.

Async because the MCP SDK is. That colours everything above it: the agent
loop and the CLI are async too. Python's `async` is contagious in a way
Java's threads are not — you cannot call an async function from sync code
without an event loop, so the choice propagates outward.
"""

from contextlib import AsyncExitStack
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..settings import settings


class McpToolbox:
    """An open connection to the MCP server, plus its tool list.

        async with McpToolbox() as box:
            box.tools                      # what the server offers
            await box.call("site_detail", {"site": "BLR-001"})
    """

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        # AsyncExitStack, not a hand-rolled list. The transport and session are
        # anyio task groups, which must be exited in the task that entered
        # them; unwinding them by hand raised "attempted to exit cancel scope
        # in a different task". This is what the stdlib provides for exactly
        # this — entering several context managers dynamically and unwinding
        # them correctly, including when an exception is in flight.
        self._stack = AsyncExitStack()
        self.tools: list[Any] = []

    async def __aenter__(self) -> "McpToolbox":
        # Auth headers ride on a custom httpx client; the transport merges its
        # own MCP headers with this client's defaults.
        http = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {settings.api_token}"}
        )

        await self._stack.__aenter__()
        read, write, *_ = await self._stack.enter_async_context(
            streamable_http_client(settings.mcp_url, http_client=http)
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))

        await session.initialize()                        # the handshake, once
        self.tools = (await session.list_tools()).tools   # discovery, once
        self._session = session
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._session = None
        await self._stack.__aexit__(*exc)

    async def call(self, name: str, arguments: dict) -> str:
        """Run one tool and return its text. Errors come back as text.

        Same discipline as the Day 5 dispatcher: a failed tool must let the
        model recover, not end the conversation.
        """
        if self._session is None:
            raise RuntimeError("use McpToolbox as an async context manager")

        result = await self._session.call_tool(name, arguments)

        # MCP returns a LIST of content blocks — text, images, several things.
        # Day 5's tools returned a bare string; this is the wrapped version.
        parts = [b.text for b in result.content if getattr(b, "type", "") == "text"]
        text = "\n".join(parts) if parts else "(tool returned no text)"

        # is_error, not isError. camelCase on the wire, snake_case in Python —
        # the same translation that bit me with inputSchema on Day 8.
        return f"Tool error: {text}" if result.is_error else text
