"""Metrics endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/metrics/cpu")
async def get_cpu_metrics() -> dict[str, str]:
    """Get CPU metrics."""
    return {"message": "Not implemented"}


@router.get("/metrics/memory")
async def get_memory_metrics() -> dict[str, str]:
    """Get memory metrics."""
    return {"message": "Not implemented"}