"""History endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/history/{metric}")
async def get_history(metric: str) -> dict[str, str]:
    """Get historical metric data."""
    return {"message": "Not implemented"}
