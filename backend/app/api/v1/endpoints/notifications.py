"""Notification inbox and alert-settings endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AdminUser,
    CurrentUser,
    NotificationServiceDep,
    PaginationDep,
    RequestContextDep,
)
from app.schemas.common import ErrorResponse, Message, Page
from app.schemas.notification import (
    AlertSettingsRead,
    AlertSettingsUpdate,
    NotificationRead,
    UnreadCount,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=Page[NotificationRead], summary="Your notifications")
async def list_notifications(
    user: CurrentUser,
    service: NotificationServiceDep,
    pagination: PaginationDep,
    unread_only: Annotated[bool, Query(description="Only unread notifications")] = False,
) -> Page[NotificationRead]:
    """The current user's notifications, newest first."""
    items, total = await service.list_for_user(
        user.id, unread_only=unread_only, offset=pagination.offset, limit=pagination.limit
    )
    return Page.create(
        [NotificationRead.model_validate(item) for item in items], total, pagination
    )


@router.get("/unread-count", response_model=UnreadCount, summary="Unread count")
async def unread_count(user: CurrentUser, service: NotificationServiceDep) -> UnreadCount:
    """How many notifications the current user has not read — for the bell badge."""
    return UnreadCount(count=await service.unread_count(user.id))


@router.post(
    "/read-all",
    response_model=Message,
    summary="Mark all as read",
)
async def mark_all_read(user: CurrentUser, service: NotificationServiceDep) -> Message:
    count = await service.mark_all_read(user.id)
    return Message(message=f"Marked {count} notification(s) as read.")


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark one as read",
    responses={404: {"model": ErrorResponse, "description": "Notification not found"}},
)
async def mark_read(
    notification_id: uuid.UUID,
    user: CurrentUser,
    service: NotificationServiceDep,
) -> NotificationRead:
    notification = await service.mark_read(notification_id, user_id=user.id)
    return NotificationRead.model_validate(notification)


# ---------------------------------------------------------------------------
# Alert settings (admin)
# ---------------------------------------------------------------------------
@router.get(
    "/settings",
    response_model=AlertSettingsRead,
    summary="Get alert settings",
)
async def get_alert_settings(
    _admin: AdminUser, service: NotificationServiceDep
) -> AlertSettingsRead:
    """The fleet-wide alert policy (admin only)."""
    settings = await service.get_settings()
    return AlertSettingsRead.model_validate(settings)


@router.patch(
    "/settings",
    response_model=AlertSettingsRead,
    status_code=status.HTTP_200_OK,
    summary="Update alert settings",
)
async def update_alert_settings(
    payload: AlertSettingsUpdate,
    admin: AdminUser,
    service: NotificationServiceDep,
    ctx: RequestContextDep,
) -> AlertSettingsRead:
    """Change the alert threshold, recipients and email toggle (admin only)."""
    settings = await service.update_settings(payload, actor=admin, ctx=ctx)
    return AlertSettingsRead.model_validate(settings)
