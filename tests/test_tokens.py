"""Short-lived browser tokens.

These run without a database, a browser or the model — pure signing logic.
The properties they pin are the ones that make it safe to put a credential
in a public web page.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from chargeops.settings import settings
from chargeops.web.tokens import ALGORITHM, TokenInvalid, mint, verify


def test_a_fresh_token_verifies_and_returns_its_session_id():
    token, sid = mint()
    assert verify(token) == sid
    assert sid.startswith("web-")


def test_every_token_gets_its_own_session():
    """Two page loads must not share a conversation."""
    _, first = mint()
    _, second = mint()
    assert first != second


def test_an_expired_token_is_rejected():
    """The library enforces `exp`; we do not have to remember to check it."""
    token, _ = mint(ttl_minutes=-1)
    with pytest.raises(TokenInvalid, match="expired"):
        verify(token)


def test_a_tampered_token_is_rejected():
    """Signed, not encrypted: readable by anyone, changeable by nobody."""
    token, _ = mint()
    forged = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(TokenInvalid):
        verify(forged)


def test_a_token_signed_with_another_secret_is_rejected():
    """Someone who knows the FORMAT still cannot mint one."""
    foreign = jwt.encode(
        {"sid": "web-evil", "scope": "chat",
         "exp": datetime.now(timezone.utc) + timedelta(hours=99)},
        "an-attackers-own-secret-key-long-enough", algorithm=ALGORITHM,
    )
    with pytest.raises(TokenInvalid):
        verify(foreign)


def test_the_wrong_scope_is_rejected():
    """Scope is checked separately from the signature: a validly signed token
    for another purpose must not open the chat endpoint."""
    wrong = jwt.encode(
        {"sid": "web-x", "scope": "admin",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm=ALGORITHM,
    )
    with pytest.raises(TokenInvalid, match="scope"):
        verify(wrong)


def test_the_payload_is_readable_by_anyone():
    """Not a bug — a JWT is a tamper-proof envelope, not a locked one.
    This test exists so nobody ever puts a secret in one."""
    token, sid = mint()
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["sid"] == sid
    assert payload["scope"] == "chat"
