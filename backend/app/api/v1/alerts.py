"""Alerts endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/alerts")
async def get_alerts() -> dict[str, str]:
    """Get alerts list."""
    return {"message": "Not implemented"}