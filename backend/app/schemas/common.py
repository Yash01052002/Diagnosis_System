"""Shared Pydantic schemas: pagination, errors and health payloads."""

from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseSchema(BaseModel):
    """Base for all API schemas."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PaginationParams(BaseModel):
    """Common ``?page=&page_size=`` query parameters."""

    page: Annotated[int, Field(ge=1, description="1-based page number")] = 1
    page_size: Annotated[int, Field(ge=1, le=200, description="Items per page")] = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page(BaseSchema, Generic[T]):
    """A page of results plus the metadata a UI needs to paginate."""

    items: list[T]
    total: int = Field(description="Total number of matching records")
    page: int
    page_size: int
    pages: int = Field(description="Total number of pages")

    @classmethod
    def create(cls, items: list[T], total: int, params: PaginationParams) -> Page[T]:
        pages = (total + params.page_size - 1) // params.page_size if total else 0
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )


class ErrorDetail(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["The requested resource was not found."])
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    """The single error envelope returned by every failing endpoint."""

    error: ErrorDetail


class Message(BaseModel):
    """Generic acknowledgement payload."""

    message: str


class HealthStatus(BaseModel):
    status: str = Field(examples=["ok"])
    version: str
    environment: str


class ReadinessStatus(HealthStatus):
    checks: dict[str, str] = Field(
        description="Per-dependency status", examples=[{"database": "ok", "redis": "skipped"}]
    )
