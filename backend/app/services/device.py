"""Device fleet management."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, TokenError, ValidationError
from app.core.logging import get_logger
from app.core.security import generate_api_key, split_api_key, verify_api_key
from app.models.audit_log import AuditAction
from app.models.device import Device, DeviceApiKey, DeviceStatus
from app.models.user import User
from app.repositories.crash import CrashReportRepository
from app.repositories.device import (
    DeviceApiKeyRepository,
    DeviceRepository,
    TagRepository,
)
from app.schemas.device import DeviceCreate, DeviceHeartbeat, DeviceStats, DeviceUpdate
from app.services.audit import AuditService
from app.services.auth import RequestContext

logger = get_logger(__name__)


class DeviceService:
    """Use-cases for registering and maintaining devices."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        devices: DeviceRepository,
        tags: TagRepository,
        api_keys: DeviceApiKeyRepository,
        crashes: CrashReportRepository,
        audit: AuditService,
    ) -> None:
        self.session = session
        self.devices = devices
        self.tags = tags
        self.api_keys = api_keys
        self.crashes = crashes
        self.audit = audit

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, device_id: uuid.UUID) -> Device:
        device = await self.devices.get_full(device_id)
        if device is None:
            raise NotFoundError("Device not found.")
        return device

    async def get_by_identifier(self, identifier: str) -> Device:
        device = await self.devices.get_by_identifier(identifier)
        if device is None:
            raise NotFoundError(
                f"No device registered with identifier {identifier!r}.",
                details={"identifier": identifier},
            )
        return device

    async def search(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        firmware_version: str | None = None,
        hardware_model: str | None = None,
        tag: str | None = None,
        owner_id: uuid.UUID | None = None,
        online_since: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[Device], int]:
        """Filtered, paginated device listing. Returns ``(items, total)``."""
        return await self.devices.search(
            query=query,
            status=status,
            firmware_version=firmware_version,
            hardware_model=hardware_model,
            tag=tag,
            owner_id=owner_id,
            online_since=online_since,
            offset=offset,
            limit=limit,
        )

    async def stats(self, device_id: uuid.UUID) -> DeviceStats:
        """Crash counters for one device."""
        device = await self.get(device_id)
        counts = await self.crashes.count_for_device(device.id)
        return DeviceStats(
            device_id=device.id,
            total_crashes=counts["total"],
            open_crashes=counts["open"],
            crashes_last_24h=counts["last_24h"],
            last_crash_at=await self.crashes.last_crash_at(device.id),
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def create(
        self, payload: DeviceCreate, *, actor: User, ctx: RequestContext | None = None
    ) -> Device:
        ctx = ctx or RequestContext()
        if await self.devices.identifier_taken(
            device_id=payload.device_id, serial_number=payload.serial_number
        ):
            raise ConflictError(
                "A device with this device_id or serial number already exists.",
                details={
                    "device_id": payload.device_id,
                    "serial_number": payload.serial_number,
                },
            )

        device = Device(
            device_id=payload.device_id.strip(),
            serial_number=payload.serial_number.strip(),
            firmware_version=payload.firmware_version,
            hardware_model=payload.hardware_model,
            status=payload.status,
            location=payload.location,
            description=payload.description,
            # An unowned device has nobody to alert, so default to the creator.
            owner_id=payload.owner_id or actor.id,
        )
        device.tags = await self.tags.get_or_create_many(payload.tags)
        self.devices.add(device)
        await self.session.flush()

        await self.audit.record(
            AuditAction.DEVICE_CREATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="device",
            resource_id=device.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"device_id": device.device_id, "tags": payload.tags},
        )
        await self.session.commit()
        logger.info("device.created", device_id=device.device_id)
        return await self.get(device.id)

    async def update(
        self,
        device_id: uuid.UUID,
        payload: DeviceUpdate,
        *,
        actor: User,
        ctx: RequestContext | None = None,
    ) -> Device:
        ctx = ctx or RequestContext()
        device = await self.get(device_id)
        data = payload.model_dump(exclude_unset=True)
        changed: dict[str, object] = {}

        for attribute in (
            "firmware_version",
            "hardware_model",
            "status",
            "location",
            "description",
            "owner_id",
        ):
            if attribute in data:
                value = data[attribute]
                setattr(device, attribute, value)
                changed[attribute] = str(value) if value is not None else None

        if "tags" in data and data["tags"] is not None:
            names = [str(tag) for tag in data["tags"]]
            device.tags = await self.tags.get_or_create_many(names)
            changed["tags"] = names

        await self.session.flush()
        await self.audit.record(
            AuditAction.DEVICE_UPDATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="device",
            resource_id=device.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"changed": list(changed.keys()), **changed},
        )
        await self.session.commit()
        return await self.get(device.id)

    async def delete(
        self, device_id: uuid.UUID, *, actor: User, ctx: RequestContext | None = None
    ) -> None:
        """Permanently delete a device and its crash history.

        Requires the ``admin`` role at the API layer: the cascade destroys
        every crash report the device ever sent, which is not recoverable.
        """
        ctx = ctx or RequestContext()
        device = await self.get(device_id)
        counts = await self.crashes.count_for_device(device.id)

        await self.audit.record(
            AuditAction.DEVICE_DELETED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="device",
            resource_id=device.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={
                "device_id": device.device_id,
                "serial_number": device.serial_number,
                "crash_reports_deleted": counts["total"],
            },
        )
        await self.devices.delete(device)
        await self.session.commit()
        logger.warning("device.deleted", device_id=device.device_id, crashes=counts["total"])

    async def heartbeat(self, device: Device, payload: DeviceHeartbeat | None = None) -> Device:
        """Record a device check-in.

        Called on every crash submission as well as explicitly, so a device
        that is crashing is never also reported as offline.
        """
        device.last_online_at = datetime.now(UTC)
        if payload is not None:
            if payload.firmware_version:
                device.firmware_version = payload.firmware_version
            if payload.status is not None:
                device.status = payload.status
            elif device.status == DeviceStatus.INACTIVE:
                # A device that just checked in is demonstrably not inactive.
                device.status = DeviceStatus.ACTIVE
        await self.session.commit()
        return device

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------
    async def create_api_key(
        self,
        device_id: uuid.UUID,
        *,
        name: str,
        expires_at: datetime | None = None,
        actor: User,
        ctx: RequestContext | None = None,
    ) -> tuple[DeviceApiKey, str]:
        """Mint a key for a device. Returns the row and the plaintext key."""
        ctx = ctx or RequestContext()
        device = await self.get(device_id)

        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise ValidationError("Expiry must be in the future.")

        generated = generate_api_key()
        key = DeviceApiKey(
            device_id=device.id,
            prefix=generated.prefix,
            key_hash=generated.key_hash,
            name=name.strip(),
            created_by_id=actor.id,
            expires_at=expires_at,
        )
        self.api_keys.add(key)
        await self.session.flush()

        await self.audit.record(
            AuditAction.DEVICE_KEY_CREATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="device",
            resource_id=device.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"key_prefix": generated.prefix, "name": key.name},
        )
        await self.session.commit()
        logger.info("device.key_created", device_id=device.device_id, prefix=generated.prefix)
        return key, generated.plaintext

    async def list_api_keys(self, device_id: uuid.UUID) -> list[DeviceApiKey]:
        device = await self.get(device_id)
        return await self.api_keys.list_for_device(device.id)

    async def revoke_api_key(
        self,
        device_id: uuid.UUID,
        key_id: uuid.UUID,
        *,
        actor: User,
        ctx: RequestContext | None = None,
    ) -> None:
        ctx = ctx or RequestContext()
        device = await self.get(device_id)
        key = await self.api_keys.get(key_id)
        if key is None or key.device_id != device.id:
            raise NotFoundError("API key not found for this device.")

        await self.api_keys.revoke(key)
        await self.audit.record(
            AuditAction.DEVICE_KEY_REVOKED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="device",
            resource_id=device.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"key_prefix": key.prefix, "name": key.name},
        )
        await self.session.commit()

    async def authenticate_api_key(self, candidate: str) -> Device:
        """Resolve a presented API key to its device.

        Raises:
            TokenError: the key is malformed, unknown, revoked, expired, or
                belongs to a decommissioned device. The message is deliberately
                identical in every case so a caller cannot probe which keys or
                devices exist.
        """
        parts = split_api_key(candidate)
        if parts is None:
            raise TokenError("Invalid device API key.")
        prefix, secret = parts

        key = await self.api_keys.get_by_prefix(prefix)
        if key is None or not verify_api_key(secret, key.key_hash):
            raise TokenError("Invalid device API key.")
        if key.is_revoked:
            raise TokenError("Invalid device API key.")
        if key.expires_at is not None and self._as_utc(key.expires_at) <= datetime.now(UTC):
            raise TokenError("Invalid device API key.")

        device = key.device
        if device is None or device.status == DeviceStatus.DECOMMISSIONED:
            raise TokenError("Invalid device API key.")

        await self.api_keys.touch_last_used(key.id)
        return device

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """SQLite returns naive datetimes; treat them as UTC."""
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
