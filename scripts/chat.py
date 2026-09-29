"""Chat with the charging-network assistant.

    uv run python scripts/chat.py                 # a conversation
    uv run python scripts/chat.py "question"      # one-shot

Requires the MCP server to be running:
    uv run python -m chargeops.server
"""

import asyncio
import sys

from chargeops.assistant import Assistant, Conversations, McpToolbox

THREAD = "cli"


async def turn(bot: Assistant, question: str) -> None:
    out = await bot.ask(question, THREAD)
    print(f"\n{out['answer']}\n")
    trimmed = f", trimmed {out['trimmed']}" if out["trimmed"] else ""
    print(
        f"  [tools: {', '.join(out['tools']) or 'none'} | "
        f"in={out['tokens_in']} out={out['tokens_out']} | "
        f"history={out['history']} msgs{trimmed}]\n",
        file=sys.stderr,
    )


async def main() -> None:
    async with McpToolbox() as box:
        bot = Assistant(box, Conversations(max_messages=20))
        print(f"{len(box.tools)} tools. Blank line to quit, 'new' to forget.\n")

        if len(sys.argv) > 1:
            await turn(bot, " ".join(sys.argv[1:]))
            return

        while True:
            try:
                q = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                break
            if q == "new":
                bot.convos.reset(THREAD)
                print("  (forgotten)\n")
                continue
            await turn(bot, q)


if __name__ == "__main__":
    asyncio.run(main())
