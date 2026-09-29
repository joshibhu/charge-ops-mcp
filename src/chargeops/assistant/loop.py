"""The agent loop — Day 5's, now async, with memory and trimming."""

import json

from openai import AsyncOpenAI

from ..settings import settings
from .bridge import to_openai_tools
from .memory import Conversations
from .mcp_client import McpToolbox

MAX_ROUNDS = 6     # the recursion limit; a confused model must not loop forever


class Assistant:
    """Ties together: the model, the MCP toolbox, and per-thread memory."""

    def __init__(self, toolbox: McpToolbox, conversations: Conversations) -> None:
        self.box = toolbox
        self.convos = conversations
        self.model = AsyncOpenAI(api_key=settings.openai_api_key)
        # Translated once at startup, not per turn — the tool list does not
        # change while a session is open.
        self.tools = to_openai_tools(toolbox.tools)

    async def ask(self, question: str, thread_id: str = "default") -> dict:
        """One turn. Returns the answer plus what it cost and did."""
        messages = self.convos.get(thread_id)
        messages.append({"role": "user", "content": question})

        used: list[str] = []
        tokens_in = tokens_out = 0

        for _ in range(MAX_ROUNDS):
            response = await self.model.chat.completions.create(
                model=settings.openai_model, messages=messages, tools=self.tools
            )
            if response.usage:
                tokens_in += response.usage.prompt_tokens
                tokens_out += response.usage.completion_tokens

            message = response.choices[0].message

            if not message.tool_calls:
                messages.append({"role": "assistant", "content": message.content or ""})
                removed = self.convos.trim(thread_id)
                return {
                    "answer": message.content or "",
                    "tools": used,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "history": len(self.convos.get(thread_id)),
                    "trimmed": removed,
                }

            messages.append(message.model_dump(exclude_none=True))

            for call in message.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                used.append(call.function.name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": await self.box.call(call.function.name, args),
                })

        return {
            "answer": f"Gave up after {MAX_ROUNDS} rounds.", "tools": used,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "history": len(messages), "trimmed": 0,
        }
