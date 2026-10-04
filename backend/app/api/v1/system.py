"""System information endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/system")
async def get_system() -> dict[str, str]:
    """Get static system information."""
    return {"message": "Not implemented"}
