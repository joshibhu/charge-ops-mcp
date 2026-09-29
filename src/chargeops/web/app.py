"""A web front end for the assistant. Browsers talk to this; it talks to MCP.

    browser  --JWT-->  this app  --API_TOKEN-->  MCP server  -->  database

The real credential never leaves this process. The browser gets a 15-minute
chat-only token instead, which is why it can live in a page.

This app is just ANOTHER CLIENT of the MCP server — the same McpToolbox the
CLI uses. Nothing on the server side knows or cares that a browser is
involved.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..assistant import Assistant, Conversations, McpToolbox
from ..settings import settings
from .tokens import TokenInvalid, mint, verify

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open ONE MCP connection for the app's lifetime.

    Not one per request: the handshake plus tools/list is two round trips,
    and paying that on every message would be visible latency. Not one per
    user either — tool calls carry no per-user state, so a single connection
    serves everyone, exactly like a database pool.

    What IS per-user is the conversation, and that lives in Conversations,
    keyed by the session id inside each token.
    """
    async with McpToolbox() as box:
        STATE["assistant"] = Assistant(box, Conversations(max_messages=20))
        yield
    STATE.clear()


app = FastAPI(title="chargeops chat", lifespan=lifespan)

# A browser refuses to call an API on another origin unless that API allows
# it. The widget is meant to be embedded on other people's pages, so this has
# to be open — but "*" means ANY site can call this endpoint. Acceptable
# because the only way in is a token this app minted. In production you would
# list the customer's domains instead.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def session_id(authorization: str = Header(default="")) -> str:
    """FastAPI dependency: turn a Bearer token into a session id, or 401."""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify(token)
    except TokenInvalid as exc:
        raise HTTPException(401, str(exc)) from exc


class NewSession(BaseModel):
    token: str
    session_id: str
    expires_in_minutes: int


@app.post("/session", response_model=NewSession)
def new_session() -> NewSession:
    """Issue a short-lived browser token. No auth — this is the front door.

    Rate limiting belongs here in production: anyone can mint a token, and
    every token can ask questions that cost money.
    """
    token, sid = mint()
    return NewSession(
        token=token, session_id=sid,
        expires_in_minutes=settings.browser_token_minutes,
    )


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.post("/chat")
async def chat(ask: Ask, sid: str = Depends(session_id)) -> dict:
    """Answer a question. Non-streaming — piece 3 adds SSE."""
    return await STATE["assistant"].ask(ask.question, thread_id=sid)


@app.post("/chat/stream")
async def chat_stream(ask: Ask, sid: str = Depends(session_id)) -> StreamingResponse:
    """Stream the answer as server-sent events.

    SSE is just a text format over ordinary HTTP:

        data: {"type":"token","text":"BLR"}\n\n
        data: {"type":"token","text":"-001"}\n\n
        data: {"type":"done","tokens_in":1519}\n\n

    No handshake, no upgrade, no second protocol. The browser's built-in
    EventSource reconnects on its own if the connection drops.
    """

    async def events():
        try:
            async for event in STATE["assistant"].ask_stream(ask.question, sid):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # noqa: BLE001
            # The response has already started, so a 500 is no longer
            # possible. The only way to report a failure now is as another
            # event, and the client has to handle it.
            yield f'data: {json.dumps({"type": "error", "message": str(exc)})}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # nginx buffers SSE into uselessness
        },
    )


WIDGET = Path(__file__).parent / "static" / "widget.html"


@app.get("/widget", response_class=HTMLResponse)
def widget() -> str:
    """The embeddable chat page.

    Served from THIS app, which is what makes /session and /chat same-origin
    for it. Embedded in an iframe on another site it becomes cross-origin,
    and the CORS middleware above is what permits that.
    """
    return WIDGET.read_text()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "tools": len(STATE["assistant"].tools)}
