"""Main API router."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    events,
    health,
    history,
    metrics,
    network,
    processes,
    services,
    state,
    storage,
)
from app.api.v1.system import router as system_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(state.router, tags=["state"])
api_router.include_router(system_router, tags=["system"])
api_router.include_router(metrics.router, tags=["metrics"])
api_router.include_router(network.router, tags=["network"])
api_router.include_router(storage.router, tags=["storage"])
api_router.include_router(processes.router, tags=["processes"])
api_router.include_router(services.router, tags=["services"])
api_router.include_router(events.router, tags=["events"])
api_router.include_router(alerts.router, tags=["alerts"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(history.router, tags=["history"])
