"""Pytest fixtures.

Tests run against an in-memory SQLite database with the real schema created
from the ORM metadata, so no PostgreSQL server is required. Everything that
touches the network (email) is replaced with an in-memory double.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from app.api.deps import get_email_service  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Role, RoleName, User  # noqa: E402
from app.services.email import InMemoryEmailSender  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings pinned to the test database and fast token lifetimes."""
    get_settings.cache_clear()
    return Settings(
        ENVIRONMENT="test",
        DATABASE_URL=TEST_DATABASE_URL,
        SECRET_KEY="test-secret-key-not-for-production-use-only",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        MAX_FAILED_LOGIN_ATTEMPTS=3,
        ACCOUNT_LOCKOUT_MINUTES=15,
        EMAIL_BACKEND="console",
        LOG_JSON=False,
        LOG_LEVEL="WARNING",
    )


@pytest_asyncio.fixture
async def engine():  # type: ignore[no-untyped-def]
    """A fresh in-memory schema per test.

    ``StaticPool`` keeps every connection pointed at the same in-memory
    database, which SQLite otherwise scopes per connection.
    """
    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:  # type: ignore[no-untyped-def]
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[no-untyped-def]
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_roles(db_session: AsyncSession) -> dict[str, Role]:
    """Insert the three built-in roles."""
    roles = {
        name: Role(name=name, description=f"{name} role")
        for name in (RoleName.ADMIN, RoleName.ENGINEER, RoleName.VIEWER)
    }
    db_session.add_all(list(roles.values()))
    await db_session.commit()
    return {str(key): value for key, value in roles.items()}


@pytest.fixture
def email_sender() -> InMemoryEmailSender:
    """Captures outgoing mail so tests can assert on reset links."""
    return InMemoryEmailSender()


@pytest_asyncio.fixture
async def app(session_factory, settings: Settings, email_sender: InMemoryEmailSender):  # type: ignore[no-untyped-def]
    """The FastAPI app with database and email dependencies overridden."""
    application = create_app(settings)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_email_service] = lambda: email_sender
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


# ---------------------------------------------------------------------------
# User factories
# ---------------------------------------------------------------------------
DEFAULT_PASSWORD = "Str0ng!Passw0rd"


@pytest_asyncio.fixture
async def user_factory(db_session: AsyncSession, seeded_roles: dict[str, Role]):  # type: ignore[no-untyped-def]
    """Return a coroutine that creates users with the given roles."""

    async def create_user(
        *,
        email: str = "user@example.com",
        password: str = DEFAULT_PASSWORD,
        roles: list[str] | None = None,
        is_active: bool = True,
        full_name: str | None = "Test User",
    ) -> User:
        user = User(
            email=email.lower(),
            full_name=full_name,
            hashed_password=hash_password(password),
            is_active=is_active,
            is_verified=True,
        )
        for role_name in roles or [RoleName.VIEWER]:
            user.roles.append(seeded_roles[str(role_name)])
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user, attribute_names=["roles"])
        return user

    return create_user


@pytest_asyncio.fixture
async def viewer_user(user_factory) -> User:  # type: ignore[no-untyped-def]
    return await user_factory(email="viewer@example.com", roles=[RoleName.VIEWER])


@pytest_asyncio.fixture
async def engineer_user(user_factory) -> User:  # type: ignore[no-untyped-def]
    return await user_factory(email="engineer@example.com", roles=[RoleName.ENGINEER])


@pytest_asyncio.fixture
async def admin_user(user_factory) -> User:  # type: ignore[no-untyped-def]
    return await user_factory(email="admin@example.com", roles=[RoleName.ADMIN])


@pytest_asyncio.fixture
async def login(client: AsyncClient):  # type: ignore[no-untyped-def]
    """Log a user in and return the JSON token payload."""

    async def do_login(email: str, password: str = DEFAULT_PASSWORD) -> dict:
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 200, response.text
        return response.json()

    return do_login


@pytest_asyncio.fixture
async def auth_headers(login):  # type: ignore[no-untyped-def]
    """Return ``Authorization`` headers for a user."""

    async def make_headers(email: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
        tokens = await login(email, password)
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    return make_headers
