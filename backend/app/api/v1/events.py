"""Events endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/events")
async def get_events() -> dict[str, str]:
    """Get events list."""
    return {"message": "Not implemented"}
