"""Bearer-token auth for the HTTP transport.

stdio needed none: only a local process could talk to the server. Over
HTTP anyone who can reach the port can run queries, so a credential is
not optional.

This is a STATIC shared secret — the simplest thing that works. Real
deployments use OAuth, which MCP supports; the trade-off is that a static
token cannot be scoped, expired, or revoked per client.
"""

import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerTokenMiddleware:
    """Reject any request without the right Authorization header."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    # Reachable without a credential. A health check that needs a secret is
    # a health check your orchestrator cannot run, and it reveals nothing:
    # it says the process is alive, which anyone can infer from the open port.
    PUBLIC_PATHS = frozenset({"/health"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") in self.PUBLIC_PATHS:
            await JSONResponse({"status": "ok"})(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        supplied = headers.get(b"authorization", b"").decode()
        expected = f"Bearer {self.token}"

        # compare_digest, not ==. A plain comparison returns faster on an
        # early mismatch, which leaks the token one character at a time to
        # anyone willing to time the responses.
        if not secrets.compare_digest(supplied, expected):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
