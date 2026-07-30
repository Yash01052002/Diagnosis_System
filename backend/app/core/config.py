"""Application configuration.

All settings are loaded from environment variables (12-factor). A single
cached ``Settings`` instance is exposed through :func:`get_settings` so that
configuration can be injected and overridden in tests.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BeforeValidator, EmailStr, Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: Any) -> Any:
    """Allow list-typed settings to be provided as comma separated strings."""
    if isinstance(value, str) and not value.startswith("["):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


CSVList = Annotated[list[str], BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    """Runtime configuration for the BlackBox backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # -- Application ---------------------------------------------------
    PROJECT_NAME: str = "BlackBox Crash Diagnosis API"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Literal["local", "test", "staging", "production"] = "local"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # -- Security ------------------------------------------------------
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 14  # 14 days
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_ALGORITHM: str = "HS256"
    PASSWORD_MIN_LENGTH: int = 10
    #: Max failed logins before an account is temporarily locked.
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15

    # -- CORS ----------------------------------------------------------
    BACKEND_CORS_ORIGINS: CSVList = ["http://localhost:5173", "http://localhost:3000"]

    # -- Database ------------------------------------------------------
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "blackbox"
    POSTGRES_PASSWORD: str = "blackbox"
    POSTGRES_DB: str = "blackbox"
    #: Full override; when set it wins over the discrete POSTGRES_* values.
    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # -- Redis / Celery -------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    # -- Email ----------------------------------------------------------
    #: ``console`` prints messages to the log; ``smtp`` sends real mail.
    EMAIL_BACKEND: Literal["console", "smtp"] = "console"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_TLS: bool = True
    # Typed as EmailStr so a reserved domain (e.g. ".local") fails at startup
    # instead of producing mail the API itself would later reject.
    EMAILS_FROM_EMAIL: EmailStr = "no-reply@blackbox.example.com"
    EMAILS_FROM_NAME: str = "BlackBox"

    # -- Firmware artifacts (Phase 2.5) ----------------------------------
    #: Where uploaded ELF/MAP files live. Mount this as a volume in Docker:
    #: symbols are re-readable from the database, but source line lookup needs
    #: the original file.
    ARTIFACT_STORAGE_DIR: str = "./data/artifacts"
    MAX_ARTIFACT_SIZE_MB: int = 256
    #: Optional external addr2line (e.g. "arm-none-eabi-addr2line"). Purely an
    #: enhancement - it resolves inlined frames. Symbolization works without it
    #: via pyelftools, so no cross toolchain is required in the container.
    ADDR2LINE_BINARY: str | None = None
    #: Symbols indexed per build. A firmware image with more than this is
    #: almost certainly a desktop binary uploaded by mistake.
    MAX_INDEXED_SYMBOLS: int = 200_000
    #: Stack words scanned when reconstructing a call chain.
    MAX_STACK_FRAMES: int = 32
    #: Cortex-M is Thumb-only, so return addresses have bit 0 set. Disable this
    #: only for a non-Thumb target, where it would filter out every frame.
    REQUIRE_THUMB_BIT: bool = True

    # -- AI diagnosis & RAG (Phase 3) ------------------------------------
    #: LLM backend. ``template`` is a deterministic, offline, grounded provider
    #: (the default, and what the test suite uses); ``openai`` and ``ollama``
    #: call a real model over HTTP. The interface is identical, which is what
    #: makes "OpenAI now, local model later" a one-line change.
    LLM_PROVIDER: Literal["template", "openai", "ollama"] = "template"
    #: Embedding backend. ``hashing`` is deterministic and offline; the others
    #: call a real embedding model.
    EMBEDDING_PROVIDER: Literal["hashing", "openai", "ollama"] = "hashing"
    #: Vector store. ``database`` keeps embeddings in PostgreSQL and scores in
    #: Python — no extra infrastructure, works everywhere. ``chroma`` uses a
    #: ChromaDB server for larger corpora.
    VECTOR_STORE: Literal["database", "chroma"] = "database"

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_CHAT_MODEL: str = "llama3.1"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"

    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_COLLECTION: str = "blackbox_kb"

    #: Dimensionality of the offline hashing embedder. Only used by the
    #: ``hashing`` provider; real providers report their own dimension.
    HASHING_EMBEDDING_DIM: int = 384
    #: Characters per knowledge-base chunk, and overlap between adjacent chunks
    #: so a fact split across a boundary is still retrievable from both sides.
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    MAX_DOCUMENT_SIZE_MB: int = 32

    #: How many chunks a diagnosis retrieves as context.
    RAG_TOP_K: int = 6
    #: Cosine similarity below which a retrieved chunk is treated as irrelevant.
    #: The anti-hallucination floor: if nothing clears this, the diagnosis is
    #: returned as explicitly uncertain rather than invented. Calibrated so the
    #: offline hashing embedder's relevant matches (~0.25) clear it while its
    #: irrelevant ones (~0.05) do not; real embedding models score well above.
    RAG_MIN_RELEVANCE: float = 0.18
    #: A diagnosis is labelled uncertain when the best retrieval score is below
    #: this, no matter what the model returns.
    RAG_CONFIDENCE_FLOOR: float = 0.18
    #: Best retrieval score at or above which a well-grounded answer may be
    #: called "certain". Real embedding models reach this for a strong match;
    #: the lexical fallback tops out at "likely", which is the honest label
    #: for a keyword-overlap retrieval feeding a template model.
    RAG_CERTAIN_THRESHOLD: float = 0.55
    LLM_MAX_TOKENS: int = 800
    LLM_TIMEOUT_SECONDS: int = 60

    # -- Frontend --------------------------------------------------------
    FRONTEND_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:5173")

    # -- Bootstrap -------------------------------------------------------
    #: Validated: an unusable address here would seed an admin that can
    #: never log in, because the login schema applies the same validation.
    FIRST_SUPERUSER_EMAIL: EmailStr = "admin@blackbox.example.com"
    FIRST_SUPERUSER_PASSWORD: str = "ChangeMe123!"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_uri(self) -> str:
        """Async SQLAlchemy DSN used by the application."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def alembic_database_uri(self) -> str:
        """Sync DSN for Alembic migrations."""
        return self.sqlalchemy_database_uri.replace("+asyncpg", "+psycopg").replace(
            "+aiosqlite", ""
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def artifact_dir(self) -> Path:
        """Artifact storage root, created on first access."""
        path = Path(self.ARTIFACT_STORAGE_DIR).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_artifact_bytes(self) -> int:
        return self.MAX_ARTIFACT_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


settings = get_settings()
