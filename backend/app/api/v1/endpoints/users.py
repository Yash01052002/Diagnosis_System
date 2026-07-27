"""User administration endpoints (admin-only, except the self-service routes)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AdminUser,
    CurrentUser,
    PaginationDep,
    RequestContextDep,
    UserServiceDep,
    require_admin,
)
from app.schemas.common import ErrorResponse, Page
from app.schemas.user import (
    RoleRead,
    UserAdminCreate,
    UserAdminUpdate,
    UserRead,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=Page[UserRead],
    dependencies=[Depends(require_admin)],
    summary="List users",
)
async def list_users(
    service: UserServiceDep,
    pagination: PaginationDep,
    q: Annotated[str | None, Query(description="Search email or full name")] = None,
    role: Annotated[str | None, Query(description="Filter by role name")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active flag")] = None,
) -> Page[UserRead]:
    """Paginated, filterable list of accounts. Requires the ``admin`` role."""
    items, total = await service.search(
        query=q,
        role=role,
        is_active=is_active,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page.create([UserRead.model_validate(item) for item in items], total, pagination)


@router.get(
    "/roles",
    response_model=list[RoleRead],
    dependencies=[Depends(require_admin)],
    summary="List assignable roles",
)
async def list_roles(service: UserServiceDep) -> list[RoleRead]:
    """Return every role that can be assigned to a user."""
    return [RoleRead.model_validate(role) for role in await service.list_roles()]


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    responses={409: {"model": ErrorResponse, "description": "Email already registered"}},
)
async def create_user(
    payload: UserAdminCreate,
    admin: AdminUser,
    service: UserServiceDep,
    ctx: RequestContextDep,
) -> UserRead:
    """Create an account with explicit roles and activation state (admin only)."""
    user = await service.create(payload, actor=admin, ctx=ctx)
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead, summary="Update your own profile")
async def update_own_profile(
    payload: UserUpdate,
    current_user: CurrentUser,
    service: UserServiceDep,
    ctx: RequestContextDep,
) -> UserRead:
    """Update the authenticated user's name or email. Roles cannot be self-assigned."""
    user = await service.update(current_user.id, payload, actor=current_user, ctx=ctx)
    return UserRead.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_admin)],
    summary="Get a user",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(user_id: uuid.UUID, service: UserServiceDep) -> UserRead:
    """Fetch a single account by id (admin only)."""
    return UserRead.model_validate(await service.get(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Update a user",
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        409: {"model": ErrorResponse, "description": "Email already registered"},
    },
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    admin: AdminUser,
    service: UserServiceDep,
    ctx: RequestContextDep,
) -> UserRead:
    """Partially update an account, including roles and activation (admin only).

    Deactivating an account revokes all of its refresh tokens.
    """
    user = await service.update(user_id, payload, actor=admin, ctx=ctx)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def delete_user(
    user_id: uuid.UUID,
    admin: AdminUser,
    service: UserServiceDep,
    ctx: RequestContextDep,
) -> None:
    """Permanently delete an account (admin only). Self-deletion is rejected."""
    await service.delete(user_id, actor=admin, ctx=ctx)
