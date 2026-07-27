"""Password hashing and JWT helpers.

This module has no knowledge of the database or the web framework; it is pure
cryptographic plumbing so it can be unit-tested in isolation and swapped out
(e.g. for Argon2 or asymmetric JWTs) without touching callers.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import Settings, settings
from app.core.exceptions import TokenError

#: bcrypt silently truncates beyond 72 bytes; reject instead of truncating.
MAX_PASSWORD_BYTES = 72

#: Work factor. Raising this invalidates nothing: ``needs_rehash`` detects
#: hashes stored at a lower cost and login transparently upgrades them.
BCRYPT_ROUNDS = 12

_HASH_COST = re.compile(r"^\$2[aby]\$(\d{2})\$")


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Return a bcrypt hash for ``password``."""
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time verification of ``plain_password`` against a stored hash."""
    encoded = plain_password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed or unknown hash in the database - treat as a failed login
        # rather than a 500, so one corrupt row cannot break the endpoint.
        return False


def needs_rehash(hashed_password: str) -> bool:
    """True when the stored hash was created with a lower work factor."""
    match = _HASH_COST.match(hashed_password)
    if match is None:
        return True  # unrecognised format: replace it on next successful login
    return int(match.group(1)) < BCRYPT_ROUNDS


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    *,
    config: Settings | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Build a signed JWT. Returns ``(token, jti, expires_at)``."""
    cfg = config or settings
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())
    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "jti": jti,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": cfg.PROJECT_NAME,
    }
    if extra_claims:
        claims.update(extra_claims)
    token = jwt.encode(claims, cfg.SECRET_KEY, algorithm=cfg.JWT_ALGORITHM)
    return token, jti, expires_at


def create_access_token(
    subject: str,
    *,
    roles: list[str] | None = None,
    config: Settings | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, str, datetime]:
    """Create a short-lived access token carrying the user's roles."""
    cfg = config or settings
    delta = expires_delta or timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_token(
        subject,
        TokenType.ACCESS,
        delta,
        config=cfg,
        extra_claims={"roles": roles or []},
    )


def create_refresh_token(
    subject: str,
    *,
    config: Settings | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, str, datetime]:
    """Create a long-lived refresh token. The ``jti`` is persisted for revocation."""
    cfg = config or settings
    delta = expires_delta or timedelta(minutes=cfg.REFRESH_TOKEN_EXPIRE_MINUTES)
    return _create_token(subject, TokenType.REFRESH, delta, config=cfg)


def decode_token(
    token: str,
    *,
    expected_type: TokenType | None = None,
    config: Settings | None = None,
) -> dict[str, Any]:
    """Decode and validate a JWT.

    Raises:
        TokenError: if the signature, expiry, issuer or type is invalid.
    """
    cfg = config or settings
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            cfg.SECRET_KEY,
            algorithms=[cfg.JWT_ALGORITHM],
            issuer=cfg.PROJECT_NAME,
        )
    except JWTError as exc:
        raise TokenError() from exc

    if expected_type is not None and payload.get("type") != expected_type.value:
        raise TokenError("Unexpected token type.")
    if not payload.get("sub"):
        raise TokenError("Token is missing a subject.")
    return payload


# --------------------------------------------------------------------------
# Opaque tokens (password reset)
# --------------------------------------------------------------------------
def generate_opaque_token(nbytes: int = 32) -> str:
    """Generate a URL-safe random secret to email to the user."""
    return secrets.token_urlsafe(nbytes)


def hash_opaque_token(token: str) -> str:
    """Hash an opaque token for storage.

    SHA-256 is appropriate here (unlike for passwords): the token already has
    256 bits of entropy, so it is not brute-forceable, and lookups must be fast.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)
