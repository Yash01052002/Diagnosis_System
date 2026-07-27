"""Device fleet endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AdminUser,
    CurrentDevice,
    CurrentUser,
    DeviceServiceDep,
    EngineerUser,
    PaginationDep,
    RequestContextDep,
    require_viewer,
)
from app.models.device import DeviceStatus
from app.schemas.common import ErrorResponse, Page
from app.schemas.device import (
    DeviceApiKeyCreate,
    DeviceApiKeyCreated,
    DeviceApiKeyRead,
    DeviceCreate,
    DeviceHeartbeat,
    DeviceRead,
    DeviceStats,
    DeviceUpdate,
)

router = APIRouter(prefix="/devices", tags=["Devices"])


@router.get(
    "",
    response_model=Page[DeviceRead],
    dependencies=[Depends(require_viewer)],
    summary="List devices",
)
async def list_devices(
    service: DeviceServiceDep,
    pagination: PaginationDep,
    q: Annotated[
        str | None, Query(description="Search id, serial, model, location or description")
    ] = None,
    status_filter: Annotated[
        DeviceStatus | None, Query(alias="status", description="Filter by status")
    ] = None,
    firmware_version: Annotated[str | None, Query(description="Exact firmware version")] = None,
    hardware_model: Annotated[str | None, Query(description="Exact hardware model")] = None,
    tag: Annotated[str | None, Query(description="Filter by tag name")] = None,
    owner_id: Annotated[uuid.UUID | None, Query(description="Filter by owner")] = None,
    online_since: Annotated[
        datetime | None, Query(description="Only devices seen at or after this time")
    ] = None,
) -> Page[DeviceRead]:
    """Paginated, filterable device list. Any authenticated role may read."""
    items, total = await service.search(
        query=q,
        status=status_filter,
        firmware_version=firmware_version,
        hardware_model=hardware_model,
        tag=tag,
        owner_id=owner_id,
        online_since=online_since,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page.create([DeviceRead.model_validate(item) for item in items], total, pagination)


@router.post(
    "",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a device",
    responses={409: {"model": ErrorResponse, "description": "Identifier already registered"}},
)
async def create_device(
    payload: DeviceCreate,
    engineer: EngineerUser,
    service: DeviceServiceDep,
    ctx: RequestContextDep,
) -> DeviceRead:
    """Register a device. Requires the ``engineer`` role.

    The device cannot submit crash reports until an API key is issued for it.
    """
    device = await service.create(payload, actor=engineer, ctx=ctx)
    return DeviceRead.model_validate(device)


@router.post(
    "/heartbeat",
    response_model=DeviceRead,
    summary="Device check-in",
    responses={401: {"model": ErrorResponse, "description": "Invalid device API key"}},
)
async def device_heartbeat(
    device: CurrentDevice,
    service: DeviceServiceDep,
    payload: DeviceHeartbeat | None = None,
) -> DeviceRead:
    """Record that a device is alive, authenticated by its API key.

    Devices may also report their current firmware version here, so an OTA
    update is reflected without anyone editing the record by hand.
    """
    updated = await service.heartbeat(device, payload)
    return DeviceRead.model_validate(await service.get(updated.id))


@router.get(
    "/{device_id}",
    response_model=DeviceRead,
    dependencies=[Depends(require_viewer)],
    summary="Get a device",
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def get_device(device_id: uuid.UUID, service: DeviceServiceDep) -> DeviceRead:
    """Fetch a single device by its internal id."""
    return DeviceRead.model_validate(await service.get(device_id))


@router.get(
    "/{device_id}/stats",
    response_model=DeviceStats,
    dependencies=[Depends(require_viewer)],
    summary="Crash counters for a device",
)
async def get_device_stats(device_id: uuid.UUID, service: DeviceServiceDep) -> DeviceStats:
    """Total, open and last-24h crash counts for one device."""
    return await service.stats(device_id)


@router.patch(
    "/{device_id}",
    response_model=DeviceRead,
    summary="Update a device",
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def update_device(
    device_id: uuid.UUID,
    payload: DeviceUpdate,
    engineer: EngineerUser,
    service: DeviceServiceDep,
    ctx: RequestContextDep,
) -> DeviceRead:
    """Partially update a device. ``device_id`` and ``serial_number`` are immutable."""
    device = await service.update(device_id, payload, actor=engineer, ctx=ctx)
    return DeviceRead.model_validate(device)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a device",
    responses={404: {"model": ErrorResponse, "description": "Device not found"}},
)
async def delete_device(
    device_id: uuid.UUID,
    admin: AdminUser,
    service: DeviceServiceDep,
    ctx: RequestContextDep,
) -> None:
    """Delete a device **and its entire crash history**.

    Restricted to ``admin`` precisely because of that cascade; engineers who
    want a device out of the way should set its status to ``decommissioned``.
    """
    await service.delete(device_id, actor=admin, ctx=ctx)


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
@router.get(
    "/{device_id}/api-keys",
    response_model=list[DeviceApiKeyRead],
    summary="List a device's API keys",
)
async def list_api_keys(
    device_id: uuid.UUID,
    engineer: EngineerUser,
    service: DeviceServiceDep,
) -> list[DeviceApiKeyRead]:
    """Key metadata only — the secrets are not recoverable."""
    keys = await service.list_api_keys(device_id)
    return [DeviceApiKeyRead.model_validate(key) for key in keys]


@router.post(
    "/{device_id}/api-keys",
    response_model=DeviceApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Issue an API key for a device",
)
async def create_api_key(
    device_id: uuid.UUID,
    payload: DeviceApiKeyCreate,
    engineer: EngineerUser,
    service: DeviceServiceDep,
    ctx: RequestContextDep,
) -> DeviceApiKeyCreated:
    """Mint a key the device uses to submit crash reports.

    The plaintext key is returned **once**; only its hash is stored. Flash it
    to the device now — a lost key can only be replaced, not recovered.
    """
    key, plaintext = await service.create_api_key(
        device_id,
        name=payload.name,
        expires_at=payload.expires_at,
        actor=engineer,
        ctx=ctx,
    )
    return DeviceApiKeyCreated(
        **DeviceApiKeyRead.model_validate(key).model_dump(), api_key=plaintext
    )


@router.delete(
    "/{device_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    responses={404: {"model": ErrorResponse, "description": "Key not found"}},
)
async def revoke_api_key(
    device_id: uuid.UUID,
    key_id: uuid.UUID,
    engineer: EngineerUser,
    service: DeviceServiceDep,
    ctx: RequestContextDep,
) -> None:
    """Revoke a key immediately. Revocation is permanent."""
    await service.revoke_api_key(device_id, key_id, actor=engineer, ctx=ctx)


@router.post(
    "/{device_id}/heartbeat",
    response_model=DeviceRead,
    summary="Record a check-in on a device's behalf",
)
async def device_heartbeat_by_id(
    device_id: uuid.UUID,
    current_user: CurrentUser,
    service: DeviceServiceDep,
    payload: DeviceHeartbeat | None = None,
) -> DeviceRead:
    """Mark a device as seen without its API key (operator action)."""
    device = await service.get(device_id)
    await service.heartbeat(device, payload)
    return DeviceRead.model_validate(await service.get(device.id))
