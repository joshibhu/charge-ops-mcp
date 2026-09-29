"""The agent loop — Day 5's, now async, with memory and trimming."""

import json
from collections.abc import AsyncIterator

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


    async def ask_stream(
        self, question: str, thread_id: str = "default"
    ) -> AsyncIterator[dict]:
        """Same loop, but yields events as they happen.

        Yields {"type": "tool"|"token"|"done", ...}.

        EVERY round is streamed, not just the last, because you cannot know
        which round is last until you have seen it. That means reassembling
        tool_call fragments as well as text: the model sends a tool name and
        its arguments in pieces, indexed, across many chunks.
        """
        messages = self.convos.get(thread_id)
        messages.append({"role": "user", "content": question})
        tokens_in = tokens_out = 0

        for _ in range(MAX_ROUNDS):
            stream = await self.model.chat.completions.create(
                model=settings.openai_model, messages=messages,
                tools=self.tools, stream=True,
                stream_options={"include_usage": True},   # Day 2's lesson
            )

            text_parts: list[str] = []
            # index -> {"id", "name", "arguments"} — rebuilt from fragments
            calls: dict[int, dict] = {}

            async for chunk in stream:
                if chunk.usage:
                    tokens_in += chunk.usage.prompt_tokens
                    tokens_out += chunk.usage.completion_tokens
                if not chunk.choices:
                    continue                              # the usage chunk

                delta = chunk.choices[0].delta

                if delta.content:
                    text_parts.append(delta.content)
                    yield {"type": "token", "text": delta.content}

                for fragment in delta.tool_calls or []:
                    call = calls.setdefault(
                        fragment.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if fragment.id:
                        call["id"] = fragment.id
                    if fragment.function and fragment.function.name:
                        call["name"] += fragment.function.name
                    if fragment.function and fragment.function.arguments:
                        call["arguments"] += fragment.function.arguments

            if not calls:                                 # it answered
                answer = "".join(text_parts)
                messages.append({"role": "assistant", "content": answer})
                removed = self.convos.trim(thread_id)
                yield {"type": "done", "tokens_in": tokens_in,
                       "tokens_out": tokens_out, "trimmed": removed,
                       "history": len(self.convos.get(thread_id))}
                return

            messages.append({
                "role": "assistant", "content": "".join(text_parts) or None,
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls.values()
                ],
            })

            for call in calls.values():
                yield {"type": "tool", "name": call["name"]}
                args = json.loads(call["arguments"] or "{}")
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": await self.box.call(call["name"], args),
                })

        yield {"type": "done", "tokens_in": tokens_in, "tokens_out": tokens_out,
               "trimmed": 0, "history": len(messages), "gave_up": True}
