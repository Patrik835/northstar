from fastapi import APIRouter

from app.api.v1 import (
    activity,
    admin,
    analytics,
    auth,
    connections,
    dashboard,
    health,
    holdings,
    performance,
    profile,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
router.include_router(holdings.router, prefix="/holdings", tags=["holdings"])
router.include_router(activity.router, prefix="/activity", tags=["activity"])
router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
router.include_router(performance.router, prefix="/performance", tags=["performance"])
router.include_router(connections.router, prefix="/connections", tags=["connections"])
router.include_router(profile.router, prefix="/profile", tags=["profile"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
