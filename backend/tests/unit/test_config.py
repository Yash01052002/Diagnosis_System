"""Configuration parsing.

The list-valued settings are the fragile ones: pydantic-settings JSON-decodes
complex fields inside the env/dotenv source *before* validators run, so without
``NoDecode`` a plain ``FOO=a,b`` line in a ``.env`` raises a parse error. That
bit `cp .env.example .env` — the documented first step — so it is pinned here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


class TestListSettings:
    def test_comma_separated_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "BACKEND_CORS_ORIGINS", "https://a.example.com,https://b.example.com"
        )
        monkeypatch.setenv("ALERT_RECIPIENT_ROLES", "admin,engineer")

        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        assert settings.BACKEND_CORS_ORIGINS == [
            "https://a.example.com",
            "https://b.example.com",
        ]
        assert settings.ALERT_RECIPIENT_ROLES == ["admin", "engineer"]

    def test_json_list_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["https://a.example.com"]')
        monkeypatch.setenv("ALERT_RECIPIENT_ROLES", '["admin"]')

        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        assert settings.BACKEND_CORS_ORIGINS == ["https://a.example.com"]
        assert settings.ALERT_RECIPIENT_ROLES == ["admin"]

    def test_whitespace_is_trimmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALERT_RECIPIENT_ROLES", " admin , engineer ,")
        assert Settings(_env_file=None).ALERT_RECIPIENT_ROLES == [  # type: ignore[call-arg]
            "admin",
            "engineer",
        ]

    def test_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
        monkeypatch.delenv("ALERT_RECIPIENT_ROLES", raising=False)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.ALERT_RECIPIENT_ROLES == ["admin", "engineer"]
        assert "http://localhost:5173" in settings.BACKEND_CORS_ORIGINS


class TestEnvExample:
    """`cp .env.example .env` must produce a bootable configuration."""

    def test_env_example_loads(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        assert ENV_EXAMPLE.is_file(), f"missing {ENV_EXAMPLE}"
        env_file = tmp_path / ".env"
        env_file.write_text(ENV_EXAMPLE.read_text())

        # Clear anything the ambient environment would mask the file with.
        for key in (
            "BACKEND_CORS_ORIGINS",
            "ALERT_RECIPIENT_ROLES",
            "DATABASE_URL",
            "SECRET_KEY",
            "ENVIRONMENT",
        ):
            monkeypatch.delenv(key, raising=False)

        settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

        assert settings.BACKEND_CORS_ORIGINS  # parsed, not raised
        assert settings.ALERT_RECIPIENT_ROLES == ["admin", "engineer"]
        assert settings.sqlalchemy_database_uri.startswith("postgresql+asyncpg://")
