"""Supabase JWT verification.

REDLY Cloud does not run its own user/password auth — Supabase Auth issues
the JWT when the desktop app signs a user in directly against Supabase. This
backend only ever *verifies* that JWT on incoming requests; it never sees a
password and never mints a session itself.

Verification is local (HS256 against the Supabase JWT secret) — no network
call to Supabase per request, so this stays cheap even at request volume.
"""

from __future__ import annotations

import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

logger = logging.getLogger("app.auth")

_bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    """The authenticated caller, resolved once per request from their JWT."""

    __slots__ = ("id", "email")

    def __init__(self, user_id: str, email: str | None) -> None:
        self.id = user_id
        self.email = email


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """FastAPI dependency: require a valid Supabase-issued JWT.

    Every route that touches per-user cloud data (agent sync, conversation
    sync, usage/cost tracking) depends on this. Routes that don't need a
    signed-in user (health check) simply don't declare the dependency.
    """
    settings = get_settings()
    if not settings.supabase_jwt_secret:
        # Misconfiguration, not a client error — fail loudly in logs so a
        # deploy without the secret set is obvious rather than silently
        # accepting every request.
        logger.error("SUPABASE_JWT_SECRET is not configured; rejecting authenticated request")
        raise _unauthorized("Server is not configured for authentication")

    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token")

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expired, please sign in again") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Invalid session token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized("Token missing subject claim")

    return CurrentUser(user_id=user_id, email=payload.get("email"))
