"""Short-lived tokens for browser sessions.

The MCP token (API_TOKEN) is long-lived and grants everything, including
run_sql. It must NEVER reach a browser — `view source` is all it takes.

So the browser gets a different credential entirely:

    API_TOKEN            browser token
    ---------            -------------
    never expires        15 minutes
    full tool access     chat only
    lives in .env        lives in the page, and that's fine
    one shared secret    one per page load, carrying a session id

A stolen browser token buys fifteen minutes of asking questions the widget
could already ask. A stolen API_TOKEN buys your database.

JWT because it is SIGNED, not encrypted. Anyone can read the contents — that
is expected. What they cannot do is change them: alter the expiry or the
session id and the signature stops matching.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from ..settings import settings

ALGORITHM = "HS256"


class TokenInvalid(Exception):
    """Expired, tampered with, or not one of ours."""


def mint(ttl_minutes: int | None = None) -> tuple[str, str]:
    """Issue a token for one browser session. Returns (token, session_id)."""
    session_id = f"web-{uuid.uuid4().hex[:12]}"
    ttl = ttl_minutes if ttl_minutes is not None else settings.browser_token_minutes
    now = datetime.now(timezone.utc)

    payload = {
        "sid": session_id,                        # which conversation
        "scope": "chat",                          # NOT sql. Narrow on purpose.
        "iat": now,                               # issued at
        "exp": now + timedelta(minutes=ttl),      # the library enforces this
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), session_id


def verify(token: str) -> str:
    """Return the session id, or raise TokenInvalid.

    jwt.decode checks the signature AND the expiry. Both failures are
    reported the same way to the caller: an expired token and a forged one
    are equally not-allowed, and distinguishing them tells an attacker which
    half they got right.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenInvalid("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalid("token invalid") from exc

    if payload.get("scope") != "chat":
        raise TokenInvalid("wrong scope")
    return payload["sid"]
