
"""Conversation memory, keyed by thread_id, with trimming.

This is the whole of what a framework's "checkpointer" does: somewhere to
keep the message list, and a key to find it by. Claude Code uses a .jsonl
file; LangGraph uses a checkpointer; this uses a dict. Swap the dict for a
Postgres table and it survives restarts.

TRIMMING IS NOT "KEEP THE LAST N". A tool result must directly follow the
assistant message that requested it — cut in the wrong place and the API
rejects the whole conversation with a 400. So the window is adjusted to a
legal boundary after slicing.
"""

SYSTEM_PROMPT = (
    "You are an operations assistant for an EV charging network. "
    "Answer from the tools provided; never guess at figures. "
    "Prefer a specific tool over raw SQL when one fits. "
    "Be concise, and say plainly when the data cannot answer the question."
)


class Conversations:
    """thread_id -> message list."""

    def __init__(self, max_messages: int = 20) -> None:
        self._threads: dict[str, list[dict]] = {}
        self.max_messages = max_messages

    def get(self, thread_id: str) -> list[dict]:
        return self._threads.setdefault(
            thread_id, [{"role": "system", "content": SYSTEM_PROMPT}]
        )

    def reset(self, thread_id: str) -> None:
        self._threads.pop(thread_id, None)

    def trim(self, thread_id: str) -> int:
        """Drop old turns. Returns how many messages were removed."""
        messages = self._threads[thread_id]
        if len(messages) <= self.max_messages + 1:      # +1 for the system message
            return 0

        system, rest = messages[0], messages[1:]
        window = rest[-self.max_messages:]

        # A `tool` message is only legal directly after an assistant message
        # carrying tool_calls. If the cut landed on one, drop forward until it
        # doesn't — an orphaned tool result is a 400, not a degraded answer.
        while window and window[0].get("role") == "tool":
            window.pop(0)

        # Likewise, do not end on an assistant turn whose tool_calls have no
        # results: the next request would be incomplete.
        while window and window[-1].get("tool_calls"):
            window.pop()

        removed = len(messages) - (1 + len(window))
        self._threads[thread_id] = [system] + window
        return removed
