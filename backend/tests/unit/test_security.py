"""Unit tests for password hashing and JWT handling."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import Settings
from app.core.exceptions import TokenError
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    needs_rehash,
    verify_password,
)


@pytest.fixture
def config() -> Settings:
    return Settings(SECRET_KEY="unit-test-secret", ENVIRONMENT="test")


class TestPasswordHashing:
    def test_hash_is_salted_and_verifiable(self) -> None:
        first = hash_password("Str0ng!Passw0rd")
        second = hash_password("Str0ng!Passw0rd")

        assert first != second, "each hash must use a unique salt"
        assert verify_password("Str0ng!Passw0rd", first)
        assert verify_password("Str0ng!Passw0rd", second)

    def test_wrong_password_is_rejected(self) -> None:
        assert not verify_password("wrong", hash_password("Str0ng!Passw0rd"))

    def test_malformed_hash_does_not_raise(self) -> None:
        assert not verify_password("anything", "not-a-bcrypt-hash")

    def test_oversized_password_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password("a" * 73)

    def test_oversized_password_fails_verification(self) -> None:
        assert not verify_password("a" * 73, hash_password("Str0ng!Passw0rd"))

    def test_current_hashes_do_not_need_rehashing(self) -> None:
        assert not needs_rehash(hash_password("Str0ng!Passw0rd"))

    @pytest.mark.parametrize(
        "stored",
        [
            "$2b$04$abcdefghijklmnopqrstuv",  # below the configured work factor
            "sha256$legacy$deadbeef",  # a hash from some other scheme
            "",
        ],
    )
    def test_weak_or_foreign_hashes_are_flagged(self, stored: str) -> None:
        assert needs_rehash(stored)


class TestJWT:
    def test_access_token_round_trip(self, config: Settings) -> None:
        token, jti, expires_at = create_access_token("user-1", roles=["engineer"], config=config)
        payload = decode_token(token, expected_type=TokenType.ACCESS, config=config)

        assert payload["sub"] == "user-1"
        assert payload["roles"] == ["engineer"]
        assert payload["jti"] == jti
        assert payload["exp"] == int(expires_at.timestamp())

    def test_refresh_token_is_typed(self, config: Settings) -> None:
        token, _, _ = create_refresh_token("user-1", config=config)

        assert decode_token(token, config=config)["type"] == "refresh"
        with pytest.raises(TokenError, match="Unexpected token type"):
            decode_token(token, expected_type=TokenType.ACCESS, config=config)

    def test_expired_token_is_rejected(self, config: Settings) -> None:
        token, _, _ = create_access_token(
            "user-1", config=config, expires_delta=timedelta(seconds=-10)
        )
        with pytest.raises(TokenError):
            decode_token(token, config=config)

    def test_token_signed_with_other_key_is_rejected(self, config: Settings) -> None:
        token, _, _ = create_access_token("user-1", config=config)
        other = Settings(SECRET_KEY="a-different-secret", ENVIRONMENT="test")

        with pytest.raises(TokenError):
            decode_token(token, config=other)

    def test_tampered_token_is_rejected(self, config: Settings) -> None:
        token, _, _ = create_access_token("user-1", config=config)
        header, payload, signature = token.split(".")
        tampered = f"{header}.{payload}x.{signature}"

        with pytest.raises(TokenError):
            decode_token(tampered, config=config)


class TestOpaqueTokens:
    def test_tokens_are_unique_and_hash_deterministically(self) -> None:
        first = generate_opaque_token()
        second = generate_opaque_token()

        assert first != second
        assert len(first) >= 32
        assert hash_opaque_token(first) == hash_opaque_token(first)
        assert hash_opaque_token(first) != hash_opaque_token(second)
