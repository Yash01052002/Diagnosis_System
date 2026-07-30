"""Firmware build artifact endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import (
    AdminUser,
    BuildServiceDep,
    EngineerUser,
    PaginationDep,
    RequestContextDep,
    SymbolicationServiceDep,
    require_viewer,
)
from app.models.build import ArtifactType, BuildStatus
from app.schemas.build import (
    BuildUploadResult,
    FirmwareBuildRead,
    ResymbolicateRequest,
    ResymbolicateResult,
)
from app.schemas.common import ErrorResponse, Page

router = APIRouter(prefix="/builds", tags=["Firmware Builds"])


@router.get(
    "",
    response_model=Page[FirmwareBuildRead],
    dependencies=[Depends(require_viewer)],
    summary="List firmware builds",
)
async def list_builds(
    service: BuildServiceDep,
    pagination: PaginationDep,
    q: Annotated[str | None, Query(description="Search version, filename or notes")] = None,
    firmware_version: Annotated[str | None, Query(description="Exact firmware version")] = None,
    build_version: Annotated[str | None, Query(description="Exact build version")] = None,
    status_filter: Annotated[
        BuildStatus | None, Query(alias="status", description="Filter by index status")
    ] = None,
    artifact_type: Annotated[
        ArtifactType | None, Query(description="Filter by artifact type")
    ] = None,
) -> Page[FirmwareBuildRead]:
    """Paginated list of uploaded ELF/MAP artifacts."""
    items, total = await service.search(
        query=q,
        firmware_version=firmware_version,
        build_version=build_version,
        status=status_filter,
        artifact_type=artifact_type,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page.create(
        [FirmwareBuildRead.model_validate(item) for item in items], total, pagination
    )


@router.post(
    "",
    response_model=BuildUploadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an ELF or MAP file",
    responses={
        422: {"model": ErrorResponse, "description": "Artifact empty, too large or unparsable"}
    },
)
async def upload_build(
    engineer: EngineerUser,
    service: BuildServiceDep,
    ctx: RequestContextDep,
    file: Annotated[UploadFile, File(description="The .elf, .axf or .map file")],
    firmware_version: Annotated[str, Form(description="Firmware version this build is for")],
    build_version: Annotated[
        str | None, Form(description="Git SHA or CI build number, if any")
    ] = None,
    hardware_model: Annotated[str | None, Form(description="Target hardware model")] = None,
    notes: Annotated[str | None, Form(description="Free-form notes")] = None,
) -> BuildUploadResult:
    """Upload a build artifact and index its symbols.

    Send as `multipart/form-data`. The artifact type is detected from the file
    contents, not its name — an ELF called `firmware.map` is still an ELF.

    Indexing runs inline and normally takes well under a second, so the
    response already reports how many symbols were found and whether debug
    info was present. Uploading again for the same
    `(firmware_version, build_version)` **replaces** the previous artifact:
    a rebuilt image supersedes its predecessor, and keeping both would make
    symbolization ambiguous.

    An ELF with DWARF gives `function+offset at file:line`. A MAP file gives
    function names only — still far better than a bare hex address.
    """
    build = await service.upload(
        stream=file.file,
        filename=file.filename or "artifact",
        firmware_version=firmware_version,
        build_version=build_version,
        hardware_model=hardware_model,
        notes=notes,
        actor=engineer,
        ctx=ctx,
    )
    detail = FirmwareBuildRead.model_validate(build)
    message = (
        f"Indexed {build.symbol_count:,} symbols"
        + (" with debug info." if build.has_debug_info else " without debug info.")
        if build.symbol_count
        else "No symbols could be indexed from this artifact."
    )
    return BuildUploadResult(**detail.model_dump(), message=message)


@router.get(
    "/{build_id}",
    response_model=FirmwareBuildRead,
    dependencies=[Depends(require_viewer)],
    summary="Get a firmware build",
    responses={404: {"model": ErrorResponse, "description": "Build not found"}},
)
async def get_build(build_id: uuid.UUID, service: BuildServiceDep) -> FirmwareBuildRead:
    """Metadata and indexing status for one artifact."""
    return FirmwareBuildRead.model_validate(await service.get(build_id))


@router.post(
    "/{build_id}/resymbolicate",
    response_model=ResymbolicateResult,
    summary="Re-symbolize stored crashes against this build",
    responses={404: {"model": ErrorResponse, "description": "Build not found"}},
)
async def resymbolicate(
    build_id: uuid.UUID,
    payload: ResymbolicateRequest,
    engineer: EngineerUser,
    builds: BuildServiceDep,
    symbolication: SymbolicationServiceDep,
) -> ResymbolicateResult:
    """Upgrade crashes that were collected before this artifact existed.

    This is what makes a late ELF upload worth doing: reports already sitting
    in the database as raw hex are re-resolved into function names and
    re-grouped, rather than staying unreadable forever.
    """
    build = await builds.get(build_id)
    result = await symbolication.resymbolicate_for_build(
        firmware_version=payload.firmware_version or build.firmware_version,
        build_version=payload.build_version or build.build_version,
        limit=payload.limit,
    )
    return ResymbolicateResult(**result)


@router.delete(
    "/{build_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a firmware build",
    responses={404: {"model": ErrorResponse, "description": "Build not found"}},
)
async def delete_build(
    build_id: uuid.UUID,
    admin: AdminUser,
    service: BuildServiceDep,
    ctx: RequestContextDep,
) -> None:
    """Delete an artifact, its symbols and its stored file.

    Crash reports keep the symbolication they already have — deleting a build
    removes the ability to symbolize *new* crashes, not results already
    recorded.
    """
    await service.delete(build_id, actor=admin, ctx=ctx)
