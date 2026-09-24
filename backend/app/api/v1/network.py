"""Network endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/network")
async def get_network() -> dict[str, str]:
    """Get network state."""
    return {"message": "Not implemented"}