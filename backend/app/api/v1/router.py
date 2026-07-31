"""API v1 router aggregation.

New feature routers (devices, crashes, analytics) are registered here in later
phases; versioning is handled by mounting this router under ``/api/v1``.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    analytics,
    audit,
    auth,
    builds,
    crash_groups,
    crashes,
    devices,
    diagnoses,
    export,
    knowledge,
    notifications,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(devices.router)
api_router.include_router(crashes.router)
api_router.include_router(crash_groups.router)
api_router.include_router(builds.router)
api_router.include_router(knowledge.router)
api_router.include_router(diagnoses.router)
api_router.include_router(analytics.router)
api_router.include_router(export.router)
api_router.include_router(notifications.router)
api_router.include_router(audit.router)

__all__ = ["api_router"]
