"""Storage endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/storage")
async def get_storage() -> dict[str, str]:
    """Get storage state."""
    return {"message": "Not implemented"}