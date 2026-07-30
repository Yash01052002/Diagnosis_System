"""Pytest fixtures.

Tests run against an in-memory SQLite database with the real schema created
from the ORM metadata, so no PostgreSQL server is required. Everything that
touches the network (email) is replaced with an in-memory double.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from app.api.deps import get_email_service  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.security import generate_api_key, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import enable_sqlite_foreign_keys, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    BuildStatus,
    BuildSymbol,
    CrashReport,
    CrashSeverity,
    CrashStatus,
    Device,
    DeviceApiKey,
    DeviceStatus,
    FaultType,
    FirmwareBuild,
    Role,
    RoleName,
    Tag,
    User,
)
from app.services.elf_parser import ElfParser  # noqa: E402
from app.services.email import InMemoryEmailSender  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:  # type: ignore[no-untyped-def]
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
        # Isolated artifact storage so uploads never touch the repo tree.
        ARTIFACT_STORAGE_DIR=str(tmp_path_factory.mktemp("artifacts")),
        # The fixture ELF is x86-64, which has no Thumb bit; requiring one
        # would filter out every reconstructed stack frame.
        REQUIRE_THUMB_BIT=False,
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
    # Without this SQLite ignores ON DELETE CASCADE, and the suite would pass
    # while the same delete orphaned rows on PostgreSQL.
    enable_sqlite_foreign_keys(test_engine)
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


# ---------------------------------------------------------------------------
# Device and crash factories
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def device_factory(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    """Create devices directly, bypassing the API."""
    counter = count(1)

    async def create_device(
        *,
        device_id: str | None = None,
        serial_number: str | None = None,
        firmware_version: str = "1.4.2",
        hardware_model: str = "STM32F407VG",
        status: str = DeviceStatus.ACTIVE,
        owner: User | None = None,
        tags: list[str] | None = None,
        location: str | None = None,
        last_online_at: datetime | None = None,
    ) -> Device:
        index = next(counter)
        device = Device(
            device_id=device_id or f"STM32-F4-{index:04d}",
            serial_number=serial_number or f"SN-TEST-{index:06d}",
            firmware_version=firmware_version,
            hardware_model=hardware_model,
            status=status,
            location=location,
            owner_id=owner.id if owner else None,
            last_online_at=last_online_at,
        )
        for name in tags or []:
            normalized = Tag.normalize(name)
            existing = (
                (await db_session.execute(select(Tag).where(Tag.name == normalized)))
                .scalars()
                .first()
            )
            device.tags.append(existing or Tag(name=normalized))
        db_session.add(device)
        await db_session.commit()
        await db_session.refresh(device, attribute_names=["tags"])
        return device

    return create_device


@pytest_asyncio.fixture
async def api_key_factory(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    """Issue a device API key, returning the plaintext for use in headers."""

    async def create_key(
        device: Device,
        *,
        name: str = "test-key",
        expires_at: datetime | None = None,
        revoked: bool = False,
    ) -> str:
        generated = generate_api_key()
        key = DeviceApiKey(
            device_id=device.id,
            prefix=generated.prefix,
            key_hash=generated.key_hash,
            name=name,
            expires_at=expires_at,
            revoked_at=datetime.now(UTC) if revoked else None,
        )
        db_session.add(key)
        await db_session.commit()
        return generated.plaintext

    return create_key


@pytest_asyncio.fixture
async def crash_factory(db_session: AsyncSession):  # type: ignore[no-untyped-def]
    """Create crash reports directly, bypassing ingestion."""

    async def create_crash(
        device: Device,
        *,
        fault_type: str = FaultType.HARD_FAULT,
        severity: str = CrashSeverity.CRITICAL,
        status: str = CrashStatus.NEW,
        firmware_version: str | None = None,
        task_name: str = "SensorTask",
        occurred_at: datetime | None = None,
        program_counter: int | None = 0x08001A2C,
        ai_diagnosis: str | None = None,
    ) -> CrashReport:
        when = occurred_at or datetime.now(UTC)
        report = CrashReport(
            device_id=device.id,
            firmware_version=firmware_version or device.firmware_version,
            occurred_at=when,
            received_at=when,
            fault_type=fault_type,
            task_name=task_name,
            program_counter=program_counter,
            severity=severity,
            status=status,
            ai_diagnosis=ai_diagnosis,
        )
        db_session.add(report)
        await db_session.commit()
        await db_session.refresh(report)
        return report

    return create_crash


def crash_payload(**overrides: object) -> dict[str, object]:
    """A representative STM32 + FreeRTOS crash payload."""
    payload: dict[str, object] = {
        "firmware_version": "1.4.2",
        "build_version": "a1b2c3d",
        "timestamp": "2026-07-27T09:14:22Z",
        "fault_type": "HardFault",
        "task_name": "SensorTask",
        "pc": "0x08001A2C",
        "lr": "0x08001A0F",
        "sp": "0x20017FA0",
        "registers": {"r0": "0x00000000", "r1": "0x20000100", "xpsr": "0x61000000"},
        "stack": ["0x08001A2C", "0x20017FB0"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Firmware build fixtures
# ---------------------------------------------------------------------------
#: A small C program compiled with debug info. Using a real ELF rather than a
#: hand-rolled fake is deliberate: the symbol table, section flags and DWARF
#: line program are exactly what pyelftools will meet in production, and a
#: fixture that only resembled one would hide the bugs worth catching.
_FIXTURE_SOURCE = """
#include <stdint.h>
volatile int sink;
int helper_add(int a, int b) { return a + b; }
int compute_checksum(const uint8_t *d, int n) {
    int s = 0;
    for (int i = 0; i < n; i++) s = helper_add(s, d[i]);
    return s;
}
void sensor_task_body(void) { sink = compute_checksum((const uint8_t*)"abc", 3); }
int main(void) { sensor_task_body(); return sink; }
"""


@pytest.fixture(scope="session")
def elf_fixture(tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """Compile a real ELF once per session.

    Skips rather than fails when no C compiler is available, so the rest of
    the suite still runs on a machine without build tools.
    """
    compiler = shutil.which("gcc") or shutil.which("cc")
    if compiler is None:
        pytest.skip("no C compiler available to build the ELF fixture")

    directory = tmp_path_factory.mktemp("elf")
    source = directory / "fw.c"
    source.write_text(_FIXTURE_SOURCE)
    elf = directory / "fw.elf"

    result = subprocess.run(
        [compiler, "-g", "-O0", "-o", str(elf), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not elf.is_file():
        pytest.skip(f"could not compile the ELF fixture: {result.stderr[:200]}")
    return elf


@pytest.fixture(scope="session")
def elf_symbols(elf_fixture: Path) -> dict[str, int]:
    """``{function_name: address}`` for the fixture's own functions."""
    info = ElfParser().parse(elf_fixture)
    return {
        symbol.name: symbol.address
        for symbol in info.function_symbols
        if symbol.name in {"helper_add", "compute_checksum", "sensor_task_body", "main"}
    }


@pytest.fixture
def artifact_settings(settings: Settings, tmp_path: Path) -> Settings:
    """Settings pointed at a per-test artifact directory."""
    return settings.model_copy(
        update={
            "ARTIFACT_STORAGE_DIR": str(tmp_path / "artifacts"),
            # The fixture ELF is x86-64, which has no Thumb bit; requiring one
            # would filter out every stack candidate.
            "REQUIRE_THUMB_BIT": False,
        }
    )


@pytest_asyncio.fixture
async def build_factory(db_session: AsyncSession, elf_fixture: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Create an indexed FirmwareBuild backed by the real ELF."""

    async def create_build(
        *,
        firmware_version: str = "1.4.2",
        build_version: str | None = "a1b2c3d",
        status: str = BuildStatus.INDEXED,
        with_symbols: bool = True,
        copy_artifact: bool = True,
    ) -> FirmwareBuild:
        info = ElfParser().parse(elf_fixture)

        storage = tmp_path / "artifacts"
        storage.mkdir(parents=True, exist_ok=True)
        stored = storage / f"{uuid4()}.elf"
        if copy_artifact:
            shutil.copy(elf_fixture, stored)

        build = FirmwareBuild(
            firmware_version=firmware_version,
            build_version=build_version,
            artifact_type="elf",
            original_filename="fw.elf",
            storage_path=str(stored),
            file_size=elf_fixture.stat().st_size,
            sha256="0" * 64,
            status=status,
            arch=info.arch,
            has_debug_info=info.has_dwarf,
            entry_point=info.entry_point,
            symbol_count=len(info.symbols) if with_symbols else 0,
            sections={
                "sections": [
                    {
                        "name": section.name,
                        "start": section.start,
                        "size": section.size,
                        "executable": section.executable,
                    }
                    for section in info.sections
                ]
            },
        )
        db_session.add(build)
        await db_session.flush()

        if with_symbols:
            db_session.add_all(
                [
                    BuildSymbol(
                        build_id=build.id,
                        name=symbol.name,
                        address=symbol.address,
                        size=symbol.size,
                        kind=symbol.kind,
                    )
                    for symbol in info.symbols
                ]
            )
        await db_session.commit()
        await db_session.refresh(build)
        return build

    return create_build
