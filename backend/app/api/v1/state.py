"""System state endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/state")
async def get_state() -> dict[str, str]:
    """Get current system state snapshot."""
    return {"message": "Not implemented"}
