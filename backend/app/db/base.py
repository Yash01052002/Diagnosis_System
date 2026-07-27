"""Declarative base and common column types."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import CHAR, JSON, TypeDecorator

#: Deterministic constraint names so Alembic autogenerate produces stable diffs.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID type.

    Uses PostgreSQL's native ``UUID`` when available and falls back to a
    36-character string elsewhere (SQLite, used by the test suite).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


#: JSONB on PostgreSQL, plain JSON elsewhere.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        uuid.UUID: GUID,
        dict[str, Any]: JSONType,
    }

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """Adds a UUID surrogate primary key generated in Python."""

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4, sort_order=-100
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at``.

    Values are generated in Python so that the attribute is populated during
    the flush itself. A SQL-side ``onupdate`` would expire the attribute and
    force a follow-up SELECT, which is illegal inside async serialization.
    ``server_default`` is kept so rows inserted by raw SQL are still stamped.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
        sort_order=100,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
        sort_order=101,
    )
